"""
Funding Rates page.
"""

import streamlit as st
from config.constants import (
    INTERVAL_OPTIONS,
    APP_TITLE,
    APP_DESCRIPTION,
    PAGE_TITLE
)
from api.endpoints import (
    fetch_loris_funding_data,
    fetch_drift_markets_24h
)
from data.processing import merge_funding_rate_data
from utils.formatting import (
    process_raw_data_for_display,
    create_styled_dataframe,
    format_dataframe_for_display
)


def main():
    """Main page logic for Funding Rates."""
    st.set_page_config(page_title="Funding Rates", layout="wide")
    st.title("📈 Funding Rates")
    st.write("Compare perpetual funding rates across exchanges with flexible time intervals.")

    # === DATA FETCHING ===
    with st.spinner("Loading funding rates data..."):
        hyperliquid_data = fetch_loris_funding_data()
        drift_data = fetch_drift_markets_24h()

    # === PERPS DATA MERGING ===
    merged_perps_data = merge_funding_rate_data(hyperliquid_data, drift_data)

    selected_interval = st.selectbox(
        "Select target funding interval:",
        list(INTERVAL_OPTIONS.keys()),
        index=0  # Default to 1 yr
    )
    target_hours = INTERVAL_OPTIONS[selected_interval]

    # Use the pre-merged perps data
    if not merged_perps_data:
        st.error("Failed to load funding data from APIs. Please try again later.")
        st.stop()
    formatted_data = process_raw_data_for_display(merged_perps_data, target_hours)
    df = create_styled_dataframe(formatted_data)
    st.subheader(f"Funding Rates (%), scaled to {selected_interval}")
    styled_df = format_dataframe_for_display(df)
    st.dataframe(styled_df)
    with st.expander("🔍 Show raw API response"):
        st.write("**Hyperliquid Data:**")
        st.json(hyperliquid_data)
        st.write("**Drift Data:**")
        st.json(drift_data)


if __name__ == "__main__":
    main()
