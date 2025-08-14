"""
Utility functions for formatting and display operations.
"""

import pandas as pd
import streamlit as st
from typing import Dict, List, Optional, Any
from config.constants import EXCHANGE_NAME_MAPPING, DISPLAY_COLUMNS, PERCENTAGE_CONVERSION_FACTOR, INTERVAL_OPTIONS, SPOT_LEVERAGE_LEVELS
from data.models import FundingRateRow, MoneyMarketEntry


def scale_funding_rate_to_percentage(
    rate: float,
    original_hours: int,
    target_hours: int
) -> float:
    """
    Scale funding rate to desired interval and convert to percentage.

    Args:
        rate: Original funding rate as decimal
        original_hours: Original interval in hours
        target_hours: Target interval in hours

    Returns:
        Scaled rate as percentage
    """
    return rate * (target_hours / original_hours) * PERCENTAGE_CONVERSION_FACTOR


def create_funding_rate_row(token_name: str, exchanges_data: List[List]) -> FundingRateRow:
    """
    Create a funding rate row from token exchange data.
    All rates are normalized to 1-hour intervals.

    Args:
        token_name: Name of the token
        exchanges_data: List of [exchange_name, details] pairs

    Returns:
        FundingRateRow object with scaled percentages
    """
    row = FundingRateRow(token=token_name)

    for exchange_name, details in exchanges_data:
        if details is not None:
            try:
                rate = details.get("fundingRate", 0)

                # Note: This function creates the row but doesn't scale yet
                # Scaling happens in process_raw_data_for_display
                if exchange_name == "HlPerp":
                    row.hyperliquid = rate
                elif exchange_name == "BinPerp":
                    row.binance = rate
                elif exchange_name == "BybitPerp":
                    row.bybit = rate
                elif exchange_name == "DriftPerp":
                    row.drift = rate
            except (ValueError, TypeError):
                continue

    return row


def process_raw_data_for_display(
    raw_data: List[List],
    target_hours: int
) -> List[Dict[str, Optional[float]]]:
    """
    Process raw funding data into display format with scaling.
    All rates are normalized to 1-hour intervals, so scaling is simplified.

    Args:
        raw_data: Raw data in [token, exchanges] format
        target_hours: Target interval for scaling

    Returns:
        List of dictionaries ready for DataFrame creation
    """
    formatted_data = []

    for token_entry in raw_data:
        token_name = token_entry[0]
        exchanges = token_entry[1]

        entry = {
            "Token": token_name,
            "Hyperliquid": None,
            "Binance": None,
            "Bybit": None,
            "Drift": None
        }

        for exchange_name, details in exchanges:
            if details is not None:
                try:
                    rate = details.get("fundingRate", 0)
                    # Since rates are normalized to 1-hour intervals, scaling is simplified
                    scaled_percent = scale_funding_rate_to_percentage(rate, 1, target_hours)

                    # Map exchange names to display columns
                    display_name = EXCHANGE_NAME_MAPPING.get(exchange_name)
                    if display_name and display_name in entry:
                        entry[display_name] = scaled_percent

                except (ValueError, TypeError):
                    continue

        formatted_data.append(entry)

    return formatted_data


def create_styled_dataframe(
    data: List[Dict[str, Optional[float]]],
    sort_by: str = "Token"
) -> pd.DataFrame:
    """
    Create and style DataFrame for display.

    Args:
        data: List of dictionaries with funding rate data
        sort_by: Column name to sort by

    Returns:
        Styled pandas DataFrame
    """
    df = pd.DataFrame(data)
    df = df.sort_values(by=sort_by)

    # Convert numeric columns to proper types
    for col in DISPLAY_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def format_dataframe_for_display(df: pd.DataFrame) -> Any:
    """
    Apply styling and formatting to DataFrame for Streamlit display.

    Args:
        df: DataFrame to format

    Returns:
        Styled DataFrame ready for st.dataframe()
    """
    # Create format dictionary for numeric columns
    format_dict = {
        col: "{:.4f}%" for col in df.columns if col != "Token"
    }

    return df.style.format(format_dict)


