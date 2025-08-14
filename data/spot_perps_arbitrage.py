"""
Spot and Perps arbitrage calculations for funding rate opportunities.
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from data.money_markets_processing import get_staking_rate_by_mint, get_rates_by_bank_address
from data.spot_arbitrage import calculate_hourly_fee_rates
from config.constants import DEFAULT_TARGET_HOURS


@dataclass
class SpotPerpsOpportunity:
    spot_direction: str  # "Long" or "Short"
    asset: str
    spot_rates: Dict[str, float]  # {protocol: rate}
    perps_rates: Dict[str, float]  # {exchange: rate}
    spot_vs_perps_arb: Optional[float]
    perps_vs_perps_arb: Optional[float]


def calculate_spot_rate_with_direction(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    asset: str,
    leverage: float = 2.0,
    direction: str = "long",  # "long" or "short"
    target_hours: int = DEFAULT_TARGET_HOURS
) -> Dict[str, float]:
    """
    Calculate spot rates for an asset in a specific direction.

    Note: The returned rates are in percentage format scaled to the target interval.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        asset: Asset to calculate rates for
        leverage: Leverage level (default 2.0)
        direction: "long" or "short" position
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)

    Returns:
        Dictionary of {protocol: rate} where rates are in percentage format scaled to target interval
    """
    spot_rates = {}

    # Helper: get protocol/market/bank for an asset
    def get_protocol_market_pairs(token_config, asset):
        return [(b["protocol"], b["market"], b["bank"]) for b in token_config[asset]["banks"]]

    asset_pairs = get_protocol_market_pairs(token_config, asset)
    asset_mint = token_config[asset]["mint"]
    asset_staking_rate = get_staking_rate_by_mint(staking_data, asset_mint) or 0.0

    for protocol, market, asset_bank in asset_pairs:
        # Find matching USDC bank for the same protocol/market
        usdc_bank = None
        for usdc_bank_info in token_config["USDC"]["banks"]:
            if usdc_bank_info["protocol"] == protocol and usdc_bank_info["market"] == market:
                usdc_bank = usdc_bank_info["bank"]
                break

        if not usdc_bank:
            continue  # Skip if no matching USDC bank found

        # Get rates based on direction
        if direction == "long":
            # Long: lend asset, borrow USDC
            lend_rates = get_rates_by_bank_address(rates_data, asset_bank)
            borrow_rates = get_rates_by_bank_address(rates_data, usdc_bank)
            lend_staking_rate = asset_staking_rate
            borrow_staking_rate = get_staking_rate_by_mint(staking_data, token_config["USDC"]["mint"]) or 0.0
        else:  # short
            # Short: lend USDC, borrow asset
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

        # Log the data being used for calculation
        import logging
        logging.info(f"""
        🔍 SPOT PERPS ARBITRAGE DATA USED:
        ===================================
        Asset: {asset}
        Direction: {direction.upper()}
        Protocol: {protocol}
        Market: {market}
        Asset Bank: {asset_bank}
        USDC Bank: {usdc_bank}
        Target Hours: {target_hours}
        Leverage: {leverage}x

        Rates Data:
        - Asset Lend Rate: {lend_rate:.6f}% APY
        - Asset Borrow Rate: {borrow_rate:.6f}% APY
        - Asset Staking Rate: {asset_staking_rate:.6f}% APY
        - USDC Staking Rate: {borrow_staking_rate:.6f}% APY

        Position Details:
        - Long: Lend {asset}, Borrow USDC
        - Short: Lend USDC, Borrow {asset}
        """)

        try:
            hourly_rate = calculate_hourly_fee_rates(
                lend_rates, borrow_rates,
                lend_staking_rate, borrow_staking_rate,
                leverage
            )
            # Scale to target interval
            scaled_rate = hourly_rate * target_hours
            spot_rates[f"{protocol}({market})"] = scaled_rate
        except ValueError:
            continue

    return spot_rates


def get_perps_rates_for_asset(
    hyperliquid_data: dict,
    drift_data: dict,
    asset: str,
    target_hours: int = DEFAULT_TARGET_HOURS
) -> Dict[str, float]:
    """
    Get funding rates from all perps exchanges for an asset.
    Uses the centralized processing approach from data/processing.py.

    Args:
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset: Asset to get funding rates for ("BTC" or "SOL")
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)

    Returns:
        Dictionary of {exchange: funding_rate} scaled to target interval
    """
    from data.processing import merge_funding_rate_data
    from utils.formatting import scale_funding_rate_to_percentage
    from config.constants import EXCHANGE_NAME_MAPPING

    # Use the centralized processing approach
    merged_data = merge_funding_rate_data(hyperliquid_data, drift_data)

    perps_rates = {}

    # Find the asset in the merged data
    for token_entry in merged_data:
        if token_entry[0] == asset:  # Match the asset name
            exchanges = token_entry[1]

            for exchange_name, details in exchanges:
                if details is not None:
                    try:
                        rate = details.get("fundingRate", 0)
                        # Scale to target interval and convert to percentage
                        scaled_percent = scale_funding_rate_to_percentage(rate, 1, target_hours)

                        # Map exchange names to display names
                        display_name = EXCHANGE_NAME_MAPPING.get(exchange_name)
                        if display_name:
                            perps_rates[display_name] = scaled_percent
                        else:
                            # Fallback to original exchange name if not in mapping
                            perps_rates[exchange_name] = scaled_percent

                    except (ValueError, TypeError):
                        continue
            break

    return perps_rates


def calculate_spot_vs_perps_arb(
    spot_rate: float,
    perps_rates: Dict[str, float],
    spot_direction: str
) -> Optional[float]:
    """
    Calculate spot vs perps arbitrage opportunity.

    Args:
        spot_rate: Hourly spot rate
        perps_rates: Dictionary of {exchange: funding_rate}
        spot_direction: "Long" or "Short"

    Returns:
        Most negative net_arb (best opportunity) or None if no opportunity
    """
    if not perps_rates:
        return None

    net_arbs = []

    for exchange, funding_rate in perps_rates.items():
        if spot_direction == "Long":
            # Long spot: net_arb = spot_rate - funding_rate
            net_arb = spot_rate - funding_rate
        else:  # Short
            # Short spot: net_arb = spot_rate + funding_rate
            net_arb = spot_rate + funding_rate

        net_arbs.append(net_arb)

    # Find most negative net_arb (best opportunity)
    best_arb = min(net_arbs)

    # Return None if no negative arbitrage opportunity
    return best_arb if best_arb < 0 else None


def calculate_perps_vs_perps_arb(
    perps_rates: Dict[str, float]
) -> Optional[float]:
    """
    Calculate perps vs perps arbitrage opportunity.

    Args:
        perps_rates: Dictionary of {exchange: funding_rate}

    Returns:
        Most negative net_arb (best opportunity) or None if no opportunity
    """
    if len(perps_rates) < 2:
        return None

    net_arbs = []
    exchanges = list(perps_rates.keys())

    # Calculate all pairs
    for i in range(len(exchanges)):
        for j in range(i + 1, len(exchanges)):
            exchange_a = exchanges[i]
            exchange_b = exchanges[j]
            rate_a = perps_rates[exchange_a]
            rate_b = perps_rates[exchange_b]

            # net_arb = funding_rate_A - funding_rate_B
            net_arb = rate_a - rate_b
            net_arbs.append(net_arb)

    if not net_arbs:
        return None

    # Find most negative net_arb (best opportunity)
    best_arb = min(net_arbs)

    # Return None if no negative arbitrage opportunity
    return best_arb if best_arb < 0 else None


def create_spot_perps_opportunities_table(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    asset_variants: list,
    asset_type: str,  # "BTC" or "SOL"
    leverage: float = 2.0,
    target_hours: int = DEFAULT_TARGET_HOURS,
    show_spot_vs_perps: bool = True,
    show_perps_vs_perps: bool = False
) -> pd.DataFrame:
    """
    Create table with spot and perps arbitrage opportunities.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset_variants: List of asset variants (e.g., ["CBBTC", "WBTC", "XBTC"])
        asset_type: "BTC" or "SOL" for perps mapping
        leverage: Leverage level for spot calculations
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)
        show_spot_vs_perps: Whether to show Spot vs Perps arbitrage column
        show_perps_vs_perps: Whether to show Perps vs Perps arbitrage column

    Returns:
        DataFrame with all columns including arbitrage calculations
    """
    rows = []

    # Get perps rates for the asset type
    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)

    # Calculate for both Long and Short directions for the main asset (BTC or SOL)
    for direction in ["Long", "Short"]:
        # Create row with main asset
        row = {
            "Spot Direction": direction,
            "Asset": asset_type,
        }

        # Calculate spot rates for each variant
        variant_rates = {}
        for variant in asset_variants:
            spot_rates = calculate_spot_rate_with_direction(
                token_config, rates_data, staking_data,
                variant, leverage, direction.lower(), target_hours
            )
            variant_rates[variant] = spot_rates

        # Add spot rates columns for each variant
        for variant in asset_variants:
            rates = variant_rates.get(variant, {})
            # Add columns for each protocol/market for this variant
            for protocol, rate in rates.items():
                column_name = f"{variant}({protocol})"
                row[column_name] = rate

        # Add perps rates columns
        for exchange, rate in perps_rates.items():
            row[exchange] = rate

        # Calculate arbitrage opportunities using ALL spot rates to find the BEST opportunity
        all_spot_vs_perps_opportunities = []
        
        # Check all variants and all protocols to find the best arbitrage
        for variant, variant_rates_dict in variant_rates.items():
            for protocol, spot_rate in variant_rates_dict.items():
                # Calculate arbitrage for this specific spot rate
                arb_opportunity = calculate_spot_vs_perps_arb(
                    spot_rate, perps_rates, direction
                )
                if arb_opportunity is not None:
                    all_spot_vs_perps_opportunities.append(arb_opportunity)
        
        # Find the BEST (most negative) arbitrage opportunity across all variants/protocols
        if all_spot_vs_perps_opportunities:
            spot_vs_perps_arb = min(all_spot_vs_perps_opportunities)
        else:
            spot_vs_perps_arb = None
            
        # Perps vs perps calculation remains the same (independent of spot rates)
        perps_vs_perps_arb = calculate_perps_vs_perps_arb(perps_rates)

        # Add arbitrage columns
        row["Spot vs Perps Arb"] = spot_vs_perps_arb
        row["Perps vs Perps Arb"] = perps_vs_perps_arb

        rows.append(row)

    if rows:
        df = pd.DataFrame(rows)
        columns = list(df.columns)
        columns.remove('Asset')
        # Remove arb columns for reordering
        if 'Spot vs Perps Arb' in columns:
            columns.remove('Spot vs Perps Arb')
        if 'Perps vs Perps Arb' in columns:
            columns.remove('Perps vs Perps Arb')
        # Build new order based on filter settings
        new_order = ['Asset']
        if show_spot_vs_perps:
            new_order.append('Spot vs Perps Arb')
        if show_perps_vs_perps:
            new_order.append('Perps vs Perps Arb')
        new_order += columns
        # Only keep columns that exist in df
        new_order = [col for col in new_order if col in df.columns]
        df = df[new_order]
        return df
    else:
        return pd.DataFrame()


def format_spot_perps_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Format the spot perps opportunities DataFrame to display percentage symbols.
    Keeps values as floats for sorting/filtering while displaying as percentages.

    Args:
        df: DataFrame with spot perps opportunities data

    Returns:
        DataFrame with float values (for functionality) and percentage display
    """
    # Return the original DataFrame - we'll use Streamlit's formatting instead
    return df


