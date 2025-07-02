from esim.models import DigisellerOrder, AiraloOrder, AiraloSim
from celery import shared_task
from airalo.views import get_airalo_token
from django.utils import timezone
from django.conf import settings
import requests
import json






AIRALO_BASE_API_URL = "https://sandbox-partners-api.airalo.com"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def purchase_airalo_sim(self, digiseller_order_id):
    try:
        order = DigisellerOrder.objects.select_related("airalo_package").get(pk=digiseller_order_id)
    except DigisellerOrder.DoesNotExist:
        return

    order.status = "processing"
    order.save(update_fields=["status"])

    payload = {
        "quantity":     int(order.quantity),
        "package_id":   order.airalo_package.package_id,
        "type":         "sim",
        "description":  f"{order.quantity} {order.airalo_package.package_id}",
        "brand_settings_name": "",
        
        "to_email": order.buyer_email,
        "sharing_option[]": "pdf",
        "copy_address[]": "ajayghosh28@gmail.com"
    }
    
    api_token = get_airalo_token()
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }

    try:
        r = requests.post(
            f"{AIRALO_BASE_API_URL}/v2/orders",
            headers=headers,
            data=payload,                # Airalo expects multipart/form-data
            timeout=15,
        )
    except Exception as exc:
        order.status = "failed"
        order.error_message = str(exc)
        order.save(update_fields=["status", "error_message"])
        raise self.retry(exc=exc)

    if r.status_code != 200:
        order.status = "failed"
        order.error_message = f"HTTP {r.status_code}: {r.text}"
        order.save(update_fields=["status", "error_message"])
        return

    data = r.json()["data"]

    # ---------- Persist AiraloOrder ----------
    airalo_order = AiraloOrder.objects.create(
        airalo_id      = data["id"],
        code           = data["code"],
        currency       = data["currency"],
        package_id     = data["package_id"],
        quantity       = data["quantity"],
        type           = data["type"],
        description    = data["description"],
        esim_type      = data.get("esim_type"),
        validity       = data.get("validity"),
        package_title  = data.get("package"),
        data           = data.get("data"),
        price          = data["price"],
        created_at_api = timezone.datetime.strptime(data["created_at"], "%Y-%m-%d %H:%M:%S"),
        manual_installation = data.get("manual_installation"),
        qrcode_installation = data.get("qrcode_installation"),
        installation_guides = data.get("installation_guides"),
        net_price           = data.get("net_price"),
        raw_payload         = data,
    )

    # ---------- Persist SIMs ----------
    for sim in data.get("sims", []):
        AiraloSim.objects.create(
            airalo_order = airalo_order,
            sim_id       = sim["id"],
            iccid        = sim["iccid"],
            lpa          = sim["lpa"],
            qrcode       = sim["qrcode"],
            qrcode_url   = sim["qrcode_url"],
            direct_apple_installation_url = sim.get("direct_apple_installation_url"),
            apn_type     = sim.get("apn_type"),
            apn_value    = sim.get("apn_value"),
            is_roaming   = sim.get("is_roaming", False),
            raw_payload  = sim,
        )

    # ---------- Link back & finish ----------
    order.airalo_order = airalo_order
    order.status       = "completed"
    order.save(update_fields=["airalo_order", "status"])

    # For debugging now:
    print("✅ Airalo order created:", airalo_order.code)
    for sim in airalo_order.sims.all():
        print("   ▶ ICCID:", sim.iccid)
        
    try:
        deliver_unique_code(order.unique_code)
    except Exception as exc:
        print(f"❌ Failed to call Digiseller deliver endpoint: {exc}")
    else:
        # deliver_response already printed inside helper
        print("✅ Digiseller deliver endpoint completed.")



def deliver_unique_code(code: str):
    from digiseller.views import get_digiseller_token
    """
    Tell Digiseller “Ive delivered the goods for this unique code.”
    PUT https://api.digiseller.com/api/purchases/unique-code/{code}/deliver?token={token}
    """
    token = get_digiseller_token()
    print(f"🔑 Using Digiseller API token++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++: {token}")
    url = (
        f"https://api.digiseller.com/api/purchases/"
        f"unique-code/{code}/deliver?token={token}"
    )
    headers = {
        "Accept": "application/json",
    }
    resp = requests.put(url, headers=headers, timeout=10)
    # for debugging, always print full status & body
    print("🔔 Digiseller deliver status:", resp.status_code)
    try:
        payload = resp.json()
        print("🔔 Digiseller deliver response JSON:", json.dumps(payload, indent=2))
    except ValueError:
        payload = {"text": resp.text}
        print("🔔 Digiseller deliver response text:", resp.text)
    resp.raise_for_status()
    return payload
