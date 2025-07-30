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
from api.endpoints import (
    fetch_hyperliquid_funding_data,
    fetch_drift_markets_24h,
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates
)
from data.processing import process_drift_data
from data.merger import merge_funding_data
from data.money_markets_processing import process_money_markets_data
from utils.formatting import (
    process_raw_data_for_display,
    create_styled_dataframe,
    format_dataframe_for_display,
    process_money_markets_for_display,
    create_money_markets_dataframe,
    format_money_markets_for_display
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
    # Fetch data from both sources
    hyperliquid_data = fetch_hyperliquid_funding_data()
    drift_data = fetch_drift_markets_24h()

    # Process and merge data
    processed_drift_data = process_drift_data(drift_data)
    merged_data = merge_funding_data(hyperliquid_data, processed_drift_data)

    return merged_data, hyperliquid_data, drift_data


@st.cache_data
def load_money_markets_data():
    """
    Load and process money markets data from Asgard API with caching.

    Returns:
        Tuple of (processed_money_markets, rates_raw, staking_raw) for display
    """
    # Fetch data from both endpoints
    rates_data = fetch_asgard_current_rates()
    staking_data = fetch_asgard_staking_rates()

    # Process data
    processed_money_markets = process_money_markets_data(rates_data, staking_data)

    return processed_money_markets, rates_data, staking_data


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


def render_money_markets_table():
    """
    Render the money markets table section.
    """
    st.header("💰 Money Markets")

    # Load data with progress indicator
    with st.spinner("Loading money markets data..."):
        money_markets_data, rates_raw, staking_raw = load_money_markets_data()

    # Check if we have data
    if not money_markets_data:
        st.error("Failed to load money markets data from APIs. Please try again later.")
        return

    # Process data for display
    formatted_data = process_money_markets_for_display(money_markets_data)

    # Create and style DataFrame
    df = create_money_markets_dataframe(formatted_data)

    # Display table
    styled_df = format_money_markets_for_display(df)
    st.dataframe(styled_df, use_container_width=True)

    # Optional: Raw data expander for debugging
    with st.expander("🔍 Show raw money markets API responses"):
        st.write("**Current Rates Data:**")
        st.json(rates_raw)
        st.write("**Staking Rates Data:**")
        st.json(staking_raw)


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

    # Render money markets section FIRST (above funding rates)
    render_money_markets_table()

    # Add separator
    st.divider()

    # Render interval selector for funding rates
    selected_interval, target_hours = render_interval_selector()

    # Load funding data with progress indicator
    with st.spinner("Loading funding data..."):
        merged_data, hyperliquid_raw, drift_raw = load_funding_data()

    # Check if we have data
    if not merged_data:
        st.error("Failed to load funding data from APIs. Please try again later.")
        st.stop()

    # Render funding rates table
    render_funding_table(merged_data, selected_interval, target_hours)

    # Render raw data section
    render_raw_data_expander(hyperliquid_raw, drift_raw)


if __name__ == "__main__":
    main()
