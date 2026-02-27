from celery import shared_task
from django.utils import timezone
from django.conf import settings
from django.db import transaction
import requests
import json
import logging
import time
import uuid
import hashlib
import traceback
from datetime import datetime

from esim.models import (
    DigisellerOrder, 
    AiraloOrder, 
    AiraloSim,
    ESIMAccessOrder,
    ESIMAccessSIM,
    ESIMAccessFailedOrder
)
from digiseller.views import get_digiseller_token

logger = logging.getLogger(__name__)

# Configuration
ESIMACCESS_BASE_API_URL = getattr(settings, 'ESIMACCESS_API_BASE_URL', 'https://api.esimaccess.com')
ESIMACCESS_API_KEY = getattr(settings, 'ESIMACCESS_API_KEY', '')

MAX_RETRIES = 5
RETRY_DELAY = 60  # seconds


def _make_esimaccess_headers():
    """Make headers for eSIM Access API requests"""
    if not ESIMACCESS_API_KEY:
        logger.error("ESIMACCESS_API_KEY not configured in settings")
    return {
        "RT-AccessCode": ESIMACCESS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


def generate_transaction_id(digiseller_order_id: int) -> str:
    """
    Generate a unique transaction ID for eSIM Access order
    Must be unique and max 50 chars
    """
    unique_str = f"DIG{ digiseller_order_id }-{int(timezone.now().timestamp())}-{uuid.uuid4().hex[:8]}"
    # Hash to ensure it's within 50 chars
    return hashlib.md5(unique_str.encode()).hexdigest()[:50]


def fetch_package_details(package_code: str) -> dict:
    """
    Fetch current package details from eSIM Access API
    Endpoint: POST /api/v1/open/package/list
    """
    url = f"{ESIMACCESS_BASE_API_URL}/api/v1/open/package/list"
    headers = _make_esimaccess_headers()
    
    payload = {
        "page": 1,
        "pageSize": 100
    }

    logger.info(f"Fetching package details for {package_code}")
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if resp.status_code != 200:
                logger.error(f"Failed to fetch packages (attempt {attempt}): {resp.status_code}")
                if attempt == MAX_RETRIES:
                    return None
                time.sleep(2 ** attempt)
                continue
                
            data = resp.json()
            
            if not data.get("success"):
                logger.error(f"API error: {data.get('errorMsg')}")
                if attempt == MAX_RETRIES:
                    return None
                time.sleep(2 ** attempt)
                continue
            
            # Extract packages from response
            obj_data = data.get("obj", {})
            package_list = obj_data.get("packageList", [])
            
            # Find the specific package
            for pkg in package_list:
                if pkg.get("packageCode") == package_code or pkg.get("slug") == package_code:
                    logger.info(f"Found package {package_code} with price {pkg.get('price')} cents")
                    return pkg
            
            logger.error(f"Package {package_code} not found in response")
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error fetching package details (attempt {attempt}): {str(e)}")
            if attempt == MAX_RETRIES:
                return None
            time.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Unexpected error fetching package details: {str(e)}")
            if attempt == MAX_RETRIES:
                return None
            time.sleep(2 ** attempt)
    
    return None


def post_esimaccess_order(package_code: str, quantity: int, description: str, 
                          digiseller_order_id: int, package_price_cents: int) -> dict:
    """
    Post an order to eSIM Access API
    Endpoint: POST /api/v1/open/esim/order
    """
    url = f"{ESIMACCESS_BASE_API_URL}/api/v1/open/esim/order"
    headers = _make_esimaccess_headers()
    
    # Generate unique transaction ID
    transaction_id = generate_transaction_id(digiseller_order_id)
    
    # Calculate total amount
    amount = package_price_cents * quantity
    
    payload = {
        "transactionId": transaction_id,
        "amount": amount,
        "packageInfoList": [{
            "packageCode": package_code,
            "count": quantity,
            "price": package_price_cents
        }]
    }

    logger.info(f"Posting eSIM Access order: {json.dumps(payload)}")
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            
            logger.info(f"Response status: {resp.status_code}")
            
            if resp.status_code != 200:
                logger.error(f"HTTP Error Response Body: {resp.text}")
                if attempt == MAX_RETRIES:
                    raise Exception(f"HTTP Error {resp.status_code}: {resp.text[:200]}")
                time.sleep(2 ** attempt)
                continue
                
            data = resp.json()
            logger.info(f"eSIM Access order response: {json.dumps(data)}")
            
            if not data.get("success"):
                error_msg = data.get("errorMsg", "Unknown error")
                error_code = data.get("errorCode", "Unknown")
                logger.error(f"API returned error: {error_code} - {error_msg}")
                raise Exception(f"API Error {error_code}: {error_msg}")
            
            # Extract the order number from the response
            obj_data = data.get("obj", {})
            order_no = obj_data.get("orderNo")
            
            if not order_no:
                logger.error(f"No orderNo in response: {data}")
                raise Exception("No orderNo in response")
            
            logger.info(f"Order placed successfully with orderNo: {order_no}")
            return {"orderNo": order_no, "transactionId": transaction_id}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request exception attempt {attempt}: {str(e)}")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error attempt {attempt}: {str(e)}")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)
        except Exception as exc:
            logger.error(f"Order POST attempt {attempt} failed: {str(exc)}")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)
    
    raise Exception("Failed to post order after all retries")


