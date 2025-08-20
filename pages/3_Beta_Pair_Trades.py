"""
Pair Strategies page: variable-asset pair strategies (e.g., WETH/CBBTC, SOL/CBBTC, JitoSOL/CBBTC).
"""

import streamlit as st

from config import get_token_config
from data.spot_perps.pair_strategy import (
    display_weth_cbbtc_strategy_section,
    display_sol_cbbtc_strategy_section,
    display_jitosol_cbbtc_strategy_section,
)


def main():
    st.set_page_config(page_title="Beta Pair Trades", layout="wide")
    st.title("🤝 Beta Pair Trades")
    st.write("Analyze base/quote long strategies with per-asset compounding, prices, and P&L.")

    token_config = get_token_config()

    # WETH/CBBTC
    st.subheader("WETH / CBBTC")
    display_weth_cbbtc_strategy_section(token_config)

    st.divider()

    # SOL/CBBTC
    st.subheader("SOL / CBBTC")
    display_sol_cbbtc_strategy_section(token_config)

    st.divider()

    # JitoSOL/CBBTC
    st.subheader("JitoSOL / CBBTC")
    display_jitosol_cbbtc_strategy_section(token_config)


if __name__ == "__main__":
    main()