def display_spot_perps_opportunities_section(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict
) -> None:
    """
    Display complete spot and perps opportunities section.
    Shows separate tables for BTC and SOL with asset-specific opportunities below each table.

    Note: The spot rates displayed are already in percentage format (hourly fee rates).
    """
    import streamlit as st
    from config.constants import SPOT_PERPS_CONFIG
    from utils.formatting import create_sidebar_settings, display_settings_info

    # Get settings from sidebar
    settings = create_sidebar_settings()

    # Display settings info
    display_settings_info(settings)

    # Extract settings values
    show_breakdowns = settings["show_breakdowns"]
    show_detailed_opportunities = settings["show_detailed_opportunities"]
    show_profitable_only = settings["show_profitable_only"]
    show_spot_vs_perps = settings["show_spot_vs_perps"]
    show_perps_vs_perps = settings["show_perps_vs_perps"]
    show_table_breakdown = settings["show_table_breakdown"]
    target_hours = settings["target_hours"]
    selected_leverage = settings["selected_leverage"]

    # Create separate tables for BTC and SOL
    asset_configs = {
        "BTC": (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC"),
        "SOL": (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL")
    }

    for asset_name, (asset_variants, asset_type) in asset_configs.items():
        st.subheader(f"{asset_name}")

        opportunities_df = create_spot_perps_opportunities_table(
            token_config, rates_data, staking_data,
            hyperliquid_data, drift_data,
            asset_variants, asset_type, selected_leverage,
            target_hours,
            show_spot_vs_perps=show_spot_vs_perps,
            show_perps_vs_perps=show_perps_vs_perps
        )

        if not opportunities_df.empty:
            # Display DataFrame with percentage formatting, no index, and new column order
            st.dataframe(
                opportunities_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Asset": st.column_config.TextColumn(
                        "Asset",
                        pinned=True
                    ),
                    **({
                        "Spot vs Perps Arb": st.column_config.NumberColumn(
                            "Spot vs Perps Arb",
                            format="%.6f%%",
                            pinned=True
                        )
                    } if show_spot_vs_perps else {}),
                    **({
                        "Perps vs Perps Arb": st.column_config.NumberColumn(
                            "Perps vs Perps Arb",
                            format="%.6f%%",
                            pinned=True
                        )
                    } if show_perps_vs_perps else {}),
                    **{
                        col: st.column_config.NumberColumn(
                            col,
                            format="%.6f%%"
                        ) for col in opportunities_df.columns
                        if col not in ["Spot Direction", "Asset", "Spot vs Perps Arb", "Perps vs Perps Arb"] and opportunities_df[col].dtype in ['float64', 'float32', 'int64', 'int32']
                    }
                }
            )
        else:
            st.info(f"No valid opportunities found for {asset_name} assets.")

        # Display all possible arbitrage opportunities
        if show_detailed_opportunities:
            display_all_possible_arbitrage_opportunities(
                token_config, rates_data, staking_data, hyperliquid_data, drift_data,
                asset_name, asset_variants, asset_type, target_hours, selected_leverage,
                show_profitable_only, show_spot_vs_perps, show_perps_vs_perps
            )

        # Show calculation breakdowns if requested
        if show_breakdowns:
            display_spot_perps_breakdowns(
                token_config, rates_data, staking_data, hyperliquid_data, drift_data,
                asset_name, asset_variants, asset_type, target_hours, selected_leverage
            )
        
        # Show table arbitrage calculation breakdown if requested
        if show_table_breakdown:
            display_table_arbitrage_calculation_breakdown(
                token_config, rates_data, staking_data, hyperliquid_data, drift_data,
                asset_name, asset_variants, asset_type, target_hours, selected_leverage
            )

        st.divider()