def query_esimaccess_order(order_no: str) -> dict:
    """
    Query eSIM Access order status and get eSIM details
    Endpoint: POST /api/v1/open/esim/query
    """
    url = f"{ESIMACCESS_BASE_API_URL}/api/v1/open/esim/query"
    headers = _make_esimaccess_headers()
    
    payload = {
        "orderNo": order_no,
        "esimTranNo": "",
        "iccid": "",
        "pager": {
            "pageNum": 1,
            "pageSize": 20
        }
    }

    logger.info(f"Querying eSIM Access order: {order_no}")
    
    max_query_retries = 10  # More retries for query as eSIMs may take time to generate
    for attempt in range(1, max_query_retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            
            logger.info(f"Query attempt {attempt} status: {resp.status_code}")
            
            if resp.status_code != 200:
                logger.warning(f"Query failed with status {resp.status_code}")
                if attempt == max_query_retries:
                    return None
                time.sleep(5)
                continue
                
            data = resp.json()
            
            if not data.get("success"):
                error_msg = data.get("errorMsg", "Unknown error")
                logger.warning(f"Query returned error: {error_msg}")
                if attempt == max_query_retries:
                    return None
                time.sleep(5)
                continue
            
            obj_data = data.get("obj", {})
            esim_list = obj_data.get("esimList", [])
            
            if esim_list:
                logger.info(f"✅ Found {len(esim_list)} eSIMs for order {order_no}")
                return obj_data
            else:
                logger.info(f"No eSIMs found yet for order {order_no}, retrying... (attempt {attempt}/{max_query_retries})")
                if attempt == max_query_retries:
                    return obj_data
                # Exponential backoff
                time.sleep(5 * (2 ** min(attempt, 5)))
            
        except Exception as exc:
            logger.error(f"Query attempt {attempt} failed: {str(exc)}")
            if attempt == max_query_retries:
                return None
            time.sleep(5)
    
    return None


def save_esimaccess_sims(airalo_order, query_response):
    """Save eSIMs from eSIM Access response to AiraloSim and ESIMAccessSIM models"""
    esim_list = query_response.get("esimList", [])
    saved_count = 0
    
    for sim_data in esim_list:
        # Check if SIM already exists
        iccid = sim_data.get("iccid", "")
        if AiraloSim.objects.filter(iccid=iccid).exists():
            logger.info(f"SIM with ICCID {iccid} already exists, skipping")
            continue
        
        # Parse the activation code (AC) which contains SM-DP+ address and activation code
        ac = sim_data.get("ac", "")
        smdp_address = ""
        activation_code = ""
        
        if ac and ac.startswith("LPA:"):
            # Format: LPA:1$smdp_address$activation_code
            parts = ac.split("$")
            if len(parts) >= 3:
                smdp_address = parts[1]
                activation_code = parts[2]
        
        # Calculate expiry date
        expired_time = None
        if sim_data.get("expiredTime"):
            try:
                # Try ISO format first
                expired_time = datetime.strptime(
                    sim_data["expiredTime"], 
                    "%Y-%m-%dT%H:%M:%S%z"
                )
            except:
                try:
                    # Try without timezone
                    expired_time = datetime.strptime(
                        sim_data["expiredTime"], 
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if timezone.is_naive(expired_time):
                        expired_time = timezone.make_aware(expired_time)
                except:
                    logger.warning(f"Could not parse expiredTime: {sim_data.get('expiredTime')}")
        
        # Get package info
        package_list = sim_data.get("packageList", [])
        package_name = ""
        if package_list:
            package_name = package_list[0].get("packageName", "")
        
        # Create AiraloSim record (for compatibility with existing system)
        with transaction.atomic():
            airalo_sim = AiraloSim.objects.create(
                airalo_order=airalo_order,
                sim_id=sim_data.get("esimTranNo", 0),
                iccid=iccid,
                lpa=activation_code,
                qrcode=sim_data.get("qrCode", ""),
                qrcode_url=sim_data.get("qrCodeUrl", ""),
                direct_apple_installation_url="",
                apn_type="",
                apn_value=sim_data.get("apn", ""),
                is_roaming=False,
                raw_payload=sim_data,
            )
            
            # Create ESIMAccessSIM record for eSIM Access specific fields
            ESIMAccessSIM.objects.create(
                airalo_sim=airalo_sim,
                esim_tran_no=sim_data.get("esimTranNo", ""),
                imsi=sim_data.get("imsi", ""),
                smdp_address=smdp_address,
                activation_code=activation_code,
                confirmation_code=sim_data.get("confirmationCode", ""),
                msisdn=sim_data.get("msisdn", ""),
                total_volume=sim_data.get("totalVolume", 0),
                total_duration=sim_data.get("totalDuration", 0),
                duration_unit=sim_data.get("durationUnit", "DAY"),
                package_name=package_name,
                smdp_status=sim_data.get("smdpStatus", ""),
                active_type=sim_data.get("activeType"),
                data_type=sim_data.get("dataType"),
                raw_payload=sim_data
            )
        
        saved_count += 1
        logger.info(f"✅ Saved eSIM with ICCID: {iccid}")
    
    return saved_count


def deliver_unique_code(code: str):
    """Tell Digiseller that goods have been delivered"""
    from digiseller.views import get_digiseller_token
    
    token = get_digiseller_token()
    url = f"https://api.digiseller.com/api/purchases/unique-code/{code}/deliver?token={token}"
    headers = {"Accept": "application/json"}
    
    logger.info(f"Calling Digiseller deliver endpoint for code: {code}")
    
    try:
        resp = requests.put(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        try:
            payload = resp.json()
        except ValueError:
            payload = {"text": resp.text}
        
        logger.info(f"✅ Digiseller deliver response: {payload}")
        return payload
    except Exception as e:
        logger.error(f"❌ Failed to call Digiseller deliver endpoint: {str(e)}")
        raise


@shared_task(bind=True, max_retries=10, default_retry_delay=RETRY_DELAY)
def fetch_esimaccess_details_async(self, order_no, airalo_order_id, digiseller_order_id):
    """Async task to fetch eSIM details for an eSIM Access order"""
    logger.info(f"Fetching eSIM details for order {order_no}")
    
    max_attempts = 15
    for attempt in range(1, max_attempts + 1):
        try:
            query_response = query_esimaccess_order(order_no)
            
            if query_response and query_response.get("esimList"):
                airalo_order = AiraloOrder.objects.get(id=airalo_order_id)
                saved_count = save_esimaccess_sims(airalo_order, query_response)
                
                logger.info(f"✅ Successfully fetched {saved_count} eSIMs for order {order_no} on attempt {attempt}")
                
                # Update Digiseller order if needed
                DigisellerOrder.objects.filter(id=digiseller_order_id).update(
                    digiseller_transaction_status=2
                )
                
                return {"success": True, "attempt": attempt, "saved": saved_count}
            
            logger.info(f"Attempt {attempt}/{max_attempts}: No eSIMs yet for order {order_no}")
            
        except Exception as e:
            logger.error(f"Error fetching eSIM details (attempt {attempt}): {str(e)}")
        
        # Exponential backoff
        time.sleep(10 * (2 ** min(attempt, 5)))
    
    logger.error(f"Failed to fetch eSIM details for order {order_no} after {max_attempts} attempts")
    
    # Log failure but don't retry further
    try:
        ESIMAccessFailedOrder.objects.create(
            digiseller_order_id=digiseller_order_id,
            order_no=order_no,
            package_code="",
            payload={"order_no": order_no, "airalo_order_id": airalo_order_id},
            error_message="Failed to fetch eSIM details after max attempts",
            reason="Max attempts reached",
            status=3  # Permanent Failure
        )
    except Exception as e:
        logger.error(f"Failed to log failure: {e}")
    
    return {"success": False, "error": "Max attempts reached"}


@shared_task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=RETRY_DELAY)
def purchase_esimaccess_sim(self, digiseller_order_id):
    """
    Purchase eSIM from eSIM Access API for a Digiseller order
    """
    logger.info(f"🚀 Starting purchase_esimaccess_sim for Digiseller order {digiseller_order_id}")
    
    try:
        order = DigisellerOrder.objects.select_related("airalo_package").get(pk=digiseller_order_id)
    except DigisellerOrder.DoesNotExist:
        logger.error(f"DigisellerOrder {digiseller_order_id} not found")
        return

    # Verify it's an eSIM Access package
    if not order.airalo_package:
        logger.error(f"Order {digiseller_order_id} has no package assigned")
        order.status = "failed"
        order.error_message = "No package assigned"
        order.save(update_fields=["status", "error_message"])
        return

    if order.airalo_package.provider != 'esimaccess':
        logger.error(f"Order {digiseller_order_id} is not an eSIM Access package (provider: {order.airalo_package.provider})")
        order.status = "failed"
        order.error_message = f"Not an eSIM Access package: {order.airalo_package.provider}"
        order.save(update_fields=["status", "error_message"])
        return

    # Update order status
    order.status = "processing"
    order.save(update_fields=["status"])

    package_code = order.airalo_package.package_id
    quantity = int(order.quantity)
    description = f"digiseller-order-{order.order_id}"
    
    logger.info(f"📦 Processing eSIM Access order {digiseller_order_id} for package {package_code}, quantity {quantity}")

    try:
        # Step 1: Fetch current package price from API
        logger.info(f"🔍 Fetching current price for package {package_code}")
        package_details = fetch_package_details(package_code)
        
        if not package_details:
            raise Exception(f"Could not fetch package details for {package_code}")
        
        # Get the current price from API (in cents)
        api_price_cents = package_details.get("price", 0)
        if not api_price_cents:
            raise Exception(f"No price found for package {package_code}")
        
        logger.info(f"💰 API price: {api_price_cents} cents for package {package_code}")

        # Step 2: Place the order with the price from API
        logger.info(f"🛒 Placing eSIM Access order for package {package_code}")
        order_response = post_esimaccess_order(
            package_code=package_code,
            quantity=quantity,
            description=description,
            digiseller_order_id=digiseller_order_id,
            package_price_cents=api_price_cents
        )
        
        # Get the order number from the response
        order_no = order_response.get("orderNo")
        transaction_id = order_response.get("transactionId")
        
        if not order_no:
            raise Exception("No orderNo in response")
        
        logger.info(f"✅ eSIM Access order placed successfully with orderNo: {order_no}")
        
        # Step 3: Create AiraloOrder record (for compatibility with existing system)
        with transaction.atomic():
            airalo_order = AiraloOrder.objects.create(
                airalo_id=0,  # Not applicable for eSIM Access
                code=order_no,
                currency="USD",
                package_id=package_code,
                quantity=quantity,
                type="sim",
                description=description,
                package_title=order.airalo_package.title,
                data=order.airalo_package.data or "",
                price=order.airalo_package.price,
                created_at_api=timezone.now(),
                manual_installation="",
                qrcode_installation="",
                installation_guides={},
                net_price=float(api_price_cents) / 100,  # Convert cents to dollars/euros
                raw_payload=order_response,
            )
            
            # Create ESIMAccessOrder record for eSIM Access specific data
            esimaccess_order = ESIMAccessOrder.objects.create(
                esimaccess_id=0,
                order_no=order_no,
                transaction_id=transaction_id,
                currency="USD",
                package_id=package_code,
                quantity=quantity,
                type="sim",
                description=description,
                package_title=order.airalo_package.title,
                data=order.airalo_package.data or "",
                price=order.airalo_package.price,
                net_price=float(api_price_cents) / 100,
                status="completed",
                created_at_api=timezone.now(),
                raw_payload=order_response,
            )
        
        # Link the AiraloOrder to the DigisellerOrder
        order.airalo_order = airalo_order
        order.save(update_fields=["airalo_order"])
        
        # Step 4: Try to query eSIM details immediately
        try:
            query_response = query_esimaccess_order(order_no)
            if query_response and query_response.get("esimList"):
                saved_count = save_esimaccess_sims(airalo_order, query_response)
                logger.info(f"✅ Immediately fetched {saved_count} eSIMs for order {order_no}")
                
                # Mark order as completed
                order.status = "completed"
                order.save(update_fields=["status"])
                
                # Call Digiseller deliver endpoint
                try:
                    deliver_unique_code(order.unique_code)
                    order.digiseller_transaction_status = 2
                    order.save(update_fields=["digiseller_transaction_status"])
                    logger.info("✅ Digiseller deliver endpoint completed immediately.")
                except Exception as exc:
                    logger.error(f"❌ Failed to call Digiseller deliver endpoint: {exc}")
                    # Don't fail the whole order if deliver fails - can be retried separately
                
                return {"success": True, "order_no": order_no, "sims_fetched": True}
            else:
                logger.info(f"⏳ No eSIMs available immediately for order {order_no}, scheduling background fetch")
                
                # Mark order as completed even without eSIMs - they'll come later
                order.status = "completed"
                order.save(update_fields=["status"])
                
                # Call Digiseller deliver endpoint (some providers deliver immediately even without eSIMs)
                try:
                    deliver_unique_code(order.unique_code)
                    order.digiseller_transaction_status = 2
                    order.save(update_fields=["digiseller_transaction_status"])
                    logger.info("✅ Digiseller deliver endpoint completed (eSIMs pending).")
                except Exception as exc:
                    logger.error(f"❌ Failed to call Digiseller deliver endpoint: {exc}")
                    # Still schedule background fetch - we can retry deliver later
                
                # Schedule background task to fetch eSIMs later
                fetch_esimaccess_details_async.delay(
                    order_no, 
                    airalo_order.id, 
                    digiseller_order_id
                )
                
                return {"success": True, "order_no": order_no, "sims_fetched": False}
                
        except Exception as e:
            logger.warning(f"⚠️ Error in immediate eSIM fetch: {str(e)}")
            
            # Still mark order as completed - we'll fetch later
            order.status = "completed"
            order.save(update_fields=["status"])
            
            # Try to deliver anyway
            try:
                deliver_unique_code(order.unique_code)
                order.digiseller_transaction_status = 2
                order.save(update_fields=["digiseller_transaction_status"])
            except Exception as exc:
                logger.error(f"❌ Failed to call Digiseller deliver endpoint: {exc}")
            
            # Schedule background fetch
            fetch_esimaccess_details_async.delay(
                order_no, 
                airalo_order.id, 
                digiseller_order_id
            )
            
            return {"success": True, "order_no": order_no, "sims_fetched": False}
            
    except requests.exceptions.Timeout as exc:
        logger.error(f"❌ Timeout for order {digiseller_order_id}: {exc}")
        order.status = "failed"
        order.error_message = f"Timeout: {str(exc)}"
        order.save(update_fields=["status", "error_message"])
        
        # Log failure
        ESIMAccessFailedOrder.objects.create(
            digiseller_order=order,
            order_no="",
            package_code=package_code,
            payload={"package_code": package_code, "quantity": quantity},
            error_message=str(exc),
            stack_trace=traceback.format_exc(),
            reason="API Timeout",
            status=1
        )
        
        # Retry with exponential backoff
        countdown = RETRY_DELAY * (2 ** (self.request.retries))
        raise self.retry(exc=exc, countdown=countdown)
        
    except Exception as exc:
        logger.error(f"❌ Failed to process eSIM Access order {digiseller_order_id}: {str(exc)}")
        logger.error(traceback.format_exc())
        
        order.status = "failed"
        order.error_message = str(exc)[:255]
        order.save(update_fields=["status", "error_message"])
        
        # Log failure
        try:
            ESIMAccessFailedOrder.objects.create(
                digiseller_order=order,
                order_no="",
                package_code=package_code if 'package_code' in locals() else 'unknown',
                payload={"package_code": package_code if 'package_code' in locals() else 'unknown', 
                        "quantity": quantity if 'quantity' in locals() else 0},
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                reason=str(exc)[:100],
                status=1
            )
        except Exception as log_err:
            logger.error(f"Failed to log failure: {log_err}")
        
        # Retry with exponential backoff
        countdown = RETRY_DELAY * (2 ** (self.request.retries))
        raise self.retry(exc=exc, countdown=countdown)


@shared_task
def retry_failed_esimaccess_orders():
    """Retry all failed eSIM Access orders that haven't exceeded max retries"""
    logger.info("🔄 Starting retry_failed_esimaccess_orders")
    
    failed_orders = ESIMAccessFailedOrder.objects.filter(
        status=1,  # New
        retry_count__lt=MAX_RETRIES
    ).select_related('digiseller_order')[:50]  # Process in batches
    
    retry_count = 0
    for failed in failed_orders:
        if failed.digiseller_order:
            logger.info(f"Retrying failed order {failed.digiseller_order.id}")
            
            # Increment retry count
            failed.retry_count += 1
            failed.last_retry_at = timezone.now()
            failed.status = 2  # Retrying
            failed.save(update_fields=["retry_count", "last_retry_at", "status"])
            
            # Re-enqueue the task
            purchase_esimaccess_sim.delay(failed.digiseller_order.id)
            retry_count += 1
    
    logger.info(f"✅ Retried {retry_count} failed orders")
    return retry_count


@shared_task
def test_esimaccess_connection():
    """Test task to verify eSIM Access API connection"""
    logger.info("Testing eSIM Access API connection...")
    
    try:
        if not ESIMACCESS_API_KEY:
            return {"success": False, "error": "No access code configured"}
        
        headers = _make_esimaccess_headers()
        
        # Test with a minimal package list request
        url = f"{ESIMACCESS_BASE_API_URL}/api/v1/open/package/list"
        payload = {"page": 1, "pageSize": 10}
        
        logger.info(f"Testing eSIM Access API: {url}")
        
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": data.get("success", False),
                "status_code": resp.status_code,
                "message": "Connection successful" if data.get("success") else data.get("errorMsg"),
                "package_count": len(data.get("obj", {}).get("packageList", [])) if data.get("success") else 0
            }
        else:
            return {
                "success": False,
                "status_code": resp.status_code,
                "error": resp.text[:500]
            }
            
    except Exception as e:
        logger.error(f"Test connection error: {str(e)}")
        return {"success": False, "error": str(e)}