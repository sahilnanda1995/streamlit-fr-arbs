"""
Spot and Perps arbitrage calculations for funding rate opportunities.
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from data.money_markets_processing import get_staking_rate_by_mint, get_rates_by_bank_address
from data.spot_arbitrage import calculate_hourly_fee_rates


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
    target_hours: int = 1
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
        target_hours: Target interval in hours (default 1)

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
    target_hours: int = 1
) -> Dict[str, float]:
    """
    Get funding rates from all perps exchanges for an asset.

    Args:
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset: Asset to get funding rates for ("BTC" or "SOL")
        target_hours: Target interval in hours (default 1)

    Returns:
        Dictionary of {exchange: funding_rate} scaled to target interval
    """
    perps_rates = {}

    # Extract funding rates from Hyperliquid data
    if hyperliquid_data and isinstance(hyperliquid_data, list):
        for asset_data in hyperliquid_data:
            if isinstance(asset_data, list) and len(asset_data) >= 2:
                asset_name = asset_data[0]
                if asset_name == asset:
                    exchanges_data = asset_data[1]
                    for exchange_data in exchanges_data:
                        if isinstance(exchange_data, list) and len(exchange_data) >= 2:
                            exchange_name = exchange_data[0]
                            funding_info = exchange_data[1]
                            if isinstance(funding_info, dict):
                                funding_rate_str = funding_info.get("fundingRate", "0")
                                try:
                                    funding_rate = float(funding_rate_str)
                                    # Convert to hourly rate first
                                    interval_hours = funding_info.get("fundingIntervalHours", 8)
                                    hourly_rate = funding_rate / interval_hours
                                    # Scale to target interval
                                    scaled_rate = hourly_rate * target_hours
                                    perps_rates[exchange_name] = scaled_rate
                                except (ValueError, ZeroDivisionError):
                                    continue
                    break

    # Extract funding rates from Drift data
    if drift_data and isinstance(drift_data, dict):
        markets = drift_data.get("markets", [])
        for market in markets:
            if isinstance(market, dict) and market.get("symbol") == f"{asset}-PERP":
                # Convert to percentage and scale to target interval
                funding_rate = market.get("fundingRate", 0)
                # Assuming Drift rates are already hourly, scale to target interval
                scaled_rate = funding_rate * target_hours
                perps_rates["Drift"] = scaled_rate
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
    target_hours: int = 1
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
        target_hours: Target interval in hours (default 1)

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

        # Calculate arbitrage opportunities using the first available spot rate
        first_available_rate = None
        for variant_rates_dict in variant_rates.values():
            if variant_rates_dict:
                first_available_rate = list(variant_rates_dict.values())[0]
                break

        if first_available_rate is not None:
            spot_vs_perps_arb = calculate_spot_vs_perps_arb(
                first_available_rate, perps_rates, direction
            )
            perps_vs_perps_arb = calculate_perps_vs_perps_arb(perps_rates)
        else:
            spot_vs_perps_arb = None
            perps_vs_perps_arb = None

        # Add arbitrage columns
        row["Spot vs Perps Arb"] = spot_vs_perps_arb
        row["Perps vs Perps Arb"] = perps_vs_perps_arb

        rows.append(row)

    if rows:
        return pd.DataFrame(rows)
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
    from config.constants import SPOT_PERPS_CONFIG, INTERVAL_OPTIONS, SPOT_LEVERAGE_LEVELS

    st.header("💰 Spot and FR Opportunities")

    # Add interval selection
    selected_interval = st.selectbox(
        "Select target interval:",
        list(INTERVAL_OPTIONS.keys()),
        index=0  # Default to 1 hr
    )
    target_hours = INTERVAL_OPTIONS[selected_interval]

    # Add leverage selection
    selected_leverage = st.selectbox(
        "Select spot leverage:",
        SPOT_LEVERAGE_LEVELS,
        index=1  # Default to 2x leverage
    )

    st.caption(f"💡 Rates and arbitrage opportunities scaled to {selected_interval} interval with {selected_leverage}x leverage")

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
            target_hours
        )

        if not opportunities_df.empty:
            # Display DataFrame with percentage formatting
            st.dataframe(
                opportunities_df,
                use_container_width=True,
                column_config={
                    col: st.column_config.NumberColumn(
                        col,
                        format="%.6f%%"
                    ) for col in opportunities_df.columns
                    if col not in ["Spot Direction", "Asset"] and opportunities_df[col].dtype in ['float64', 'float32', 'int64', 'int32']
                }
            )
        else:
            st.info(f"No valid opportunities found for {asset_name} assets.")

        # Display asset-specific opportunities below each table
        display_asset_specific_opportunities(
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
    target_hours: int = 1
) -> Dict[str, List[Dict]]:
    """
    Create a summary of all arbitrage opportunities, ranked by profitability.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        target_hours: Target interval in hours (default 1)

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
    target_hours: int = 1
) -> None:
    """
    Display a summary of all arbitrage opportunities, ranked by profitability.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        target_hours: Target interval in hours (default 1)
    """
    import streamlit as st

    opportunities = create_arbitrage_opportunities_summary(
        token_config, rates_data, staking_data, hyperliquid_data, drift_data, target_hours
    )

    st.subheader("🎯 Arbitrage Opportunities Summary")

    # Display Spot vs Perps opportunities
    if opportunities['spot_vs_perps']:
        st.write("**💰 Spot vs Perps Opportunities:**")
        for i, opp in enumerate(opportunities['spot_vs_perps'][:5]):  # Show top 5
            color = "🟢" if opp['arbitrage_rate'] < 0 else "🔴"
            st.write(f"{color} **{i+1}.** {opp['description']}")
    else:
        st.write("**💰 Spot vs Perps:** No profitable opportunities found")

    st.write("---")

    # Display Perps vs Perps opportunities
    if opportunities['perps_vs_perps']:
        st.write("**📈 Perps vs Perps Opportunities:**")
        for i, opp in enumerate(opportunities['perps_vs_perps'][:5]):  # Show top 5
            color = "🟢" if opp['arbitrage_rate'] < 0 else "🔴"
            st.write(f"{color} **{i+1}.** {opp['description']}")
    else:
        st.write("**📈 Perps vs Perps:** No profitable opportunities found")

    # Show best overall opportunity
    all_opportunities = opportunities['spot_vs_perps'] + opportunities['perps_vs_perps']
    if all_opportunities:
        best_opp = min(all_opportunities, key=lambda x: x['arbitrage_rate'])
        st.write("---")
        st.write(f"**🏆 Best Overall Opportunity:** {best_opp['description']}")
        st.write(f"*Rate: {best_opp['arbitrage_rate']:.6f}%*")


