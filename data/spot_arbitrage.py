"""
Spot arbitrage calculations for hourly fee rates.
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Callable
from data.money_markets_processing import get_staking_rate_by_mint, get_rates_by_bank_address
from data.spot_perps.helpers import compute_effective_max_leverage


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
    import logging

    if leverage < 1:
        raise ValueError("Leverage must be >= 1")

    # Get rates, defaulting to 0 if not available
    lend_rate = lend_rates.get("lendingRate", 0.0) or 0.0
    borrow_rate = borrow_rates.get("borrowingRate", 0.0) or 0.0

    # Handle None staking rates and convert from decimal to percentage format
    lend_staking = (lend_staking_rate or 0.0) * 100  # Convert from decimal to percentage
    borrow_staking = (borrow_staking_rate or 0.0) * 100  # Convert from decimal to percentage

    # Calculate net rates
    net_lend = lend_rate + lend_staking
    net_borrow = borrow_rate + borrow_staking

    # Calculate fee rate: (borrow_rate + staking) * (leverage - 1) - (lend_rate + staking) * leverage
    fee_rate = net_borrow * (leverage - 1) - net_lend * leverage

    # Convert to hourly rate (result is already in percentage format)
    hourly_rate = fee_rate / (365 * 24)

    # Log the calculation data
    logging.info(f"""
    📊 SPOT FEE RATE CALCULATION:
    ==============================
    Input Data:
    - Lend Rate: {lend_rate:.6f}% APY
    - Borrow Rate: {borrow_rate:.6f}% APY
    - Lend Staking Rate: {lend_staking:.6f}% APY
    - Borrow Staking Rate: {borrow_staking:.6f}% APY
    - Leverage: {leverage}x

    Intermediate Calculations:
    - Net Lend Rate: {net_lend:.6f}% APY (lend_rate + lend_staking)
    - Net Borrow Rate: {net_borrow:.6f}% APY (borrow_rate + borrow_staking)
    - Fee Rate: {fee_rate:.6f}% APY (net_borrow * (leverage-1) - net_lend * leverage)
    - Hourly Rate: {hourly_rate:.8f}% per hour (fee_rate / (365*24))
    - Note: Hourly rate will be converted to yearly for display

    Formula: ({net_borrow:.6f} * {leverage-1}) - ({net_lend:.6f} * {leverage}) = {fee_rate:.6f}% APY
    """)

    return hourly_rate


def create_spot_arbitrage_table(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    asset_group: list,
    borrow_asset: str = "USDC",
    leverage_levels: list = [1, 2, 3, 4, 5],
    position_type: str = "long",  # "long" or "short"
    logger: Optional[Callable[[str], None]] = None,
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
                if logger is not None:
                    missing_parts = []
                    if not lend_rates:
                        missing_parts.append("lending")
                    if not borrow_rates:
                        missing_parts.append("borrowing")
                    missing_str = "/".join(missing_parts)
                    logger(
                        f"Skipping {asset} {position_type.upper()} at {protocol} ({market}): missing {missing_str} data."
                    )
                continue

            lend_rate = lend_rates.get("lendingRate")
            borrow_rate = borrow_rates.get("borrowingRate")
            if lend_rate is None or borrow_rate is None:
                if logger is not None:
                    missing_parts = []
                    if lend_rate is None:
                        missing_parts.append("lending")
                    if borrow_rate is None:
                        missing_parts.append("borrowing")
                    missing_str = "/".join(missing_parts)
                    logger(
                        f"Skipping {asset} {position_type.upper()} at {protocol} ({market}): {missing_str} rate not available."
                    )
                continue

            # Log the data being used for calculation
            import logging
            logging.info(f"""
            🔍 SPOT ARBITRAGE DATA USED:
            =============================
            Asset: {asset}
            Position Type: {position_type.upper()}
            Protocol: {protocol}
            Market: {market}
            Asset Bank: {asset_bank}
            Borrow Bank: {borrow_bank}

            Rates Data:
            - Asset Lend Rate: {lend_rate:.6f}% APY
            - Asset Borrow Rate: {borrow_rate:.6f}% APY
            - Asset Staking Rate: {asset_staking_rate:.6f}% APY
            - Borrow Asset Staking Rate: {borrow_staking_rate:.6f}% APY

            Position Details:
            - Long: Lend {asset}, Borrow {borrow_asset}
            - Short: Lend {borrow_asset}, Borrow {asset}
            """)

            # Calculate hourly fee rates for all leverage levels
            # Note: These rates are already in percentage format (e.g., 0.01 = 0.01% per hour)
            row = {
                "Asset": asset,
                "Protocol": protocol,
                "Market": market,
            }

            for leverage in leverage_levels:
                # Enforce per-bank max leverage caps
                effective_max = compute_effective_max_leverage(
                    token_config,
                    asset_bank if position_type == "long" else borrow_bank,
                    borrow_bank if position_type == "long" else asset_bank,
                    position_type,
                )
                if leverage > effective_max:
                    row[f"{leverage}x"] = None
                    continue
                try:
                    hourly_rate = calculate_hourly_fee_rates(
                        lend_rates, borrow_rates,
                        lend_staking_rate, borrow_staking_rate,
                        leverage
                    )
                    # Convert hourly rate to yearly rate (multiply by hours in a year)
                    yearly_rate = hourly_rate * 365 * 24
                    row[f"{leverage}x"] = yearly_rate
                except ValueError:
                    row[f"{leverage}x"] = None

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
    from utils.formatting import create_sidebar_settings, display_settings_info

    # Get settings from sidebar (only show breakdowns option for this page)
    with st.sidebar:
        st.header("⚙️ Settings")
        st.subheader("📊 Display Options")
        show_breakdowns = st.checkbox(
            "🔍 Show Calculation Breakdowns",
            value=False,
            help="Show detailed calculation breakdowns below each table"
        )
        show_missing_data = st.checkbox(
            "🔎 Show missing data diagnostics",
            value=False,
            help="Display which protocol/market rows were skipped due to missing lending/borrowing rates",
        )

    # Display settings info
    if show_breakdowns:
        st.info("📊 Calculation breakdowns will be shown below each table showing the exact data and formulas used.")

    # Asset groups configuration
    asset_groups = {
        "SOL Variants": SPOT_ASSET_GROUPS["SOL_VARIANTS"],
        "BTC Variants": SPOT_ASSET_GROUPS["BTC_VARIANTS"]
    }

    for group_name, assets in asset_groups.items():
        st.subheader(f"{group_name}")

        # Long positions
        st.write("**Long Positions** (Lend Asset, Borrow USDC)")
        long_logs: List[str] = []
        long_df = create_spot_arbitrage_table(
            token_config, rates_data, staking_data,
            assets, borrow_asset=SPOT_BORROW_ASSET,
            leverage_levels=SPOT_LEVERAGE_LEVELS, position_type="long",
            logger=(long_logs.append if show_missing_data else None),
        )
        if not long_df.empty:
            # Format leverage columns with % symbols
            styled_long_df = format_spot_arbitrage_dataframe(long_df)
            st.dataframe(styled_long_df, use_container_width=True)

            # Show calculation breakdowns if requested
            if show_breakdowns:
                display_calculation_breakdowns(
                    token_config, rates_data, staking_data,
                    assets, SPOT_BORROW_ASSET, SPOT_LEVERAGE_LEVELS, "long"
                )
        else:
            st.info(f"No valid protocol/market pairs found for {group_name} long positions.")
        if show_missing_data and long_logs:
            with st.expander(f"🔎 Missing data for {group_name} (Long)"):
                for line in long_logs:
                    st.write("- ", line)

        # Short positions
        st.write("**Short Positions** (Lend USDC, Borrow Asset)")
        short_logs: List[str] = []
        short_df = create_spot_arbitrage_table(
            token_config, rates_data, staking_data,
            assets, borrow_asset=SPOT_BORROW_ASSET,
            leverage_levels=SPOT_LEVERAGE_LEVELS, position_type="short",
            logger=(short_logs.append if show_missing_data else None),
        )
        if not short_df.empty:
            # Format leverage columns with % symbols
            styled_short_df = format_spot_arbitrage_dataframe(short_df)
            st.dataframe(styled_short_df, use_container_width=True)

            # Show calculation breakdowns if requested
            if show_breakdowns:
                display_calculation_breakdowns(
                    token_config, rates_data, staking_data,
                    assets, SPOT_BORROW_ASSET, SPOT_LEVERAGE_LEVELS, "short"
                )
        else:
            st.info(f"No valid protocol/market pairs found for {group_name} short positions.")
        if show_missing_data and short_logs:
            with st.expander(f"🔎 Missing data for {group_name} (Short)"):
                for line in short_logs:
                    st.write("- ", line)

        st.divider()


def display_calculation_breakdowns(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    asset_group: list,
    borrow_asset: str,
    leverage_levels: list,
    position_type: str
) -> None:
    """
    Display detailed calculation breakdowns for spot arbitrage.

    Args:
        token_config: Token configuration dictionary
        rates_data: Current rates data from API
        staking_data: Staking rates data from API
        asset_group: List of assets to show breakdowns for
        borrow_asset: Asset being borrowed (usually USDC)
        leverage_levels: List of leverage levels
        position_type: "long" or "short"
    """
    import streamlit as st

    st.subheader("📊 Calculation Breakdowns")

    # Helper: get protocol/market/bank for an asset
    def get_protocol_market_pairs(token_config, asset):
        return [(b["protocol"], b["market"], b["bank"]) for b in token_config[asset]["banks"]]

    # Build protocol/market pairs for borrow asset
    borrow_pairs = get_protocol_market_pairs(token_config, borrow_asset)
    borrow_pairs_dict = {(p, m): bank for p, m, bank in borrow_pairs}

    for asset in asset_group:
        st.write(f"**{asset}**")

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

            # Display breakdown for this protocol/market combination
            with st.expander(f"🔍 {protocol} ({market}) - {position_type.upper()}"):
                st.write(f"**Asset:** {asset}")
                st.write(f"**Protocol:** {protocol}")
                st.write(f"**Market:** {market}")
                st.write(f"**Position Type:** {position_type.upper()}")
                st.write(f"**Asset Bank:** {asset_bank}")
                st.write(f"**Borrow Bank:** {borrow_bank}")

                st.write("**📈 Rates Data:**")
                st.write(f"- Asset Lend Rate: {lend_rate:.6f}% APY")
                st.write(f"- Asset Borrow Rate: {borrow_rate:.6f}% APY")
                st.write(f"- Asset Staking Rate: {asset_staking_rate * 100:.6f}% APY (raw: {asset_staking_rate:.6f})")
                st.write(f"- {borrow_asset} Staking Rate: {borrow_staking_rate * 100:.6f}% APY (raw: {borrow_staking_rate:.6f})")

                st.write("**🧮 Calculations by Leverage:**")

                for leverage in leverage_levels:
                    try:
                        # Calculate net rates (convert staking rates from decimal to percentage)
                        net_lend = lend_rate + (lend_staking_rate * 100)  # Convert from decimal to percentage
                        net_borrow = borrow_rate + (borrow_staking_rate * 100)  # Convert from decimal to percentage

                        # Calculate fee rate
                        fee_rate = net_borrow * (leverage - 1) - net_lend * leverage

                        # Convert to hourly rate (for internal calculation)
                        hourly_rate = fee_rate / (365 * 24)
                        # Convert hourly rate back to yearly for display
                        yearly_rate = hourly_rate * 365 * 24

                        st.write(f"**{leverage}x Leverage:**")
                        st.write(f"- Net Lend Rate: {net_lend:.6f}% APY")
                        st.write(f"- Net Borrow Rate: {net_borrow:.6f}% APY")
                        st.write(f"- Fee Rate: {fee_rate:.6f}% APY")
                        st.write(f"- Yearly Rate: {yearly_rate:.2f}% per year")
                        st.write(f"- Formula: ({net_borrow:.6f} × {leverage-1}) - ({net_lend:.6f} × {leverage}) = {fee_rate:.6f}% APY")
                        st.write("---")

                    except ValueError:
                        st.write(f"**{leverage}x Leverage:** Invalid calculation")


def format_spot_arbitrage_dataframe(df: pd.DataFrame) -> Any:
    """
    Apply styling and formatting to spot arbitrage DataFrame for Streamlit display.

    Note: The yearly fee rates are already in percentage format, so we just add % symbols.

    Args:
        df: DataFrame to format

    Returns:
        Styled DataFrame ready for st.dataframe()
    """
    # Create format dictionary for leverage columns (columns ending with "x")
    format_dict = {}
    for col in df.columns:
        if col.endswith("x") and any(char.isdigit() for char in col):
            format_dict[col] = "{:.2f}%"

    # Apply formatting with None handling
    styled_df = df.style.format(format_dict, na_rep="None")

    return styled_df
