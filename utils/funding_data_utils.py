"""
Common funding data fetching logic to reduce duplication across pages.
"""

import streamlit as st
from typing import Dict, Any, Tuple, Optional
from api.endpoints import fetch_loris_funding_data, fetch_drift_markets_24h


def fetch_funding_data_with_retry() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Fetch funding data from both APIs with unified error handling and retry logic.
    
    Returns:
        Tuple of (hyperliquid_data, drift_data) or (None, None) if failed
    """
    # Fetch Loris consolidated funding data
    try:
        hyperliquid_data = fetch_loris_funding_data()
    except Exception as e:
        st.error(f"Failed to load consolidated funding data: {e}")
        if st.button("Retry loading funding data"):
            st.rerun()
        return None, None
    
    # Validate hyperliquid data structure
    if not hyperliquid_data or not isinstance(hyperliquid_data, dict):
        st.warning("Funding data is currently unavailable.")
        if st.button("Retry loading funding data"):
            st.rerun()
        return None, None
    
    # Fetch Drift data
    drift_data = fetch_drift_markets_24h()
    
    return hyperliquid_data, drift_data


def display_funding_data_loading_section() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Display loading section for funding data and return the fetched data.
    
    Returns:
        Tuple of (hyperliquid_data, drift_data) or (None, None) if failed
    """
    with st.spinner("Loading funding rates data..."):
        return fetch_funding_data_with_retry()


def validate_funding_data(hyperliquid_data: Dict[str, Any], drift_data: Dict[str, Any]) -> bool:
    """
    Validate that funding data is in the expected format.
    
    Args:
        hyperliquid_data: Data from Loris API
        drift_data: Data from Drift API
        
    Returns:
        True if data is valid, False otherwise
    """
    if not hyperliquid_data or not isinstance(hyperliquid_data, dict):
        return False
    
    if not drift_data or not isinstance(drift_data, dict):
        return False
        
    return True


def display_funding_data_debug_section(hyperliquid_data: Dict[str, Any], drift_data: Dict[str, Any]) -> None:
    """
    Display raw API response data in an expandable section for debugging.
    
    Args:
        hyperliquid_data: Data from Loris API
        drift_data: Data from Drift API
    """
    with st.expander("🔍 Show raw API response"):
        st.write("**Hyperliquid Data:**")
        st.json(hyperliquid_data)
        st.write("**Drift Data:**")
        st.json(drift_data)


def handle_funding_data_error() -> None:
    """Display error message for funding data failures."""
    st.error("Failed to load funding data from APIs. Please try again later.")
    st.stop()