def display_asset_specific_opportunities(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    asset_name: str,
    asset_variants: list,
    asset_type: str,
    target_hours: int = 1,
    leverage: float = 2.0
) -> None:
    """
    Display asset-specific arbitrage opportunities and best strategies.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset_name: Asset name (e.g., "BTC", "SOL")
        asset_variants: List of asset variants
        asset_type: Asset type for perps mapping
        target_hours: Target interval in hours
        leverage: Leverage level for spot calculations (default 2.0)
    """
    import streamlit as st
    from config.constants import SPOT_PERPS_CONFIG

    # Get perps rates for this asset type
    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)

    # Calculate perps vs perps opportunities for this asset
    perps_vs_perps_arb = calculate_perps_vs_perps_arb(perps_rates)

    # Collect all opportunities for this asset
    asset_opportunities = []

    # Add perps vs perps opportunity if available
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
            # Calculate APY (assuming the rate continues for a year)
            apy = abs(best_rate) * 365 * 24 / target_hours
            asset_opportunities.append({
                'type': 'Perps vs Perps',
                'description': f"{best_pair[0]} vs {best_pair[1]}: {best_rate:.6f}%",
                'rate': best_rate,
                'apy': apy,
                'details': f"{best_pair[0]}: {best_pair[2]:.6f}%, {best_pair[1]}: {best_pair[3]:.6f}%"
            })

    # Calculate spot vs perps opportunities for each variant
    for variant in asset_variants:
        for direction in ["Long", "Short"]:
            spot_rates = calculate_spot_rate_with_direction(
                token_config, rates_data, staking_data,
                variant, leverage,
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
                        # Calculate APY (assuming the rate continues for a year)
                        apy = abs(spot_vs_perps_arb) * 365 * 24 / target_hours
                        asset_opportunities.append({
                            'type': 'Spot vs Perps',
                            'description': f"{variant} {direction} Spot vs {best_exchange} Perps: {spot_vs_perps_arb:.6f}%",
                            'rate': spot_vs_perps_arb,
                            'apy': apy,
                            'details': f"Spot Rate: {spot_rate:.6f}%, {best_exchange} Funding: {best_funding_rate:.6f}%"
                        })

    # Sort opportunities by profitability (most negative first)
    asset_opportunities.sort(key=lambda x: x['rate'])

    # Display asset-specific opportunities
    if asset_opportunities:
        st.write(f"**🎯 {asset_name} Best Strategies:**")

        # Show top 3 opportunities
        for i, opp in enumerate(asset_opportunities[:3]):
            color = "🟢" if opp['rate'] < 0 else "🔴"
            apy_text = f" (earn up to {opp['apy']:.1f}% APY)" if opp['rate'] < 0 else f" (cost up to {opp['apy']:.1f}% APY)"
            st.write(f"{color} **{i+1}.** {opp['description']}{apy_text}")
            st.caption(f"*{opp['details']}*")

        # Show best overall opportunity for this asset
        best_opp = min(asset_opportunities, key=lambda x: x['rate'])
        best_apy_text = f" (earn up to {best_opp['apy']:.1f}% APY)" if best_opp['rate'] < 0 else f" (cost up to {best_opp['apy']:.1f}% APY)"
        st.write("---")
        st.write(f"**🏆 Best {asset_name} Strategy:** {best_opp['description']}{best_apy_text}")
        st.write(f"*{best_opp['details']}*")
    else:
        st.write(f"**🎯 {asset_name} Strategies:** No profitable opportunities found")
