from django.shortcuts import render,redirect
from django.contrib import messages
from django.http.response import HttpResponseRedirect
from django.utils import timezone
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from django.contrib.auth import login, logout, authenticate
from rest_framework.decorators import api_view
from django.http import JsonResponse
from rest_framework import status
from datetime import timedelta
from django.utils.dateparse import parse_datetime
from django.core.cache import cache
from rest_framework.response import Response
from django.db.models import Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.db.models import Count
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from esim.utils import digiseller_stats as ds
from django.db.models.functions import TruncMonth
from esim.utils import airalo_stats as airalo_stats
from ggsel.models import *
from django.db import transaction
from django.conf import settings
import requests
import hashlib
import time
import json
import re
from .models import *
import traceback
from esim.tasks import sync_esimaccess_packages_task


def is_valid_email(email):
    """Simple regex for email validation"""
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)


@login_required
def dashboard(request):
    buyer_stats, total_unique_buyers = ds.get_unique_buyer_stats()
    monthly_stats = ds.get_monthly_digiseller_stats()
    recent_orders = ds.get_recent_orders()

    context = {
        'total_unique_buyers': total_unique_buyers,
        'buyer_stats': buyer_stats,
        'monthly_totals': json.dumps(monthly_stats["monthly_totals"]),
        'sales_per_month': json.dumps(monthly_stats["sales_per_month"]),  # now contains total amounts
        'failed_orders_per_month': json.dumps(monthly_stats["failed_orders_per_month"]),
        'recent_orders': recent_orders,
    }
    return render(request, 'index.html', context)


def monthly_order_totals(request):
    data = (
        DigisellerOrder.objects
        .filter(purchase_date__isnull=False)
        .annotate(month=TruncMonth('purchase_date'))
        .values('month')
        .annotate(total_amount=Sum('purchase_amount'))
        .order_by('month')
    )
    
    print("Monthly Order Totals Data:", data)

    monthly_data = [0] * 12  # Initialize for Jan–Dec

    for entry in data:
        month_index = entry['month'].month - 1  # Jan = 0
        monthly_data[month_index] = round(entry['total_amount'] or 0, 2)

    return JsonResponse({'monthly_totals': monthly_data})


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        # Authenticate using email as username (ensure email is unique)
        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)
            return redirect('dashboard')  # Change 'home' to your main page name
        else:
            messages.error(request, "Invalid email or password")

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('login')  # redirect to your login page


def sync_data(request):
    stats = airalo_stats.get_package_operator_stats()
    product_stats = ds.get_digiseller_product_variant_stats()
    from django.db.models import Count, Q, Min, Max, Avg

    # Basic package stats
    esim_total_packages = Package.objects.filter(provider='esimaccess').count()
    esim_active_packages = Package.objects.filter(provider='esimaccess').count()
    esim_inactive_packages = Package.objects.filter(provider='esimaccess').count()

    # Variant stats
    esim_with_variant = Package.objects.filter(
        provider='esimaccess',
        digiseller_variants__isnull=False
    ).distinct().count()

    esim_without_variant = esim_total_packages - esim_with_variant

    # Country and operator stats
    esim_countries = Package.objects.filter(
        provider='esimaccess'
    ).values('operator__country__title').distinct().count()

    esim_operators = Package.objects.filter(
        provider='esimaccess'
    ).values('operator').distinct().count()

    # Price stats
    esim_price_stats = Package.objects.filter(
        provider='esimaccess'
    ).aggregate(
        min_price=Min('price'),
        max_price=Max('price'),
        avg_price=Avg('price')
    )

    # Unlimited packages
    esim_unlimited_packages = Package.objects.filter(
        provider='esimaccess',
        is_unlimited=True
    ).count()

    # Create comprehensive stats dictionary
    esim_stats = {
        "total_packages": esim_total_packages,
        "active_packages": esim_active_packages,
        "inactive_packages": esim_inactive_packages,
        "packages_with_variant": esim_with_variant,
        "packages_without_variant": esim_without_variant,
        "total_countries": esim_countries,
        "total_operators": esim_operators,
        "min_price": esim_price_stats['min_price'],
        "max_price": esim_price_stats['max_price'],
        "avg_price": round(esim_price_stats['avg_price'], 2) if esim_price_stats['avg_price'] else 0,
        "unlimited_packages": esim_unlimited_packages,
    }

    context = {
        "total_operators": stats["total_operators"],
        "total_packages": stats["total_packages"],
        "packages_with_variant": stats["packages_with_variant"],
        "packages_without_variant": stats["packages_without_variant"],

        # Product/variant stats
        "total_products": product_stats["total_products"],
        "total_variants": product_stats["total_variants"],
        "variants_with_package": product_stats["variants_with_package"],
        "variants_without_package": product_stats["variants_without_package"],

        "esim_total_packages": esim_stats["total_packages"],
        "esim_active_packages": esim_stats["active_packages"],
        "esim_inactive_packages": esim_stats["inactive_packages"],
        "esim_packages_with_variant": esim_stats["packages_with_variant"],
        "esim_packages_without_variant": esim_stats["packages_without_variant"],
        "esim_total_countries": esim_stats["total_countries"],
        "esim_total_operators": esim_stats["total_operators"],
        "esim_min_price": esim_stats["min_price"],
        "esim_max_price": esim_stats["max_price"],
        "esim_avg_price": esim_stats["avg_price"],
        "esim_unlimited_packages": esim_stats["unlimited_packages"],
        "esim_stats": esim_stats,
    }

    return render(request, 'sync_data/sync_data.html', context)

