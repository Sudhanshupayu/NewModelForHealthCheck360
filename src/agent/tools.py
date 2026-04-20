"""Tool definitions for the HealthCheck360 agent."""

import logging
from typing import List

from langchain_core.tools import Tool, StructuredTool
from pydantic import BaseModel, Field

from src.api_client import HealthCheckClient
from src.summarizer import (
    calculate_readiness_score,
    format_readiness_report,
    format_overview_summary,
)

logger = logging.getLogger(__name__)


class MerchantIDInput(BaseModel):
    """Input schema for merchant ID based tools."""
    mid: str = Field(description="The Merchant ID (MID) to query")


def create_product_status_tool(client: HealthCheckClient) -> StructuredTool:
    """Create a tool for fetching product status.
    
    Args:
        client: HealthCheckClient instance
        
    Returns:
        Configured StructuredTool
    """
    def get_product_status(mid: str) -> str:
        """Fetch product status for a merchant and return formatted readiness report."""
        try:
            logger.info(f"Tool: Fetching product status for MID {mid}")
            
            # Fetch data from API
            response = client.get_product_status(mid)
            
            # Calculate readiness scores
            readiness_data = calculate_readiness_score(response)
            
            # Format the report
            report = format_readiness_report(readiness_data)
            
            return report
            
        except Exception as e:
            logger.error(f"Error fetching product status: {e}")
            return f"Error fetching product status for MID {mid}: {str(e)}"
    
    return StructuredTool.from_function(
        func=get_product_status,
        name="get_product_status",
        description=(
            "Fetches the status of all payment products for a merchant. "
            "Returns a readiness report showing which products are fully ready, "
            "partially ready, or not configured. Use this when the user asks about "
            "product status, what's active, or readiness for a merchant."
        ),
        args_schema=MerchantIDInput,
    )


def create_merchant_overview_tool(client: HealthCheckClient) -> StructuredTool:
    """Create a tool for fetching merchant overview.
    
    Args:
        client: HealthCheckClient instance
        
    Returns:
        Configured StructuredTool
    """
    def get_merchant_overview(mid: str) -> str:
        """Fetch comprehensive merchant overview and return formatted summary."""
        try:
            logger.info(f"Tool: Fetching merchant overview for MID {mid}")
            
            # Fetch data from API
            response = client.get_merchant_overview(mid)
            
            # Format the summary
            summary = format_overview_summary(response)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error fetching merchant overview: {e}")
            return f"Error fetching overview for MID {mid}: {str(e)}"
    
    return StructuredTool.from_function(
        func=get_merchant_overview,
        name="get_merchant_overview",
        description=(
            "Fetches comprehensive merchant configuration including merchant info, "
            "KYC status, onboarding status, enabled products, banking codes, "
            "technical configurations, API rate limits, and callback settings. "
            "Use this when the user asks about merchant configuration, overview, "
            "settings, or detailed information."
        ),
        args_schema=MerchantIDInput,
    )


def get_tools(client: HealthCheckClient = None) -> List[StructuredTool]:
    """Get all available tools for the agent.
    
    Args:
        client: Optional HealthCheckClient instance. If not provided, creates one.
        
    Returns:
        List of configured tools
    """
    if client is None:
        client = HealthCheckClient()
    
    return [
        create_product_status_tool(client),
        create_merchant_overview_tool(client),
    ]
