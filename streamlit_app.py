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

    # === Spot Hourly Rates ===
    st.header("💰 Spot Hourly Rates")
    # === SPOT Hourly RATES TABLE FOR SOL, JITOSOL, JUPSOL ===
    st.subheader("SOL Spot Hourly Rates Table(SOL, JITOSOL, JUPSOL)")

    import pandas as pd

    # Assets to show (all uppercase for consistency)
    sol_assets = ["SOL", "JITOSOL", "JUPSOL"]
    borrow_asset = "USDC"  # Default, but can be made dynamic

    # Load token config and convert keys to uppercase
    from config import get_token_config
    token_config = get_token_config()

    # Helper: get protocol/market/bank for an asset
    def get_protocol_market_pairs(token_config, asset):
        return [(b["protocol"], b["market"], b["bank"]) for b in token_config[asset]["banks"]]

    # Build protocol/market pairs for USDC
    usdc_pairs = get_protocol_market_pairs(token_config, borrow_asset)
    usdc_pairs_dict = {(p, m): bank for p, m, bank in usdc_pairs}

    # Helper: get staking rate for asset
    from data.money_markets_processing import get_staking_rate_by_mint

    # Helper: get rates by bank address
    from data.money_markets_processing import get_rates_by_bank_address

    rows = []
    for asset in sol_assets:
        asset_pairs = get_protocol_market_pairs(token_config, asset)
        asset_mint = token_config[asset]["mint"]
        asset_staking_rate = get_staking_rate_by_mint(staking_data, asset_mint) or 0.0
        for protocol, market, asset_bank in asset_pairs:
            # Only include if USDC has the same protocol/market
            if (protocol, market) not in usdc_pairs_dict:
                continue
            usdc_bank = usdc_pairs_dict[(protocol, market)]
            # Get lending/borrowing rates
            asset_rates = get_rates_by_bank_address(rates_data, asset_bank)
            usdc_rates = get_rates_by_bank_address(rates_data, usdc_bank)
            if not asset_rates or not usdc_rates:
                continue
            lend_rate = asset_rates.get("lendingRate")
            borrow_rate = usdc_rates.get("borrowingRate")
            if lend_rate is None or borrow_rate is None:
                continue
            # Staking rate for USDC (usually 0)
            usdc_mint = token_config[borrow_asset]["mint"]
            usdc_staking_rate = get_staking_rate_by_mint(staking_data, usdc_mint) or 0.0
            # Net rates
            net_lend = lend_rate + asset_staking_rate
            net_borrow = borrow_rate + usdc_staking_rate
            # Calculate hourly rates for 1x-5x
            row = {
                "Asset": asset,
                "Protocol": protocol,
                "Market": market,
            }
            for lev in range(1, 6):
                apy = net_borrow * (lev - 1) - net_lend * lev
                hourly = apy / (365 * 24)
                row[f"{lev}x (hr)"] = hourly
            rows.append(row)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No valid protocol/market pairs with both lending and borrowing rates found for SOL, JITOSOL, JUPSOL.")

    # === BTC SPOT Hourly RATES TABLE FOR CBBTC, WBTC, xBTC ===
    st.subheader("BTC Spot Hourly Rates Table(CBBTC, WBTC, xBTC)")
    btc_assets = ["CBBTC", "WBTC", "XBTC"]
    # Reuse token_config, rates_data, staking_data, etc.
    btc_rows = []
    for asset in btc_assets:
        asset_pairs = get_protocol_market_pairs(token_config, asset)
        asset_mint = token_config[asset]["mint"]
        asset_staking_rate = get_staking_rate_by_mint(staking_data, asset_mint) or 0.0
        for protocol, market, asset_bank in asset_pairs:
            if (protocol, market) not in usdc_pairs_dict:
                continue
            usdc_bank = usdc_pairs_dict[(protocol, market)]
            asset_rates = get_rates_by_bank_address(rates_data, asset_bank)
            usdc_rates = get_rates_by_bank_address(rates_data, usdc_bank)
            if not asset_rates or not usdc_rates:
                continue
            lend_rate = asset_rates.get("lendingRate")
            borrow_rate = usdc_rates.get("borrowingRate")
            if lend_rate is None or borrow_rate is None:
                continue
            usdc_mint = token_config[borrow_asset]["mint"]
            usdc_staking_rate = get_staking_rate_by_mint(staking_data, usdc_mint) or 0.0
            net_lend = lend_rate + asset_staking_rate
            net_borrow = borrow_rate + usdc_staking_rate
            row = {
                "Asset": asset,
                "Protocol": protocol,
                "Market": market,
            }
            for lev in range(1, 6):
                apy = net_borrow * (lev - 1) - net_lend * lev
                hourly = apy / (365 * 24)
                row[f"{lev}x (hr)"] = hourly
            btc_rows.append(row)
    if btc_rows:
        btc_df = pd.DataFrame(btc_rows)
        st.dataframe(btc_df, use_container_width=True)
    else:
        st.info("No valid protocol/market pairs with both lending and borrowing rates found for CBBTC, WBTC, xBTC.")

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
