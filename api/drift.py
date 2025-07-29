"""
Drift API client for fetching 24h market data including funding rates.
"""

from typing import List, Dict
from .base import BaseAPIClient
from config.constants import DRIFT_API_URL
from data.models import DriftResponse


class DriftClient(BaseAPIClient):
    """Client for interacting with Drift API."""

    def __init__(self):
        """Initialize Drift API client."""
        super().__init__(DRIFT_API_URL)

    def fetch_markets_24h(self) -> DriftResponse:
        """
        Fetch 24h market data from Drift API.

        Returns:
            DriftResponse object with market data or error information
        """
        response = self.get()

        return DriftResponse(
            success=response.success,
            data=response.data,
            error=response.error
        )

    def get_perp_markets(self) -> List[Dict]:
        """
        Get perpetual markets data with filtering applied.

        Returns:
            List of perpetual market data dictionaries
        """
        response = self.fetch_markets_24h()
        return response.get_perp_markets()

    def get_funding_data(self) -> List:
        """
        Get funding data in the original format for backward compatibility.

        Returns:
            List of funding data or empty list if request failed
        """
        response = self.fetch_markets_24h()

        if response.success and response.data:
            return response.data

        return []
