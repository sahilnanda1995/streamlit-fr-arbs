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
    direction: str = "long"  # "long" or "short"
) -> Dict[str, float]:
    """
    Calculate spot rates for an asset in a specific direction.

    Note: The returned hourly rates are already in percentage format (e.g., 0.01 represents 0.01% per hour).

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        asset: Asset to calculate rates for
        leverage: Leverage level (default 2.0)
        direction: "long" or "short" position

    Returns:
        Dictionary of {protocol: hourly_rate} where rates are in percentage format
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
            spot_rates[f"{protocol}({market})"] = hourly_rate
        except ValueError:
            continue

    return spot_rates


def get_perps_rates_for_asset(
    hyperliquid_data: dict,
    drift_data: dict,
    asset: str
) -> Dict[str, float]:
    """
    Get funding rates from all perps exchanges for an asset.

    Args:
        hyperliquid_data: Hyperliquid funding data
        drift_data: Drift funding data
        asset: Asset to get funding rates for ("BTC" or "SOL")

    Returns:
        Dictionary of {exchange: funding_rate}
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
                                    # Convert to hourly rate
                                    interval_hours = funding_info.get("fundingIntervalHours", 8)
                                    hourly_rate = funding_rate / interval_hours
                                    perps_rates[exchange_name] = hourly_rate
                                except (ValueError, ZeroDivisionError):
                                    continue
                    break

    # Extract funding rates from Drift data
    if drift_data and isinstance(drift_data, dict):
        markets = drift_data.get("markets", [])
        for market in markets:
            if isinstance(market, dict) and market.get("symbol") == f"{asset}-PERP":
                # Convert to percentage and scale to hourly
                funding_rate = market.get("fundingRate", 0)
                perps_rates["Drift"] = funding_rate
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
    leverage: float = 2.0
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

    Returns:
        DataFrame with all columns including arbitrage calculations
    """
    rows = []

    # Get perps rates for the asset type
    perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type)

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
                variant, leverage, direction.lower()
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


def display_spot_perps_opportunities_section(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict
) -> None:
    """
    Display complete spot and perps opportunities section.
    Shows separate tables for BTC and SOL.

    Note: The spot rates displayed are already in percentage format (hourly fee rates).
    """
    import streamlit as st
    from config.constants import SPOT_PERPS_CONFIG

    st.header("💰 Spot and FR Opportunities")

    # Create separate tables for BTC and SOL
    asset_configs = {
        "BTC": (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC"),
        "SOL": (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL")
    }

    for asset_name, (asset_variants, asset_type) in asset_configs.items():
        st.subheader(f"{asset_name} Assets")

        opportunities_df = create_spot_perps_opportunities_table(
            token_config, rates_data, staking_data,
            hyperliquid_data, drift_data,
            asset_variants, asset_type, SPOT_PERPS_CONFIG["DEFAULT_SPOT_LEVERAGE"]
        )

        if not opportunities_df.empty:
            st.dataframe(opportunities_df, use_container_width=True)
        else:
            st.info(f"No valid opportunities found for {asset_name} assets.")

        st.divider()