def sync_esimaccess_data(request):
    """
    Sync packages from eSIM Access API
    """
    import logging
    from django.http import JsonResponse
    
    logger = logging.getLogger(__name__)
    
    try:
        # Check if this is a status check request
        task_id = request.GET.get('task_id')
        if task_id:
            # Since tasks run synchronously in development, they complete immediately
            # So we can return completed status
            return JsonResponse({
                'status': 'completed',
                'message': 'Task completed successfully'
            })
        
        # Start the Celery task - in eager mode this runs immediately
        task = sync_esimaccess_packages_task.delay()
        
        # In eager mode, the task is already done when we get here
        return JsonResponse({
            'success': True,
            'message': 'eSIM Access sync completed successfully',
            'task_id': task.id,
            'status': 'completed'  # Add this to indicate completion
        })
        
    except Exception as e:
        logger.error(f"Error starting eSIM Access sync: {str(e)}")
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def digiseller_products(request, market_id=None):
    if market_id:
        digiseller_products = DigisellerProduct.objects.filter(market__market_id=market_id)
    else:
        digiseller_products = DigisellerProduct.objects.all()
    
    context = {
        'digiseller_products': digiseller_products,
    }
    return render(request, 'digiseller/digiseller_products.html', context)

@login_required
def digiseller_product(request, id):
    digiseller_product = get_object_or_404(DigisellerProduct, id=id)
    variants = digiseller_product.variants.all()
    
    countries = Country.objects.all().order_by('title')
    operator_countries = OperatorCountry.objects.all()

    selected_country_id = request.GET.get('country')
    selected_operator_id = request.GET.get('operator')

    selected_country = countries.filter(id=selected_country_id).first() if selected_country_id else countries.first()
    selected_operator = Operator.objects.filter(id=selected_operator_id).first() if selected_operator_id else None

    # Fetch packages based on filters (both Airalo and ESIM Access)
    packages = Package.objects.select_related('operator', 'operator__country')

    if selected_country:
        packages = packages.filter(operator__country=selected_country)

    if selected_operator:
        packages = packages.filter(operator=selected_operator)

    context = {
        'digiseller_product': digiseller_product,
        'variants': variants,
        'countries': countries,
        'operator_countries': operator_countries,
        'operators': Operator.objects.all().order_by('title'),
        'selected_country_id': selected_country.id if selected_country else None,
        'selected_country_title': selected_country.title if selected_country else '',
        'selected_operator_id': selected_operator.id if selected_operator else None,
        'packages': packages.order_by('-price'),
        'providers': PackageProvider.choices,
    }
    return render(request, 'digiseller/digiseller_product.html', context)


