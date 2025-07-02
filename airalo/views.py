from django.shortcuts import render,redirect
from django.contrib import messages
from django.http.response import HttpResponseRedirect
from django.utils import timezone
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth import login,logout,authenticate
from rest_framework.decorators import api_view
from django.http import JsonResponse
from rest_framework import status
from datetime import timedelta
from django.utils.dateparse import parse_datetime
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.db.models import Count
from celery import shared_task
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseBadRequest

from django.conf import settings
from typing import Dict, List, Tuple
import requests
import traceback
import logging
import hashlib
import time
import json
import re
from esim.models import *

logger = logging.getLogger(__name__)  # Optional: use logger if configured




# Constants
AIRALO_BASE_API_URL = "https://sandbox-partners-api.airalo.com"

TOKEN_URL = f"{AIRALO_BASE_API_URL}/v2/token"
PACKAGES_URL = f"{AIRALO_BASE_API_URL}/v2/packages?limit=200"


# Token management
def get_airalo_token(force=False):
    token_obj = AiraloToken.objects.last()
    if token_obj and not force and token_obj.expires_at > timezone.now():
        return token_obj.access_token

    files = {
        "client_id": (None, settings.AIRALO_CLIENT_ID),
        "client_secret": (None, settings.AIRALO_CLIENT_SECRET),
        "grant_type": (None, "client_credentials"),
    }
    
    resp = requests.post(TOKEN_URL, files=files)
    if resp.status_code in (401, 422):
        raise Exception(f"Token error {resp.status_code}: {resp.json()}")
    resp.raise_for_status()
    data = resp.json().get("data", {})

    access = data.get("access_token")
    expires = data.get("expires_in", 0)
    expires_at = timezone.now() + timedelta(seconds=expires)

    AiraloToken.objects.all().delete()
    AiraloToken.objects.create(access_token=access, expires_at=expires_at)
    return access


# Data processing
def process_country(country_data):
    country, _ = Country.objects.update_or_create(
        slug=country_data.get("slug"),
        defaults={
            "country_code": country_data.get("country_code"),
            "title": country_data.get("title"),
            "image_url": country_data.get("image", {}).get("url"),
            "image_width": country_data.get("image", {}).get("width"),
            "image_height": country_data.get("image", {}).get("height"),
        }
    )

    for op in country_data.get("operators", []):
        try:
            operator, _ = Operator.objects.update_or_create(
                operator_id=op.get("id"), country=country,
                defaults={
                    "type": op.get("type"),
                    "is_prepaid": op.get("is_prepaid"),
                    "title": op.get("title"),
                    "esim_type": op.get("esim_type"),
                    "apn_type": op.get("apn_type"),
                    "apn_value": op.get("apn_value"),
                    "is_roaming": op.get("is_roaming"),
                    "info": op.get("info"),
                    "plan_type": op.get("plan_type"),
                    "activation_policy": op.get("activation_policy"),
                    "is_kyc_verify": op.get("is_kyc_verify"),
                    "rechargeability": op.get("rechargeability"),
                    "other_info": op.get("other_info"),
                    "image_url": op.get("image", {}).get("url"),
                    "image_width": op.get("image", {}).get("width"),
                    "image_height": op.get("image", {}).get("height"),
                }
            )

            apn_data = op.get("apn", {})
            APN.objects.update_or_create(
                operator=operator,
                defaults={
                    "ios_apn_type": apn_data.get("ios", {}).get("apn_type"),
                    "ios_apn_value": apn_data.get("ios", {}).get("apn_value"),
                    "android_apn_type": apn_data.get("android", {}).get("apn_type"),
                    "android_apn_value": apn_data.get("android", {}).get("apn_value"),
                }
            )

            # Coverages & networks
            for cov in op.get("coverages", []):
                coverage, _ = Coverage.objects.update_or_create(
                    operator=operator, name=cov.get("name"), code=cov.get("code")
                )
                coverage.networks.all().delete()
                for net in cov.get("networks", []):
                    Network.objects.create(
                        coverage=coverage,
                        name=net.get("name"),
                        types=net.get("types"),
                    )

            # Operator countries
            for oc in op.get("countries", []):
                OperatorCountry.objects.update_or_create(
                    operator=operator, country_code=oc.get("country_code"),
                    defaults={
                        "title": oc.get("title"),
                        "image_url": oc.get("image", {}).get("url"),
                        "image_width": oc.get("image", {}).get("width"),
                        "image_height": oc.get("image", {}).get("height"),
                    }
                )

            # Packages
            for pkg in op.get("packages", []):
                try:
                    Package.objects.update_or_create(
                        package_id=pkg.get("id"), operator=operator,
                        defaults={
                            "type": pkg.get("type"),
                            "price": pkg.get("price"),
                            "amount": pkg.get("amount"),
                            "day": pkg.get("day"),
                            "is_unlimited": pkg.get("is_unlimited"),
                            "title": pkg.get("title"),
                            "short_info": pkg.get("short_info"),
                            "qr_installation": pkg.get("qr_installation"),
                            "manual_installation": pkg.get("manual_installation"),
                            "is_fair_usage_policy": pkg.get("is_fair_usage_policy"),
                            "fair_usage_policy": pkg.get("fair_usage_policy"),
                            "data": pkg.get("data"),
                            "voice": pkg.get("voice"),
                            "text": pkg.get("text"),
                            "net_price": pkg.get("net_price"),
                            "prices": pkg.get("prices"),
                        }
                    )
                except Exception as e:
                    AiraloFailedPackage.objects.create(reason=str(e), data=pkg)
        except Exception as e:
            AiraloFailedPackage.objects.create(reason=str(e), data=op)

    return country.slug


