from esim.models import DigisellerOrder, AiraloOrder, AiraloSim
from celery import shared_task
from airalo.views import get_airalo_token
from django.utils import timezone
from django.conf import settings
import requests






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








# @shared_task(bind=True, max_retries=3, default_retry_delay=60)
# def purchase_airalo_sim(self, digiseller_order_id):
#     try:
#         order = DigisellerOrder.objects.select_related("airalo_package").get(pk=digiseller_order_id)
#     except DigisellerOrder.DoesNotExist:
#         return

#     order.status = "processing"
#     order.save(update_fields=["status"])

#     payload = {
#         "quantity":     int(order.quantity),
#         "package_id":   order.airalo_package.package_id,
#         "type":         "sim",
#         "description":  f"{order.quantity} {order.airalo_package.package_id}",
#         "brand_settings_name": "",
#         "to_email": order.buyer_email,
#         "sharing_option[]": "pdf",
#         "copy_address[]": "ajayghosh28@gmail.com"
#     }
#     print(f"[Task] Payload prepared: {payload}")

#     api_token = get_airalo_token()
#     headers = {
#         "Authorization": f"Bearer {api_token}",
#         "Accept": "application/json",
#     }

#     try:
#         r = requests.post(
#             f"{AIRALO_BASE_API_URL}/v2/orders",
#             headers=headers,
#             data=payload,                # multipart/form-data
#             timeout=15,
#         )
#     except Exception as exc:
#         order.status = "failed"
#         order.error_message = str(exc)
#         order.save(update_fields=["status", "error_message"])
#         raise self.retry(exc=exc)

#     if r.status_code != 200:
#         order.status = "failed"
#         order.error_message = f"HTTP {r.status_code}: {r.text}"
#         order.save(update_fields=["status", "error_message"])
#         return

#     resp_json = r.json()

#     data = resp_json.get("data", {})

#     # Persist AiraloOrder
#     try:
#         airalo_order = AiraloOrder.objects.create(
#             airalo_id      = data["id"],
#             code           = data["code"],
#             currency       = data["currency"],
#             package_id     = data["package_id"],
#             quantity       = data["quantity"],
#             type           = data["type"],
#             description    = data["description"],
#             esim_type      = data.get("esim_type"),
#             validity       = data.get("validity"),
#             package_title  = data.get("package"),
#             data           = data.get("data"),
#             price          = data["price"],
#             created_at_api = timezone.datetime.strptime(data["created_at"], "%Y-%m-%d %H:%M:%S"),
#             manual_installation = data.get("manual_installation"),
#             qrcode_installation = data.get("qrcode_installation"),
#             installation_guides = data.get("installation_guides"),
#             net_price           = data.get("net_price"),
#             raw_payload         = data,
#         )

#     except Exception as exc:
#         order.status = "failed"
#         order.error_message = f"AiraloOrder create error: {exc}"
#         order.save(update_fields=["status", "error_message"])
#         return

#     sims = data.get("sims", [])

#     created_sims = 0
#     for sim in sims:
#         try:
#             obj = AiraloSim.objects.create(
#                 airalo_order = airalo_order,
#                 sim_id       = sim["id"],
#                 iccid        = sim["iccid"],
#                 lpa          = sim["lpa"],
#                 qrcode       = sim["qrcode"],
#                 qrcode_url   = sim["qrcode_url"],
#                 direct_apple_installation_url = sim.get("direct_apple_installation_url"),
#                 apn_type     = sim.get("apn_type"),
#                 apn_value    = sim.get("apn_value"),
#                 is_roaming   = sim.get("is_roaming", False),
#                 raw_payload  = sim,
#             )
            
#         except Exception as exc:
#             print(f"[Task][ERROR] Failed to create AiraloSim for sim {sim}: {exc}")

#     print(f"[Task] Total sims created: {created_sims}")

#     # Link back & finalize
#     order.airalo_order = airalo_order
#     order.status       = "completed"
#     order.save(update_fields=["airalo_order", "status"])
#     print(f"[Task] Order {order.id} marked completed")