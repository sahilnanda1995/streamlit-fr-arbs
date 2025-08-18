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
    fetch_loris_funding_data,
    fetch_drift_markets_24h,
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates
)
from data.spot_perps import display_curated_arbitrage_section, display_jlp_strategy_section

def main():
    """Main application logic."""
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.write(APP_DESCRIPTION)

    # === DATA FETCHING AT THE TOP ===
    with st.spinner("Loading..."):
        rates_data = fetch_asgard_current_rates()
        staking_data = fetch_asgard_staking_rates()
        hyperliquid_data = fetch_loris_funding_data()
        drift_data = fetch_drift_markets_24h()

    # === CURATED SPOT AND PERPS ARBITRAGE SECTION ===
    # Load token config
    from config import get_token_config
    token_config = get_token_config()

    # Display curated arbitrage section only
    display_curated_arbitrage_section(
        token_config,
        rates_data,
        staking_data,
        hyperliquid_data,
        drift_data
    )

    # === JLP strategy section (below backtesting) ===
    display_jlp_strategy_section(token_config)


if __name__ == "__main__":
    main()
