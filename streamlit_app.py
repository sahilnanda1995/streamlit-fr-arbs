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

    # === Delta Neutral Arbitrage Calculator ===
    st.header("🧮 Delta Neutral Arbitrage Calculator")
    st.markdown("""
    Estimate profit from delta-neutral strategies by configuring both long and short sides. The calculator will auto-balance exposure and alert you if essential data is missing.
    """)

    # General Inputs
    total_capital = st.number_input("Total Capital (USDC)", min_value=0.0, value=1000.0, step=100.0)
    holding_period_days = st.number_input("Holding Period (days)", min_value=1, value=7, step=1)

    # Load token config for dynamic protocol/market options
    import json
    with open('token_config.json') as f:
        raw_token_config = json.load(f)
    token_config = {k.upper(): v for k, v in raw_token_config.items()}

    def get_protocols_for_token(token):
        """Get available protocols for a token."""
        token = token.upper()
        banks = token_config.get(token, {}).get("banks", [])
        return sorted(set(b["protocol"] for b in banks))

    def get_markets_for_token_protocol(token, protocol):
        """Get available markets for a token and protocol."""
        token = token.upper()
        banks = token_config.get(token, {}).get("banks", [])
        return sorted(set(b["market"] for b in banks if b["protocol"] == protocol))

    def get_all_available_tokens():
        """Get all available tokens from both spot and perp sources."""
        all_tokens = set()

        # Get spot tokens from token_config
        spot_tokens = set(token_config.keys())
        all_tokens.update(spot_tokens)

        # Get perp tokens from merged data
        processed_drift_data = process_drift_data(drift_data)
        merged_data = merge_funding_data(hyperliquid_data, processed_drift_data)

        for token_entry in merged_data:
            if len(token_entry) >= 2:
                all_tokens.add(token_entry[0].upper())

        return sorted(list(all_tokens))

    def get_available_market_types_for_token(token):
        """Get available market types (Spot/Perp) for a given token."""
        available = []

        # Check spot availability
        if token.upper() in token_config:
            available.append("Spot")

        # Check perp availability
        processed_drift_data = process_drift_data(drift_data)
        merged_data = merge_funding_data(hyperliquid_data, processed_drift_data)

        for token_entry in merged_data:
            if len(token_entry) >= 2 and token_entry[0].upper() == token.upper():
                available.append("Perp")
                break

        return available

    def get_perp_exchanges_for_token(token):
        """Get available perp exchanges for a token based on merged data."""
        # Use the same merged data that's used in the funding rates table
        processed_drift_data = process_drift_data(drift_data)
        merged_data = merge_funding_data(hyperliquid_data, processed_drift_data)

        exchanges = []

        # Look for the token in the merged data
        for token_entry in merged_data:
            if len(token_entry) >= 2 and token_entry[0].upper() == token.upper():
                # Check each exchange for this token
                for exchange_name, details in token_entry[1]:
                    if details is not None:
                        # Map internal exchange names to user-friendly names
                        if exchange_name == "HlPerp":
                            exchanges.append("hyperliquid")
                        elif exchange_name == "BinPerp":
                            exchanges.append("binance")
                        elif exchange_name == "BybitPerp":
                            exchanges.append("bybit")
                        elif exchange_name == "DriftPerp":
                            exchanges.append("drift")
                break

        return sorted(set(exchanges)) if exchanges else []

    st.subheader("Long Side Configuration")
    # Dynamic token selection
    all_tokens = get_all_available_tokens()
    long_token = st.selectbox("Long Token", ["Select"] + all_tokens)

    # Dynamic market type selection based on selected token
    if long_token != "Select":
        available_market_types = get_available_market_types_for_token(long_token)
        if available_market_types:
            long_market_type = st.selectbox("Long Market Type", ["Select"] + available_market_types, key="long_market_type")
        else:
            long_market_type = st.selectbox("Long Market Type", ["Select"], disabled=True, key="long_market_type")
            st.warning(f"No market types available for {long_token}")
    else:
        long_market_type = st.selectbox("Long Market Type", ["Select"], disabled=True, key="long_market_type")

    # Show available options for transparency, but use the first available for calculation
    long_protocol = long_market = long_exchange = None
    if long_token != "Select" and long_market_type == "Spot":
        protocols = get_protocols_for_token(long_token)
        if protocols:
            long_protocol = st.selectbox("Long Protocol", protocols, key="long_protocol")
            markets = get_markets_for_token_protocol(long_token, long_protocol)
            if markets:
                long_market = st.selectbox("Long Market", markets, key="long_market")
        else:
            st.warning(f"No protocols available for {long_token}")
    elif long_token != "Select" and long_market_type == "Perp":
        exchanges = get_perp_exchanges_for_token(long_token)
        if exchanges:
            long_exchange = st.selectbox("Long Perp Exchange", exchanges, key="long_exchange")
        else:
            st.warning(f"No perp exchanges available for {long_token}")

    long_leverage = st.slider("Long Leverage", min_value=1, max_value=5, value=1)

    st.subheader("Short Side Configuration")
    # Dynamic token selection
    short_token = st.selectbox("Short Token", ["Select"] + all_tokens)

    # Dynamic market type selection based on selected token
    if short_token != "Select":
        available_market_types_short = get_available_market_types_for_token(short_token)
        if available_market_types_short:
            short_market_type = st.selectbox("Short Market Type", ["Select"] + available_market_types_short, key="short_market_type")
        else:
            short_market_type = st.selectbox("Short Market Type", ["Select"], disabled=True, key="short_market_type")
            st.warning(f"No market types available for {short_token}")
    else:
        short_market_type = st.selectbox("Short Market Type", ["Select"], disabled=True, key="short_market_type")

    # Show available options for transparency, but use the first available for calculation
    short_protocol = short_market = short_exchange = None
    if short_token != "Select" and short_market_type == "Spot":
        protocols = get_protocols_for_token(short_token)
        if protocols:
            short_protocol = st.selectbox("Short Protocol", protocols, key="short_protocol")
            markets = get_markets_for_token_protocol(short_token, short_protocol)
            if markets:
                short_market = st.selectbox("Short Market", markets, key="short_market")
        else:
            st.warning(f"No protocols available for {short_token}")
    elif short_token != "Select" and short_market_type == "Perp":
        exchanges = get_perp_exchanges_for_token(short_token)
        if exchanges:
            short_exchange = st.selectbox("Short Perp Exchange", exchanges, key="short_exchange")
        else:
            st.warning(f"No perp exchanges available for {short_token}")

    short_leverage = st.slider("Short Leverage", min_value=1, max_value=5, value=1)

    # Exposure Balancing Logic
    if long_leverage + short_leverage > 0:
        capital_long = total_capital * short_leverage / (long_leverage + short_leverage)
        capital_short = total_capital * long_leverage / (long_leverage + short_leverage)
    else:
        capital_long = capital_short = 0

    st.markdown(f"**Auto-Split Capital:** Long Side: ${capital_long:,.2f}, Short Side: ${capital_short:,.2f}")
    st.markdown(f"**Notional Exposure:** Long: ${capital_long * long_leverage:,.2f}, Short: ${capital_short * short_leverage:,.2f}")

    # Calculation Trigger
    calc_btn = st.button("Calculate Arb")

    # Helper functions for rate fetching
    import json
    from data.money_markets_processing import get_rates_by_bank_address, get_staking_rate_by_mint
    with open('token_config.json') as f:
        raw_token_config = json.load(f)
    token_config = {k.upper(): v for k, v in raw_token_config.items()}

    def get_bank_info(token, protocol=None, market=None):
        token = token.upper()
        banks = token_config.get(token, {}).get("banks", [])
        if protocol and market:
            for b in banks:
                if b["protocol"].lower() == protocol.lower() and b["market"].lower() == market.lower():
                    return b
        elif banks:
            return banks[0]
        return None

    def get_spot_rates(token, protocol, market, rates_data, staking_data):
        bank = get_bank_info(token, protocol, market)
        if not bank:
            return None, None, None, None
        bank_addr = bank["bank"]
        mint = token_config[token.upper()]["mint"]
        rates = get_rates_by_bank_address(rates_data, bank_addr)
        staking = get_staking_rate_by_mint(staking_data, mint) or 0.0
        lend = rates.get("lendingRate") if rates else None
        borrow = rates.get("borrowingRate") if rates else None
        return lend, borrow, staking, bank

    def get_perp_funding_rate(token, exchange, market, drift_data, hyperliquid_data):
        """Get funding rate for a token from the specified exchange."""
        # Use the same merged data that's used in the funding rates table
        processed_drift_data = process_drift_data(drift_data)
        merged_data = merge_funding_data(hyperliquid_data, processed_drift_data)

        # Map user-friendly exchange names back to internal names
        exchange_mapping = {
            "drift": "DriftPerp",
            "hyperliquid": "HlPerp",
            "binance": "BinPerp",
            "bybit": "BybitPerp"
        }

        internal_exchange_name = exchange_mapping.get(exchange.lower())
        if not internal_exchange_name:
            return None

        # Look for the token in the merged data
        for token_entry in merged_data:
            if len(token_entry) >= 2 and token_entry[0].upper() == token.upper():
                # Check each exchange for this token
                for exchange_name, details in token_entry[1]:
                    if exchange_name == internal_exchange_name and details is not None:
                        try:
                            funding_rate = float(details.get("fundingRate", 0))
                            interval = details.get("fundingIntervalHours", 1)
                            # Convert to annualized percentage (like in the table)
                            return funding_rate * (8760 / interval) * 100  # 8760 hours in a year
                        except (ValueError, TypeError):
                            return None
                break

        return None

    if calc_btn:
        # Check for required selections
        missing = []
        if long_token == "Select":
            missing.append("Long Token")
        if long_market_type == "Select":
            missing.append("Long Market Type")
        if long_market_type == "Spot":
            if not long_protocol:
                missing.append("Long Protocol")
            if not long_market:
                missing.append("Long Market")
        elif long_market_type == "Perp":
            if not long_exchange:
                missing.append("Long Perp Exchange")
        if short_token == "Select":
            missing.append("Short Token")
        if short_market_type == "Select":
            missing.append("Short Market Type")
        if short_market_type == "Spot":
            if not short_protocol:
                missing.append("Short Protocol")
            if not short_market:
                missing.append("Short Market")
        elif short_market_type == "Perp":
            if not short_exchange:
                missing.append("Short Perp Exchange")
        if missing:
            st.warning(f"Essential data is not available to calculate: {', '.join(missing)}.")
        else:
            # Calculate hourly rates for long side
            if long_market_type == "Spot":
                # Long spot: borrow USDC, lend token (inverse of short position)
                token_lend, usdc_borrow, token_staking, _ = get_spot_rates(long_token, long_protocol, long_market, rates_data, staking_data)
                usdc_lend, usdc_borrow_rate, usdc_staking, _ = get_spot_rates("USDC", long_protocol, long_market, rates_data, staking_data)

                if token_lend is None or usdc_borrow is None:
                    st.warning(f"Required rates not available for long {long_token} spot position.")
                    st.stop()

                # Net rates
                token_net_lend = token_lend + (token_staking or 0)
                usdc_net_borrow = usdc_borrow + (usdc_staking or 0)

                # Long position: earn on token lending, pay on USDC borrowing
                long_hourly_rate = (token_net_lend * long_leverage - usdc_net_borrow * (long_leverage - 1)) / (365 * 24)
                long_breakdown = f"Spot ({long_protocol}/{long_market}): {long_hourly_rate:.6f}% per hour"

            else:  # Perp
                funding = get_perp_funding_rate(long_token, long_exchange, None, drift_data, hyperliquid_data)
                if funding is None:
                    st.warning(f"Funding rate not available for {long_token} perp on {long_exchange}.")
                    st.stop()

                # Convert annual funding rate to hourly rate
                long_hourly_rate = funding / (365 * 24)
                long_breakdown = f"Perp ({long_exchange}): {long_hourly_rate:.6f}% per hour"

            # Calculate hourly rates for short side
            if short_market_type == "Spot":
                # Short spot: borrow token, lend USDC (same as BTC/SOL table)
                token_lend, token_borrow, token_staking, _ = get_spot_rates(short_token, short_protocol, short_market, rates_data, staking_data)
                usdc_lend, usdc_borrow_rate, usdc_staking, _ = get_spot_rates("USDC", short_protocol, short_market, rates_data, staking_data)

                if token_borrow is None or usdc_lend is None:
                    st.warning(f"Required rates not available for short {short_token} spot position.")
                    st.stop()

                # Net rates
                token_net_borrow = token_borrow + (token_staking or 0)
                usdc_net_lend = usdc_lend + (usdc_staking or 0)

                # Short position: earn on USDC lending, pay on token borrowing
                short_hourly_rate = (usdc_net_lend * (short_leverage - 1) - token_net_borrow * short_leverage) / (365 * 24)
                short_breakdown = f"Spot ({short_protocol}/{short_market}): {short_hourly_rate:.6f}% per hour"

            else:  # Perp
                funding2 = get_perp_funding_rate(short_token, short_exchange, None, drift_data, hyperliquid_data)
                if funding2 is None:
                    st.warning(f"Funding rate not available for {short_token} perp on {short_exchange}.")
                    st.stop()

                # Convert annual funding rate to hourly rate and make negative for short
                short_hourly_rate = -funding2 / (365 * 24)
                short_breakdown = f"Perp ({short_exchange}): {short_hourly_rate:.6f}% per hour"

            # Calculate arbitrage opportunity
            rate_differential = long_hourly_rate + short_hourly_rate

            # Calculate interest amounts based on notional exposures
            long_notional = capital_long * long_leverage
            short_notional = capital_short * short_leverage

            long_interest_per_hour = long_hourly_rate * long_notional / 100
            short_interest_per_hour = short_hourly_rate * short_notional / 100
            net_interest_per_hour = long_interest_per_hour + short_interest_per_hour

            st.success("**Delta-Neutral Arbitrage Rates**")

            # Summary
            st.markdown(f"**Long Side:** {long_token} | {long_market_type} | {long_breakdown}")
            st.markdown(f"**Short Side:** {short_token} | {short_market_type} | {short_breakdown}")
            st.markdown(f"**Rate Differential:** {rate_differential:.6f}% per hour")

            # Interest calculations
            st.markdown("### Interest Per Hour")
            st.markdown(f"**Long Side Interest:** ${long_interest_per_hour:,.6f} per hour (Rate: {long_hourly_rate:.6f}% × Notional: ${long_notional:,.2f})")
            st.markdown(f"**Short Side Interest:** ${short_interest_per_hour:,.6f} per hour (Rate: {short_hourly_rate:.6f}% × Notional: ${short_notional:,.2f})")
            st.markdown(f"**Net Interest:** ${net_interest_per_hour:,.6f} per hour")

            if rate_differential > 0:
                st.markdown("❌ **No Arbitrage Opportunity Detected:**")
            elif rate_differential < 0:
                st.markdown("✅ **Arbitrage Opportunity Detected:**")
            else:
                st.markdown("⚖️ **Balanced:** Rates are equal")

    # === Spot Hourly Rates ===
    st.header("💰 Spot Hourly Rates")
    # === SPOT Hourly RATES TABLE FOR SOL, JITOSOL, JUPSOL ===
    st.subheader("SOL Spot Hourly Rates Table(SOL, JITOSOL, JUPSOL)")

    import pandas as pd

    # Assets to show (all uppercase for consistency)
    sol_assets = ["SOL", "JITOSOL", "JUPSOL"]
    borrow_asset = "USDC"  # Default, but can be made dynamic

    # Load token config and convert keys to uppercase
    import json
    with open('token_config.json') as f:
        raw_token_config = json.load(f)
    token_config = {k.upper(): v for k, v in raw_token_config.items()}

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
