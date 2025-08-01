"""
Money Markets page.
"""

import streamlit as st
from config.constants import (
    APP_TITLE,
    APP_DESCRIPTION,
    PAGE_TITLE
)
from api.endpoints import (
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates
)
from data.money_markets_processing import process_money_markets_data
from utils.formatting import (
    process_money_markets_for_display,
    create_money_markets_dataframe,
    format_money_markets_for_display
)


def main():
    """Main page logic for Money Markets."""
    st.set_page_config(page_title="Money Markets", layout="wide")
    st.title("💰 Money Markets")
    st.write("Display current lending/borrowing rates and staking yields across multiple DeFi protocols.")

    # === DATA FETCHING ===
    with st.spinner("Loading money markets data..."):
        rates_data = fetch_asgard_current_rates()
        staking_data = fetch_asgard_staking_rates()

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


if __name__ == "__main__":
    main()
