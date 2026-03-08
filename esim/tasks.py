from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from django.conf import settings
import logging


from decimal import Decimal
from django.utils.text import slugify
import uuid
from .models import Package, Operator, Country, OperatorCountry, ESIMAccessPackage, ESIMAccessFailedPackage
from esim.utils.esimaccess import ESIMAccessService

User = get_user_model()

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, soft_time_limit=7200, time_limit=10800)
def sync_esimaccess_packages_task(self):
    """
    Celery task to sync eSIM Access packages asynchronously
    """
    result = {
        'success': False,
        'message': '',
        'stats': {
            'packages_added': 0,
            'packages_updated': 0,
            'packages_failed': 0,
            'operators_added': 0,
            'operators_updated': 0,
        }
    }
    
    try:
        service = ESIMAccessService()
        all_packages = service.fetch_all_packages()
        
        total_packages = len(all_packages)
        logger.info(f"✅ Total unique packages to process: {total_packages}")
        
        if total_packages == 0:
            result['message'] = "No packages found to sync"
            result['success'] = True
            return result
        
        # Process in smaller batches
        batch_size = 100
        for i in range(0, total_packages, batch_size):
            batch = all_packages[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(total_packages + batch_size - 1)//batch_size}")
            
            for idx, package_data in enumerate(batch):
                try:
                    process_result = process_esimaccess_package(package_data)
                    
                    if process_result['created']:
                        result['stats']['packages_added'] += 1
                    else:
                        result['stats']['packages_updated'] += 1
                    
                except Exception as e:
                    result['stats']['packages_failed'] += 1
                    logger.error(f"Error processing package: {str(e)}")
                    
                    try:
                        ESIMAccessFailedPackage.objects.create(
                            reason=str(e)[:255],
                            data=package_data
                        )
                    except:
                        pass
            
            # Update task state
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': min(i + batch_size, total_packages),
                    'total': total_packages,
                    'stats': result['stats']
                }
            )
        
        result['success'] = True
        result['message'] = f"Successfully synced {result['stats']['packages_added'] + result['stats']['packages_updated']} packages"
        
    except Exception as e:
        logger.error(f"Sync error: {str(e)}")
        result['error'] = str(e)
    
    return result


