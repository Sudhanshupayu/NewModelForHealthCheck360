"""Tests for the agent module."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.agent.tools import (
    MerchantIDInput,
    create_product_status_tool,
    create_merchant_overview_tool,
    get_tools,
)


class TestMerchantIDInput:
    """Tests for MerchantIDInput schema."""
    
    def test_valid_mid(self):
        """Should accept valid MID."""
        input_obj = MerchantIDInput(mid="123")
        assert input_obj.mid == "123"
    
    def test_mid_as_string(self):
        """MID should be stored as string."""
        input_obj = MerchantIDInput(mid="2")
        assert isinstance(input_obj.mid, str)


class TestProductStatusTool:
    """Tests for product status tool."""
    
    @pytest.fixture
    def mock_client(self):
        """Create mock client."""
        client = Mock()
        client.get_product_status.return_value = {
            "mid": "2",
            "product_status": {
                "Credit Card": {"flags": "Yes", "modes": "Yes", "status": "Yes"},
                "Mealcards": {"flags": "No", "modes": "No", "status": "No"},
            }
        }
        return client
    
    def test_tool_creation(self, mock_client):
        """Should create a valid tool."""
        tool = create_product_status_tool(mock_client)
        
        assert tool.name == "get_product_status"
        assert "product" in tool.description.lower()
    
    def test_tool_returns_report(self, mock_client):
        """Tool should return formatted report."""
        tool = create_product_status_tool(mock_client)
        
        result = tool.invoke({"mid": "2"})
        
        assert "MID" in result or "Merchant" in result
        assert "Credit Card" in result
    
    def test_tool_handles_error(self, mock_client):
        """Tool should handle API errors gracefully."""
        mock_client.get_product_status.side_effect = Exception("API Error")
        tool = create_product_status_tool(mock_client)
        
        result = tool.invoke({"mid": "invalid"})
        
        assert "Error" in result


class TestMerchantOverviewTool:
    """Tests for merchant overview tool."""
    
    @pytest.fixture
    def mock_client(self):
        """Create mock client."""
        client = Mock()
        client.get_merchant_overview.return_value = {
            "merchantInfo": {
                "mid": "2",
                "name": "Test Merchant",
                "key": "testkey",
                "approved": "Yes",
                "active": "Yes"
            },
            "kycStatus": {"merchantApprovalStatus": "Approved"}
        }
        return client
    
    def test_tool_creation(self, mock_client):
        """Should create a valid tool."""
        tool = create_merchant_overview_tool(mock_client)
        
        assert tool.name == "get_merchant_overview"
        assert "overview" in tool.description.lower()
    
    def test_tool_returns_summary(self, mock_client):
        """Tool should return formatted summary."""
        tool = create_merchant_overview_tool(mock_client)
        
        result = tool.invoke({"mid": "2"})
        
        assert "Test Merchant" in result
        assert "Approved" in result


class TestGetTools:
    """Tests for get_tools function."""
    
    def test_returns_list(self):
        """Should return a list of tools."""
        with patch('src.agent.tools.HealthCheckClient'):
            tools = get_tools()
            
            assert isinstance(tools, list)
            assert len(tools) == 2
    
    def test_tool_names(self):
        """Should have correct tool names."""
        with patch('src.agent.tools.HealthCheckClient'):
            tools = get_tools()
            
            names = [t.name for t in tools]
            assert "get_product_status" in names
            assert "get_merchant_overview" in names