# View entry point with rate-limit handling
@api_view(["GET"])
@permission_classes([AllowAny])
def sync_airalo_data(request):
    try:
        token = get_airalo_token()
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    headers = {"Authorization": f"Bearer {token}"}
    page_url = PACKAGES_URL
    request_count = 0
    start_time = time.time()

    processed = []

    while page_url:
        request_count += 1
        elapsed = time.time() - start_time
        if request_count >= 40 and elapsed < 60:
            time.sleep(60 - elapsed)
            request_count = 0
            start_time = time.time()

        resp = requests.get(page_url, headers=headers)
        if resp.status_code == 401:
            token = get_airalo_token(force=True)
            headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(page_url, headers=headers)
        if resp.status_code != 200:
            AiraloFailedPackage.objects.create(reason=f"HTTP {resp.status_code}", data={"url": page_url})
            break

        data = resp.json()
        for country_data in data.get("data", []):
            slug = process_country(country_data)
            processed.append(slug)

        page_url = data.get("links", {}).get("next")

    return Response({"processed_countries": processed}, status=status.HTTP_200_OK)



@api_view(['GET'])
@permission_classes([AllowAny])  # <-- use this instead
def unique_operator_count(request):
    unique_count = Package.objects.values('operator').distinct().count()
    return Response({'unique_operator_count': unique_count}, status=status.HTTP_200_OK)



# Celery task in the server
@api_view(['GET'])
@permission_classes([AllowAny])  # <-- use this instead
def unique_operator_count(request):
    unique_count = Package.objects.values('operator').distinct().count()
    return Response({'unique_operator_count': unique_count}, status=status.HTTP_200_OK)



# Celery task in the server