@login_required
def get_packages_by_region(request):
    """Fetch packages filtered by country or region with optional provider filter"""
    country_id = request.GET.get('country')
    operator_country_id = request.GET.get('region')
    provider = request.GET.get('provider')  # New: filter by provider
    
    packages = Package.objects.select_related('operator', 'operator__country')

    if operator_country_id:
        packages = packages.filter(operator__available_countries__id=operator_country_id)
    elif country_id:
        packages = packages.filter(operator__country_id=country_id)
    
    # Apply provider filter if specified
    if provider:
        packages = packages.filter(provider=provider)

    packages = packages.order_by('-price')
    
    html = render_to_string('digiseller/includes/package_cards.html', {'packages': packages})
    return JsonResponse({'html': html})


# @require_POST
# def update_variants(request):
#     # iterate over all POST keys looking for those that set the airalo_package
#     for key, val in request.POST.items():
#         m = re.match(r'^variant_airalo_package_(\d+)$', key)
#         if not m:
#             continue
#         variant_id = m.group(1)
#         package_id = val or None  # blank ==> None

#         # update that variant
#         try:
#             variant = DigisellerVariant.objects.get(pk=variant_id)
#         except DigisellerVariant.DoesNotExist:
#             continue

#         # assign the FK (Django lets you assign the PK directly)
#         variant.airalo_package_id = package_id
#         variant.save(update_fields=['airalo_package'])
#     # then redirect (or re‑render the page with a success message)
#     return redirect('digiseller_product')

@require_POST
def update_variants(request):
    try:
        data = json.loads(request.body)
        assignments = data.get('assignments', {})
        for variant_id, pkg_id in assignments.items():
            variant = DigisellerVariant.objects.filter(pk=variant_id).first()
            if not variant:
                continue
            variant.airalo_package_id = pkg_id
            variant.save(update_fields=['airalo_package'])
        # explicit 200 OK on success
        return JsonResponse({
            'success': True,
            'message': 'Airalo Packages updated successfully!'
        }, status=200)
    except Exception as e:
        # HTTP 400 on any error
        return JsonResponse({
            'success': False,
            'error': f'Failed to update: {e}'
        }, status=400)

# def get_packages_by_region(request):
#     country_id = request.GET.get('country')
#     operator_country_id = request.GET.get('region')

#     packages = Package.objects.select_related('operator', 'operator__country')

#     if operator_country_id:
#         packages = packages.filter(operator__available_countries__id=operator_country_id)
#     elif country_id:
#         packages = packages.filter(operator__country_id=country_id)

#     data = [
#         {
#             'id': p.id,
#             'operator_title': p.operator.title,
#             'country_title': p.operator.country.title,
#             'data': p.data,
#             'day': p.day,
#             'price': p.price
#         }
#         for p in packages
#     ]
    
#     print("Country ID:", country_id)
#     print("Operator Country ID:", operator_country_id)
#     print("Packages found:", packages.count())
    
#     return JsonResponse({'packages': data})


def digiseller_deliver(request):
    """
    Handles Digiseller redirect with ?uniquecode=...
    Also extracts and logs all other query parameters.
    """
    code = request.GET.get('uniquecode')

    # Get all query parameters as a dictionary
    all_params = request.GET.dict()


    # Continue with your logic...
    return render(request, 'digiseller/digiseller_deliver.html', {'code': code})



def order_sample(request):
    return render(request, 'order/order_sample.html', )

    
    
