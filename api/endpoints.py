"""
Functional API endpoints for fetching data from external services.
"""

import streamlit as st
from typing import List, Dict, Any
from .http_utils import get_request, post_request
from config.constants import (
    HYPERLIQUID_API_URL,
    HYPERLIQUID_HEADERS,
    HYPERLIQUID_REQUEST_BODY,
    DRIFT_API_URL,
    ASGARD_CURRENT_RATES_URL,
    ASGARD_STAKING_RATES_URL
)


@st.cache_data
def fetch_hyperliquid_funding_data() -> List[Dict[str, Any]]:
    """
    Fetch predicted funding rates from Hyperliquid API.

    Returns:
        List of funding data or empty list if request failed
    """
    response_data = post_request(
        url=HYPERLIQUID_API_URL,
        headers=HYPERLIQUID_HEADERS,
        json_data=HYPERLIQUID_REQUEST_BODY
    )

    return response_data if response_data is not None else []


@st.cache_data
def fetch_drift_markets_24h() -> Dict[str, Any]:
    """
    Fetch 24h market data from Drift API.

    Returns:
        Market data dictionary or empty dict if request failed
    """
    response_data = get_request(url=DRIFT_API_URL)

    return response_data if response_data is not None else {}


@st.cache_data
def fetch_asgard_current_rates() -> List[Dict[str, Any]]:
    """
    Fetch current lending and borrowing rates from Asgard API.

    Returns:
        List of rates data or empty list if request failed
    """
    response_data = get_request(url=ASGARD_CURRENT_RATES_URL)

    if response_data is not None and isinstance(response_data, dict):
        # Extract the 'data' field from the response
        return response_data.get("data", [])
    return []


@st.cache_data
def fetch_asgard_staking_rates() -> List[Dict[str, Any]]:
    """
    Fetch current staking rates from Asgard API.

    Returns:
        List of staking data or empty list if request failed
    """
    response_data = get_request(url=ASGARD_STAKING_RATES_URL)

    if response_data is not None and isinstance(response_data, dict):
        # Extract the 'data' field from the response
        return response_data.get("data", [])
    return []
