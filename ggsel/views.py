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
from datetime import datetime
from django.db.models import Count
from django.views.decorators.csrf import csrf_exempt
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple
from django.http import HttpResponse
from django.utils import translation
import traceback
import base64
from django.conf import settings
import requests
import hashlib
import logging
import time
import json
import re
from esim.models import *
from ggsel.models import *
from airalo.tasks.airalo_tasks import(
    purchase_airalo_sim_for_ggsel,
    fetch_completed_orders,
    purchase_airalo_voucher_for_ggsel
)






logger = logging.getLogger(__name__)

# API Endpoints
GGSEL_TOKEN_CACHE_KEY = 'ggsel_token'
TOKEN_API_URL = "https://seller.ggsel.com/api_sellers/api/apilogin"
SELLER_GOODS_URL = "https://seller.ggsel.com/api_sellers/api/seller-goods"
PRODUCT_DETAIL_URL = "https://seller.ggsel.com/api_sellers/api/products/{product_id}/data"
GGSEL_BASE_API = "https://seller.ggsel.com"

SELLER_ID = settings.GGSEL_SELLER_ID
API_KEY = settings.GGSEL_API_KEY

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

# 1. Manage Digiseller token creation with caching
def get_ggsel_token():
    """
    Get a valid Digiseller token from cache or request a new one using their API.
    Retries on failure with exponential backoff.
    """
    token = cache.get(GGSEL_TOKEN_CACHE_KEY)
    if token:
        return token

    timestamp = int(time.time())
    signature = hashlib.sha256(f"{API_KEY}{timestamp}".encode('utf-8')).hexdigest()

    payload = {
        "seller_id": int(SELLER_ID),
        "timestamp": str(timestamp),
        "sign": str(signature)
    }
    
    print('payload in get token: ', payload)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"🔁 Attempt {attempt} to get Digiseller token")
            response = requests.post(TOKEN_API_URL, json=payload, timeout=10)
            response.raise_for_status()

            result = json.loads(response.content.decode('utf-8-sig'))

            if result.get("retval") != 0:
                raise Exception(f"Digiseller error {result.get('retval')}: {result.get('desc')}")

            token = result.get("token")
            valid_thru_str = result.get("valid_thru")

            if not token or not valid_thru_str:
                raise Exception("Token or valid_thru missing from response")

            valid_thru = parse_datetime(valid_thru_str)
            if valid_thru is None:
                raise Exception(f"Invalid valid_thru format: {valid_thru_str}")

            if valid_thru.tzinfo is None:
                valid_thru = timezone.make_aware(valid_thru, timezone.utc)

            now = timezone.now()
            ttl_seconds = int((valid_thru - now).total_seconds())
            if ttl_seconds <= 0:
                raise Exception("Received expired token")

            cache.set(GGSEL_TOKEN_CACHE_KEY, token, timeout=ttl_seconds)
            print("✅ Token obtained and cached: ", token)
            return token

        except Exception as e:
            logger.exception(f"❌ Attempt {attempt} failed to get token: {e}")
            if attempt == MAX_RETRIES:
                raise Exception(f"Failed to obtain Digiseller token after {MAX_RETRIES} attempts: {e}")
            else:
                time.sleep(RETRY_DELAY_SECONDS * attempt)  # exponential backoff
    

# 2. Fetch seller goods list with generated token
# def fetch_seller_goods(rows=1000, owner_id=1):
#     """
#     Fetch all seller goods from Digiseller API, handling pagination automatically.
#     Returns a list of all product rows.
#     """
#     token = get_ggsel_token()
#     all_products = []
#     page = 1
#     total_pages = 1  # Default fallback

#     try:
#         while page <= total_pages:
#             payload = {
#                 "id_seller": SELLER_ID,
#                 "order_col": "name",
#                 "order_dir": "asc",
#                 "rows": rows,
#                 "page": page,
#                 "currency": "RUR",
#                 "lang": "en-US",
#                 "show_hidden": 1,
#                 "owner_id": owner_id,
#             }

#             logger.info(f"📄 Fetching page {page} (rows={rows}, owner_id={owner_id})")
#             resp = requests.post(f"{SELLER_GOODS_URL}?token={token}", json=payload, timeout=20)
#             resp.raise_for_status()