def create_arbitrage_opportunities_summary(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS
) -> Dict[str, List[Dict]]:
    """
    Create a summary of all arbitrage opportunities, ranked by profitability.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)

    Returns:
        Dictionary with 'spot_vs_perps' and 'perps_vs_perps' opportunities ranked by profitability
    """
    from config.constants import SPOT_PERPS_CONFIG

    opportunities = {
        'spot_vs_perps': [],
        'perps_vs_perps': []
    }

    # Process each asset group
    asset_configs = {
        "BTC": (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC"),
        "SOL": (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL")
    }

    for asset_name, (asset_variants, asset_type) in asset_configs.items():
        # Get perps rates for this asset type
        perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)

        # Calculate perps vs perps opportunities for this asset
        perps_vs_perps_arb = calculate_perps_vs_perps_arb(perps_rates)
        if perps_vs_perps_arb is not None:
            # Find the specific exchange pair that creates this opportunity
            exchanges = list(perps_rates.keys())
            best_pair = None
            best_rate = float('inf')

            for i in range(len(exchanges)):
                for j in range(i + 1, len(exchanges)):
                    exchange_a = exchanges[i]
                    exchange_b = exchanges[j]
                    rate_a = perps_rates[exchange_a]
                    rate_b = perps_rates[exchange_b]
                    net_arb = rate_a - rate_b

                    if net_arb < best_rate:
                        best_rate = net_arb
                        best_pair = (exchange_a, exchange_b, rate_a, rate_b)

            if best_pair:
                opportunities['perps_vs_perps'].append({
                    'asset': asset_type,
                    'asset_name': asset_name,
                    'exchange_a': best_pair[0],
                    'exchange_b': best_pair[1],
                    'rate_a': best_pair[2],
                    'rate_b': best_pair[3],
                    'arbitrage_rate': best_rate,
                    'description': f"{asset_name} {best_pair[0]} vs {best_pair[1]}: {best_rate:.6f}%"
                })

        # Calculate spot vs perps opportunities for each variant
        for variant in asset_variants:
            for direction in ["Long", "Short"]:
                spot_rates = calculate_spot_rate_with_direction(
                    token_config, rates_data, staking_data,
                    variant, SPOT_PERPS_CONFIG["DEFAULT_SPOT_LEVERAGE"],
                    direction.lower(), target_hours
                )

                if spot_rates:
                    # Use the first available spot rate
                    spot_rate = list(spot_rates.values())[0]
                    spot_vs_perps_arb = calculate_spot_vs_perps_arb(
                        spot_rate, perps_rates, direction
                    )

                    if spot_vs_perps_arb is not None:
                        # Find the best perps exchange for this opportunity
                        best_exchange = None
                        best_funding_rate = None

                        for exchange, funding_rate in perps_rates.items():
                            if direction == "Long":
                                net_arb = spot_rate - funding_rate
                            else:  # Short
                                net_arb = spot_rate + funding_rate

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
                                'description': f"{variant} {direction} Spot vs {best_exchange} Perps: {spot_vs_perps_arb:.6f}%"
                            })

    # Sort opportunities by profitability (most negative first)
    opportunities['spot_vs_perps'].sort(key=lambda x: x['arbitrage_rate'])
    opportunities['perps_vs_perps'].sort(key=lambda x: x['arbitrage_rate'])

    return opportunities