def convert_to_display_percentage(decimal_rate: float, scale_factor: float = 1.0) -> float:
    """
    Convert decimal rate to display percentage.

    Args:
        decimal_rate: Rate as decimal (e.g., 0.0001)
        scale_factor: Additional scaling factor

    Returns:
        Percentage for display (e.g., 0.01 for 0.01%)
    """
    return decimal_rate * PERCENTAGE_CONVERSION_FACTOR * scale_factor


def format_percentage_string(value: Optional[float], decimal_places: int = 4) -> str:
    """
    Format a percentage value as a string.

    Args:
        value: Percentage value to format
        decimal_places: Number of decimal places

    Returns:
        Formatted percentage string
    """
    if value is None:
        return "N/A"

    return f"{value:.{decimal_places}f}%"


def create_exchange_summary(data: List[Dict[str, Optional[float]]]) -> Dict[str, Dict[str, Any]]:
    """
    Create summary statistics for each exchange.

    Args:
        data: List of funding rate data dictionaries

    Returns:
        Dictionary with summary stats for each exchange
    """
    summary = {}

    df = pd.DataFrame(data)

    for col in DISPLAY_COLUMNS:
        if col in df.columns:
            series = pd.to_numeric(df[col], errors="coerce").dropna()

            summary[col] = {
                "count": len(series),
                "mean": series.mean() if not series.empty else None,
                "median": series.median() if not series.empty else None,
                "min": series.min() if not series.empty else None,
                "max": series.max() if not series.empty else None,
                "std": series.std() if not series.empty else None
            }

    return summary


# Money Markets formatting functions

def process_money_markets_for_display(
    money_markets_data: List[MoneyMarketEntry]
) -> List[Dict[str, Optional[float]]]:
    """
    Process money markets data into display format.

    Args:
        money_markets_data: List of MoneyMarketEntry objects

    Returns:
        List of dictionaries ready for DataFrame creation
    """
    formatted_data = []

    for entry in money_markets_data:
        formatted_entry = {
            "Token": entry.token,
            "Protocol": entry.protocol,
            "Market Key": entry.market_key,
            # Lending and Borrow rates are already in percentage, so just use as-is
            "Lending Rate": entry.lending_rate if entry.lending_rate is not None else None,
            "Borrow Rate": entry.borrow_rate if entry.borrow_rate is not None else None,
            # Staking rate is in decimal, so convert to percentage
            "Staking Rate": convert_to_display_percentage(entry.staking_rate) if entry.staking_rate is not None else None
        }
        formatted_data.append(formatted_entry)

    return formatted_data


def create_money_markets_dataframe(
    data: List[Dict[str, Optional[float]]],
    sort_by: str = "Token"
) -> pd.DataFrame:
    """
    Create and style DataFrame for money markets display.

    Args:
        data: List of dictionaries with money markets data
        sort_by: Column name to sort by

    Returns:
        Styled pandas DataFrame
    """
    df = pd.DataFrame(data)
    df = df.sort_values(by=[sort_by, "Protocol"])

    # Convert numeric columns to proper types, handling None values
    numeric_columns = ["Lending Rate", "Borrow Rate", "Staking Rate"]
    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def format_money_markets_for_display(df: pd.DataFrame) -> Any:
    """
    Apply styling and formatting to money markets DataFrame for Streamlit display.

    Args:
        df: DataFrame to format

    Returns:
        Styled DataFrame ready for st.dataframe()
    """
    # Create format dictionary for numeric columns
    format_dict = {}
    for col in df.columns:
        if col in ["Lending Rate", "Borrow Rate", "Staking Rate"]:
            format_dict[col] = "{:.4f}%"

    # Apply formatting with None handling
    styled_df = df.style.format(format_dict, na_rep="None")

    return styled_df


