from typing import Dict, List, Optional

import pandas as pd

from config.constants import DEFAULT_TARGET_HOURS
from .calculations import (
    calculate_spot_rate_with_direction,
    get_perps_rates_for_asset,
    calculate_spot_vs_perps_arb,
    calculate_perps_vs_perps_arb,
)
from .helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_apy_from_net_arb,
)
from data.money_markets_processing import get_staking_rate_by_mint, get_rates_by_bank_address


def display_asset_top_opportunities(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    asset_name: str,
    asset_variants: list,
    asset_type: str,
    target_hours: int = DEFAULT_TARGET_HOURS,
    leverage: float = 2.0,
) -> None:
    import streamlit as st

    asset_opportunities: List[Dict] = []
    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)

    for variant in asset_variants:
        long_rates = calculate_spot_rate_with_direction(
            token_config, rates_data, staking_data, variant, leverage, "long", target_hours
        )
        short_rates = calculate_spot_rate_with_direction(
            token_config, rates_data, staking_data, variant, leverage, "short", target_hours
        )

        all_protocols = set(list(long_rates.keys()) + list(short_rates.keys()))
        for protocol in all_protocols:
            if protocol in long_rates and long_rates[protocol] is not None:
                long_arb = calculate_spot_vs_perps_arb(long_rates[protocol], perps_rates, "Long")
                if long_arb is not None and long_arb < 0:
                    best_exchange = None
                    for exchange, funding_rate in perps_rates.items():
                        if (long_rates[protocol] - funding_rate) == long_arb:
                            best_exchange = exchange
                            break
                    if best_exchange:
                        asset_opportunities.append({
                            'asset': asset_name,
                            'variant': variant,
                            'protocol': protocol,
                            'direction': 'L',
                            'spot_rate': long_rates[protocol],
                            'perps_exchange': best_exchange,
                            'funding_rate': perps_rates[best_exchange],
                            'arbitrage_rate': long_arb,
                            'apy': abs(long_arb) * 365 * 24 / target_hours,
                        })

            if protocol in short_rates and short_rates[protocol] is not None:
                short_arb = calculate_spot_vs_perps_arb(short_rates[protocol], perps_rates, "Short")
                if short_arb is not None and short_arb < 0:
                    best_exchange = None
                    for exchange, funding_rate in perps_rates.items():
                        if (short_rates[protocol] + funding_rate) == short_arb:
                            best_exchange = exchange
                            break
                    if best_exchange:
                        asset_opportunities.append({
                            'asset': asset_name,
                            'variant': variant,
                            'protocol': protocol,
                            'direction': 'S',
                            'spot_rate': short_rates[protocol],
                            'perps_exchange': best_exchange,
                            'funding_rate': perps_rates[best_exchange],
                            'arbitrage_rate': short_arb,
                            'apy': abs(short_arb) * 365 * 24 / target_hours,
                        })

    asset_top = sorted(asset_opportunities, key=lambda x: x['arbitrage_rate'])[:3]
    if asset_top:
        st.subheader(f"🏆 Top {asset_name} Arbitrage Opportunities")
        for i, opp in enumerate(asset_top):
            ranking_emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
            protocol_display = opp['protocol'].replace('(', ' (')
            st.markdown(
                f"{ranking_emoji} {opp['asset']} "
                f"<span style='color: #00ff00'>{opp['apy']:.0f}%</span> • "
                f"💰 Buy {opp['variant']} {protocol_display} {opp['spot_rate']:.2f}% • "
                f"🎯 Sell {opp['asset']} {opp['perps_exchange']} {opp['funding_rate']:.2f}%",
                unsafe_allow_html=True,
            )
        st.markdown("<br>", unsafe_allow_html=True)