def social_media_links(request):
    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        action = data.get('action')

        if action == 'add':
            title = data.get('title')
            description = data.get('description')
            is_active = data.get('is_active', False)
            telegram = data.get('telegram_link')
            facebook = data.get('facebook_link')
            instagram = data.get('instagram_link')
            youtube = data.get('youtube_link')

            if not title or not telegram:
                return JsonResponse({'status': 'error', 'message': 'Title and Telegram link are required.'})

            SocialMediaAd.objects.create(
                title=title,
                description=description,
                is_active=bool(is_active),
                telegram_link=telegram,
                facebook_link=facebook,
                instagram_link=instagram,
                youtube_link=youtube
            )
            return JsonResponse({'status': 'success', 'message': 'Ad added successfully.'})

        elif action == 'edit':
            ad_id = data.get('id')
            title = data.get('title')
            description = data.get('description')
            is_active = data.get('is_active')
            telegram = data.get('telegram_link')
            facebook = data.get('facebook_link')
            instagram = data.get('instagram_link')
            youtube = data.get('youtube_link')

            if not ad_id or not title or not telegram:
                return JsonResponse({'status': 'error', 'message': 'Title and Telegram link are required.'})

            try:
                ad = SocialMediaAd.objects.get(id=ad_id)
                ad.title = title
                ad.description = description
                ad.is_active = is_active == "true"
                ad.telegram_link = telegram
                ad.facebook_link = facebook
                ad.instagram_link = instagram
                ad.youtube_link = youtube
                ad.save()
                return JsonResponse({'status': 'success', 'message': 'Ad updated successfully.'})
            except SocialMediaAd.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Ad not found.'})

        elif action == 'delete':
            ad_id = data.get('id')
            try:
                SocialMediaAd.objects.get(id=ad_id).delete()
                return JsonResponse({'status': 'success', 'message': 'Ad deleted successfully.'})
            except SocialMediaAd.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Ad not found.'})

    else:
        ads = SocialMediaAd.objects.all()
        return render(request, 'advertisements/social_media_links.html', {'social_ads': ads})
    
    

def product_ad(request):
    ads = SelectedProductAd.objects.all()
    products = DigisellerProduct.objects.all()
    
    context = {
        'selected_product_ads': ads,
        'products': products,
    }
    
    return render(request, 'advertisements/product_ad.html', context)


def get_product_items(request, ad_id):
    items = ProductAdItem.objects.filter(advertisement_id=ad_id).select_related('product')
    
    data = []
    for item in items:
        data.append({
            "id": item.id,
            "product_id": item.product.id if item.product else None,
            "product_name": item.product.name_goods if item.product else "",
            "display_name": item.display_name or (item.product.name_goods if item.product else ""),
            "product_url": item.product_url or "",
        })
    
    return JsonResponse({"items": data})

    
@require_POST
def add_selected_product_ad(request):
    try:
        # Start an atomic transaction so we don't create a half-finished ad
        with transaction.atomic():
            # 1. Basic ad fields
            title = request.POST.get('title', '').strip()
            if not title:
                return JsonResponse({'status': 'error', 'message': 'Title is required.'})
            description = request.POST.get('description', '').strip()
            # Note: unchecked checkboxes don’t appear in POST
            is_active = request.POST.get('is_active') == 'on'

            ad = SelectedProductAd.objects.create(
                title=title,
                description=description,
                is_active=is_active
            )

            # 2. Loop through each product row
            products       = request.POST.getlist('products[]')
            display_names  = request.POST.getlist('display_names[]')
            product_urls   = request.POST.getlist('product_urls[]')

            for prod_id, disp_name, url in zip(products, display_names, product_urls):
                # skip entirely blank rows
                if not prod_id and not disp_name.strip() and not url.strip():
                    continue

                # try to fetch the linked product, if any
                product = None
                if prod_id:
                    try:
                        product = DigisellerProduct.objects.get(pk=prod_id)
                    except DigisellerProduct.DoesNotExist:
                        # you could return an error here instead if you prefer
                        product = None

                ProductAdItem.objects.create(
                    advertisement=ad,
                    product=product,
                    display_name=disp_name.strip() or None,
                    product_url=url.strip() or None
                )

        return JsonResponse({
            'status': 'success',
            'message': 'Advertisement created successfully.'
        })

    except Exception as e:
        # Log e if you want, then surface a friendly error
        return JsonResponse({
            'status': 'error',
            'message': f'An unexpected error occurred: {e}'
        })
        
        
