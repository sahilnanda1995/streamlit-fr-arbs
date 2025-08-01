"""
Spot arbitrage calculations for hourly fee rates.
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from data.money_markets_processing import get_staking_rate_by_mint, get_rates_by_bank_address


def calculate_hourly_fee_rates(
    lend_rates: dict,      # Rates for the asset we're lending
    borrow_rates: dict,    # Rates for the asset we're borrowing
    lend_staking_rate: float,  # Can be None/0 if not available
    borrow_staking_rate: float, # Can be None/0 if not available
    leverage: float,       # Should be >= 1
) -> float:  # Returns hourly fee rate in percentage format for the given leverage
    """
    Calculate hourly fee rate for a given leverage level.

    Note: The returned rate is already in percentage format (e.g., 0.01 represents 0.01% per hour).

    Args:
        lend_rates: Dictionary containing lending rate
        borrow_rates: Dictionary containing borrowing rate
        lend_staking_rate: Staking rate for the lent asset (can be 0)
        borrow_staking_rate: Staking rate for the borrowed asset (can be 0)
        leverage: Leverage level (should be >= 1)

    Returns:
        Hourly fee rate as a float in percentage format (e.g., 0.01 = 0.01% per hour)
    """
    if leverage < 1:
        raise ValueError("Leverage must be >= 1")

    # Get rates, defaulting to 0 if not available
    lend_rate = lend_rates.get("lendingRate", 0.0) or 0.0
    borrow_rate = borrow_rates.get("borrowingRate", 0.0) or 0.0

    # Handle None staking rates
    lend_staking = lend_staking_rate or 0.0
    borrow_staking = borrow_staking_rate or 0.0

    # Calculate net rates
    net_lend = lend_rate + lend_staking
    net_borrow = borrow_rate + borrow_staking

    # Calculate fee rate: (borrow_rate + staking) * (leverage - 1) - (lend_rate + staking) * leverage
    fee_rate = net_borrow * (leverage - 1) - net_lend * leverage

    # Convert to hourly rate (result is already in percentage format)
    hourly_rate = fee_rate / (365 * 24)

    return hourly_rate


def create_spot_arbitrage_table(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    asset_group: list,
    borrow_asset: str = "USDC",
    leverage_levels: list = [1, 2, 3, 4, 5],
    position_type: str = "long"  # "long" or "short"
) -> pd.DataFrame:
    """
    Create a DataFrame with spot arbitrage calculations for given asset group.

    Note: The hourly fee rates returned are already in percentage format (e.g., 0.01 represents 0.01% per hour).

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        asset_group: List of assets to calculate for
        borrow_asset: Asset to borrow (default USDC)
        leverage_levels: List of leverage levels to calculate
        position_type: "long" or "short" position

    Returns:
        DataFrame with arbitrage calculations (hourly fee rates in percentage format)
    """
    rows = []

    # Helper: get protocol/market/bank for an asset
    def get_protocol_market_pairs(token_config, asset):
        return [(b["protocol"], b["market"], b["bank"]) for b in token_config[asset]["banks"]]

    # Build protocol/market pairs for borrow asset
    borrow_pairs = get_protocol_market_pairs(token_config, borrow_asset)
    borrow_pairs_dict = {(p, m): bank for p, m, bank in borrow_pairs}

    for asset in asset_group:
        asset_pairs = get_protocol_market_pairs(token_config, asset)
        asset_mint = token_config[asset]["mint"]
        asset_staking_rate = get_staking_rate_by_mint(staking_data, asset_mint) or 0.0

        for protocol, market, asset_bank in asset_pairs:
            # Only include if borrow asset has the same protocol/market
            if (protocol, market) not in borrow_pairs_dict:
                continue

            borrow_bank = borrow_pairs_dict[(protocol, market)]

            # Get rates based on position type
            if position_type == "long":
                # Long: lend asset, borrow USDC
                lend_rates = get_rates_by_bank_address(rates_data, asset_bank)
                borrow_rates = get_rates_by_bank_address(rates_data, borrow_bank)
                lend_staking_rate = asset_staking_rate
                borrow_staking_rate = get_staking_rate_by_mint(staking_data, token_config[borrow_asset]["mint"]) or 0.0
            else:  # short
                # Short: lend USDC, borrow asset
                lend_rates = get_rates_by_bank_address(rates_data, borrow_bank)
                borrow_rates = get_rates_by_bank_address(rates_data, asset_bank)
                lend_staking_rate = get_staking_rate_by_mint(staking_data, token_config[borrow_asset]["mint"]) or 0.0
                borrow_staking_rate = asset_staking_rate

            if not lend_rates or not borrow_rates:
                continue

            lend_rate = lend_rates.get("lendingRate")
            borrow_rate = borrow_rates.get("borrowingRate")
            if lend_rate is None or borrow_rate is None:
                continue

            # Calculate hourly fee rates for all leverage levels
            # Note: These rates are already in percentage format (e.g., 0.01 = 0.01% per hour)
            row = {
                "Asset": asset,
                "Protocol": protocol,
                "Market": market,
            }

            for leverage in leverage_levels:
                try:
                    hourly_rate = calculate_hourly_fee_rates(
                        lend_rates, borrow_rates,
                        lend_staking_rate, borrow_staking_rate,
                        leverage
                    )
                    row[f"{leverage}x (hr)"] = hourly_rate
                except ValueError:
                    row[f"{leverage}x (hr)"] = None

            rows.append(row)

    if rows:
        return pd.DataFrame(rows)
    else:
        return pd.DataFrame()  # Return empty DataFrame if no data


def display_spot_arbitrage_section(
    token_config: dict,
    rates_data: dict,
    staking_data: dict
) -> None:
    """
    Display the complete spot arbitrage section with long and short positions.

    Note: The hourly fee rates displayed are already in percentage format and will be shown with % symbols.
    """
    import streamlit as st
    from config.constants import SPOT_ASSET_GROUPS, SPOT_BORROW_ASSET, SPOT_LEVERAGE_LEVELS

    st.header("💰 Spot Hourly Fee Rates")
    st.caption("💡 Values shown are hourly fee rates in percentage format (e.g., 0.01% per hour)")

    # Asset groups configuration
    asset_groups = {
        "SOL Variants": SPOT_ASSET_GROUPS["SOL_VARIANTS"],
        "BTC Variants": SPOT_ASSET_GROUPS["BTC_VARIANTS"]
    }

    for group_name, assets in asset_groups.items():
        st.subheader(f"{group_name}")

        # Long positions
        st.write("**Long Positions** (Lend Asset, Borrow USDC)")
        long_df = create_spot_arbitrage_table(
            token_config, rates_data, staking_data,
            assets, borrow_asset=SPOT_BORROW_ASSET,
            leverage_levels=SPOT_LEVERAGE_LEVELS, position_type="long"
        )
        if not long_df.empty:
            # Format leverage columns with % symbols
            styled_long_df = format_spot_arbitrage_dataframe(long_df)
            st.dataframe(styled_long_df, use_container_width=True)
        else:
            st.info(f"No valid protocol/market pairs found for {group_name} long positions.")

        # Short positions
        st.write("**Short Positions** (Lend USDC, Borrow Asset)")
        short_df = create_spot_arbitrage_table(
            token_config, rates_data, staking_data,
            assets, borrow_asset=SPOT_BORROW_ASSET,
            leverage_levels=SPOT_LEVERAGE_LEVELS, position_type="short"
        )
        if not short_df.empty:
            # Format leverage columns with % symbols
            styled_short_df = format_spot_arbitrage_dataframe(short_df)
            st.dataframe(styled_short_df, use_container_width=True)
        else:
            st.info(f"No valid protocol/market pairs found for {group_name} short positions.")

        st.divider()


def format_spot_arbitrage_dataframe(df: pd.DataFrame) -> Any:
    """
    Apply styling and formatting to spot arbitrage DataFrame for Streamlit display.

    Note: The hourly fee rates are already in percentage format, so we just add % symbols.

    Args:
        df: DataFrame to format

    Returns:
        Styled DataFrame ready for st.dataframe()
    """
    # Create format dictionary for leverage columns (columns containing "x (hr)")
    format_dict = {}
    for col in df.columns:
        if "x (hr)" in col:
            format_dict[col] = "{:.4f}%"

    # Apply formatting with None handling
    styled_df = df.style.format(format_dict, na_rep="None")

    return styled_df
