"""
Hyperliquid API client for fetching predicted funding rates.
"""

from typing import List
from .base import BaseAPIClient
from config.constants import HYPERLIQUID_API_URL, HYPERLIQUID_HEADERS, HYPERLIQUID_REQUEST_BODY
from data.models import HyperliquidResponse


class HyperliquidClient(BaseAPIClient):
    """Client for interacting with Hyperliquid API."""

    def __init__(self):
        """Initialize Hyperliquid API client."""
        super().__init__(HYPERLIQUID_API_URL)

    def fetch_predicted_fundings(self) -> HyperliquidResponse:
        """
        Fetch predicted funding rates from Hyperliquid API.

        Returns:
            HyperliquidResponse object with funding data or error information
        """
        response = self.post(
            headers=HYPERLIQUID_HEADERS,
            json_data=HYPERLIQUID_REQUEST_BODY
        )

        return HyperliquidResponse(
            success=response.success,
            data=response.data,
            error=response.error
        )

    def get_funding_data(self) -> List:
        """
        Get funding data in the original format for backward compatibility.

        Returns:
            List of funding data or empty list if request failed
        """
        response = self.fetch_predicted_fundings()

        if response.success and response.data:
            return response.data

        return []