#             text = resp.content.decode("utf-8-sig")
#             raw = json.loads(text)

#             if page == 1:
#                 total_pages = int(raw.get("pages", 1))
#                 logger.info(f"🧾 Total pages to fetch: {total_pages}")

#             page_rows = raw.get("rows", [])
#             all_products.extend(page_rows)

#             logger.info(f"✅ Page {page}/{total_pages} fetched: {len(page_rows)} items")

#             if not page_rows:
#                 logger.warning(f"⚠️ No data returned on page {page}, stopping early.")
#                 break

#             page += 1
#             time.sleep(1)  # Optional delay to avoid rate limiting

#         logger.info(f"🎯 Total products fetched: {len(all_products)}")
#         return all_products

#     except Exception as e:
#         logger.exception(f"fetch_seller_goods error: {e}")
#         GgselFailedEntry.objects.create(
#             reason=f"fetch_seller_goods error: {e}",
#             data={"owner_id": owner_id, "page": page},
#         )
#         return []


def fetch_seller_goods(rows=1000, owner_id=1, max_workers=8):
    """
    Fetch all seller goods from Digiseller API concurrently.
    Returns a list of all product rows.
    """
    logger.info(f"[fetch_seller_goods] START owner_id={owner_id}, rows={rows}, max_workers={max_workers}")
    token = get_ggsel_token()
    all_products = []
    page = 1
    total_pages = 1
    
    logger.info(f"[fetch_seller_goods] token acquired: {token[:8]}..." if token else "[fetch_seller_goods] token is empty/null")

    # First call just to get total pages
    try:
        logger.info(f"📄 Fetching first page to detect total page count...")
        payload = {
            "id_seller": SELLER_ID,
            "order_col": "name",
            "order_dir": "asc",
            "rows": rows,
            "page": page,
            "currency": "RUR",
            "lang": "en-US",
            "show_hidden": 1,
            "owner_id": owner_id,
        }
        logger.info(f"[fetch_seller_goods] first page payload: {payload}")
        
        resp = requests.post(f"{SELLER_GOODS_URL}?token={token}", json=payload, timeout=20)
        
        logger.info(f"[fetch_seller_goods] first page response status={resp.status_code}")
        logger.info(f"[fetch_seller_goods] first page raw response preview={resp.text[:500]}")
        
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig")
        
        logger.info(f"[fetch_seller_goods] first page decoded text preview={text[:500]}")
        
        raw = json.loads(text)

        total_pages = int(raw.get("pages", 1))
        first_page_rows = raw.get("rows", [])
        all_products.extend(first_page_rows)

        logger.info(f"🧾 Total pages detected: {total_pages}")
        logger.info(f"✅ Page 1 fetched with {len(first_page_rows)} items")

    except Exception as e:
        logger.exception(f"[fetch_seller_goods] Initial page fetch failed: {e}")
        return []

    # Helper function to fetch a single page
    def fetch_page(page_number):
        try:
            payload["page"] = page_number
            resp = requests.post(f"{SELLER_GOODS_URL}?token={token}", json=payload, timeout=20)
            resp.raise_for_status()
            text = resp.content.decode("utf-8-sig")
            raw = json.loads(text)
            rows = raw.get("rows", [])
            logger.info(f"✅ Page {page_number} fetched ({len(rows)} items)")
            return rows
        except Exception as e:
            logger.exception(f"⚠️ Error fetching page {page_number}: {e}")
            GgselFailedEntry.objects.create(
                reason=f"fetch_seller_goods page {page_number} error: {e}",
                data={"owner_id": owner_id, "page": page_number},
            )
            return []

    # Fetch remaining pages concurrently
    if total_pages > 1:
        logger.info(f"🚀 Fetching remaining {total_pages - 1} pages concurrently (max_workers={max_workers})")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_page, p): p for p in range(2, total_pages + 1)}
            for future in as_completed(futures):
                try:
                    rows = future.result()
                    all_products.extend(rows)
                except Exception as e:
                    logger.exception(f"Thread exception on page {futures[future]}: {e}")

    logger.info(f"🎯 Total products fetched: {len(all_products)}")
    return all_products

