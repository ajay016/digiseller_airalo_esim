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
from django.http import JsonResponse, HttpResponseBadRequest
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
from django.views.decorators.csrf import csrf_exempt
from typing import Dict, List, Tuple
import base64
from django.conf import settings
import requests
import hashlib
import time
import json
import re
from esim.models import *
from airalo.tasks.airalo_tasks import purchase_airalo_sim







# API Endpoints
DIGISELLER_TOKEN_CACHE_KEY = 'digiseller_token'
TOKEN_API_URL = "https://api.digiseller.ru/api/apilogin"
SELLER_GOODS_URL = "https://api.digiseller.com/api/seller-goods"
PRODUCT_DETAIL_URL = "https://api.digiseller.com/api/products/{product_id}/data?lang=en-US"

SELLER_ID = settings.DIGISELLER_SELLER_ID
API_KEY = settings.DIGISELLER_API_KEY

# 1. Manage Digiseller token creation with caching
def get_digiseller_token():
    """
    Get a valid Digiseller token from cache or request a new one using their API.
    """
    token = cache.get(DIGISELLER_TOKEN_CACHE_KEY)
    if token:
        return token  # ✅ still valid

    # 🔒 Step 1: Generate sign
    timestamp = int(time.time())
    signature = hashlib.sha256(f"{API_KEY}{timestamp}".encode('utf-8')).hexdigest()

    # 🧾 Step 2: Prepare payload
    payload = {
        "seller_id": SELLER_ID,
        "timestamp": timestamp,
        "sign": signature
    }

    try:
        response = requests.post(TOKEN_API_URL, json=payload, timeout=10)
        response.raise_for_status()
        result = json.loads(response.content.decode('utf-8-sig'))  # decode BOM if present

        # Step 3: Check Digiseller-specific retval
        if result.get("retval") != 0:
            raise Exception(f"Digiseller error {result.get('retval')}: {result.get('desc')}")

        token = result.get("token")
        valid_thru_str = result.get("valid_thru")

        if not token or not valid_thru_str:
            raise Exception("Token or valid_thru missing from response")

        # Step 4: Parse validity and compute TTL
        valid_thru = parse_datetime(valid_thru_str)
        if valid_thru is None:
            raise Exception(f"Invalid valid_thru format: {valid_thru_str}")

        if valid_thru.tzinfo is None:
            valid_thru = timezone.make_aware(valid_thru, timezone.utc)

        now = timezone.now()
        ttl_seconds = int((valid_thru - now).total_seconds())

        if ttl_seconds <= 0:
            raise Exception("Received expired token")

        # ✅ Step 5: Cache the token for its exact TTL
        cache.set(DIGISELLER_TOKEN_CACHE_KEY, token, timeout=ttl_seconds)
        return token

    except Exception as e:
        raise Exception(f"Failed to obtain Digiseller token: {e}")

# 2. Fetch seller goods list with generated token
def fetch_seller_goods(rows=200, page=2):
    token = get_digiseller_token()
    payload = {"id_seller": SELLER_ID, "order_col": "name", "order_dir": "asc",
               "rows": rows, "page": page, "currency": "RUR", "lang": "en-US",
               "show_hidden": 1, "owner_id": 1}
    resp = requests.post(f"{SELLER_GOODS_URL}?token={token}", json=payload, timeout=15)
    try:
        resp.raise_for_status()
        text = resp.content.decode('utf-8-sig')
        raw = json.loads(text)
        return raw.get("rows", [])
    except Exception as e:
        DigisellerFailedEntry.objects.create(reason=f"fetch_seller_goods error: {e}", data={'payload': payload})
        return []

# 3. Filter products starting with 'esim' (case-insensitive)
def filter_esim_products(products):
    return [p for p in products if p.get("name_goods", "").lower().startswith("esim")]


