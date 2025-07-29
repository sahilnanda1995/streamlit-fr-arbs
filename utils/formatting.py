"""
Utility functions for formatting and display operations.
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from config.constants import EXCHANGE_NAME_MAPPING, DISPLAY_COLUMNS, PERCENTAGE_CONVERSION_FACTOR
from data.models import FundingRateRow


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
                rate = float(details.get("fundingRate", 0))
                interval = details.get("fundingIntervalHours", 1)

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
                    rate = float(details.get("fundingRate", 0))
                    interval = details.get("fundingIntervalHours", 1)
                    scaled_percent = scale_funding_rate_to_percentage(rate, interval, target_hours)

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