def create_spot_perps_opportunities_table(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    asset_variants: list,
    asset_type: str,
    leverage: float = 2.0,
    target_hours: int = DEFAULT_TARGET_HOURS,
    show_spot_vs_perps: bool = True,
    show_perps_vs_perps: bool = False,
) -> pd.DataFrame:
    rows: List[Dict] = []

    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)
    for direction in ["Long", "Short"]:
        row: Dict = {"Asset": asset_type, "Spot Direction": direction}

        variant_rates: Dict[str, Dict[str, float]] = {}
        for variant in asset_variants:
            spot_rates = calculate_spot_rate_with_direction(
                token_config, rates_data, staking_data,
                variant, leverage, direction.lower(), target_hours,
            )
            variant_rates[variant] = spot_rates

        for variant in asset_variants:
            for protocol, rate in variant_rates.get(variant, {}).items():
                row[f"{variant}({protocol})"] = rate

        for exchange, rate in perps_rates.items():
            row[exchange] = rate

        all_spot_vs_perps: List[float] = []
        for variant, variant_rates_dict in variant_rates.items():
            for _, spot_rate in variant_rates_dict.items():
                arb = calculate_spot_vs_perps_arb(spot_rate, perps_rates, direction)
                if arb is not None:
                    all_spot_vs_perps.append(arb)

        row["Spot vs Perps Arb"] = min(all_spot_vs_perps) if all_spot_vs_perps else None
        row["Perps vs Perps Arb"] = calculate_perps_vs_perps_arb(perps_rates)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    columns = list(df.columns)
    for col in ['Asset', 'Spot Direction', 'Spot vs Perps Arb', 'Perps vs Perps Arb']:
        if col in columns:
            columns.remove(col)
    new_order = ['Asset', 'Spot Direction']
    if show_spot_vs_perps:
        new_order.append('Spot vs Perps Arb')
    if show_perps_vs_perps:
        new_order.append('Perps vs Perps Arb')
    new_order += columns
    new_order = [c for c in new_order if c in df.columns]
    return df[new_order]


def format_spot_perps_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return df