# 4. Fetch detailed product variants
def fetch_product_variants(product_id):
    url = PRODUCT_DETAIL_URL.format(product_id=product_id)
    
    headers = {
        'Accept': 'application/json',
    }
    
    print('url of the fetched product variant: ', url)
    resp = requests.get(url, headers=headers, timeout=15)
    try:
        resp.raise_for_status()
        print('response: ', resp)
        text = resp.content.decode('utf-8-sig')
        raw = json.loads(text)
        print('json data: ', raw)
        return raw.get("product", {}).get("options", [])
    except Exception as e:
        DigisellerFailedEntry.objects.create(
            reason=f"fetch_product_variants error (id {product_id}): {e}",
            data={'product_id': product_id}
        )
        return []


# 5. Save product and its variants
def save_product_with_variants(prod_data):
    # Save product
    product, _ = DigisellerProduct.objects.update_or_create(
        id_goods=prod_data["id_goods"],
        defaults={
            "name_goods": prod_data.get("name_goods"),
            "info_goods": prod_data.get("info_goods"),
            "add_info": prod_data.get("add_info"),
            "price": prod_data.get("price"),
            "currency": prod_data.get("currency"),
            "cnt_sell": prod_data.get("cnt_sell"),
            "price_usd": prod_data.get("price_usd"),
            "price_rur": prod_data.get("price_rur"),
            "price_eur": prod_data.get("price_eur"),
        }
    )
    # Remove old variants
    product.variants.all().delete()

    # Create new variants
    options = fetch_product_variants(product.id_goods)
    first_option = next((opt for opt in options if opt.get("type") == "radio"), None)

    if first_option:
        for variant in first_option.get("variants", []):
            try:
                DigisellerVariant.objects.create(
                    product=product,
                    variant_value=variant.get("value"),
                    text=variant.get("text", ""),
                    default=bool(variant.get("default")),
                    modify=variant.get("modify"),
                    modify_value=variant.get("modify_value"),
                    modify_value_default=variant.get("modify_value_default"),
                    modify_type=variant.get("modify_type"),
                    visible=bool(variant.get("visible", 1)),
                )
            except Exception as e:
                DigisellerFailedEntry.objects.create(
                    reason=f"variant save error (prod {product.id_goods}): {e}",
                    data=variant
                )
    return product