def display_arbitrage_opportunities_summary(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS
) -> None:
    """
    Display a summary of all arbitrage opportunities, ranked by profitability.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)
    """
    import streamlit as st

    opportunities = create_arbitrage_opportunities_summary(
        token_config, rates_data, staking_data, hyperliquid_data, drift_data, target_hours
    )

    st.subheader("🎯 Arbitrage Opportunities Summary")

    # Display Spot vs Perps opportunities
    if opportunities['spot_vs_perps']:
        st.write("**💰 Spot vs Perps Opportunities:**")
        for i, opp in enumerate(opportunities['spot_vs_perps']):  # Show all opportunities
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
                    if opp['arbitrage_rate'] < 0:
                        st.success("✅ Profitable")
                        apy = abs(opp['arbitrage_rate']) * 365 * 24
                        st.metric("Potential APY", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")
                    else:
                        st.error("❌ Costly")
                        apy = abs(opp['arbitrage_rate']) * 365 * 24
                        st.metric("Potential Cost", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")

                    if i == 0:
                        st.info("🥇 **Best Spot vs Perps**")
                    elif i < 3:
                        st.info(f"#{i+1} Best")
    else:
        st.write("**💰 Spot vs Perps:** No opportunities found")

    st.write("---")

    # Display Perps vs Perps opportunities
    if opportunities['perps_vs_perps']:
        st.write("**📈 Perps vs Perps Opportunities:**")
        for i, opp in enumerate(opportunities['perps_vs_perps']):  # Show all opportunities
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
                    if opp['arbitrage_rate'] < 0:
                        st.success("✅ Profitable")
                        apy = abs(opp['arbitrage_rate']) * 365 * 24
                        st.metric("Potential APY", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")
                    else:
                        st.error("❌ Costly")
                        apy = abs(opp['arbitrage_rate']) * 365 * 24
                        st.metric("Potential Cost", f"{apy:.1f}%", delta=f"{opp['arbitrage_rate']:.4f}%")

                    if i == 0:
                        st.info("🥇 **Best Perps vs Perps**")
                    elif i < 3:
                        st.info(f"#{i+1} Best")
    else:
        st.write("**📈 Perps vs Perps:** No opportunities found")

    # Show summary statistics
    st.write("---")
    all_opportunities = opportunities['spot_vs_perps'] + opportunities['perps_vs_perps']
    if all_opportunities:
        profitable_spot = sum(1 for opp in opportunities['spot_vs_perps'] if opp['arbitrage_rate'] < 0)
        profitable_perps = sum(1 for opp in opportunities['perps_vs_perps'] if opp['arbitrage_rate'] < 0)
        total_profitable = profitable_spot + profitable_perps
        total_opportunities = len(all_opportunities)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Opportunities", total_opportunities)
        with col2:
            st.metric("Profitable", total_profitable)
        with col3:
            st.metric("Success Rate", f"{(total_profitable/total_opportunities*100):.1f}%" if total_opportunities > 0 else "0%")
        with col4:
            st.metric("Spot vs Perps", f"{len(opportunities['spot_vs_perps'])} opportunities")

        # Show best overall opportunity
        best_opp = min(all_opportunities, key=lambda x: x['arbitrage_rate'])
        st.write("---")
        st.write(f"**🏆 Best Overall Opportunity:** {best_opp['description']}")
        st.write(f"*Rate: {best_opp['arbitrage_rate']:.6f}%*")

        # Add APY calculation for best opportunity
        if best_opp['arbitrage_rate'] < 0:
            apy = abs(best_opp['arbitrage_rate']) * 365 * 24
            st.success(f"✅ Potential APY: {apy:.1f}%")
        else:
            apy = abs(best_opp['arbitrage_rate']) * 365 * 24
            st.error(f"❌ Potential Cost: {apy:.1f}%")


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
    show_perps_vs_perps: bool = True
) -> None:
    """
    Display all possible arbitrage opportunities with comprehensive details.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset_name: Asset name (e.g., "BTC", "SOL")
        asset_variants: List of asset variants
        asset_type: Asset type for perps mapping
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)
        leverage: Leverage level for spot calculations (default 2.0)
        show_profitable_only: Filter to show only profitable opportunities
        show_spot_vs_perps: Show spot vs perps opportunities
        show_perps_vs_perps: Show perps vs perps opportunities
    """
    import streamlit as st
    from config.constants import SPOT_PERPS_CONFIG

    # Get perps rates for this asset type
    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)

    # Collect all possible arbitrage opportunities
    all_opportunities = []

    # Helper function to get protocol/market/bank for an asset
    def get_protocol_market_pairs(token_config, asset):
        return [(b["protocol"], b["market"], b["bank"]) for b in token_config[asset]["banks"]]

    # 1. SPOT VS PERPS OPPORTUNITIES
    if show_spot_vs_perps:
        for variant in asset_variants:
            for direction in ["Long", "Short"]:
                # Get spot rates for this variant and direction
                spot_rates = calculate_spot_rate_with_direction(
                    token_config, rates_data, staking_data,
                    variant, leverage, direction.lower(), target_hours
                )

                # For each spot rate (protocol/market), compare with all perps exchanges
                for protocol_market, spot_rate in spot_rates.items():
                    for exchange, funding_rate in perps_rates.items():
                        # Calculate arbitrage
                        if direction == "Long":
                            net_arb = spot_rate - funding_rate
                        else:  # Short
                            net_arb = spot_rate + funding_rate

                        # Apply profitability filter
                        if show_profitable_only and net_arb >= 0:
                            continue

                        # Calculate APY
                        apy = abs(net_arb) * 365 * 24 / target_hours

                        opportunity = {
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
                            'calculation': f"Net Arb = {spot_rate:.6f}% {'-' if direction == 'Long' else '+'} {funding_rate:.6f}% = {net_arb:.6f}%"
                        }
                        all_opportunities.append(opportunity)

    # 2. PERPS VS PERPS OPPORTUNITIES
    if show_perps_vs_perps and len(perps_rates) >= 2:
        exchanges = list(perps_rates.keys())
        for i in range(len(exchanges)):
            for j in range(i + 1, len(exchanges)):
                exchange_a = exchanges[i]
                exchange_b = exchanges[j]
                rate_a = perps_rates[exchange_a]
                rate_b = perps_rates[exchange_b]

                # Calculate arbitrage (Long A, Short B)
                net_arb = rate_a - rate_b

                # Apply profitability filter
                if show_profitable_only and net_arb >= 0:
                    continue

                # Calculate APY
                apy = abs(net_arb) * 365 * 24 / target_hours

                opportunity = {
                    'type': 'Perps vs Perps',
                    'token': asset_type,
                    'protocol': 'N/A',
                    'market': 'N/A',
                    'direction': 'Long A, Short B',
                    'spot_rate': 'N/A',
                    'perps_exchange': f"{exchange_a} vs {exchange_b}",
                    'funding_rate': f"{rate_a:.6f}% vs {rate_b:.6f}%",
                    'net_arb': net_arb,
                    'apy': apy,
                    'description': f"{asset_type} {exchange_a} vs {exchange_b} Perps",
                    'details': f"{exchange_a}: {rate_a:.6f}%, {exchange_b}: {rate_b:.6f}%",
                    'calculation': f"Net Arb = {rate_a:.6f}% - {rate_b:.6f}% = {net_arb:.6f}%"
                }
                all_opportunities.append(opportunity)

    # Sort opportunities by profitability (most negative first)
    all_opportunities.sort(key=lambda x: x['net_arb'])

    # Display all opportunities in expandable section
    if all_opportunities:
        with st.expander(f"🔍 **All Possible {asset_name} Arbitrage Opportunities** ({len(all_opportunities)} found)", expanded=False):
            st.write(f"**📊 Found {len(all_opportunities)} arbitrage opportunities for {asset_name}**")

            # Summary statistics
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

                        # Display each opportunity with comprehensive details
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
                        else:  # Perps vs Perps
                            st.write(f"- **Exchange Pair:** {opp['perps_exchange']}")
                            st.write(f"- **Funding Rates:** {opp['funding_rate']}")

                        st.write(f"- **Net Arbitrage:** {opp['net_arb']:.6f}%")
                        st.write(f"- **Annual Yield:** {opp['apy']:.2f}% APY")
                        st.write(f"- **Profit Status:** {profit_status}")

                        st.write("**🧮 Calculation:**")
                        st.write(f"- {opp['calculation']}")

                        st.write("**📊 Strategy Breakdown:**")
                        if opp['type'] == 'Spot vs Perps':
                            if 'Long' in opp['direction']:
                                st.write(f"- Long {opp['token']} on {opp['protocol']} ({opp['market']})")
                                st.write(f"- Short {asset_type} on {opp['perps_exchange']}")
                                st.write(f"- Strategy: Long Spot + Short Perps")
                            else:
                                st.write(f"- Short {opp['token']} on {opp['protocol']} ({opp['market']})")
                                st.write(f"- Long {asset_type} on {opp['perps_exchange']}")
                                st.write(f"- Strategy: Short Spot + Long Perps")
                            st.write(f"- Leverage: {leverage}x")
                        else:  # Perps vs Perps
                            exchanges = opp['perps_exchange'].split(' vs ')
                            st.write(f"- Long {asset_type} on {exchanges[0]}")
                            st.write(f"- Short {asset_type} on {exchanges[1]}")
                            st.write(f"- Strategy: Cross-exchange arbitrage")

                        st.write(f"- Target Hours: {target_hours}h")

                        # Risk assessment
                        st.write("**⚠️ Risk Assessment:**")
                        if opp['net_arb'] < 0:
                            st.write("- ✅ **Low Risk**: Profitable opportunity")
                            st.write("- 📈 **Potential**: Earn money from rate differential")
                            st.write("- ⏰ **Timing**: Execute when rates are favorable")
                        else:
                            st.write("- ❌ **High Risk**: Costly opportunity")
                            st.write("- 💸 **Potential**: Loss from rate differential")
                            st.write("- ⚠️ **Warning**: Avoid this strategy")

                        # Execution guidance
                        st.write("**🎯 Execution Guidance:**")
                        if opp['net_arb'] < 0:
                            st.write("- 🚀 **Recommended**: Execute this strategy")
                            st.write("- 📊 **Monitor**: Track rate changes")
                            st.write("- 🔄 **Reassess**: Review periodically")
                        else:
                            st.write("- 🛑 **Avoid**: Do not execute this strategy")
                            st.write("- 👀 **Watch**: Monitor for rate improvements")
                            st.write("- ⏳ **Wait**: Better opportunities may arise")

                    with col2:
                        # Visual indicators
                        if opp['net_arb'] < 0:
                            st.success("✅ Profitable")
                            st.metric("Potential APY", f"{opp['apy']:.1f}%", delta=f"{opp['net_arb']:.4f}%")
                        else:
                            st.error("❌ Costly")
                            st.metric("Potential Cost", f"{opp['apy']:.1f}%", delta=f"{opp['net_arb']:.4f}%")

                        # Ranking
                        if i == 0:
                            st.info("🥇 **Best**")
                        elif i < 3:
                            st.info(f"#{i+1}")

                        # Quick stats
                        st.write("**📈 Quick Stats:**")
                        st.write(f"- Rank: #{i+1}")
                        st.write(f"- Type: {opp['type']}")
                        st.write(f"- Token: {opp['token']}")
                        if opp['net_arb'] < 0:
                            st.write(f"- Profit: {abs(opp['net_arb']):.6f}%")
                        else:
                            st.write(f"- Cost: {abs(opp['net_arb']):.6f}%")
    else:
        st.info(f"**🔍 No arbitrage opportunities found for {asset_name}**")
        if show_profitable_only:
            st.write("💡 *Try unchecking 'Show Profitable Only' to see all opportunities*")


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
    leverage: float = 2.0
) -> None:
    """
    Display detailed calculation breakdowns for spot perps arbitrage.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset_name: Asset name (e.g., "BTC", "SOL")
        asset_variants: List of asset variants
        asset_type: Asset type for perps mapping
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)
        leverage: Leverage level for spot calculations
    """
    import streamlit as st

    st.subheader(f"📊 {asset_name} Calculation Breakdowns")

    # Get perps rates for this asset type
    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)

    st.write("**📈 Perps Funding Rates:**")
    for exchange, rate in perps_rates.items():
        st.write(f"- {exchange}: {rate:.6f}%")

    st.write("---")

    # Helper: get protocol/market/bank for an asset
    def get_protocol_market_pairs(token_config, asset):
        return [(b["protocol"], b["market"], b["bank"]) for b in token_config[asset]["banks"]]

    for variant in asset_variants:
        st.write(f"**{variant}**")

        asset_pairs = get_protocol_market_pairs(token_config, variant)
        asset_mint = token_config[variant]["mint"]
        asset_staking_rate = get_staking_rate_by_mint(staking_data, asset_mint) or 0.0

        for protocol, market, asset_bank in asset_pairs:
            # Find matching USDC bank for the same protocol/market
            usdc_bank = None
            for usdc_bank_info in token_config["USDC"]["banks"]:
                if usdc_bank_info["protocol"] == protocol and usdc_bank_info["market"] == market:
                    usdc_bank = usdc_bank_info["bank"]
                    break

            if not usdc_bank:
                continue  # Skip if no matching USDC bank found

            for direction in ["long", "short"]:
                # Get rates based on direction
                if direction == "long":
                    # Long: lend asset, borrow USDC
                    lend_rates = get_rates_by_bank_address(rates_data, asset_bank)
                    borrow_rates = get_rates_by_bank_address(rates_data, usdc_bank)
                    lend_staking_rate = asset_staking_rate
                    borrow_staking_rate = get_staking_rate_by_mint(staking_data, token_config["USDC"]["mint"]) or 0.0
                else:  # short
                    # Short: lend USDC, borrow asset
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

                # Display breakdown for this protocol/market combination
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

                    # Calculate spot rate
                    try:
                        # Calculate net rates (convert staking rates from decimal to percentage)
                        net_lend = lend_rate + (lend_staking_rate * 100)  # Convert from decimal to percentage
                        net_borrow = borrow_rate + (borrow_staking_rate * 100)  # Convert from decimal to percentage

                        # Calculate fee rate
                        fee_rate = net_borrow * (leverage - 1) - net_lend * leverage

                        # Convert to hourly rate
                        hourly_rate = fee_rate / (365 * 24)

                        # Scale to target interval
                        scaled_rate = hourly_rate * target_hours

                        st.write("**🧮 Spot Rate Calculation:**")
                        st.write(f"- Net Lend Rate: {net_lend:.6f}% APY")
                        st.write(f"- Net Borrow Rate: {net_borrow:.6f}% APY")
                        st.write(f"- Fee Rate: {fee_rate:.6f}% APY")
                        st.write(f"- Hourly Rate: {hourly_rate:.8f}% per hour")
                        st.write(f"- Scaled Rate ({target_hours}h): {scaled_rate:.8f}%")
                        st.write(f"- Formula: ({net_borrow:.6f} × {leverage-1}) - ({net_lend:.6f} × {leverage}) = {fee_rate:.6f}% APY")

                        # Calculate arbitrage opportunities
                        if direction == "long":
                            net_arb = scaled_rate - min(perps_rates.values()) if perps_rates else None
                        else:  # short
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
    leverage: float = 2.0
) -> None:
    """
    Display detailed breakdown of how the 'Spot vs Perps Arb' column is calculated in the main table.
    
    This function shows the exact calculation logic used in create_spot_perps_opportunities_table()
    to help debug discrepancies between table values and expander values.
    
    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset_name: Asset name (e.g., "BTC", "SOL")
        asset_variants: List of asset variants
        asset_type: Asset type for perps mapping
        target_hours: Target interval in hours (default from DEFAULT_TARGET_HOURS)
        leverage: Leverage level for spot calculations (default 2.0)
    """
    import streamlit as st
    
    with st.expander(f"🔬 **{asset_name} Table Arbitrage Calculation Breakdown**", expanded=False):
        st.write(f"**📊 How the 'Spot vs Perps Arb' column is calculated for {asset_name}**")
        st.write("---")
        
        # Get perps rates for this asset type (same as table logic)
        perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)
        
        st.write("**📈 Step 1: Perps Rates (used for all calculations)**")
        for exchange, rate in perps_rates.items():
            st.write(f"- {exchange}: {rate:.8f}%")
        st.write("")
        
        # Calculate for both Long and Short directions (same as table logic)
        for direction in ["Long", "Short"]:
            st.write(f"**🎯 Step 2: {direction.upper()} Direction Calculation**")
            
            # Calculate spot rates for each variant (same as table logic)
            variant_rates = {}
            for variant in asset_variants:
                spot_rates = calculate_spot_rate_with_direction(
                    token_config, rates_data, staking_data,
                    variant, leverage, direction.lower(), target_hours
                )
                variant_rates[variant] = spot_rates
                
                st.write(f"  **{variant} Spot Rates:**")
                for protocol, rate in spot_rates.items():
                    st.write(f"    - {protocol}: {rate:.8f}%")
            
            # Show the corrected "best arbitrage across all rates" selection logic
            st.write(f"  **✅ CORRECTED: Best Arbitrage Across ALL Rates Selection Logic**")
            
            # Calculate arbitrage opportunities using ALL spot rates to find the BEST opportunity
            all_spot_vs_perps_opportunities = []
            opportunity_details = []
            
            # Check all variants and all protocols to find the best arbitrage
            for variant, variant_rates_dict in variant_rates.items():
                for protocol, spot_rate in variant_rates_dict.items():
                    # Calculate arbitrage for this specific spot rate
                    arb_opportunity = calculate_spot_vs_perps_arb(
                        spot_rate, perps_rates, direction
                    )
                    if arb_opportunity is not None:
                        all_spot_vs_perps_opportunities.append(arb_opportunity)
                        opportunity_details.append({
                            'variant': variant,
                            'protocol': protocol,
                            'spot_rate': spot_rate,
                            'arbitrage': arb_opportunity
                        })
            
            st.write(f"  **🧮 Step 3: All Arbitrage Calculations**")
            st.write(f"    - Direction = {direction}")
            st.write(f"    - Found {len(all_spot_vs_perps_opportunities)} profitable opportunities:")
            
            # Show all opportunities
            for i, detail in enumerate(opportunity_details):
                st.write(f"      {i+1}. {detail['variant']} - {detail['protocol']}: {detail['spot_rate']:.8f}% → {detail['arbitrage']:.8f}%")
            
            # Find the BEST (most negative) arbitrage opportunity across all variants/protocols
            if all_spot_vs_perps_opportunities:
                spot_vs_perps_arb = min(all_spot_vs_perps_opportunities)
                
                # Find which opportunity was the best
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
                spot_vs_perps_arb = None
                st.write(f"  **🏆 Step 4: Best Arbitrage Selection**")
                st.write(f"    - No profitable opportunities found")
                st.info(f"    ℹ️ **Table shows: None (no profitable opportunity)**")
            
            st.write("---")
        
        st.write("**🔍 Key Points (CORRECTED LOGIC):**")
        st.write("1. **All Rates Considered**: Table now uses ALL available spot rates from ALL variants")
        st.write("2. **Best Rate Selection**: Table uses the BEST (most profitable) arbitrage opportunity")
        st.write("3. **Comprehensive Comparison**: Each row compares ALL spot rates against all perps rates")
        st.write("4. **Min Selection**: Returns the most negative (best) arbitrage opportunity across everything")
        st.write("5. **Profitability Filter**: Returns None if no negative (profitable) opportunities exist")
        
        st.write("**✅ This should now match the expander:**")
        st.write("- Table shows BEST opportunity across all variants × all protocols × all exchanges")
        st.write("- Expander shows same data with more detailed breakdown")
        st.write("- Both should now show identical best arbitrage values!")
