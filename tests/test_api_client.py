"""Tests for the HealthCheck API client."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests

from src.api_client.healthcheck_client import HealthCheckClient


class TestHealthCheckClient:
    """Tests for HealthCheckClient."""
    
    @pytest.fixture
    def client(self):
        """Create a client instance."""
        return HealthCheckClient(
            base_url="https://test.example.com",
            timeout=10
        )
    
    @pytest.fixture
    def mock_response(self):
        """Create a mock response."""
        response = Mock()
        response.json.return_value = {"test": "data"}
        response.raise_for_status = Mock()
        return response
    
    def test_initialization(self, client):
        """Client should initialize with correct settings."""
        assert client.base_url == "https://test.example.com"
        assert client.timeout == 10
    
    def test_session_has_cookies(self, client):
        """Session should have cookies set."""
        assert len(client.session.cookies) > 0
    
    def test_session_has_headers(self, client):
        """Session should have default headers."""
        assert "User-Agent" in client.session.headers
        assert "Accept" in client.session.headers
    
    @patch.object(requests.Session, 'get')
    def test_get_product_status_makes_request(self, mock_get, client, mock_response):
        """get_product_status should make correct API call."""
        mock_get.return_value = mock_response
        
        client.get_product_status("123")
        
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "/api/getProductStatus" in call_args[0][0]
        assert call_args[1]["params"] == {"mid": "123"}
    
    @patch.object(requests.Session, 'get')
    def test_get_merchant_overview_makes_request(self, mock_get, client, mock_response):
        """get_merchant_overview should make correct API call."""
        mock_get.return_value = mock_response
        
        client.get_merchant_overview("456")
        
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "/api/overview" in call_args[0][0]
        assert call_args[1]["params"] == {"mid": "456"}
    
    @patch.object(requests.Session, 'get')
    def test_returns_json_response(self, mock_get, client, mock_response):
        """Should return parsed JSON response."""
        mock_response.json.return_value = {"mid": "2", "product_status": {}}
        mock_get.return_value = mock_response
        
        result = client.get_product_status("2")
        
        assert result == {"mid": "2", "product_status": {}}
    
    @patch.object(requests.Session, 'get')
    def test_raises_on_error(self, mock_get, client):
        """Should raise exception on HTTP error."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response
        
        with pytest.raises(requests.HTTPError):
            client.get_product_status("invalid")


class TestCookieHandling:
    """Tests for cookie configuration."""
    
    def test_cookies_loaded_from_config(self):
        """Cookies should be loaded from config."""
        from config.cookies import get_cookies
        
        cookies = get_cookies()
        assert isinstance(cookies, dict)
        assert len(cookies) > 0
    
    def test_cookie_header_format(self):
        """Cookie header should be properly formatted."""
        from config.cookies import get_cookie_header
        
        header = get_cookie_header()
        assert isinstance(header, str)
        assert "=" in header