# 6. Main view to orchestrate the sync process
@api_view(["POST"])
@permission_classes([AllowAny])
def sync_esim_products(request):
    try:
        raw_products = fetch_seller_goods()
        esim_products = filter_esim_products(raw_products)

        saved_ids = []
        for prod in esim_products:
            try:
                saved = save_product_with_variants(prod)
                saved_ids.append(saved.id_goods)
            except Exception as e:
                DigisellerFailedEntry.objects.create(
                    reason=f"save_product error (id {prod.get('id_goods')}): {e}",
                    data=prod
                )
        return Response({"saved_product_ids": saved_ids}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def variant_duplicate_texts(request):
    # Group by 'text', count how many times each appears, and filter where count > 1
    duplicates = (
        DigisellerVariant.objects
        .values('text')
        .annotate(text_count=Count('id'))
        .filter(text_count__gt=1)
    )

    response_data = {
        "total_duplicate_texts": duplicates.count(),
        "duplicates": list(duplicates)
    }

    return Response(response_data, status=status.HTTP_200_OK)



@require_GET
def digiseller_webhook_test(request):
    # Dummy values to simulate Digiseller's behavior
    password = "your_webhook_password".lower()
    ID_I = 256070005
    ID_D = 3498404
    AMOUNT = 19.99
    CURRENCY = "WMZ"
    EMAIL = "ajayghosh28@gmail.com"
    DATE = "2025-06-24 15:30:00"
    THROUGH = base64.b64encode(b"user_id=42&tracking_id=abc123").decode()
    AGENT = "test-agent"
    CARTUID = "cart-uid-001"
    ISMYPRODUCT = True
    IP = "192.168.1.100"

    # SHA256 hash of "password;ID_I;ID_D"
    hash_string = f"{password};{ID_I};{ID_D}"
    SHA256 = hashlib.sha256(hash_string.encode()).hexdigest()

    payload = {
        "ID_I": ID_I,
        "ID_D": ID_D,
        "Amount": AMOUNT,
        "Currency": CURRENCY,
        "Email": EMAIL,
        "Date": DATE,
        "SHA256": SHA256,
        "Through": THROUGH,
        "IP": IP,
        "Agent": AGENT,
        "CartUID": CARTUID,
        "IsMyProduct": ISMYPRODUCT
    }

    # Change this to your real callback URL in production
    callback_url = request.build_absolute_uri("/digiseller/webhook-callback/")

    try:
        response = requests.post(callback_url, json=payload, timeout=10)
        return JsonResponse({
            "status": "Test payload sent",
            "sent_payload": payload,
            "response_status_code": response.status_code,
            "response_body": response.text
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    
    
    
# @csrf_exempt
# @require_POST
# def digiseller_webhook_callback(request):
#     try:
#         data = json.loads(request.body.decode("utf-8"))
#         print("🚀 Received Webhook Data:")
#         for key, value in data.items():
#             print(f"{key}: {value}")
        
#         # Future logic will go here (order validation, user linking, etc.)
#         return JsonResponse({"status": "Webhook received", "received_data": data})
    
#     except json.JSONDecodeError:
#         return HttpResponseBadRequest("Invalid JSON")


# @csrf_exempt
# @require_POST
# def digiseller_webhook_callback(request):
#     # 1) Parse incoming JSON
#     try:
#         data = json.loads(request.body.decode("utf-8"))
#     except json.JSONDecodeError:
#         return HttpResponseBadRequest("Invalid JSON")

#     order_id   = data.get("ID_I")
#     product_id = data.get("ID_D")

#     print("🚀 Received Webhook Data:", data)

#     # 2) If product not in our DB, skip
#     if not DigisellerProduct.objects.filter(id_goods=product_id).exists():
#         print("❌ Product not found, skipping.")
#         return JsonResponse({"status": "no action needed"})

#     # 3) Fetch the full purchase-info from Digiseller
#     token        = get_digiseller_token()
#     purchase_url = f"https://api.digiseller.com/api/purchase/info/{order_id}?token={token}"
#     resp         = requests.get(purchase_url, timeout=10)

#     if resp.status_code != 200:
#         return JsonResponse(
#             {"error": f"Digiseller info API returned {resp.status_code}"}, 
#             status=502
#         )

#     content = resp.json().get("content", {})

#     # 4) Validate that the Digiseller API's item_id matches our product_id
#     if content.get("item_id") != product_id:
#         print(f"❌ item_id ({content.get('item_id')}) != product_id ({product_id}), skipping.")
#         return JsonResponse({"status": "no action needed"})

#     # 5) Only proceed if unique_code_state.state == 1
#     if content.get("unique_code_state", {}).get("state") != 1:
#         print("❌ unique_code_state.state != 1, skipping.")
#         return JsonResponse({"status": "no action needed"})

#     # 6) Now process selected variants
#     product    = DigisellerProduct.objects.get(id_goods=product_id)
#     buyer_info = content.get("buyer_info", {})
#     quantity = content.get("cnt_goods", 1)

#     for opt in content.get("options", []):
#         user_data_id = opt.get("user_data_id")

#         try:
#             variant = DigisellerVariant.objects.get(
#                 product=product,
#                 variant_value=user_data_id
#             )
#         except DigisellerVariant.DoesNotExist:
#             continue

#         airalo_pkg = variant.airalo_package
#         if not airalo_pkg:
#             continue

#         # 🔍 For now, just print:
#         print("▶️ Airalo package ID:", airalo_pkg.package_id)

#         # Override buyer email for testing:
#         email = buyer_info.get("email")
#         # email = "ajayghosh28@gmail.com"   # ← uncomment to force

#         print("▶️ Buyer info:", {
#             "email": email,
#             "ip":     buyer_info.get("ip_address"),
#             "method": buyer_info.get("payment_method"),
#         })

#         # Optional: persist to your DigisellerOrder model here…

#     return JsonResponse({"status": "processed"})



@csrf_exempt
@require_POST
def digiseller_webhook_callback(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    try:
        handle_digiseller_webhook(payload)
    except SkipWebhook as exc:
        # Nothing to do for this event (invalid product, duplicate, etc.)
        print(f"ℹ️  {exc}")
        return JsonResponse({"status": "no action needed"})
    except Exception as exc:
        # Unexpected error – log & surface 5xx so Digiseller retries
        print(f"❗️ Internal error: {exc}")
        return JsonResponse({"error": "internal failure"}, status=500)

    return JsonResponse({"status": "processed"})


class SkipWebhook(Exception):
    """Raised when a webhook should be safely ignored (not an error)."""


def get_purchase_info(order_id: int, token: str) -> Dict:
    """Fetch purchase/info and raise for network / API failures."""
    url = f"https://api.digiseller.com/api/purchase/info/{order_id}?token={token}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json().get("content", {})


def validate_product(content: Dict, product_id: int) -> None:
    """Ensure product matches and unique_code_state == 1; else skip."""
    if content.get("item_id") != product_id:
        raise SkipWebhook("item_id does not match product_id")

    if content.get("unique_code_state", {}).get("state") != 1:
        raise SkipWebhook("unique_code_state.state != 1")


def find_matching_variants(
    product: DigisellerProduct,
    options: List[Dict]
) -> List[Tuple[DigisellerVariant, Package]]:
    """Return [(variant, airalo_package), …] for any matching user_data_id."""
    matches = []

    for opt in options:
        v_id = opt.get("user_data_id")
        try:
            variant = DigisellerVariant.objects.get(
                product=product, variant_value=v_id
            )
        except DigisellerVariant.DoesNotExist:
            continue

        if variant.airalo_package:
            matches.append((variant, variant.airalo_package))

    if not matches:
        raise SkipWebhook("No variants matched / mapped to Airalo packages")

    return matches


def handle_digiseller_webhook(payload: Dict) -> None:
    """
    Orchestrates the full processing flow; raises SkipWebhook when
    the event should be ignored and lets other exceptions propagate.
    """
    order_id   = payload.get("ID_I")
    product_id = payload.get("ID_D")

    product_qs = DigisellerProduct.objects.filter(id_goods=product_id)
    if not product_qs.exists():
        raise SkipWebhook("Product not found in DB")

    token    = get_digiseller_token()
    content  = get_purchase_info(order_id, token)
    validate_product(content, product_id)

    product      = product_qs.get()
    variants     = find_matching_variants(product, content.get("options", []))
    buyer_info   = content.get("buyer_info", {})
    quantity     = content.get("cnt_goods", 1)

    # --- For now just log; later call Airalo & persist order ---
    for variant, airalo_pkg in variants:
        print("▶️ Airalo package:", airalo_pkg.package_id)
        
        # save the digiseller order
        persist_and_queue(
            product, variant, airalo_pkg,
            buyer_info, quantity,
            content, order_id
        )
        
        email = buyer_info.get("email")
        # email = "ajayghosh28@gmail.com"  # ← test override
        print("▶️ Buyer info:", {
            "email":    email,
            "ip":       buyer_info.get("ip_address"),
            "method":   buyer_info.get("payment_method"),
            "quantity": quantity,
        })

        # create_digiseller_order(...)
        # queue_airalo_purchase(...)
        
        
def persist_and_queue(product, variant, airalo_pkg, buyer_info, quantity, content, order_id):
    """Create DigisellerOrder and enqueue Celery task."""
    # email = buyer_info.get("email")
    digiseller_order = DigisellerOrder.objects.create(
        order_id=order_id,
        product=product,
        variant=variant,
        airalo_package=airalo_pkg,
        quantity=quantity,
        buyer_email="ajayghosh28@gmail.com",   # FORCED for testing
        buyer_ip=buyer_info.get("ip_address"),
        buyer_payment_method=buyer_info.get("payment_method"),
        purchase_amount=content.get("amount"),
        purchase_currency=content.get("currency_type"),
        invoice_state=content.get("invoice_state"),
        raw_payload=content,
        status="received",
    )
    
    purchase_airalo_sim.delay(digiseller_order.id)
