"""
Reusable DataFrame processing utilities to reduce code duplication.
"""

import pandas as pd
from typing import List, Dict, Any, Optional
import streamlit as st
from api.endpoints import fetch_hourly_rates, fetch_hourly_staking


def records_to_dataframe(
    records: List[Dict[str, Any]], 
    time_col: str,
    value_cols: List[str],
    time_format: str = "hourBucket"
) -> pd.DataFrame:
    """
    Convert API records to DataFrame with standardized time handling.
    
    Args:
        records: List of records from API
        time_col: Name for the time column in output DataFrame
        value_cols: List of column names to extract from records
        time_format: Format of time field in records
        
    Returns:
        DataFrame with time and value columns
    """
    if not records:
        return pd.DataFrame(columns=[time_col] + value_cols)
    
    df = pd.DataFrame(records)
    df[time_col] = pd.to_datetime(df[time_format], utc=True).dt.tz_convert(None)
    
    for col in value_cols:
        # Map common API field names to standardized column names
        api_field = _get_api_field_name(col)
        df[col] = pd.to_numeric(df.get(api_field, 0), errors="coerce")
    
    return df[[time_col] + value_cols].sort_values(time_col)


def _get_api_field_name(col: str) -> str:
    """Map standardized column names to API field names."""
    field_mapping = {
        "asset_lend_apy": "avgLendingRate",
        "asset_borrow_apy": "avgBorrowingRate",
        "usdc_lend_apy": "avgLendingRate", 
        "usdc_borrow_apy": "avgBorrowingRate",
        "lend_apy": "avgLendingRate",
        "borrow_apy": "avgBorrowingRate", 
        "staking_apy": "avgApy"
    }
    return field_mapping.get(col, col)


def aggregate_to_4h_buckets(
    df: pd.DataFrame, 
    time_col: str = "time", 
    value_cols: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    Aggregate hourly data to 4H centered buckets.
    
    Args:
        df: DataFrame with hourly data
        time_col: Name of time column
        value_cols: Columns to aggregate (all numeric if None)
        
    Returns:
        DataFrame with 4H aggregated data
    """
    if df.empty:
        return df
    
    if value_cols is None:
        value_cols = df.select_dtypes(include=['number']).columns.tolist()
    
    df_copy = df.copy()
    df_copy["time_4h"] = df_copy[time_col].dt.floor("4h")
    
    aggregated = (
        df_copy.groupby("time_4h", as_index=False)[value_cols].mean()
        .assign(time=lambda x: pd.to_datetime(x["time_4h"]) + pd.Timedelta(hours=2))
        .drop(columns=["time_4h"])
    )
    
    return aggregated


def fetch_and_process_rates(
    bank_address: str, 
    protocol: str, 
    hours: int, 
    rate_type: str = "rates"
) -> pd.DataFrame:
    """
    Fetch and process hourly rates/staking data with error handling.
    
    Args:
        bank_address: Bank or mint address
        protocol: Protocol name
        hours: Number of hours to fetch
        rate_type: "rates" for lending/borrow rates, "staking" for staking rates
        
    Returns:
        Processed DataFrame
    """
    try:
        if rate_type == "rates":
            data = fetch_hourly_rates(bank_address, protocol, int(hours)) or []
            cols = ["lend_apy", "borrow_apy"]
        else:  # staking
            data = fetch_hourly_staking(bank_address, int(hours)) or []
            cols = ["staking_apy"]
        
        return records_to_dataframe(data, "time", cols)
        
    except Exception as e:
        st.warning(f"Error fetching {rate_type} data: {str(e)}")
        return pd.DataFrame(columns=["time"] + (["lend_apy", "borrow_apy"] if rate_type == "rates" else ["staking_apy"]))


def merge_dataframes_on_time(
    dataframes: List[pd.DataFrame], 
    time_col: str = "time",
    how: str = "inner",
    tolerance: Optional[pd.Timedelta] = None
) -> pd.DataFrame:
    """
    Merge multiple DataFrames on time column.
    
    Args:
        dataframes: List of DataFrames to merge
        time_col: Time column name
        how: Merge method ("inner", "outer", "left", "right")
        tolerance: Tolerance for merge_asof operations
        
    Returns:
        Merged DataFrame
    """
    if not dataframes:
        return pd.DataFrame()
    
    if len(dataframes) == 1:
        return dataframes[0]
    
    result = dataframes[0]
    
    for df in dataframes[1:]:
        if df.empty:
            continue
            
        if tolerance is not None:
            # Use merge_asof for time-tolerant merging
            result = pd.merge_asof(
                result.sort_values(time_col), 
                df.sort_values(time_col), 
                on=time_col, 
                direction="nearest", 
                tolerance=tolerance
            )
        else:
            # Use regular merge
            result = pd.merge(result, df, on=time_col, how=how)
    
    return result


def apply_growth_factors(
    df: pd.DataFrame, 
    rate_cols: List[str], 
    bucket_hours: float = 4.0
) -> pd.DataFrame:
    """
    Apply growth factors to rate columns for compounding calculations.
    
    Args:
        df: DataFrame with rate columns (as percentages)
        rate_cols: Column names containing rates
        bucket_hours: Hours per bucket for annualization
        
    Returns:
        DataFrame with additional growth factor columns
    """
    if df.empty:
        return df
    
    df_copy = df.copy()
    bucket_factor = bucket_hours / (365.0 * 24.0)
    
    for col in rate_cols:
        if col in df_copy.columns:
            growth_col = f"{col}_growth_factor"
            cum_growth_col = f"{col}_cum_growth"
            
            # Convert percentage to decimal and apply bucket factor
            df_copy[growth_col] = 1.0 + (df_copy[col].fillna(0.0) / 100.0) * bucket_factor
            df_copy[cum_growth_col] = df_copy[growth_col].cumprod().shift(1).fillna(1.0)
    
    return df_copy