def display_all_possible_arbitrage_opportunities(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    asset_name: str,
    asset_variants: list,
    asset_type: str,
    target_hours: int = DEFAULT_TARGET_HOURS,
    leverage: float = 2.0,
    show_profitable_only: bool = False,
    show_spot_vs_perps: bool = True,
    show_perps_vs_perps: bool = True,
) -> None:
    import streamlit as st

    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)
    all_opportunities: List[Dict] = []

    if show_spot_vs_perps:
        for variant in asset_variants:
            for direction in ["Long", "Short"]:
                spot_rates = calculate_spot_rate_with_direction(
                    token_config, rates_data, staking_data,
                    variant, leverage, direction.lower(), target_hours,
                )
                for protocol_market, spot_rate in spot_rates.items():
                    for exchange, funding_rate in perps_rates.items():
                        net_arb = (spot_rate - funding_rate) if direction == "Long" else (spot_rate + funding_rate)
                        if show_profitable_only and net_arb >= 0:
                            continue
                        apy = compute_apy_from_net_arb(net_arb, target_hours)
                        all_opportunities.append({
                            'type': 'Spot vs Perps',
                            'token': variant,
                            'protocol': protocol_market.split('(')[0],
                            'market': protocol_market.split('(')[1].split(')')[0],
                            'direction': direction,
                            'spot_rate': spot_rate,
                            'perps_exchange': exchange,
                            'funding_rate': funding_rate,
                            'net_arb': net_arb,
                            'apy': apy,
                            'description': f"{variant} {direction} Spot ({protocol_market.split('(')[0]}({protocol_market.split('(')[1].split(')')[0]})) vs {exchange} Perps",
                            'details': f"Spot: {spot_rate:.6f}%, Perps: {funding_rate:.6f}%",
                            'calculation': f"Net Arb = {spot_rate:.6f}% {'-' if direction == 'Long' else '+'} {funding_rate:.6f}% = {net_arb:.6f}%",
                        })

    if show_perps_vs_perps and len(perps_rates) >= 2:
        exchanges = list(perps_rates.keys())
        for i in range(len(exchanges)):
            for j in range(i + 1, len(exchanges)):
                rate_a = perps_rates[exchanges[i]]
                rate_b = perps_rates[exchanges[j]]
                net_arb = rate_a - rate_b
                if show_profitable_only and net_arb >= 0:
                    continue
                apy = compute_apy_from_net_arb(net_arb, target_hours)
                all_opportunities.append({
                    'type': 'Perps vs Perps',
                    'token': asset_type,
                    'protocol': 'N/A',
                    'market': 'N/A',
                    'direction': 'Long A, Short B',
                    'spot_rate': 'N/A',
                    'perps_exchange': f"{exchanges[i]} vs {exchanges[j]}",
                    'funding_rate': f"{rate_a:.6f}% vs {rate_b:.6f}%",
                    'net_arb': net_arb,
                    'apy': apy,
                    'description': f"{asset_type} {exchanges[i]} vs {exchanges[j]} Perps",
                    'details': f"{exchanges[i]}: {rate_a:.6f}%, {exchanges[j]}: {rate_b:.6f}%",
                    'calculation': f"Net Arb = {rate_a:.6f}% - {rate_b:.6f}% = {net_arb:.6f}%",
                })

    all_opportunities.sort(key=lambda x: x['net_arb'])
    if not all_opportunities:
        st.info(f"**🔍 No arbitrage opportunities found for {asset_name}**")
        if show_profitable_only:
            st.write("💡 *Try unchecking 'Show Profitable Only' to see all opportunities*")
        return

    with st.expander(f"🔍 **All Possible {asset_name} Arbitrage Opportunities** ({len(all_opportunities)} found)", expanded=False):
        st.write(f"**📊 Found {len(all_opportunities)} arbitrage opportunities for {asset_name}**")
        profitable_count = sum(1 for opp in all_opportunities if opp['net_arb'] < 0)
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Opportunities", len(all_opportunities))
        with col2:
            st.metric("Profitable", profitable_count)
        with col3:
            st.metric("Success Rate", f"{(profitable_count/len(all_opportunities)*100):.1f}%" if all_opportunities else "0%")
        with col4:
            st.metric("Best Rate", f"{min(all_opportunities, key=lambda x: x['net_arb'])['net_arb']:.6f}%" if all_opportunities else "N/A")

        st.divider()

        for i, opp in enumerate(all_opportunities):
            color = "🟢" if opp['net_arb'] < 0 else "🔴"
            profit_status = "💰 PROFITABLE" if opp['net_arb'] < 0 else "💸 COSTLY"
            with st.expander(f"{color} **{i+1}.** {opp['description']}: {opp['net_arb']:.6f}%", expanded=False):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write("**📋 Opportunity Details:**")
                    st.write(f"- **Type:** {opp['type']}")
                    st.write(f"- **Token:** {opp['token']}")
                    st.write(f"- **Protocol:** {opp['protocol']}")
                    st.write(f"- **Market:** {opp['market']}")
                    st.write(f"- **Direction:** {opp['direction']}")
                    if opp['type'] == 'Spot vs Perps':
                        st.write(f"- **Spot Rate:** {opp['spot_rate']:.6f}%")
                        st.write(f"- **Perps Exchange:** {opp['perps_exchange']}")
                        st.write(f"- **Funding Rate:** {opp['funding_rate']:.6f}%")
                    else:
                        st.write(f"- **Exchange Pair:** {opp['perps_exchange']}")
                        st.write(f"- **Funding Rates:** {opp['funding_rate']}")
                    st.write(f"- **Net Arbitrage:** {opp['net_arb']:.6f}%")
                    st.write(f"- **Annual Yield:** {opp['apy']:.2f}% APY")
                    st.write(f"- **Profit Status:** {profit_status}")
                    st.write("**🧮 Calculation:**")
                    st.write(f"- {opp['calculation']}")
                with col2:
                    if opp['net_arb'] < 0:
                        st.success("✅ Profitable")
                        st.metric("Potential APY", f"{opp['apy']:.1f}%", delta=f"{opp['net_arb']:.4f}%")
                    else:
                        st.error("❌ Costly")
                        st.metric("Potential Cost", f"{opp['apy']:.1f}%", delta=f"{opp['net_arb']:.4f}%")
                    if i == 0:
                        st.info("🥇 **Best**")
                    elif i < 3:
                        st.info(f"#{i+1}")


