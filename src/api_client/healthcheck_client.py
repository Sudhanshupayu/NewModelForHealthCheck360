"""HTTP client for HealthCheck360 API with cookie-based authentication."""

import logging
from typing import Any, Dict, Optional

import requests
from requests.exceptions import RequestException

from config.settings import settings
from config.cookies import get_cookies

logger = logging.getLogger(__name__)


class HealthCheckClient:
    """Client for interacting with HealthCheck360 API."""
    
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        """Initialize the client.
        
        Args:
            base_url: API base URL (defaults to settings)
            timeout: Request timeout in seconds (defaults to settings)
        """
        self.base_url = base_url or settings.api_base_url
        self.timeout = timeout or settings.api_timeout
        self.session = requests.Session()
        self._setup_session()
    
    def _setup_session(self) -> None:
        """Configure session with default headers and cookies."""
        self.session.cookies.update(get_cookies())
        self.session.headers.update({
            "Accept": "*/*",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make an authenticated GET request.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            JSON response as dictionary
            
        Raises:
            RequestException: If the request fails
        """
        url = f"{self.base_url}{endpoint}"
        logger.info(f"Making request to: {url} with params: {params}")
        
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logger.error(f"API request failed: {e}")
            raise
    
    def get_product_status(self, mid: str) -> Dict[str, Any]:
        """Get product status for a merchant.
        
        Args:
            mid: Merchant ID
            
        Returns:
            Product status data including flags, modes, and status for each product
        """
        logger.info(f"Fetching product status for MID: {mid}")
        return self._make_request("/api/getProductStatus", params={"mid": mid})
    
    def get_merchant_overview(self, mid: str) -> Dict[str, Any]:
        """Get comprehensive merchant overview.
        
        Args:
            mid: Merchant ID
            
        Returns:
            Merchant overview including info, KYC, onboarding, banking codes, etc.
        """
        logger.info(f"Fetching merchant overview for MID: {mid}")
        return self._make_request("/api/overview", params={"mid": mid})


# Singleton instance for convenience
_client: Optional[HealthCheckClient] = None


def get_client() -> HealthCheckClient:
    """Get or create the singleton client instance."""
    global _client
    if _client is None:
        _client = HealthCheckClient()
    return _client
