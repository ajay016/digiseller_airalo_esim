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