def edit_selected_product_ad(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)

    try:
        data = json.loads(request.body)

        ad_id = data.get("id")
        title = data.get("title", "").strip()
        description = data.get("description", "").strip()
        is_active = data.get("is_active", False)
        products = data.get("products", [])
        
        if not title:
            return JsonResponse({"status": "error", "message": "Title is required."}, status=400)

        ad = SelectedProductAd.objects.get(id=ad_id)
        ad.title = title
        ad.description = description
        ad.is_active = is_active
        ad.save()

        existing_items = ProductAdItem.objects.filter(advertisement=ad)
        existing_item_ids = set(existing_items.values_list("id", flat=True))
        processed_item_ids = set()

        for prod_data in products:
            item_id = prod_data.get("id")
            product_id = prod_data.get("product_id")
            display_name = prod_data.get("display_name", "").strip()
            product_url = prod_data.get("product_url", "").strip()

            # Skip empty rows (no product_id and no display_name)
            if not product_id and not display_name:
                continue

            if item_id:
                # Update existing item
                try:
                    item = ProductAdItem.objects.get(id=item_id, advertisement=ad)
                except ProductAdItem.DoesNotExist:
                    continue  # silently skip if item not found
            else:
                item = ProductAdItem(advertisement=ad)

            item.display_name = display_name
            item.product_url = product_url
            item.product = DigisellerProduct.objects.filter(id=product_id).first() if product_id else None
            item.save()
            processed_item_ids.add(item.id)

        # Remove deleted product rows
        items_to_delete = existing_items.exclude(id__in=processed_item_ids)
        items_to_delete.delete()

        return JsonResponse({"status": "success", "message": "Product advertisement updated successfully."})

    except SelectedProductAd.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Advertisement not found."}, status=404)
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Unexpected error: {str(e)}"}, status=500)
    
    
@require_POST
def delete_product_ad(request): 
    data = json.loads(request.body)
    ad_id = data.get("id")

    try:
        ad = SelectedProductAd.objects.get(id=ad_id)
        ad.delete()
        return JsonResponse({"status": "success", "message": "Product ad deleted successfully."})
    except SelectedProductAd.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Product ad not found."})
    
    
def purchase_discount(request):
    purchase_discount_ads = PurchaseDiscountAd.objects.all()
    
    context = {
        "purchase_discount_ads": purchase_discount_ads
    }
    
    return render(request, 'advertisements/purchase_discount.html', context)


