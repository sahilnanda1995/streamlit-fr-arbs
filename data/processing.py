"""
Data processing functions for transforming API responses into standardized formats.
"""

from typing import List, Dict, Any
from config.constants import (
    PERP_SYMBOL_SUFFIX,
    PERCENTAGE_CONVERSION_FACTOR
)


def merge_funding_rate_data(
    hyperliquid_response: List[List],
    drift_response: Dict[str, Any]
) -> List[List]:
    """
    Process and merge funding rate data from Hyperliquid and Drift APIs.
    All rates are normalized to 1-hour intervals and returned as numbers.

    Args:
        hyperliquid_response: Raw response from Hyperliquid API
        drift_response: Raw response from Drift API

    Returns:
        List of [token_name, [[exchange_name, exchange_info]]] entries. fundingRate is in decimal format.
    """
    # Handle empty or None responses
    if not hyperliquid_response:
        hyperliquid_response = []
    if not drift_response:
        drift_response = {"data": []}

    # Process Hyperliquid data
    hyperliquid_processed = process_hyperliquid_raw_data(hyperliquid_response)

    # Process Drift data
    drift_processed = process_drift_raw_data(drift_response)

    # Merge the processed data
    return merge_processed_data(hyperliquid_processed, drift_processed)


def process_hyperliquid_raw_data(hyperliquid_response: List[List]) -> List[List]:
    """
    Process Hyperliquid API response and normalize funding rates to 1-hour intervals.

    Args:
        hyperliquid_response: Raw response from Hyperliquid API

    Returns:
        List of [token_name, [[exchange_name, exchange_info]]] entries
    """
    processed_data = []

    # Handle empty or None responses
    if not hyperliquid_response:
        return []

    for item in hyperliquid_response:
        if not item or len(item) < 2:
            continue

        token_name = item[0]
        exchanges = item[1]

        if not exchanges:
            continue

        processed_exchanges = []
        for exchange in exchanges:
            if not exchange or len(exchange) < 2:
                continue

            exchange_name = exchange[0]
            details = exchange[1]

            if not details:
                continue

            try:
                funding_rate = float(details.get("fundingRate", 0))
                funding_interval = details.get("fundingIntervalHours", 1)

                # Normalize to 1-hour interval
                if funding_interval != 1:
                    funding_rate = funding_rate / funding_interval

                processed_exchanges.append([exchange_name, {
                    "fundingRate": funding_rate
                }])
            except (ValueError, TypeError):
                continue

        if processed_exchanges:
            processed_data.append([token_name, processed_exchanges])

    return processed_data


def process_drift_raw_data(drift_response: Dict[str, Any]) -> List[List]:
    """
    Process Drift API response and normalize funding rates to 1-hour intervals.

    Args:
        drift_response: Raw response from Drift API

    Returns:
        List of [token_name, [[exchange_name, exchange_info]]] entries
    """
    processed_data = []

    # Handle empty or None responses
    if not drift_response:
        return []

    # Filter for perp markets only
    perp_markets = get_perp_markets_from_drift_data(drift_response)

    for item in perp_markets:
        if not item:
            continue

        symbol = item.get("symbol", "")
        if not symbol:
            continue

        # Extract token name by removing -PERP suffix
        token_name = symbol.replace(PERP_SYMBOL_SUFFIX, "")

        try:
            # Get avgFunding and convert from percentage to decimal
            avg_funding = item.get("avgFunding", 0)
            funding_rate_decimal = avg_funding / PERCENTAGE_CONVERSION_FACTOR

            # Create entry with 1-hour normalized rate
            drift_entry = [
                token_name,
                [["DriftPerp", {
                    "fundingRate": funding_rate_decimal
                }]]
            ]
            processed_data.append(drift_entry)
        except (ValueError, TypeError):
            continue

    return processed_data


def merge_processed_data(hyperliquid_data: List[List], drift_data: List[List]) -> List[List]:
    """
    Merge processed Hyperliquid and Drift data into unified dataset.

    Args:
        hyperliquid_data: Processed Hyperliquid data
        drift_data: Processed Drift data

    Returns:
        Merged list with combined exchange data for each token
    """
    # Handle empty data
    if not hyperliquid_data and not drift_data:
        return []

    # Create dictionaries for easy lookup
    hl_dict = {entry[0]: entry for entry in hyperliquid_data if entry and len(entry) >= 2}
    drift_dict = {entry[0]: entry for entry in drift_data if entry and len(entry) >= 2}

    merged_data = []

    # Process all tokens from both sources
    all_tokens = set(hl_dict.keys()) | set(drift_dict.keys())

    for token in all_tokens:
        if token in hl_dict and token in drift_dict:
            # Token exists in both sources - merge exchanges
            hl_entry = hl_dict[token]
            drift_entry = drift_dict[token]

            # Combine exchange data
            combined_exchanges = hl_entry[1] + drift_entry[1]
            merged_entry = [token, combined_exchanges]
            merged_data.append(merged_entry)

        elif token in hl_dict:
            # Token only in Hyperliquid
            merged_data.append(hl_dict[token])

        elif token in drift_dict:
            # Token only in Drift
            merged_data.append(drift_dict[token])

    return merged_data


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


def create_exchange_entry(exchange_name: str, funding_rate: float) -> List:
    """
    Create standardized exchange entry format.
    All rates are normalized to 1-hour intervals.

    Args:
        exchange_name: Name of the exchange
        funding_rate: Funding rate as decimal (normalized to 1-hour interval)

    Returns:
        Standardized exchange entry
    """
    return [exchange_name, {
        "fundingRate": funding_rate
    }]
