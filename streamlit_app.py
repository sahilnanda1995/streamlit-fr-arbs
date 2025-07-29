"""
Streamlit application for funding rate comparison across exchanges.
"""

import streamlit as st

# Import from our organized modules
from config.constants import (
    INTERVAL_OPTIONS,
    APP_TITLE,
    APP_DESCRIPTION,
    PAGE_TITLE
)
from api.hyperliquid import HyperliquidClient
from api.drift import DriftClient
from data.processing import process_drift_data
from data.merger import merge_funding_data
from utils.formatting import (
    process_raw_data_for_display,
    create_styled_dataframe,
    format_dataframe_for_display
)


def configure_page():
    """Configure Streamlit page settings and display header."""
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.write(APP_DESCRIPTION)


@st.cache_data
def load_funding_data():
    """
    Load and process funding data from all sources with caching.

    Returns:
        Tuple of (merged_data, hyperliquid_raw, drift_raw) for display
    """
    # Initialize API clients
    hyperliquid_client = HyperliquidClient()
    drift_client = DriftClient()

    # Fetch data from both sources
    hyperliquid_data = hyperliquid_client.get_funding_data()
    drift_data = drift_client.get_funding_data()

    # Process and merge data
    processed_drift_data = process_drift_data(drift_data)
    merged_data = merge_funding_data(hyperliquid_data, processed_drift_data)

    return merged_data, hyperliquid_data, drift_data


def render_interval_selector():
    """
    Render the interval selection dropdown.

    Returns:
        Tuple of (selected_interval, target_hours)
    """
    selected_interval = st.selectbox(
        "Select target funding interval:",
        list(INTERVAL_OPTIONS.keys())
    )
    target_hours = INTERVAL_OPTIONS[selected_interval]

    return selected_interval, target_hours


def render_funding_table(merged_data, selected_interval, target_hours):
    """
    Render the main funding rates table.

    Args:
        merged_data: Processed funding data
        selected_interval: Selected time interval
        target_hours: Target hours for scaling
    """
    # Process data for display
    formatted_data = process_raw_data_for_display(merged_data, target_hours)

    # Create and style DataFrame
    df = create_styled_dataframe(formatted_data)

    # Display table
    st.subheader(f"Funding Rates (%), scaled to {selected_interval}")
    styled_df = format_dataframe_for_display(df)
    st.dataframe(styled_df)


def render_raw_data_expander(hyperliquid_raw, drift_raw):
    """
    Render expandable section with raw API responses.

    Args:
        hyperliquid_raw: Raw Hyperliquid API response
        drift_raw: Raw Drift API response
    """
    with st.expander("🔍 Show raw API response"):
        st.write("**Hyperliquid Data:**")
        st.json(hyperliquid_raw)
        st.write("**Drift Data:**")
        st.json(drift_raw)


def main():
    """Main application logic."""
    # Configure page
    configure_page()

    # Render interval selector
    selected_interval, target_hours = render_interval_selector()

    # Load data with progress indicator
    with st.spinner("Loading funding data..."):
        merged_data, hyperliquid_raw, drift_raw = load_funding_data()

    # Check if we have data
    if not merged_data:
        st.error("Failed to load funding data from APIs. Please try again later.")
        st.stop()

    # Render main table
    render_funding_table(merged_data, selected_interval, target_hours)

    # Render raw data section
    render_raw_data_expander(hyperliquid_raw, drift_raw)


if __name__ == "__main__":
    main()
