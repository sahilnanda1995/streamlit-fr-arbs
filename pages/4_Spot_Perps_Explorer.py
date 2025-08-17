"""
Spot & Perps Explorer: full analysis moved from main page.
Includes: top opportunities, tables, all opportunities, detailed breakdowns.
"""

import streamlit as st

from api.endpoints import (
    fetch_loris_funding_data,
    fetch_drift_markets_24h,
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates,
)
from config import get_token_config
from data.spot_perps import (
    display_spot_perps_opportunities_section,
)


def main():
    st.set_page_config(page_title="Spot & Perps Explorer", layout="wide")
    st.title("🔍 Spot & Perps Explorer")
    st.write("Deep-dive explorer with tables, detailed opportunities, and breakdowns.")

    with st.spinner("Loading..."):
        rates_data = fetch_asgard_current_rates()
        staking_data = fetch_asgard_staking_rates()
        hyperliquid_data = fetch_loris_funding_data()
        drift_data = fetch_drift_markets_24h()

    token_config = get_token_config()

    # Render the full section that previously lived on the main page
    display_spot_perps_opportunities_section(
        token_config,
        rates_data,
        staking_data,
        hyperliquid_data,
        drift_data,
    )


if __name__ == "__main__":
    main()


