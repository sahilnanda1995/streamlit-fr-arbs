"""
Streamlit application for funding rate comparison across exchanges.
"""

import streamlit as st

# Import from our organized modules
from config.constants import (
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
from data.spot_perps_arbitrage import display_spot_perps_opportunities_section

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

    # === SPOT AND PERPS OPPORTUNITIES SECTION ===
    # Load token config
    from config import get_token_config
    token_config = get_token_config()

    # Display spot and perps opportunities section
    display_spot_perps_opportunities_section(
        token_config, rates_data, staking_data,
        hyperliquid_data, drift_data
    )


if __name__ == "__main__":
    main()
