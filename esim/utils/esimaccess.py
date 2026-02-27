# admin_panel/utils/esimaccess.py
import time
import json
import requests
import logging
import traceback
from django.conf import settings

logger = logging.getLogger(__name__)

class ESIMAccessService:
    """
    Service class for eSIM Access API integration
    Uses RT-AccessCode header for authentication (same as working view)
    """

    def __init__(self):
        self.base_url = getattr(settings, 'ESIMACCESS_API_BASE_URL', 'https://api.esimaccess.com')
        self.access_code = getattr(settings, 'ESIMACCESS_API_KEY', '')
        
        if not self.access_code:
            raise ValueError("ESIMACCESS_API_KEY (AccessCode) must be configured in settings")

    # -------------------------------------------------
    # REQUEST HANDLER
    # -------------------------------------------------
    def _post(self, endpoint: str, body: dict) -> dict:
        """
        Make a POST request to the eSIM Access API using RT-AccessCode header
        
        Args:
            endpoint (str): API endpoint (e.g., "/api/v1/open/package/list")
            body (dict): Request body
            
        Returns:
            dict: Response data
        """
        url = f"{self.base_url}{endpoint}"
        
        # Headers matching the working view
        headers = {
            'RT-AccessCode': self.access_code,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        logger.info(f"Making POST request to: {url}")
        logger.info(f"Request body: {json.dumps(body)}")
        
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=30
            )

            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"HTTP Error Response: {response.text[:1000]}")
                raise Exception(f"HTTP Error {response.status_code}: {response.text[:200]}")

            data = response.json()
            
            logger.info(f"Response success: {data.get('success')}")

            if not data.get("success"):
                error_msg = data.get("errorMsg", "Unknown error")
                error_code = data.get("errorCode", "Unknown code")
                logger.error(f"API Error: {error_code} - {error_msg}")
                raise Exception(f"{error_code}: {error_msg}")

            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    # -------------------------------------------------
    # FETCH ALL PACKAGES (FULL PAGINATION)
    # -------------------------------------------------
    def fetch_all_packages(self) -> list:
        """
        Fetch all packages from eSIM Access API
        Based on working view code - returns all packages in one response
        """
        logger.info("Fetching all packages from eSIM Access API...")
        
        # Try to get all packages at once first (like your working view)
        body = {
            "page": 1,
            "pageSize": 10000  # Request a large page size to get all at once
        }
        
        try:
            response_data = self._post("/api/v1/open/package/list", body)
            
            # Extract packages from response
            all_packages = []
            
            if isinstance(response_data, dict):
                if response_data.get("success") is True:
                    obj_data = response_data.get("obj")
                    
                    if isinstance(obj_data, dict):
                        if "packageList" in obj_data:
                            package_list = obj_data["packageList"]
                            if isinstance(package_list, list):
                                all_packages = package_list
                                logger.info(f"✅ Found {len(all_packages)} packages in single response")
            
            # If no packages found with large page size, fall back to original method
            if not all_packages:
                logger.info("Large page size didn't work, falling back to original method...")
                all_packages = self._fetch_with_pagination()
            
            return all_packages
            
        except Exception as e:
            logger.error(f"Error fetching packages: {str(e)}")
            # Fall back to pagination
            return self._fetch_with_pagination()

    def _fetch_with_pagination(self) -> list:
        """
        Fallback method with corrected pagination
        """
        all_packages = []
        page = 1
        page_size = 100
        
        # Store unique package IDs to avoid duplicates
        seen_package_ids = set()
        
        while True:
            logger.info(f"Fetching page {page}...")
            
            body = {
                "page": page,
                "pageSize": page_size
            }
            
            try:
                response_data = self._post("/api/v1/open/package/list", body)
                
                # Extract packages
                page_packages = []
                if isinstance(response_data, dict):
                    if response_data.get("success") is True:
                        obj_data = response_data.get("obj")
                        if isinstance(obj_data, dict) and "packageList" in obj_data:
                            page_packages = obj_data["packageList"]
                
                if not page_packages:
                    logger.info("No more packages found")
                    break
                
                # Filter out duplicates
                new_packages = []
                for pkg in page_packages:
                    pkg_id = pkg.get('packageCode')
                    if pkg_id and pkg_id not in seen_package_ids:
                        seen_package_ids.add(pkg_id)
                        new_packages.append(pkg)
                
                if not new_packages:
                    logger.info("No new unique packages on this page, stopping")
                    break
                
                all_packages.extend(new_packages)
                logger.info(f"Added {len(new_packages)} new packages, total: {len(all_packages)}")
                
                # Check if we've seen these packages before - if it's the same as last page, stop
                if len(new_packages) < len(page_packages):
                    logger.info("Duplicate packages detected, stopping pagination")
                    break
                
                page += 1
                
                # Safety limit
                if page > 100:
                    logger.warning("Reached page limit")
                    break
                    
            except Exception as e:
                logger.error(f"Error on page {page}: {str(e)}")
                break
        
        logger.info(f"✅ Total unique packages fetched: {len(all_packages)}")
        return all_packages