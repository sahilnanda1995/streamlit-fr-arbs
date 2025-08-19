from typing import Tuple

import pandas as pd


def prepare_display_series(series_df: pd.DataFrame, dir_lower: str) -> pd.DataFrame:
    """
    Prepare display-only columns for plotting while leaving original data unchanged.
    - spot_rate_pct_display: negative of spot_rate_pct
    - net_arb_pct_display: negative of net_arb_pct
    - funding_pct_display: funding_pct (long) or negative (short)
    """
    df_plot = series_df.copy()
    df_plot["time"] = pd.to_datetime(df_plot["time"])  # ensure dtype
    df_plot["spot_rate_pct_display"] = -df_plot["spot_rate_pct"]
    df_plot["net_arb_pct_display"] = -df_plot["net_arb_pct"]
    df_plot["funding_pct_display"] = df_plot["funding_pct"] if dir_lower == "long" else -df_plot["funding_pct"]
    return df_plot


def compute_earnings_and_implied_apy(
    df_plot: pd.DataFrame,
    dir_lower: str,
    total_cap: float,
    leverage: float,
) -> Tuple[pd.DataFrame, float, float, float]:
    """
    Compute per-bucket earnings and implied APY using the same semantics as backtesting.
    Returns (df_calc, spot_cap, perps_cap, implied_apy).
    """
    # Match existing backtesting allocation, with perps notional adjusted for short direction
    spot_cap = total_cap / 2
    if dir_lower == "short":
        perps_cap = total_cap / 2 * max(0.0, float(leverage) - 1.0)
    else:
        perps_cap = total_cap / 2 * float(leverage)

    # 4h as fraction of a year
    bucket_factor = 4.0 / (365.0 * 24.0)

    df_calc = df_plot.copy()
    # Keep original values for all calculations; display-only columns are already present
    # Spot: negative rate => interest earned, positive => paid
    df_calc["spot_interest_usd"] = - spot_cap * (df_calc["spot_rate_pct"] / 100.0) * bucket_factor
    # Perps funding: long +1, short -1
    fund_sign = 1.0 if dir_lower == "long" else -1.0
    df_calc["funding_interest_usd"] = perps_cap * fund_sign * (df_calc["funding_pct"] / 100.0) * bucket_factor
    df_calc["total_interest_usd"] = df_calc["spot_interest_usd"] + df_calc["funding_interest_usd"]
    # Capital deployed columns (constant per bucket)
    df_calc["spot_capital_usd"] = float(spot_cap)
    df_calc["perps_capital_usd"] = float(perps_cap)

    # Implied APY
    total_hours = len(df_calc) * 4.0
    deployed_notional = total_cap
    implied_apy = 0.0
    if deployed_notional > 0 and total_hours > 0:
        implied_apy = (
            df_calc["total_interest_usd"].sum()
            / (deployed_notional * (total_hours / (365.0 * 24.0)))
        ) * 100.0

    return df_calc, spot_cap, perps_cap, implied_apy


def build_breakdown_table_df(df_calc: pd.DataFrame, dir_lower: str) -> pd.DataFrame:
    """
    Build the breakdown table DataFrame with display-only inversions applied,
    matching the existing backtesting table behavior.
    """
    tbl = df_calc[[
        "time",
        "spot_rate_pct",
        "funding_pct",
        "net_arb_pct",
        "spot_capital_usd",
        "perps_capital_usd",
        "spot_interest_usd",
        "funding_interest_usd",
        "total_interest_usd",
    ]].copy()
    # Display-only adjustments
    tbl["spot_rate_pct"] = -tbl["spot_rate_pct"]
    tbl["net_arb_pct"] = -tbl["net_arb_pct"]
    tbl["funding_pct"] = df_calc["funding_pct_display"].values
    # Rounding as in existing backtesting
    tbl = tbl.round({
        "spot_rate_pct": 3,
        "funding_pct": 3,
        "net_arb_pct": 3,
        "spot_capital_usd": 2,
        "perps_capital_usd": 2,
        "spot_interest_usd": 2,
        "funding_interest_usd": 2,
        "total_interest_usd": 2,
    })
    return tbl


def style_breakdown_table(tbl: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """
    Apply the same styling/formatting as backtesting for display in Streamlit.
    """
    def _style_series(s: pd.Series):
        col = s.name
        styles = []
        for v in s:
            if pd.isna(v):
                styles.append("")
            else:
                if col == "spot_interest_usd":
                    styles.append("color: #16a34a" if v > 0 else ("color: #dc2626" if v < 0 else ""))
                else:
                    styles.append("color: #16a34a" if v > 0 else ("color: #dc2626" if v < 0 else ""))
        return styles

    percent_format = {
        "spot_rate_pct": "{:.2f}%",
        "funding_pct": "{:.2f}%",
        "net_arb_pct": "{:.2f}%",
    }

    styled = (
        tbl.style
        .format(percent_format)
        .apply(_style_series, subset=["spot_interest_usd"])
        .apply(_style_series, subset=["funding_interest_usd"])
        .apply(_style_series, subset=["total_interest_usd"])
    )
    return styled


