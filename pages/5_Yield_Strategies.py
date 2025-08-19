"""
Yield Strategies page: JLP and ALP strategy simulators.
"""

import streamlit as st

from config import get_token_config
from data.spot_perps import (
    display_alp_strategy_section,
    display_asset_strategy_section,
)


def main():
    st.set_page_config(page_title="Yield Strategies", layout="wide")
    st.title("🌾 Yield Strategies")
    st.write("Explore lending/borrowing yield strategies with compounding and P&L breakdowns.")

    token_config = get_token_config()

    # JLP strategy
    st.subheader("JLP Strategy")
    display_asset_strategy_section(token_config, "JLP")

    st.divider()

    # ALP strategy
    st.subheader("ALP Strategy")
    display_alp_strategy_section(token_config)


if __name__ == "__main__":
    main()