# 3. Filter products starting with 'esim' (case-insensitive)
def filter_esim_products(products):
    return [p for p in products if p.get("name_goods", "").lower().startswith("esim")]


# 4. Fetch detailed product variants
def fetch_product_variants(product_id):
    url = PRODUCT_DETAIL_URL.format(product_id=product_id)
    
    headers = {
        'Accept': 'application/json',
    }
    
    resp = requests.get(url, headers=headers, timeout=15)
    try:
        resp.raise_for_status()
        text = resp.content.decode('utf-8-sig')
        raw = json.loads(text)
        return raw.get("product", {}).get("options", [])
    except Exception as e:
        logger.exception(f"fetch_product_variants error (id {product_id}): {e}")
        GgselFailedEntry.objects.create(
            reason=f"fetch_product_variants error (id {product_id}): {e}",
            data={'product_id': product_id}
        )
        return []


# 5. Save product and its variants
def save_product_with_variants(prod_data):
    # Save product
    product, _ = GgselProduct.objects.update_or_create(
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
    # product.variants.all().delete()
    
    # Track current variant_values to find which to delete later
    updated_variant_values = set()

    # Create new variants
    options = fetch_product_variants(product.id_goods)
    first_option = next((opt for opt in options if opt.get("type") == "radio"), None)

    if first_option:
        for variant in first_option.get("variants", []):
            variant_value = variant.get("value")
            updated_variant_values.add(variant_value)

            try:
                # Create or update variant by variant_value
                GgselVariant.objects.update_or_create(
                    product=product,
                    variant_value=variant_value,
                    defaults={
                        "text": variant.get("text", ""),
                        "default": bool(variant.get("default")),
                        "modify": variant.get("modify"),
                        "modify_value": variant.get("modify_value"),
                        "modify_value_default": variant.get("modify_value_default"),
                        "modify_type": variant.get("modify_type"),
                        "visible": bool(variant.get("visible", 1)),
                    }
                )
            except Exception as e:
                logger.exception(f"variant save error (prod {product.id_goods}): {e}")
                GgselFailedEntry.objects.create(
                    reason=f"variant save error (prod {product.id_goods}): {e}",
                    data=variant
                )

    # Delete variants that are no longer present in the fetched data
    GgselVariant.objects.filter(
        product=product
    ).exclude(
        variant_value__in=updated_variant_values
    ).delete()

    return product

# 6. Main view to orchestrate the sync process
@api_view(["POST"])
@permission_classes([AllowAny])
def sync_ggsel_products(request):
    logger.info("[sync_ggsel_products] START")
    logger.info(f"[sync_ggsel_products] request.data={request.data}")

    try:
        owner_id = request.data.get("owner_id", 1)
        logger.info(f"[sync_ggsel_products] owner_id={owner_id}")

        raw_products = fetch_seller_goods(owner_id=owner_id)
        logger.info(f"[sync_ggsel_products] total fetched={len(raw_products)}")

        esim_products = filter_esim_products(raw_products)
        logger.info(f"[sync_ggsel_products] filtered eSIM products={len(esim_products)}")

        if esim_products:
            logger.info(
                f"[sync_ggsel_products] first 10 esim product ids="
                f"{[p.get('id_goods') for p in esim_products[:10]]}"
            )

        saved_ids = []
        for index, prod in enumerate(esim_products, start=1):
            logger.info(
                f"[sync_ggsel_products] processing {index}/{len(esim_products)} "
                f"id_goods={prod.get('id_goods')} name={prod.get('name_goods')}"
            )
            try:
                saved = save_product_with_variants(prod)
                saved_ids.append(saved.id_goods)
                logger.info(f"[sync_ggsel_products] saved product id_goods={saved.id_goods}")
            except Exception as e:
                logger.exception(f"[sync_ggsel_products] save_product error (id {prod.get('id_goods')}): {e}")
                GgselFailedEntry.objects.create(
                    reason=f"save_product error (id {prod.get('id_goods')}): {e}",
                    data=prod,
                )

        logger.info(f"[sync_ggsel_products] END success saved_count={len(saved_ids)}")
        return Response({"saved_product_ids": saved_ids}, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.exception(f"[sync_ggsel_products] Sync failed: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def variant_duplicate_texts(request):
    # Group by 'text', count how many times each appears, and filter where count > 1
    duplicates = (
        GgselVariant.objects
        .values('text')
        .annotate(text_count=Count('id'))
        .filter(text_count__gt=1)
    )

    response_data = {
        "total_duplicate_texts": duplicates.count(),
        "duplicates": list(duplicates)
    }

    return Response(response_data, status=status.HTTP_200_OK)



# @require_GET
# def digiseller_webhook_test(request):
#     # Dummy values to simulate Digiseller's behavior
#     password = "your_webhook_password".lower()
#     ID_I = 256070005
#     ID_D = 3498404
#     AMOUNT = 19.99
#     CURRENCY = "WMZ"
#     EMAIL = "ajayghosh28@gmail.com"
#     DATE = "2025-06-24 15:30:00"
#     THROUGH = base64.b64encode(b"user_id=42&tracking_id=abc123").decode()
#     AGENT = "test-agent"
#     CARTUID = "cart-uid-001"
#     ISMYPRODUCT = True
#     IP = "192.168.1.100"

#     # SHA256 hash of "password;ID_I;ID_D"
#     hash_string = f"{password};{ID_I};{ID_D}"
#     SHA256 = hashlib.sha256(hash_string.encode()).hexdigest()

#     payload = {
#         "ID_I": ID_I,
#         "ID_D": ID_D,
#         "Amount": AMOUNT,
#         "Currency": CURRENCY,
#         "Email": EMAIL,
#         "Date": DATE,
#         "SHA256": SHA256,
#         "Through": THROUGH,
#         "IP": IP,
#         "Agent": AGENT,
#         "CartUID": CARTUID,
#         "IsMyProduct": ISMYPRODUCT
#     }

#     # Change this to your real callback URL in production
#     callback_url = request.build_absolute_uri("/digiseller/webhook-callback/")

#     try:
#         response = requests.post(callback_url, json=payload, timeout=10)
#         return JsonResponse({
#             "status": "Test payload sent",
#             "sent_payload": payload,
#             "response_status_code": response.status_code,
#             "response_body": response.text
#         })
#     except Exception as e:
#         return JsonResponse({"error": str(e)}, status=500)
    
    
    
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
#     token        = get_ggsel_token()
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

#         # Optional: persist to your GgselOrder model here…

#     return JsonResponse({"status": "processed"})



# @csrf_exempt
# @require_POST
# def digiseller_webhook_callback(request):
#     try:
#         payload = json.loads(request.body.decode("utf-8"))
#         print('webhook payload: ', payload)
#     except json.JSONDecodeError:
#         return HttpResponseBadRequest("Invalid JSON")

#     try:
#         handle_digiseller_webhook(payload)
#     except SkipWebhook as exc:
#         # Nothing to do for this event (invalid product, duplicate, etc.)
#         print(f"ℹ️  {exc}")
#         return JsonResponse({"status": "no action needed"})
#     except Exception as exc:
#         # Unexpected error – log & surface 5xx so Digiseller retries
#         print(f"❗️ Internal error: {exc}")
#         return JsonResponse({"error": "internal failure"}, status=500)

#     return JsonResponse({"status": "processed"})


class SkipWebhook(Exception):
    """Raised when a webhook should be safely ignored (not an error)."""
    
    
# @require_GET
# def digiseller_deliver(request):
#     code = request.GET.get("uniquecode")
#     if not code:
#         return HttpResponseBadRequest("Missing code")

#     # 1. Call the Digiseller “unique‑code” API to fetch its content,
#     #    including inv (your order_id) and unique_code_state.state.
#     verify_unique_code_and_get_info(code)
#     # data = verify_unique_code_and_get_info(code)
#     # if data["unique_code_state"]["state"] != 1:
#     #     return HttpResponse("Payment not confirmed", status=402)

#     # 5. Redirect buyer to your thank‑you page
#     # return HttpResponseRedirect("/thank-you/")
#     return render(request, "order_confirmation/order_confirmation.html", {
#         "code": code
#     })


# @require_GET
# def ggseller_deliver(request):
#     # 1️⃣ Handle language
#     lang = request.GET.get('lang', 'ru')
#     if lang not in dict(settings.LANGUAGES):
#         lang = 'ru'
#     translation.activate(lang)
#     request.LANGUAGE_CODE = lang

#     # 2️⃣ Extract GET parameters
#     id_i = request.GET.get("id_i")  # order ID
#     id_d = request.GET.get("id_d")
#     amount = request.GET.get("amount")
#     currency = request.GET.get("curr")
#     date = request.GET.get("date")
#     email = request.GET.get("email")
#     sha256 = request.GET.get("sha256")
#     ip = request.GET.get("ip")
#     is_my_product = request.GET.get("isMyProduct")

#     print("🔍 Received parameters:", {
#         "id_i": id_i,
#         "id_d": id_d,
#         "amount": amount,
#         "currency": currency,
#         "date": date,
#         "email": email,
#         "sha256": sha256,
#         "ip": ip,
#         "isMyProduct": is_my_product,
#     })

#     # 3️⃣ Validate required params
#     if not id_i or not id_d:
#         return HttpResponseBadRequest("Missing required parameters: id_i or id_d")

#     order_id = int(id_i)

#     # 4️⃣ Save failed order record if not exists
#     failed_order, created = GgselFailedOrder.objects.get_or_create(
#         order_id=order_id,
#         defaults={"status": "pending"}
#     )

#     # 5️⃣ Handle webhook
#     try:
#         ggsel_order = handle_ggseller_webhook(request.GET, order_id)
#     except SkipWebhook as exc:
#         failed_order.status = "skipped"
#         failed_order.save(update_fields=["status"])
#         return HttpResponse(f"Order ignored: {exc}", status=200)
#     except Exception as exc:
#         failed_order.status = "error"
#         failed_order.save(update_fields=["status"])
#         return HttpResponse(f"Server error: {exc}", status=500)

#     failed_order.status = "success"
#     failed_order.save(update_fields=["status"])

#     # 6️⃣ Extract variant & validity
#     variant = ggsel_order.variant
#     package = variant.airalo_package if variant else None

#     validity = None
#     if package and package.package_id:
#         for part in package.package_id.split("-"):
#             if "day" in part.lower():
#                 try:
#                     number = int(part.lower().replace("days", "").replace("day", ""))
#                     validity = f"{number} Days"
#                     break
#                 except ValueError:
#                     pass

#     # 7️⃣ Load ads
#     purchase_discount_ad = PurchaseDiscountAd.objects.filter(is_active=True).last()
#     travel_guide_ad = TravelGuideAd.objects.filter(is_active=True).last()
#     selected_product_ad = SelectedProductAd.objects.filter(is_active=True).last()
#     social_media_ad = SocialMediaAd.objects.filter(is_active=True).last()
#     sponsor_ad = SponsorAd.objects.filter(is_active=True).last()
#     product_ad_items = selected_product_ad.items.all() if selected_product_ad else []

#     # 8️⃣ Build context
#     context = {
#         'current_lang': lang,
#         'available_langs': settings.LANGUAGES,
#         "order_id": ggsel_order.order_id,
#         "product": ggsel_order.product,
#         "variant": ggsel_order.variant.text,
#         "quantity": ggsel_order.quantity,
#         "purchase_amount": amount or ggsel_order.purchase_amount,
#         "purchase_currency": currency or ggsel_order.purchase_currency,
#         "purchase_date": date or ggsel_order.purchase_date,
#         "email": email,
#         "ip": ip,
#         "sha256": sha256,
#         "validity": validity,
#         "is_my_product": is_my_product,
#         "purchase_discount_ad": purchase_discount_ad,
#         "travel_guide_ad": travel_guide_ad,
#         "selected_product_ad": selected_product_ad,
#         "social_media_ad": social_media_ad,
#         "sponsor_ad": sponsor_ad,
#         'product_ad_items': product_ad_items
#     }

#     return render(request, "order_confirmation/order_confirmation.html", context)


@require_GET
def ggseller_deliver(request):
    lang = request.GET.get('lang', 'ru')
    if lang not in dict(settings.LANGUAGES):
        lang = 'ru'

    # 2) Activate it
    translation.activate(lang)
    request.LANGUAGE_CODE = lang
    
    print("DEBUG: GET params =", dict(request.GET))
    
    lang = request.GET.get('lang', 'ru')
    print("DEBUG: requested lang =", lang)
    
    code = request.GET.get("uniquecode")
    print('---------unique code--------', code)
    if not code:
        return HttpResponseBadRequest("Missing code")
    
    # Save failed order record early
    if not GgselFailedOrder.objects.filter(unique_code=code).exists():
        failed_order, created = GgselFailedOrder.objects.get_or_create(
            unique_code=code,
            defaults={"status": "pending"}
        )

    try:
        digiseller_order = verify_unique_code_and_get_info(code)
    except SkipWebhook as exc:
        GgselFailedOrder.objects.filter(unique_code=code).update(status="skipped")
        return HttpResponse(f"Order ignored: {exc}", status=200)
    except Exception as exc:
        GgselFailedOrder.objects.filter(unique_code=code).update(status="error")
        return HttpResponse(f"Server error: {exc}", status=500)
    
    variant = digiseller_order.variant
    package = variant.airalo_package if variant else None
    
    # Extract validity from package_id
    validity = None
    if package and package.package_id:
        parts = package.package_id.split("-")
        for part in parts:
            if "day" in part.lower():
                try:
                    number = int(part.lower().replace("days", "").replace("day", ""))
                    validity = f"{number} Days"
                    break
                except ValueError:
                    pass
                
    # Get last active instances of all ad models
    purchase_discount_ad = PurchaseDiscountAd.objects.filter(is_active=True).last()
    travel_guide_ad = TravelGuideAd.objects.filter(is_active=True).last()
    selected_product_ad = SelectedProductAd.objects.filter(is_active=True).last()
    social_media_ad = SocialMediaAd.objects.filter(is_active=True).last()
    sponsor_ad = SponsorAd.objects.filter(is_active=True).last()
    
    product_ad_items = selected_product_ad.items.all() if selected_product_ad else []

    context = {
        'current_lang': lang,
        'available_langs': settings.LANGUAGES,
        "order_id": digiseller_order.order_id,
        "product": digiseller_order.product,
        "variant": digiseller_order.variant.text,
        "quantity": digiseller_order.quantity,
        "purchase_amount": digiseller_order.purchase_amount,
        "purchase_currency": digiseller_order.purchase_currency,
        "purchase_date": digiseller_order.purchase_date,
        "unique_code": digiseller_order.unique_code,
        "validity": validity,
        
        "purchase_discount_ad": purchase_discount_ad,
        "travel_guide_ad": travel_guide_ad,
        "selected_product_ad": selected_product_ad,
        "social_media_ad": social_media_ad,
        "sponsor_ad": sponsor_ad,
        'product_ad_items': product_ad_items
    }

    return render(request, "order_confirmation/order_confirmation.html", context)


def verify_unique_code_and_get_info(code: str) -> Dict:
    token = get_ggsel_token()
    url = f"{GGSEL_BASE_API}/api_sellers/api/purchases/unique-code/{code}?token={token}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    data = resp.json()

    inv = data.get("inv")
    id_goods = data.get("id_goods")

    if not inv or inv == 0:
        raise ValueError(f"Invalid or missing 'inv' in Digiseller response: {inv}")
    if not id_goods or id_goods == 0:
        raise ValueError(f"Invalid or missing 'id_goods' (product ID) in Digiseller response: {id_goods}")

    try:
        ggsel_order = handle_ggseller_webhook(data, code)
    except SkipWebhook as exc:
        # Nothing to do for this event (invalid product, duplicate, etc.)
        print(f"ℹ️  {exc}")
        raise  # Let it propagate so you can handle it in the view
    except Exception as exc:
        # Unexpected error – log & surface 5xx so Digiseller retries
        print(f"❗️ Internal error: {exc}")
        raise


    return ggsel_order


def get_purchase_info(order_id: int, token: str) -> Dict:
    """Fetch purchase/info and raise for network / API failures."""
    url = f"{GGSEL_BASE_API}/api_sellers/api/purchase/info/{order_id}?token={token}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json().get("content", {})


def validate_product(content: Dict, product_id: int, order_id: int) -> None:
    """Ensure product matches and unique_code_state == 1; else skip."""
    if content.get("item_id") != product_id:
        raise SkipWebhook("item_id does not match product_id")

    # if content.get("unique_code_state", {}).get("state") != 1:
    #     update_ggsel_order(order_id, content.get("unique_code_state", {}).get("state"))
    #     raise SkipWebhook("unique_code_state.state != 1")


def find_matching_variants(
        product: GgselProduct,
        options: List[Dict]
    ) -> List[Tuple[GgselVariant, Package]]:
    """Return [(variant, airalo_package), …] for any matching user_data_id."""
    matches = []

    for opt in options:
        v_id = opt.get("user_data_id")
        try:
            variant = GgselVariant.objects.get(
                product=product, variant_value=v_id
            )
        except GgselVariant.DoesNotExist:
            continue

        if variant.airalo_package:
            matches.append((variant, variant.airalo_package))

    if not matches:
        raise SkipWebhook("No variants matched / mapped to Airalo packages")

    return matches


def handle_ggseller_webhook(data: dict, code):
    """
    Processes a Ggsel order webhook and creates or updates the GgselOrder entry.
    Raises SkipWebhook if the event should be ignored.
    """
    order_id   = data.get("inv")
    product_id = data.get("id_goods")
    

    product_qs = GgselProduct.objects.filter(id_goods=product_id)
    if not product_qs.exists():
        raise SkipWebhook("Product not found in DB")

    token = get_ggsel_token()
    content = get_purchase_info(order_id, token)
    validate_product(content, product_id, order_id)

    product = product_qs.get()
    variants = find_matching_variants(product, content.get("options", []))
    buyer_info = content.get("buyer_info", {})
    quantity = content.get("cnt_goods", 1)
    purchase_date_raw = content.get("purchase_date", '')

    for variant, airalo_pkg in variants:
        print("▶️ Airalo package:", airalo_pkg.package_id)
        ggsel_order = persist_and_queue(
            product, variant, airalo_pkg,
            buyer_info, quantity,
            content, order_id, purchase_date_raw, code=order_id
        )

        print("▶️ Buyer info:", {
            "email": buyer_info.get("email"),
            "ip": buyer_info.get("ip_address"),
            "method": buyer_info.get("payment_method"),
            "quantity": quantity,
        })

        return ggsel_order


        # create_ggsel_order(...)
        # queue_airalo_purchase(...)
        
        
def persist_and_queue(product, variant, airalo_pkg, buyer_info, quantity, content, order_id, purchase_date_raw, code):
    """Create GgselOrder and enqueue Celery task."""
    try:
        # If the order already exists, no need to recreate it
        ggsel_order = GgselOrder.objects.get(order_id=order_id)
        GgselFailedOrder.objects.filter(order_id=order_id).delete()
        return ggsel_order
    except GgselOrder.DoesNotExist:
        pass  # Proceed to create the order

    # Parse purchase_date string (e.g., "29.05.2025 8:49:40")
    try:
        purchase_date = datetime.strptime(purchase_date_raw, "%d.%m.%Y %H:%M:%S")
        if timezone.is_naive(purchase_date):
            purchase_date = timezone.make_aware(purchase_date)
    except (ValueError, TypeError):
        purchase_date = None  # Fallback if parsing fails

    # Create new order
    ggsel_order = GgselOrder.objects.create(
        order_id=order_id,
        product=product,
        variant=variant,
        airalo_package=airalo_pkg,
        quantity=quantity,
        buyer_email=buyer_info.get("email"),
        buyer_ip=buyer_info.get("ip_address"),
        buyer_payment_method=buyer_info.get("payment_method"),
        purchase_amount=content.get("amount"),
        purchase_currency=content.get("currency_type"),
        invoice_state=content.get("invoice_state"),
        purchase_date=purchase_date,
        ggsel_transaction_status=content.get("unique_code_state", {}).get("state", 1),
        raw_payload=content,
        status="received",
        unique_code=code  # keep this field for GgselOrder (still in model)
    )

    # Enqueue the Celery background task
    # purchase_airalo_sim_for_ggsel.delay(ggsel_order.id)
    mode = getattr(settings, "AIRALO_FULFILLMENT_MODE", "order")
    logger.info("📦 persist_and_queue: fulfillment_mode=%s order_id=%s", mode, ggsel_order.order_id)

    if mode == "voucher":
        purchase_airalo_voucher_for_ggsel.delay(ggsel_order.id)
        logger.info("📦 persist_and_queue: queued voucher task ggsel_order_id=%s", ggsel_order.id)
    else:
        purchase_airalo_sim_for_ggsel.delay(ggsel_order.id)
        logger.info("📦 persist_and_queue: queued SIM order task ggsel_order_id=%s", ggsel_order.id)

    # Remove any failed-order record for this order
    GgselFailedOrder.objects.filter(order_id=order_id).delete()

    # Retry any remaining failed orders (optional but useful)
    if GgselFailedOrder.objects.exists():
        from digiseller.tasks.task import retry_all_failed_orders
        retry_all_failed_orders.delay()

    return ggsel_order

    
def update_ggsel_order(order_id: int, status: int) -> None:
    """Update only the digiseller_transaction_status field of an existing order."""

    try:
        order = GgselOrder.objects.get(id=order_id)
        order.digiseller_transaction_status = status
        order.save(update_fields=['ggsel_transaction_status'])
        print(f"Updated order {order_id} with status {status}")
    except GgselOrder.DoesNotExist:
        pass  # Or handle/log error appropriately



@require_GET
def order_sample(request):
    lang = request.GET.get('lang', 'ru')
    if lang not in dict(settings.LANGUAGES):
        lang = 'ru'

    # 2) Activate it
    translation.activate(lang)
    request.LANGUAGE_CODE = lang
    
    print("DEBUG: GET params =", dict(request.GET))
    
    lang = request.GET.get('lang', 'ru')
    print("DEBUG: requested lang =", lang)
    
    code = request.GET.get("uniquecode")
    print('---------unique code--------', code)
    if not code:
        return HttpResponseBadRequest("Missing code")
    
    # Save failed order record early
    if not GgselOrder.objects.filter(unique_code=code).exists():
        failed_order, created = GgselFailedOrder.objects.get_or_create(
            unique_code=code,
            defaults={"status": "pending"}
        )

    try:
        ggsel_order = verify_unique_code_and_get_info(code)
    except SkipWebhook as exc:
        GgselFailedOrder.objects.filter(unique_code=code).update(status="skipped")
        return HttpResponse(f"Order ignored: {exc}", status=200)
    except Exception as exc:
        GgselFailedOrder.objects.filter(unique_code=code).update(status="error")
        return HttpResponse(f"Server error: {exc}", status=500)
    
    variant = ggsel_order.variant
    package = variant.airalo_package if variant else None
    
    # Extract validity from package_id
    validity = None
    if package and package.package_id:
        parts = package.package_id.split("-")
        for part in parts:
            if "day" in part.lower():
                try:
                    number = int(part.lower().replace("days", "").replace("day", ""))
                    validity = f"{number} Days"
                    break
                except ValueError:
                    pass
                
    # Get last active instances of all ad models
    purchase_discount_ad = PurchaseDiscountAd.objects.filter(is_active=True).last()
    travel_guide_ad = TravelGuideAd.objects.filter(is_active=True).last()
    selected_product_ad = SelectedProductAd.objects.filter(is_active=True).last()
    social_media_ad = SocialMediaAd.objects.filter(is_active=True).last()
    sponsor_ad = SponsorAd.objects.filter(is_active=True).last()
    
    product_ad_items = selected_product_ad.items.all() if selected_product_ad else []

    context = {
        'current_lang': lang,
        'available_langs': settings.LANGUAGES,
        "order_id": ggsel_order.order_id,
        "product": ggsel_order.product,
        "variant": ggsel_order.variant.text,
        "quantity": ggsel_order.quantity,
        "purchase_amount": ggsel_order.purchase_amount,
        "purchase_currency": ggsel_order.purchase_currency,
        "purchase_date": ggsel_order.purchase_date,
        "unique_code": ggsel_order.unique_code,
        "validity": validity,
        
        "purchase_discount_ad": purchase_discount_ad,
        "travel_guide_ad": travel_guide_ad,
        "selected_product_ad": selected_product_ad,
        "social_media_ad": social_media_ad,
        "sponsor_ad": sponsor_ad,
        'product_ad_items': product_ad_items
    }
    
    print('context on order confirmation page')

    return render(request, "order_confirmation/order_sample.html", context)
