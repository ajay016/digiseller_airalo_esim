from esim.models import DigisellerOrder, AiraloOrder, AiraloSim
from ggsel.models import GgselOrder
from celery import shared_task
from airalo.views import get_airalo_token
from requests.exceptions import RequestException, Timeout
import time
from django.utils import timezone
from django.conf import settings
import requests
import json







AIRALO_BASE_API_URL = "https://partners-api.airalo.com"
# AIRALO_BASE_API_URL = "https://imdb.com"


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
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
        "description":  order.order_id,
        "brand_settings_name": "",
        "to_email": order.buyer_email,
        "sharing_option[]": "pdf",
        "copy_address[]": "kinoblitze@gmail.com"
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
            data=payload,
            timeout=30,
        )
        # If successful POST
        r.raise_for_status()
        data = r.json()["data"]

    except Timeout as exc:
        print("❌ POST request timed out. Checking for completed orders...")

        completed_orders = fetch_completed_orders(order.order_id)
        matched_order = None
        for item in completed_orders:
            if item["description"] == payload["description"]:
                matched_order = item
                break

        if matched_order:
            print("✅ Matched completed order. Fetching full order data...")
            try:
                data = fetch_airalo_order_detail(matched_order["id"])
            except Exception as fetch_err:
                print("❌ Failed to fetch full order data:", fetch_err)
                raise self.retry(exc=fetch_err)
        else:
            print("❌ No matching completed order found. Retrying POST...")
            order.status = "failed"
            order.error_message = str(exc)
            order.save(update_fields=["status", "error_message"])
            raise self.retry(exc=exc)

    except Exception as exc:
        order.status = "failed"
        order.error_message = str(exc)
        order.save(update_fields=["status", "error_message"])
        raise self.retry(exc=exc)

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

    order.airalo_order = airalo_order
    order.status       = "completed"
    order.save(update_fields=["airalo_order", "status"])

    print("✅ Airalo order created:", airalo_order.code)
    for sim in airalo_order.sims.all():
        print("   ▶ ICCID:", sim.iccid)

    try:
        deliver_unique_code(order.unique_code)
    except Exception as exc:
        print(f"❌ Failed to call Digiseller deliver endpoint: {exc}")
    else:
        order.digiseller_transaction_status = 2
        order.save(update_fields=["digiseller_transaction_status"])
        print("✅ Digiseller deliver endpoint completed.")
        
        

@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def purchase_airalo_sim_for_ggsel(self, digiseller_order_id):
    try:
        order = GgselOrder.objects.select_related("airalo_package").get(pk=digiseller_order_id)
    except GgselOrder.DoesNotExist:
        return

    order.status = "processing"
    order.save(update_fields=["status"])

    payload = {
        "quantity":     int(order.quantity),
        "package_id":   order.airalo_package.package_id,
        "type":         "sim",
        "description":  order.order_id,
        "brand_settings_name": "",
        "to_email": order.buyer_email,
        "sharing_option[]": "pdf",
        "copy_address[]": "kinoblitze@gmail.com"
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
            data=payload,
            timeout=30,
        )
        # If successful POST
        r.raise_for_status()
        data = r.json()["data"]

    except Timeout as exc:
        print("❌ POST request timed out. Checking for completed orders...")

        completed_orders = fetch_completed_orders(order.order_id)
        matched_order = None
        for item in completed_orders:
            if item["description"] == payload["description"]:
                matched_order = item
                break

        if matched_order:
            print("✅ Matched completed order. Fetching full order data...")
            try:
                data = fetch_airalo_order_detail(matched_order["id"])
            except Exception as fetch_err:
                print("❌ Failed to fetch full order data:", fetch_err)
                raise self.retry(exc=fetch_err)
        else:
            print("❌ No matching completed order found. Retrying POST...")
            order.status = "failed"
            order.error_message = str(exc)
            order.save(update_fields=["status", "error_message"])
            raise self.retry(exc=exc)

    except Exception as exc:
        order.status = "failed"
        order.error_message = str(exc)
        order.save(update_fields=["status", "error_message"])
        raise self.retry(exc=exc)

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

    order.airalo_order = airalo_order
    order.status       = "completed"
    order.save(update_fields=["airalo_order", "status"])

    print("✅ Airalo order created:", airalo_order.code)
    for sim in airalo_order.sims.all():
        print("   ▶ ICCID:", sim.iccid)

    try:
        deliver_unique_code(order.unique_code)
    except Exception as exc:
        print(f"❌ Failed to call Digiseller deliver endpoint: {exc}")
    else:
        order.digiseller_transaction_status = 2
        order.save(update_fields=["digiseller_transaction_status"])
        print("✅ Digiseller deliver endpoint completed.")



def deliver_unique_code(code: str):
    from digiseller.views import get_digiseller_token
    """
    Tell Digiseller “Ive delivered the goods for this unique code.”
    PUT https://api.digiseller.com/api/purchases/unique-code/{code}/deliver?token={token}
    """
    token = get_digiseller_token()
    url = (
        f"https://api.digiseller.com/api/purchases/"
        f"unique-code/{code}/deliver?token={token}"
    )
    headers = {
        "Accept": "application/json",
    }
    resp = requests.put(url, headers=headers, timeout=10)
    # for debugging, always print full status & body
    try:
        payload = resp.json()
    except ValueError:
        payload = {"text": resp.text}
    resp.raise_for_status()
    return payload



def fetch_completed_orders(description: str) -> list:
    api_token = get_airalo_token()
    url = f"{AIRALO_BASE_API_URL}/v2/orders"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json"
    }
    params = {
        "limit": 20,
        "page": 1,
        "filter[description]": description,
        "filter[order_status]": "completed",
        "include": "status"
    }

    max_retries = 5
    timeout_seconds = 20

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout_seconds)
            response.raise_for_status()
            data = response.json()

            completed_orders = []
            for order in data.get("data", []):
                if order.get("status", {}).get("slug") == "completed":
                    print('order status from Airalo: ', order.get("status", {}).get("slug"))
                    completed_orders.append(order)

            return completed_orders  # list of completed orders (can be empty)

        except Timeout:
            print(f"Timeout occurred on attempt {attempt}/{max_retries}. Retrying...")
        except RequestException as e:
            print(f"Request failed on attempt {attempt}/{max_retries}: {e}")
        time.sleep(1)

    print("Failed to fetch orders after 5 retries.")
    return []


def fetch_airalo_order_detail(order_id: int) -> dict:
    api_token = get_airalo_token()
    url = f"{AIRALO_BASE_API_URL}/v2/orders/{order_id}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json"
    }

    max_retries = 5
    timeout_seconds = 20
    retry_delay = 1  # seconds between attempts

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            return response.json()["data"]

        except Timeout as exc:
            print(f"⚠️ Timeout on attempt {attempt}/{max_retries} for order {order_id}.")
        except RequestException as exc:
            print(f"⚠️ Request failed on attempt {attempt}/{max_retries} for order {order_id}: {exc}")

        if attempt < max_retries:
            time.sleep(retry_delay)
        else:
            # Last attempt failed
            raise
