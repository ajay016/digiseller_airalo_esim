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
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.db.models import Count
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from django.conf import settings
import requests
import hashlib
import time
import json
import re
from .models import *




def is_valid_email(email):
    """Simple regex for email validation"""
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)


def dashboard(request):
    return render(request, 'index.html')



def sync_data(request):
    return render(request, 'sync_data/sync_data.html')


def digiseller_products(request):
    digiseller_products = DigisellerProduct.objects.all()
    
    context = {
        'digiseller_products': digiseller_products,
    }
    return render(request, 'digiseller/digiseller_products.html', context)


def digiseller_product(request, id):
    digiseller_product = get_object_or_404(DigisellerProduct, id=id)
    variants = digiseller_product.variants.all()
    
    countries = Country.objects.all().order_by('title')
    operator_countries = OperatorCountry.objects.all()

    selected_country_id = request.GET.get('country')
    selected_operator_id = request.GET.get('operator')

    selected_country = countries.filter(id=selected_country_id).first() if selected_country_id else countries.first()
    selected_operator = Operator.objects.filter(id=selected_operator_id).first() if selected_operator_id else None

    # Fetch packages based on filters
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
    }
    return render(request, 'digiseller/digiseller_product.html', context)


def get_packages_by_region(request):
    country_id = request.GET.get('country')
    operator_country_id = request.GET.get('region')
    
    print('country entered')

    packages = Package.objects.select_related('operator', 'operator__country')

    if operator_country_id:
        packages = packages.filter(operator__available_countries__id=operator_country_id)
    elif country_id:
        packages = packages.filter(operator__country_id=country_id)

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
