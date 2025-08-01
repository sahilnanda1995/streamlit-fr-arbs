"""
Spot Hourly Fee Rates page.
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
from data.spot_arbitrage import display_spot_arbitrage_section


def main():
    """Main page logic for Spot Hourly Fee Rates."""
    st.set_page_config(page_title="Spot Hourly Fee Rates", layout="wide")
    st.title("💰 Spot Hourly Fee Rates")
    st.write("Calculate arbitrage opportunities between spot lending/borrowing markets with different leverage levels.")

    # === DATA FETCHING ===
    with st.spinner("Loading spot arbitrage data..."):
        rates_data = fetch_asgard_current_rates()
        staking_data = fetch_asgard_staking_rates()

    # === SPOT ARBITRAGE SECTION ===
    # Load token config
    from config import get_token_config
    token_config = get_token_config()

    # Display spot arbitrage section with long and short positions
    display_spot_arbitrage_section(token_config, rates_data, staking_data)


if __name__ == "__main__":
    main()