def create_sidebar_settings(
    show_breakdowns_default: bool = False,
    show_detailed_opportunities_default: bool = False,  # Changed to False by default
    show_profitable_only_default: bool = False,
    show_spot_vs_perps_default: bool = True,
    show_perps_vs_perps_default: bool = False,  # Default to False
    show_table_breakdown_default: bool = False  # New option for table breakdown analysis
) -> Dict[str, Any]:
    """
    Create sidebar settings for UI options.

    Args:
        show_breakdowns_default: Default value for show calculation breakdowns
        show_detailed_opportunities_default: Default value for show detailed opportunities
        show_profitable_only_default: Default value for show profitable only filter
        show_spot_vs_perps_default: Default value for show spot vs perps
        show_perps_vs_perps_default: Default value for show perps vs perps
        show_table_breakdown_default: Default value for show table breakdown analysis

    Returns:
        Dictionary containing all settings values
    """
    with st.sidebar:
        st.header("⚙️ Settings")

        # Display options
        st.subheader("📊 Display Options")
        show_breakdowns = st.checkbox(
            "🔍 Show Calculation Breakdowns",
            value=show_breakdowns_default,
            help="Show detailed calculation breakdowns below each table"
        )

        show_detailed_opportunities = st.checkbox(
            "📊 Show All Possible Arbitrage Opportunities",
            value=show_detailed_opportunities_default,
            help="Show comprehensive analysis of all arbitrage opportunities with detailed breakdowns"
        )
        
        show_table_breakdown = st.checkbox(
            "🔬 Show Table Breakdown Analysis",
            value=show_table_breakdown_default,
            help="Show detailed breakdown of how table arbitrage values are calculated"
        )

        # Filter options
        st.subheader("🔍 Filter Options")
        show_profitable_only = st.checkbox(
            "Show Profitable Only",
            value=show_profitable_only_default,
            help="Filter to show only profitable opportunities"
        )

        show_spot_vs_perps = st.checkbox(
            "Show Spot vs Perps",
            value=show_spot_vs_perps_default,
            help="Show spot vs perps arbitrage opportunities"
        )

        show_perps_vs_perps = st.checkbox(
            "Show Perps vs Perps",
            value=show_perps_vs_perps_default,
            help="Show perps vs perps cross-exchange opportunities"
        )

        # Configuration options
        st.subheader("⚙️ Configuration")
        selected_interval = st.selectbox(
            "Select target interval:",
            list(INTERVAL_OPTIONS.keys()),
            index=0,  # Default to 1 yr
            help="Scales all rates to your selected time period"
        )
        target_hours = INTERVAL_OPTIONS[selected_interval]

        selected_leverage = st.selectbox(
            "Select spot leverage:",
            SPOT_LEVERAGE_LEVELS,
            index=1,  # Default to 2x leverage
            help="Amplifies spot trading positions"
        )

        st.divider()
        st.caption(f"💡 **Current Settings**: {selected_interval} interval with {selected_leverage}x leverage")

        return {
            "show_breakdowns": show_breakdowns,
            "show_detailed_opportunities": show_detailed_opportunities,
            "show_profitable_only": show_profitable_only,
            "show_spot_vs_perps": show_spot_vs_perps,
            "show_perps_vs_perps": show_perps_vs_perps,
            "show_table_breakdown": show_table_breakdown,
            "target_hours": target_hours,
            "selected_leverage": selected_leverage,
            "selected_interval": selected_interval
        }


def display_settings_info(settings: Dict[str, Any]) -> None:
    """
    Display information about current settings.

    Args:
        settings: Dictionary containing settings values
    """
    if settings.get("show_breakdowns"):
        st.info("📊 Calculation breakdowns will be shown below each table showing the exact data and formulas used.")

    if settings.get("show_detailed_opportunities"):
        st.info("📊 All possible arbitrage opportunities will be shown with comprehensive analysis and detailed breakdowns.")
        
    if settings.get("show_table_breakdown"):
        st.info("🔬 Table breakdown analysis will show exactly how the main table arbitrage values are calculated.")