def display_spot_perps_breakdowns(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    asset_name: str,
    asset_variants: list,
    asset_type: str,
    target_hours: int = DEFAULT_TARGET_HOURS,
    leverage: float = 2.0,
) -> None:
    import streamlit as st

    st.subheader(f"📊 {asset_name} Calculation Breakdowns")
    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)
    st.write("**📈 Perps Funding Rates:**")
    for exchange, rate in perps_rates.items():
        st.write(f"- {exchange}: {rate:.6f}%")
    st.write("---")

    for variant in asset_variants:
        st.write(f"**{variant}**")
        asset_pairs = get_protocol_market_pairs(token_config, variant)
        asset_mint = token_config[variant]["mint"]
        asset_staking_rate = get_staking_rate_by_mint(staking_data, asset_mint) or 0.0
        for protocol, market, asset_bank in asset_pairs:
            usdc_bank = get_matching_usdc_bank(token_config, protocol, market)
            if not usdc_bank:
                continue
            for direction in ["long", "short"]:
                if direction == "long":
                    lend_rates = get_rates_by_bank_address(rates_data, asset_bank)
                    borrow_rates = get_rates_by_bank_address(rates_data, usdc_bank)
                    lend_staking_rate = asset_staking_rate
                    borrow_staking_rate = get_staking_rate_by_mint(staking_data, token_config["USDC"]["mint"]) or 0.0
                else:
                    lend_rates = get_rates_by_bank_address(rates_data, usdc_bank)
                    borrow_rates = get_rates_by_bank_address(rates_data, asset_bank)
                    lend_staking_rate = get_staking_rate_by_mint(staking_data, token_config["USDC"]["mint"]) or 0.0
                    borrow_staking_rate = asset_staking_rate
                if not lend_rates or not borrow_rates:
                    continue
                lend_rate = lend_rates.get("lendingRate")
                borrow_rate = borrow_rates.get("borrowingRate")
                if lend_rate is None or borrow_rate is None:
                    continue
                with st.expander(f"🔍 {variant} - {protocol} ({market}) - {direction.upper()}"):
                    st.write(f"**Asset:** {variant}")
                    st.write(f"**Protocol:** {protocol}")
                    st.write(f"**Market:** {market}")
                    st.write(f"**Direction:** {direction.upper()}")
                    st.write(f"**Asset Bank:** {asset_bank}")
                    st.write(f"**USDC Bank:** {usdc_bank}")
                    st.write(f"**Target Hours:** {target_hours}")
                    st.write(f"**Leverage:** {leverage}x")
                    st.write("**📈 Rates Data:**")
                    st.write(f"- Asset Lend Rate: {lend_rate:.6f}% APY")
                    st.write(f"- Asset Borrow Rate: {borrow_rate:.6f}% APY")
                    st.write(f"- Asset Staking Rate: {asset_staking_rate * 100:.6f}% APY (raw: {asset_staking_rate:.6f})")
                    st.write(f"- USDC Staking Rate: {borrow_staking_rate * 100:.6f}% APY (raw: {borrow_staking_rate:.6f})")
                    try:
                        net_lend = lend_rate + (lend_staking_rate * 100)
                        net_borrow = borrow_rate + (borrow_staking_rate * 100)
                        fee_rate = net_borrow * (leverage - 1) - net_lend * leverage
                        hourly_rate = fee_rate / (365 * 24)
                        scaled_rate = hourly_rate * target_hours
                        st.write("**🧮 Spot Rate Calculation:**")
                        st.write(f"- Net Lend Rate: {net_lend:.6f}% APY")
                        st.write(f"- Net Borrow Rate: {net_borrow:.6f}% APY")
                        st.write(f"- Fee Rate: {fee_rate:.6f}% APY")
                        st.write(f"- Hourly Rate: {hourly_rate:.8f}% per hour")
                        st.write(f"- Scaled Rate ({target_hours}h): {scaled_rate:.8f}%")
                        if direction == "long":
                            net_arb = scaled_rate - min(perps_rates.values()) if perps_rates else None
                        else:
                            net_arb = scaled_rate + max(perps_rates.values()) if perps_rates else None
                        if net_arb is not None:
                            st.write("**🎯 Arbitrage Analysis:**")
                            st.write(f"- Spot Rate: {scaled_rate:.8f}%")
                            st.write(f"- Best Perps Rate: {min(perps_rates.values()) if direction == 'long' else max(perps_rates.values()):.8f}%")
                            st.write(f"- Net Arbitrage: {net_arb:.8f}%")
                            st.write(f"- Profitable: {'Yes' if net_arb < 0 else 'No'}")
                    except ValueError:
                        st.write("**🧮 Spot Rate Calculation:** Invalid calculation")