@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def purchase_airalo_sim(digiseller_order_id):
    from digiseller.views import get_digiseller_token
    try:
        order = DigisellerOrder.objects.select_related("airalo_package").get(pk=digiseller_order_id)
    except DigisellerOrder.DoesNotExist:
        print(f"❌ Order with ID {digiseller_order_id} not found.")
        return

    order.status = "processing"
    order.save(update_fields=["status"])

    payload = {
        "quantity": int(order.quantity),
        "package_id": order.airalo_package.package_id,
        "type": "sim",
        "description": f"{order.quantity} {order.airalo_package.package_id}",
        "brand_settings_name": "",
        
        "to_email": "ajayghosh28@gmail.com",
        "sharing_option[]": "pdf",
        "copy_address[]": "ajayghosh28@gmail.com"
    }
    
    print('payload for Airalo order creation:', payload)
    
    print('Airalo package id in automated order creation:', order.airalo_package.package_id)

    api_token = get_airalo_token()
    print(f"🔑 Using Airalo API token: {api_token}")
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }

    try:
        r = requests.post(
            f"{AIRALO_BASE_API_URL}/v2/orders",
            headers=headers,
            data=payload,  # Airalo expects multipart/form-data
            timeout=15,
        )
        
        # 👇 Print full response for debugging
        print("🔁 Airalo Response Status:", r.status_code)
        print("🔁 Airalo Response Headers:", r.headers)
        try:
            print("🔁 Airalo Response JSON:", r.json())
        except Exception:
            print("🔁 Airalo Response Text (not JSON):", r.text)
    except Exception as exc:
        order.status = "failed"
        order.error_message = str(exc)
        order.save(update_fields=["status", "error_message"])
        print(f"❌ Exception during API request: {exc}")
        traceback.print_exc()
        return

    if r.status_code != 200:
        order.status = "failed"
        order.error_message = f"HTTP {r.status_code}: {r.text}"
        order.save(update_fields=["status", "error_message"])
        print(f"❌ Airalo API error: HTTP {r.status_code} - {r.text}")
        return

    try:
        data = r.json()["data"]
    except Exception as e:
        order.status = "failed"
        order.error_message = f"Invalid JSON response: {r.text}"
        order.save(update_fields=["status", "error_message"])
        print(f"❌ Failed to parse JSON: {r.text}")
        traceback.print_exc()
        return

    try:
        airalo_order = AiraloOrder.objects.create(
            airalo_id=data["id"],
            code=data["code"],
            currency=data["currency"],
            package_id=data["package_id"],
            quantity=data["quantity"],
            type=data["type"],
            description=data["description"],
            esim_type=data.get("esim_type"),
            validity=data.get("validity"),
            package_title=data.get("package"),
            data=data.get("data"),
            price=data["price"],
            created_at_api=timezone.datetime.strptime(data["created_at"], "%Y-%m-%d %H:%M:%S"),
            manual_installation=data.get("manual_installation"),
            qrcode_installation=data.get("qrcode_installation"),
            installation_guides=data.get("installation_guides"),
            net_price=data.get("net_price"),
            raw_payload=data,
        )

        for sim in data.get("sims", []):
            AiraloSim.objects.create(
                airalo_order=airalo_order,
                sim_id=sim["id"],
                iccid=sim["iccid"],
                lpa=sim["lpa"],
                qrcode=sim["qrcode"],
                qrcode_url=sim["qrcode_url"],
                direct_apple_installation_url=sim.get("direct_apple_installation_url"),
                apn_type=sim.get("apn_type"),
                apn_value=sim.get("apn_value"),
                is_roaming=sim.get("is_roaming", False),
                raw_payload=sim,
            )

        order.airalo_order = airalo_order
        order.status = "completed"
        order.digiseller_transaction_status = 2
        order.save(update_fields=["airalo_order", "status", "digiseller_transaction_status"])
        
        # call the API function here

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

    except Exception as db_exc:
        order.status = "failed"
        order.error_message = f"DB Save Error: {db_exc}"
        order.save(update_fields=["status", "error_message"])
        print(f"❌ Exception during saving AiraloOrder or SIMs: {db_exc}")
        traceback.print_exc()
        return
    
    
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
    
    
    
    
    



# @csrf_exempt
# @require_POST
# def airalo_webhook_callback(request):
#     try:
#         payload = json.loads(request.body.decode("utf-8"))
#         print("Received Airalo webhook payload:", payload)

#         # Print all headers
#         print("Received Airalo webhook headers:")
#         for header_name, header_value in request.headers.items():
#             print(f"  {header_name}: {header_value}")

#         # You can also access specific headers like this:
#         # if 'User-Agent' in request.headers:
#         #     print(f"  User-Agent: {request.headers['User-Agent']}")
#         # if 'X-Airalo-Signature' in request.headers: # Example for a potential signature header
#         #     print(f"  X-Airalo-Signature: {request.headers['X-Airalo-Signature']}")

#     except json.JSONDecodeError:
#         print("Invalid JSON received in Airalo webhook")
#         return HttpResponseBadRequest("Invalid JSON")
#     except Exception as e:
#         print(f"An unexpected error occurred: {e}")
#         return HttpResponseBadRequest("An unexpected error occurred")

#     return JsonResponse({"status": "processed"})