def add_purchase_discount(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        discount_text = request.POST.get("discount_text", "").strip()
        discount_code = request.POST.get("discount_code", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not title or not discount_code or not discount_text:
            return JsonResponse({
                "status": "error",
                "message": "Title, Discount Code and Discount Text are required."
            })

        try:
            PurchaseDiscountAd.objects.create(
                title=title,
                discount_text=discount_text,
                discount_code=discount_code,
                is_active=is_active
            )
            return JsonResponse({
                "status": "success",
                "message": "Purchase discount ad added successfully."
            })
        except Exception as e:
            return JsonResponse({
                "status": "error",
                "message": f"Failed to add discount ad. Error: {str(e)}"
            })

    return JsonResponse({"status": "error", "message": "Invalid request method."})


def edit_purchase_discount_ad(request):
    if request.method == "POST":
        ad_id = request.POST.get("edit_id")
        title = request.POST.get("edit_name")
        discount_code = request.POST.get("edit_code")
        discount_text = request.POST.get("edit_text")
        is_active_str = request.POST.get("edit_active")  # "True" or "False" string

        is_active = is_active_str == "True"

        try:
            ad = PurchaseDiscountAd.objects.get(id=ad_id)
        except PurchaseDiscountAd.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Advertisement not found."})

        # Update fields
        ad.title = title
        ad.discount_code = discount_code
        ad.discount_text = discount_text
        ad.is_active = is_active
        ad.save()

        return JsonResponse({"status": "success", "message": "Advertisement updated successfully."})
    else:
        return JsonResponse({"status": "error", "message": "Invalid request method."})
    
    
@require_POST
def delete_purchase_discount_ad(request): 
    data = json.loads(request.body)
    ad_id = data.get("id")

    try:
        ad = PurchaseDiscountAd.objects.get(id=ad_id)
        ad.delete()
        return JsonResponse({"status": "success", "message": "Product ad deleted successfully."})
    except SelectedProductAd.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Product ad not found."})
    
    

def travel_guide_ad(request):
    ads = TravelGuideAd.objects.all().order_by('-id')
    
    context = {
        "travel_guide_ads": ads
    }
    
    return render(request, 'advertisements/travel_guide_ad.html', context)


def add_travel_guide_ad(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        external_link = request.POST.get("external_link", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not title:
            return JsonResponse({"status": "error", "message": "Title is required."})
        if not external_link:
            return JsonResponse({"status": "error", "message": "External link is required."})

        ad = TravelGuideAd.objects.create(
            title=title,
            description=description,
            external_link=external_link,
            is_active=is_active,
        )

        return JsonResponse({"status": "success", "message": "Travel Guide Ad added successfully."})

    return JsonResponse({"status": "error", "message": "Invalid request method."})


def edit_travel_guide_ads(request):
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "edit":
            ad_id = request.POST.get("id")
            try:
                ad = TravelGuideAd.objects.get(pk=ad_id)
            except TravelGuideAd.DoesNotExist:
                return JsonResponse({"status": "error", "message": "Ad not found."})

            ad.title = request.POST.get("title", "").strip()
            ad.description = request.POST.get("description", "").strip()
            ad.external_link = request.POST.get("external_link", "").strip()
            ad.is_active = request.POST.get("is_active") == "true"
            ad.save()

            return JsonResponse({"status": "success", "message": "Ad updated successfully."})

        return JsonResponse({"status": "error", "message": "Invalid action."})

    # GET request
    travel_guide_ads = TravelGuideAd.objects.all()
    return render(request, "your_template_name.html", {
        "travel_guide_ads": travel_guide_ads
    })
    

@require_POST
def delete_purchase_discount_ad(request): 
    data = json.loads(request.body)
    ad_id = data.get("id")

    try:
        ad = TravelGuideAd.objects.get(id=ad_id)
        ad.delete()
        return JsonResponse({"status": "success", "message": "Product ad deleted successfully."})
    except SelectedProductAd.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Product ad not found."})
    

def sponsor_ads(request):
    sponsor_ads = SponsorAd.objects.all().order_by("-id")
    
    context = {
        "sponsor_ads": sponsor_ads
    }
    
    return render(request, "advertisements/sponsor_ads.html", context)


@require_POST
def add_sponsor_ad(request):
    if request.method == "POST":
        title = request.POST.get("title", '')
        button_label = request.POST.get("button_label", '')
        url = request.POST.get("ad_url")
        is_active = request.POST.get("is_active") == "on"
        image = request.FILES.get("image")

        # Validation
        if not title or not button_label or not image or not url:
            return JsonResponse({
                "status": "error",
                "message": "Title, Button Label, and Image are required."
            })

        try:
            SponsorAd.objects.create(
                title=title,
                button_label=button_label,
                url=url,
                is_active=is_active,
                image=image
            )
            return JsonResponse({
                "status": "success",
                "message": "Sponsor Ad added successfully."
            })
        except Exception as e:
            return JsonResponse({
                "status": "error",
                "message": f"Failed to save Sponsor Ad: {str(e)}"
            })


@require_POST
def edit_sponsor_ad(request):
    try:
        ad_id = request.POST.get("edit_add_id")
        title = request.POST.get("edit_title", "").strip()
        button_label = request.POST.get("edit_button_label", "").strip()
        url = request.POST.get("edit_ad_url", "").strip()
        is_active = request.POST.get("edit_active") == "True"
        image = request.FILES.get("edit_ad_image")

        errors = []

        # Validation
        if not ad_id:
            errors.append("Missing Ad ID.")
            
        if not url or url == 'None' or url == None:
            errors.append("Missing URL.")

        if not title:
            errors.append("Title is required.")
        elif len(title) > 255:
            errors.append("Title must not exceed 255 characters.")

        if not button_label:
            errors.append("Button label is required.")
        elif len(button_label) > 40:
            errors.append("Button label must not exceed 40 characters.")

        if url and len(url) > 2000:
            errors.append("URL is too long.")

        if errors:
            return JsonResponse({
                "status": "error",
                "message": " ".join(errors)
            })

        ad = get_object_or_404(SponsorAd, id=ad_id)

        # Update fields
        ad.title = title
        ad.button_label = button_label
        ad.url = url if url else None
        ad.is_active = is_active

        if image:
            ad.image.delete(save=False)  # Delete old image
            ad.image = image

        ad.save()

        return JsonResponse({
            "status": "success",
            "message": "Sponsor Ad updated successfully."
        })

    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": f"Error while updating: {str(e)}"
        })
            
            
@require_POST
def delete_sponsor_ad(request): 
    data = json.loads(request.body)
    ad_id = data.get("id")

    try:
        ad = SponsorAd.objects.get(id=ad_id)
        ad.delete()
        return JsonResponse({"status": "success", "message": "Product ad deleted successfully."})
    except SelectedProductAd.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Product ad not found."})
    




@login_required
def ggseller_products(request, market_id=None):
    """
    List all GGseller products, optionally filtered by a specific market.
    (If you have a `market` relation on GgselProduct, you can filter by that.)
    """
 
    ggseller_products = GgselProduct.objects.all()
    print('ggseller_products:', ggseller_products)


    context = {
        'ggseller_products': ggseller_products,
    }
    return render(request, 'ggseller/ggseller_products.html', context)


@login_required
def ggseller_product(request, id):
    """
    Show a single GGseller product and its variants,
    with filtering for country and operator to display esim packages.
    """
    ggseller_product = get_object_or_404(GgselProduct, id=id)
    variants = ggseller_product.variants.all()

    countries = Country.objects.all().order_by('title')
    operator_countries = OperatorCountry.objects.all()

    selected_country_id = request.GET.get('country')
    selected_operator_id = request.GET.get('operator')

    selected_country = (
        countries.filter(id=selected_country_id).first()
        if selected_country_id else countries.first()
    )
    selected_operator = (
        Operator.objects.filter(id=selected_operator_id).first()
        if selected_operator_id else None
    )

    # Fetch esim packages
    packages = Package.objects.select_related('operator', 'operator__country')

    if selected_country:
        packages = packages.filter(operator__country=selected_country)

    if selected_operator:
        packages = packages.filter(operator=selected_operator)

    context = {
        'ggseller_product': ggseller_product,
        'variants': variants,
        'countries': countries,
        'operator_countries': operator_countries,
        'operators': Operator.objects.all().order_by('title'),
        'selected_country_id': selected_country.id if selected_country else None,
        'selected_country_title': selected_country.title if selected_country else '',
        'selected_operator_id': selected_operator.id if selected_operator else None,
        'packages': packages.order_by('-price'),
        'providers': PackageProvider.choices,
    }
    return render(request, 'ggseller/ggseller_product.html', context)



@require_POST
def update_ggseller_variants(request):
    try:
        data = json.loads(request.body)
        assignments = data.get('assignments', {})
        for variant_id, pkg_id in assignments.items():
            variant = GgselVariant.objects.filter(pk=variant_id).first()
            if not variant:
                continue
            variant.airalo_package_id = pkg_id
            variant.save(update_fields=['airalo_package'])
        # explicit 200 OK on success
        return JsonResponse({
            'success': True,
            'message': 'Airalo Packages updated successfully!'
        }, status=200)
    except Exception as e:
        # HTTP 400 on any error
        return JsonResponse({
            'success': False,
            'error': f'Failed to update: {e}'
        }, status=400)