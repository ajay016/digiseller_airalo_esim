from django.shortcuts import render,redirect
from django.contrib import messages
from django.http.response import HttpResponseRedirect
from django.utils import timezone
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
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

from django.conf import settings
import requests
import hashlib
import time
import json
import re
from esim.models import *







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
    first_option = options[0] if options else None

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