def process_esimaccess_package(package_data):
    """
    Process individual package from eSIM Access API
    Creates separate OperatorCountry records for each country in comma-separated list
    """
    from esim.models import Package, Operator, Country, OperatorCountry
    from django.utils.text import slugify
    from decimal import Decimal
    
    logger = logging.getLogger(__name__)
    
    result = {
        'created': False,
        'operator_created': False,
        'operator_updated': False
    }
    
    # Extract package details
    package_id = package_data.get('packageCode') or str(uuid.uuid4())
    title = package_data.get('name', 'Unknown Package')
    
    # Extract pricing - FIXED: price = value * 10,000 (10000 = $1.00)
    price = package_data.get('price', 0)
    retail_price = package_data.get('retailPrice', price)
    
    # Convert using the correct formula: divide by 10,000 to get dollars
    # Example: 10000 = $1.00, 112500 = $11.25
    price_decimal = Decimal(price) / Decimal('10000')
    retail_price_decimal = Decimal(retail_price) / Decimal('10000')
    
    logger.info(f"Price conversion: {price} -> ${price_decimal} | Retail: {retail_price} -> ${retail_price_decimal}")
    
    # Handle location - can be single code or comma-separated list
    location_field = package_data.get('location', '')
    
    # Parse location codes
    location_codes = []
    if ',' in location_field:
        # Multi-country package
        location_codes = [code.strip() for code in location_field.split(',') if code.strip()]
        logger.info(f"Multi-country package with codes: {location_codes}")
    else:
        # Single country package
        location_codes = [location_field] if location_field else []
    
    # Get location network list for detailed country info
    location_network_list = package_data.get('locationNetworkList', [])
    
    # Create a dictionary mapping country codes to their details
    country_details = {}
    for loc in location_network_list:
        code = loc.get('locationCode', '')
        name = loc.get('locationName', '')
        logo = loc.get('locationLogo', '')
        if code:
            country_details[code] = {
                'name': name,
                'logo': logo,
                'operators': loc.get('operatorList', [])
            }
    
    # For each location code, create or get country and operator relationships
    primary_country = None
    primary_operator = None
    
    for idx, code in enumerate(location_codes):
        # Get country details
        country_name = country_details.get(code, {}).get('name', f"Country {code}")
        country_logo = country_details.get(code, {}).get('logo', '')
        
        # Ensure country_code is not too long
        country_code = code
        if len(country_code) > 10:
            logger.warning(f"Truncating country_code '{country_code}' to 10 characters")
            country_code = country_code[:10]
        
        # Get or create country
        country, country_created = Country.objects.get_or_create(
            country_code=country_code,
            defaults={
                'title': country_name[:100],  # Truncate to max 100
                'slug': slugify(country_name)[:50],
            }
        )
        
        # For the first country, use it as the primary for the package
        if idx == 0:
            primary_country = country
            
            # Create a primary operator (generic one for the first country)
            operator_name = f"Operator {code}"
            if len(operator_name) > 150:
                operator_name = operator_name[:150]
            
            primary_operator, operator_created = Operator.objects.get_or_create(
                title=operator_name,
                country=primary_country,
                defaults={
                    'operator_id': 0,
                    'type': 'prepaid',
                    'is_prepaid': True,
                    'image_url': country_logo,
                }
            )
            
            result['operator_created'] = operator_created
            result['operator_updated'] = not operator_created
        
        # Create OperatorCountry records for each country
        # This links the primary operator to all countries in the package
        if primary_operator:
            operator_country, oc_created = OperatorCountry.objects.get_or_create(
                operator=primary_operator,
                country_code=country_code,
                defaults={
                    'title': country_name[:100],
                    'image_url': country_logo,
                }
            )
            
            if oc_created:
                logger.info(f"Created OperatorCountry for {country_name} with operator {primary_operator.title}")
    
    # If no countries found, create a fallback
    if not primary_country:
        primary_country, _ = Country.objects.get_or_create(
            country_code='XX',
            defaults={
                'title': 'Unknown',
                'slug': 'unknown',
            }
        )
        
        primary_operator, operator_created = Operator.objects.get_or_create(
            title='Unknown Operator',
            country=primary_country,
            defaults={
                'operator_id': 0,
                'type': 'prepaid',
                'is_prepaid': True,
            }
        )
    
    # Extract package specifications
    volume_bytes = package_data.get('volume', 0)
    
    # Convert bytes to human-readable format
    if volume_bytes:
        data_gb = volume_bytes / (1024 * 1024 * 1024)
        if data_gb >= 1:
            data_amount = f"{data_gb:.1f} GB"
        else:
            data_mb = volume_bytes / (1024 * 1024)
            data_amount = f"{data_mb:.0f} MB"
    else:
        data_amount = None
    
    # Extract validity
    duration = package_data.get('duration', 0)
    duration_unit = package_data.get('durationUnit', 'DAY')
    validity_days = duration if duration_unit == 'DAY' else 30
    is_unlimited = volume_bytes == 0
    speed = package_data.get('speed', '')
    
    # Prepare short_info with countries list
    country_list = ", ".join([c for c in location_codes])
    short_info = f"{data_amount} - {speed}" if speed and data_amount else (data_amount or speed or '')
    if len(location_codes) > 1:
        short_info = f"Multiple Countries: {country_list} - {short_info}"
    
    # Prepare defaults with correct price values - REMOVED invalid fields
    defaults = {
        'operator': primary_operator,
        'type': 'prepaid',
        'price': float(price_decimal),  # Now correctly converted to dollars
        'amount': None,
        'day': validity_days,
        'is_unlimited': is_unlimited,
        'title': title[:250],
        'short_info': short_info[:300] if short_info else '',
        'data': data_amount[:50] if data_amount else None,
        'voice': None,
        'text': None,
        'net_price': float(price_decimal),  # Net price same as price for now
        'prices': {
            'USD': float(price_decimal),
            'retail': float(retail_price_decimal)
        },
    }
    
    # Create or update package
    package, created = Package.objects.update_or_create(
        package_id=package_id,
        provider='esimaccess',
        defaults=defaults
    )
    
    result['created'] = created
    
    # Log price for verification
    logger.info(f"Package {package_id} - Price: ${float(price_decimal)} (from {price}), Retail: ${float(retail_price_decimal)} (from {retail_price})")
    
    return result