def display_table_arbitrage_calculation_breakdown(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    asset_name: str,
    asset_variants: list,
    asset_type: str,
    target_hours: int = DEFAULT_TARGET_HOURS,
    leverage: float = 2.0,
) -> None:
    import streamlit as st

    with st.expander(f"🔬 **{asset_name} Table Arbitrage Calculation Breakdown**", expanded=False):
        st.write(f"**📊 How the 'Spot vs Perps Arb' column is calculated for {asset_name}**")
        st.write("---")
        perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)
        st.write("**📈 Step 1: Perps Rates (used for all calculations)**")
        for exchange, rate in perps_rates.items():
            st.write(f"- {exchange}: {rate:.8f}%")
        st.write("")
        for direction in ["Long", "Short"]:
            st.write(f"**🎯 Step 2: {direction.upper()} Direction Calculation**")
            variant_rates = {}
            for variant in asset_variants:
                spot_rates = calculate_spot_rate_with_direction(
                    token_config, rates_data, staking_data,
                    variant, leverage, direction.lower(), target_hours,
                )
                variant_rates[variant] = spot_rates
                st.write(f"  **{variant} Spot Rates:**")
                for protocol, rate in spot_rates.items():
                    st.write(f"    - {protocol}: {rate:.8f}%")
            all_spot_vs_perps_opportunities = []
            opportunity_details = []
            for variant, variant_rates_dict in variant_rates.items():
                for protocol, spot_rate in variant_rates_dict.items():
                    arb_opportunity = calculate_spot_vs_perps_arb(spot_rate, perps_rates, direction)
                    if arb_opportunity is not None:
                        all_spot_vs_perps_opportunities.append(arb_opportunity)
                        opportunity_details.append({
                            'variant': variant,
                            'protocol': protocol,
                            'spot_rate': spot_rate,
                            'arbitrage': arb_opportunity,
                        })
            st.write(f"  **🧮 Step 3: All Arbitrage Calculations**")
            st.write(f"    - Direction = {direction}")
            st.write(f"    - Found {len(all_spot_vs_perps_opportunities)} profitable opportunities:")
            for i, detail in enumerate(opportunity_details):
                st.write(f"      {i+1}. {detail['variant']} - {detail['protocol']}: {detail['spot_rate']:.8f}% → {detail['arbitrage']:.8f}%")
            if all_spot_vs_perps_opportunities:
                spot_vs_perps_arb = min(all_spot_vs_perps_opportunities)
                best_detail = None
                for detail in opportunity_details:
                    if detail['arbitrage'] == spot_vs_perps_arb:
                        best_detail = detail
                        break
                st.write(f"  **🏆 Step 4: Best Arbitrage Selection**")
                if best_detail:
                    st.write(f"    - **Best Variant:** {best_detail['variant']}")
                    st.write(f"    - **Best Protocol:** {best_detail['protocol']}")
                    st.write(f"    - **Best Spot Rate:** {best_detail['spot_rate']:.8f}%")
                st.write(f"    - **Best Arbitrage:** {spot_vs_perps_arb:.8f}%")
                st.success(f"    ✅ **Table shows: {spot_vs_perps_arb:.8f}%**")
            else:
                st.write(f"  **🏆 Step 4: Best Arbitrage Selection**")
                st.write(f"    - No profitable opportunities found")
                st.info(f"    ℹ️ **Table shows: None (no profitable opportunity)**")
            st.write("---")
        st.write("**🔍 Key Points (REVERTED TO SEPARATE ROWS):**")
        st.write("1. **Two Rows Per Asset**: Each asset (BTC/SOL) has separate Long and Short rows")
        st.write("2. **Spot Direction Column**: Clear identification of Long vs Short position")
        st.write("3. **Clean Column Headers**: No direction suffixes, just variant(protocol) format")
        st.write("4. **Per-Direction Analysis**: Each row shows rates specific to that direction")
        st.write("5. **Best Arbitrage Per Row**: Each row shows the best opportunity for that direction")


