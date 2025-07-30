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

def main():
    """Main application logic."""
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.write(APP_DESCRIPTION)

    # === DATA FETCHING AT THE TOP ===
    with st.spinner("Loading..."):
        rates_data = fetch_asgard_current_rates()
        staking_data = fetch_asgard_staking_rates()
        hyperliquid_data = fetch_hyperliquid_funding_data()
        drift_data = fetch_drift_markets_24h()

    # === SOL Spot <-> Perps Arbitrage ===
    st.header("💰 SOL Spot <-> Perps Arbitrage")


    # === MONEY MARKETS SECTION ===
    st.header("💰 Money Markets")
    processed_money_markets = process_money_markets_data(rates_data, staking_data)
    if not processed_money_markets:
        st.error("Failed to load money markets data from APIs. Please try again later.")
        return
    formatted_data = process_money_markets_for_display(processed_money_markets)
    df = create_money_markets_dataframe(formatted_data)
    styled_df = format_money_markets_for_display(df)
    st.dataframe(styled_df, use_container_width=True)
    with st.expander("🔍 Show raw money markets API responses"):
        st.write("**Current Rates Data:**")
        st.json(rates_data)
        st.write("**Staking Rates Data:**")
        st.json(staking_data)
    st.divider()

    # === FUNDING RATES SECTION ===
    selected_interval = st.selectbox(
        "Select target funding interval:",
        list(INTERVAL_OPTIONS.keys())
    )
    target_hours = INTERVAL_OPTIONS[selected_interval]
    processed_drift_data = process_drift_data(drift_data)
    merged_data = merge_funding_data(hyperliquid_data, processed_drift_data)
    if not merged_data:
        st.error("Failed to load funding data from APIs. Please try again later.")
        st.stop()
    formatted_data = process_raw_data_for_display(merged_data, target_hours)
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
