"""
Data processing functions for transforming API responses into standardized formats.
"""

from typing import List, Dict, Any
from config.constants import (
    PERP_SYMBOL_SUFFIX,
    PERCENTAGE_CONVERSION_FACTOR,
    DEFAULT_FUNDING_INTERVAL_HOURS
)


def process_drift_data(drift_data: Dict[str, Any]) -> List[List]:
    """
    Process Drift API data and convert to Hyperliquid-compatible format.

    Args:
        drift_data: Raw response from Drift API

    Returns:
        List of [token_name, [[exchange_name, exchange_info]]] entries
    """
    processed_data = []

    # First, filter for perp markets only
    perp_markets = get_perp_markets_from_drift_data(drift_data)

    for item in perp_markets:
        symbol = item.get("symbol", "")

        # Extract token name by removing -PERP suffix
        token_name = symbol.replace(PERP_SYMBOL_SUFFIX, "")

        # Get avgFunding and convert from percentage to decimal
        avg_funding = item.get("avgFunding", 0)
        funding_rate_decimal = avg_funding / PERCENTAGE_CONVERSION_FACTOR

        # Create entry in Hyperliquid-compatible format
        drift_entry = [
            token_name,
            [["DriftPerp", {
                "fundingRate": str(funding_rate_decimal),
                "fundingIntervalHours": DEFAULT_FUNDING_INTERVAL_HOURS
            }]]
        ]
        processed_data.append(drift_entry)

    return processed_data


def get_perp_markets_from_drift_data(drift_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract perpetual markets from Drift API response data.

    Args:
        drift_data: Raw response from Drift API

    Returns:
        List of perpetual market data dictionaries
    """
    if not drift_data:
        return []

    # Handle the API response structure - data is in drift_data["data"]
    data_array = drift_data.get("data", [])

    perp_markets = []
    for item in data_array:
        market_type = item.get("marketType", {})
        symbol = item.get("symbol", "")

        # Filter for perp markets
        if "perp" in market_type and symbol.endswith(PERP_SYMBOL_SUFFIX):
            perp_markets.append(item)

    return perp_markets


def filter_perp_markets(market_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter market data to only include perpetual markets.

    Args:
        market_data: List of market data from API

    Returns:
        Filtered list containing only perpetual markets
    """
    perp_markets = []

    for item in market_data:
        market_type = item.get("marketType", {})
        symbol = item.get("symbol", "")

        # Filter for perp markets
        if "perp" in market_type and symbol.endswith(PERP_SYMBOL_SUFFIX):
            perp_markets.append(item)

    return perp_markets


def extract_token_name(symbol: str) -> str:
    """
    Extract clean token name from trading symbol.

    Args:
        symbol: Trading symbol (e.g., "BTC-PERP")

    Returns:
        Clean token name (e.g., "BTC")
    """
    return symbol.replace(PERP_SYMBOL_SUFFIX, "")


def convert_percentage_to_decimal(percentage: float) -> float:
    """
    Convert percentage value to decimal.

    Args:
        percentage: Percentage value (e.g., 0.05 for 0.05%)

    Returns:
        Decimal value (e.g., 0.0005)
    """
    return percentage / PERCENTAGE_CONVERSION_FACTOR


def create_exchange_entry(exchange_name: str, funding_rate: float, interval_hours: int = None) -> List:
    """
    Create standardized exchange entry format.

    Args:
        exchange_name: Name of the exchange
        funding_rate: Funding rate as decimal
        interval_hours: Funding interval in hours

    Returns:
        Standardized exchange entry
    """
    if interval_hours is None:
        interval_hours = DEFAULT_FUNDING_INTERVAL_HOURS

    return [exchange_name, {
        "fundingRate": str(funding_rate),
        "fundingIntervalHours": interval_hours
    }]