def create_arbitrage_opportunities_summary(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS,
):
    from config.constants import SPOT_PERPS_CONFIG
    opportunities = {'spot_vs_perps': [], 'perps_vs_perps': []}
    asset_configs = {
        "BTC": (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC"),
        "SOL": (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL"),
    }
    perps_rates_by_asset = {
        asset_type: get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)
        for _, (_, asset_type) in asset_configs.items()
    }
    for asset_name, (asset_variants, asset_type) in asset_configs.items():
        perps_rates = perps_rates_by_asset[asset_type]
        perps_vs_perps_arb = calculate_perps_vs_perps_arb(perps_rates)
        if perps_vs_perps_arb is not None:
            exchanges = list(perps_rates.keys())
            best_pair = None
            best_rate = float('inf')
            for i in range(len(exchanges)):
                for j in range(i + 1, len(exchanges)):
                    net_arb = perps_rates[exchanges[i]] - perps_rates[exchanges[j]]
                    if net_arb < best_rate:
                        best_rate = net_arb
                        best_pair = (exchanges[i], exchanges[j], perps_rates[exchanges[i]], perps_rates[exchanges[j]])
            if best_pair:
                opportunities['perps_vs_perps'].append({
                    'asset': asset_type,
                    'asset_name': asset_name,
                    'exchange_a': best_pair[0],
                    'exchange_b': best_pair[1],
                    'rate_a': best_pair[2],
                    'rate_b': best_pair[3],
                    'arbitrage_rate': best_rate,
                    'description': f"{asset_name} {best_pair[0]} vs {best_pair[1]}: {best_rate:.6f}%",
                })
        for variant in asset_variants:
            for direction in ["Long", "Short"]:
                spot_rates = calculate_spot_rate_with_direction(
                    token_config, rates_data, staking_data,
                    variant, 2, direction.lower(), target_hours,
                )
                if spot_rates:
                    spot_rate = list(spot_rates.values())[0]
                    spot_vs_perps_arb = calculate_spot_vs_perps_arb(spot_rate, perps_rates, direction)
                    if spot_vs_perps_arb is not None:
                        best_exchange = None
                        best_funding_rate = None
                        for exchange, funding_rate in perps_rates.items():
                            net_arb = (spot_rate - funding_rate) if direction == "Long" else (spot_rate + funding_rate)
                            if net_arb == spot_vs_perps_arb:
                                best_exchange = exchange
                                best_funding_rate = funding_rate
                                break
                        if best_exchange:
                            opportunities['spot_vs_perps'].append({
                                'asset': variant,
                                'asset_name': asset_name,
                                'direction': direction,
                                'spot_rate': spot_rate,
                                'perps_exchange': best_exchange,
                                'funding_rate': best_funding_rate,
                                'arbitrage_rate': spot_vs_perps_arb,
                                'description': f"{variant} {direction} Spot vs {best_exchange} Perps: {spot_vs_perps_arb:.6f}%",
                            })
    opportunities['spot_vs_perps'].sort(key=lambda x: x['arbitrage_rate'])
    opportunities['perps_vs_perps'].sort(key=lambda x: x['arbitrage_rate'])
    return opportunities


def display_spot_perps_opportunities_section(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
) -> None:
    import streamlit as st
    from config.constants import SPOT_PERPS_CONFIG
    from utils.formatting import create_sidebar_settings, display_settings_info

    settings = create_sidebar_settings()
    display_settings_info(settings)

    show_breakdowns = settings["show_breakdowns"]
    show_detailed_opportunities = settings["show_detailed_opportunities"]
    show_profitable_only = settings["show_profitable_only"]
    show_spot_vs_perps = settings["show_spot_vs_perps"]
    show_perps_vs_perps = settings["show_perps_vs_perps"]
    show_table_breakdown = settings["show_table_breakdown"]
    target_hours = settings["target_hours"]
    selected_leverage = settings["selected_leverage"]

    asset_configs = [
        ("SOL", (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL")),
        ("BTC", (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC")),
    ]

    for asset_name, (asset_variants, asset_type) in asset_configs:
        display_asset_top_opportunities(
            token_config, rates_data, staking_data, hyperliquid_data, drift_data,
            asset_name, asset_variants, asset_type, target_hours, selected_leverage,
        )

        st.subheader(f"{asset_name}")
        opportunities_df = create_spot_perps_opportunities_table(
            token_config, rates_data, staking_data, hyperliquid_data, drift_data,
            asset_variants, asset_type, selected_leverage, target_hours,
            show_spot_vs_perps=show_spot_vs_perps,
            show_perps_vs_perps=show_perps_vs_perps,
        )

        if not opportunities_df.empty:
            st.dataframe(
                opportunities_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Asset": st.column_config.TextColumn("Asset", pinned=True),
                    "Spot Direction": st.column_config.TextColumn("Spot Direction", pinned=True),
                    **({
                        "Spot vs Perps Arb": st.column_config.NumberColumn(
                            "Spot vs Perps Arb", format="%.6f%%", pinned=True
                        )
                    } if show_spot_vs_perps else {}),
                    **({
                        "Perps vs Perps Arb": st.column_config.NumberColumn(
                            "Perps vs Perps Arb", format="%.6f%%", pinned=True
                        )
                    } if show_perps_vs_perps else {}),
                    **{
                        col: st.column_config.NumberColumn(col, format="%.6f%%")
                        for col in opportunities_df.columns
                        if col not in [
                            "Asset",
                            "Spot Direction",
                            "Spot vs Perps Arb",
                            "Perps vs Perps Arb",
                        ] and opportunities_df[col].dtype in ['float64', 'float32', 'int64', 'int32']
                    },
                },
            )
        else:
            st.info(f"No valid opportunities found for {asset_name} assets.")

        if show_detailed_opportunities:
            display_all_possible_arbitrage_opportunities(
                token_config, rates_data, staking_data, hyperliquid_data, drift_data,
                asset_name, asset_variants, asset_type, target_hours, selected_leverage,
                show_profitable_only, show_spot_vs_perps, show_perps_vs_perps,
            )

        if show_breakdowns:
            display_spot_perps_breakdowns(
                token_config, rates_data, staking_data, hyperliquid_data, drift_data,
                asset_name, asset_variants, asset_type, target_hours, selected_leverage,
            )

        if show_table_breakdown:
            display_table_arbitrage_calculation_breakdown(
                token_config, rates_data, staking_data, hyperliquid_data, drift_data,
                asset_name, asset_variants, asset_type, target_hours, selected_leverage,
            )


def display_arbitrage_opportunities_summary(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS,
) -> None:
    import streamlit as st

    opportunities = create_arbitrage_opportunities_summary(
        token_config, rates_data, staking_data, hyperliquid_data, drift_data, target_hours
    )
    st.subheader("🎯 Arbitrage Opportunities Summary")
    if opportunities['spot_vs_perps']:
        st.write("**💰 Spot vs Perps Opportunities:**")
        for i, opp in enumerate(opportunities['spot_vs_perps']):
            color = "🟢" if opp['arbitrage_rate'] < 0 else "🔴"
            profit_status = "💰 PROFITABLE" if opp['arbitrage_rate'] < 0 else "💸 COSTLY"
            with st.expander(f"{color} **{i+1}.** {opp['description']}", expanded=False):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write(f"**Asset:** {opp['asset']}")
                    st.write(f"**Direction:** {opp.get('direction', 'N/A')}")
                    st.write(f"**Spot Rate:** {opp.get('spot_rate', 0):.6f}%")
                    st.write(f"**Perps Exchange:** {opp.get('perps_exchange', 'N/A')}")
                    st.write(f"**Funding Rate:** {opp.get('funding_rate', 0):.6f}%")
                    st.write(f"**Arbitrage Rate:** {opp['arbitrage_rate']:.6f}%")
                    st.write(f"**Profit Status:** {profit_status}")
                with col2:
                    apy = abs(opp['arbitrage_rate']) * 365 * 24
                    if opp['arbitrage_rate'] < 0:
                        st.success("✅ Profitable")
                        st.metric("Potential APY", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")
                    else:
                        st.error("❌ Costly")
                        st.metric("Potential Cost", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")
                    if i == 0:
                        st.info("🥇 **Best Spot vs Perps**")
                    elif i < 3:
                        st.info(f"#{i+1} Best")
    else:
        st.write("**💰 Spot vs Perps:** No opportunities found")

    st.write("---")
    if opportunities['perps_vs_perps']:
        st.write("**📈 Perps vs Perps Opportunities:**")
        for i, opp in enumerate(opportunities['perps_vs_perps']):
            color = "🟢" if opp['arbitrage_rate'] < 0 else "🔴"
            profit_status = "💰 PROFITABLE" if opp['arbitrage_rate'] < 0 else "💸 COSTLY"
            with st.expander(f"{color} **{i+1}.** {opp['description']}", expanded=False):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write(f"**Asset:** {opp['asset']}")
                    st.write(f"**Exchange A:** {opp['exchange_a']}")
                    st.write(f"**Exchange B:** {opp['exchange_b']}")
                    st.write(f"**Rate A:** {opp['rate_a']:.6f}%")
                    st.write(f"**Rate B:** {opp['rate_b']:.6f}%")
                    st.write(f"**Arbitrage Rate:** {opp['arbitrage_rate']:.6f}%")
                    st.write(f"**Profit Status:** {profit_status}")
                with col2:
                    apy = abs(opp['arbitrage_rate']) * 365 * 24
                    if opp['arbitrage_rate'] < 0:
                        st.success("✅ Profitable")
                        st.metric("Potential APY", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")
                    else:
                        st.error("❌ Costly")
                        st.metric("Potential Cost", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")
                    if i == 0:
                        st.info("🥇 **Best Perps vs Perps**")
                    elif i < 3:
                        st.info(f"#{i+1} Best")
    else:
        st.write("**📈 Perps vs Perps:** No opportunities found")


