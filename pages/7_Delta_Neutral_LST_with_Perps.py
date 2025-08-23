"""
Delta Neutral with LST and Perps

User allocates total capital (default $1,000):
 - 50% to buy LST in the wallet
 - 50% to short SOL on perps at 1x

Notes:
 - LST price already reflects staking yield; we show staking APY series for reference only
 - For perps short: positive funding → earn; negative funding → pay
 - Two charts: (1) Funding vs Staking APY; (2) Wallet LST USD vs Perps position USD
 - Metrics and a detailed breakdown table are displayed
"""

from typing import Dict, Any, List, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from config import get_token_config
from config.constants import DRIFT_MARKET_INDEX, ASSET_VARIANTS
from api.endpoints import (
    fetch_birdeye_history_price,
    fetch_hourly_staking,
    fetch_drift_funding_history,
)
from utils.dataframe_utils import aggregate_to_4h_buckets, compute_implied_apy, fetch_and_process_staking_series
from utils.delta_neutral_ui import display_perps_metrics, display_apy_chart, display_net_apy_chart, display_usd_values_chart, display_breakdown_table


def _load_lst_options(token_config: Dict[str, Any]) -> List[str]:
    # SOL variants that have staking yield flag in token_config
    sol_variants = ASSET_VARIANTS.get("SOL", [])
    options: List[str] = []
    for t in sol_variants:
        info = (token_config.get(t) or {})
        if info.get("hasStakingYield", False) and info.get("mint"):
            options.append(t)
    return options or sol_variants


def _fetch_funding_series(perps_exchange: str, lookback_hours: int) -> pd.DataFrame:
    # Reuse shared builder that honors arbitrary lookbacks (4H-centered APY % series)
    from data.spot_perps.spot_history import build_perps_history_series
    return build_perps_history_series(perps_exchange.strip(), "SOL", int(lookback_hours))


def _build_breakdown(
    price_df: pd.DataFrame,
    staking_df: pd.DataFrame,
    funding_df: pd.DataFrame,
    sol_price_df: pd.DataFrame,
    total_capital_usd: float,
    leverage: float,
) -> pd.DataFrame:
    # Capital split with leverage:
    # wallet_initial = total * L / (L + 1)
    # perps_capital_initial = total - wallet_initial
    # short notional (usd) = perps_capital_initial * L
    L = max(float(leverage), 1.0)
    wallet_usd = float(total_capital_usd) * L / (L + 1.0)
    perps_capital_initial = float(total_capital_usd) - wallet_usd
    perp_short_notional_usd = perps_capital_initial * L

    # Align series on 4H centered buckets using price times as the primary index
    base = price_df.copy()
    if base.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])

    # Merge nearest within tolerance
    merged = pd.merge_asof(
        base.sort_values("time"),
        staking_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    )
    merged = pd.merge_asof(
        merged.sort_values("time"),
        funding_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    )
    merged = pd.merge_asof(
        merged.sort_values("time"),
        sol_price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    )

    merged = merged.dropna(subset=["price"])  # require LST price
    if merged.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])

    # Initial LST tokens purchased with wallet_usd at first price
    first_price = float(pd.to_numeric(merged["price"], errors="coerce").dropna().iloc[0])
    lst_tokens = (wallet_usd / first_price) if first_price > 0 else 0.0

    # Require SOL price for perps mark-to-market PnL
    merged = merged.dropna(subset=["sol_price"])  # ensure SOL price available
    if merged.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])
    first_sol_price = float(pd.to_numeric(merged["sol_price"], errors="coerce").dropna().iloc[0]) if "sol_price" in merged.columns else float("nan")
    sol_size = (float(perp_short_notional_usd) / first_sol_price) if (first_sol_price and first_sol_price > 0) else 0.0  # short size in SOL

    # Compute per-bucket values
    out = merged.copy()
    out = out.rename(columns={"price": "lst_token_price"})
    out["lst_token_amount"] = float(lst_tokens)
    out["lst_token_amount_usd"] = out["lst_token_amount"] * out["lst_token_price"]

    # Perps: short at selected leverage; exposure equals perp_short_notional_usd; track funding + price PnL
    out["perp_sol_amount"] = float(sol_size)
    # Dynamic USD exposure of the SOL short leg
    out["perp_sol_amount_usd"] = out["perp_sol_amount"] * pd.to_numeric(out.get("sol_price", 0), errors="coerce").fillna(0.0)
    # funding_df is APY % (yearly)
    # For short: positive funding → earn, negative → pay
    bucket_factor = 4.0 / (365.0 * 24.0)
    out["perp_apy"] = pd.to_numeric(out.get("funding_pct", 0), errors="coerce").fillna(0.0)
    # Funding on notional exposure
    out["perp_interest"] = float(perp_short_notional_usd) * (out["perp_apy"] / 100.0) * bucket_factor
    # Funding interest accumulates as separate USD balance, not in position value
    out["perp_usd_accumulated"] = out["perp_interest"].cumsum()
    # Mark-to-market PnL for short: -size * (price - initial_price) = size * (initial - price)
    out["perp_pnl_price"] = float(sol_size) * (float(first_sol_price) - pd.to_numeric(out.get("sol_price", 0), errors="coerce").fillna(0.0))
    # Position value excludes funding interest; includes initial capital and price PnL
    out["perp_position_value"] = float(perps_capital_initial) + out["perp_pnl_price"]
    # Perp wallet value (includes funding accumulated)
    out["perp_wallet_value"] = out["perp_position_value"] + out["perp_usd_accumulated"]

    # Net value = wallet LST USD + perps position value
    out["net_value"] = out["lst_token_amount_usd"] + out["perp_position_value"] + out["perp_usd_accumulated"]

    # Keep required columns
    cols = [
        "time",
        "lst_token_amount",
        "lst_token_price",
        "lst_token_amount_usd",
        # capital allocation (constants per row)
        # included to aid debugging and transparency
        "wallet_initial_usd",
        "perp_capital_initial_usd",
        "perp_short_notional_usd",
        "perp_position_value",
        "perp_wallet_value",
        "sol_price",
        "perp_sol_amount",
        "perp_sol_amount_usd",
        "perp_apy",
        "perp_interest",
        "perp_usd_accumulated",
        "net_value",
    ]
    # Inject constant columns
    out["wallet_initial_usd"] = float(wallet_usd)
    out["perp_capital_initial_usd"] = float(perps_capital_initial)
    out["perp_short_notional_usd"] = float(perp_short_notional_usd)
    out = out[cols].copy()
    return out


def main():
    st.set_page_config(page_title="Delta Neutral LST + Perps", layout="wide")
    st.title("Delta Neutral with LST and Perps")
    st.caption("Capital split and short notional are driven by selected perps leverage. LST yield accrues via price; funding on perps applies to short notional.")

    token_config = get_token_config()
    lst_options = _load_lst_options(token_config)
    if not lst_options:
        st.info("No LST tokens available in configuration.")
        return

    # Controls
    col_a, col_b, col_c, col_d = st.columns([1, 1, 1, 1])
    with col_a:
        lst_symbol = st.selectbox("LST Token", lst_options, index=0)
    with col_b:
        perps_exchange = st.selectbox("Perps Exchange", ["Hyperliquid", "Drift"], index=0)
    with col_c:
        lookback_choice = st.selectbox("Time Period", ["1 week", "2 weeks", "1 month", "2 months", "3 months"], index=4)
        lookback_map = {"1 week": 168, "2 weeks": 336, "1 month": 720, "2 months": 1440, "3 months": 2160}
        lookback_hours = int(lookback_map.get(lookback_choice, 2160))
    with col_d:
        total_capital = st.number_input("Total Capital (USD)", min_value=0.0, value=1000.0, step=100.0)
    leverage = st.slider("Perps leverage", min_value=1.0, max_value=5.0, value=2.0, step=0.5)

    # Data - using existing utilities
    with st.spinner("Loading series..."):
        try:
            # Get time range
            end_ts = pd.Timestamp.utcnow()
            start_ts = end_ts - pd.Timedelta(hours=int(lookback_hours))
            start = int(start_ts.timestamp())
            end = int(end_ts.timestamp())
            
            # LST price using existing API
            info = token_config.get(lst_symbol, {}) or {}
            lst_mint = info.get("mint")
            if lst_mint:
                price_points = fetch_birdeye_history_price(lst_mint, start, end, bucket="4H") or []
                lst_price_df = pd.DataFrame(price_points)
                if not lst_price_df.empty:
                    lst_price_df["time"] = pd.to_datetime(lst_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
                    lst_price_df = lst_price_df.sort_values("time")[["time", "price"]]
                else:
                    lst_price_df = pd.DataFrame(columns=["time", "price"])
            else:
                lst_price_df = pd.DataFrame(columns=["time", "price"])
                
            # LST staking series using shared helper
            lst_staking_df = fetch_and_process_staking_series(token_config, lst_symbol, lookback_hours)
                
            # SOL price using existing API
            sol_mint = (token_config.get("SOL", {}) or {}).get("mint")
            if sol_mint:
                sol_points = fetch_birdeye_history_price(sol_mint, start, end, bucket="4H") or []
                sol_price_df = pd.DataFrame(sol_points)
                if not sol_price_df.empty:
                    sol_price_df["time"] = pd.to_datetime(sol_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
                    sol_price_df = sol_price_df.sort_values("time")[["time", "price"]].rename(columns={"price": "sol_price"})
                else:
                    sol_price_df = pd.DataFrame(columns=["time", "sol_price"])
            else:
                sol_price_df = pd.DataFrame(columns=["time", "sol_price"])
                
            # Funding series using existing builder
            funding_df = _fetch_funding_series(perps_exchange, lookback_hours)
            
        except Exception as e:
            st.error(f"Failed to load historical series: {e}")
            if st.button("Retry loading data"):
                st.rerun()
            return

    if lst_price_df.empty or funding_df.empty or sol_price_df.empty:
        st.warning("Required data is currently unavailable.")
        if st.button("Retry loading data"):
            st.rerun()
        return

    # Build breakdown series
    series = _build_breakdown(lst_price_df, lst_staking_df, funding_df, sol_price_df, float(total_capital), float(leverage))
    if series.empty:
        st.info("No aligned data available for the selected options.")
        return

    # Metrics (moved above charts)
    first_row = series.head(1)
    last_row = series.tail(1)
    lst_usd_start = float(first_row["lst_token_amount_usd"].iloc[0]) if not first_row.empty else 0.0
    lst_usd_now = float(last_row["lst_token_amount_usd"].iloc[0]) if not last_row.empty else 0.0
    perp_pos_start = float(first_row["perp_position_value"].iloc[0]) if not first_row.empty else (float(total_capital) / 2.0)
    perp_pos_now = float(last_row["perp_position_value"].iloc[0]) if not last_row.empty else perp_pos_start
    perp_sol_usd_start = float(first_row["perp_sol_amount_usd"].iloc[0]) if not first_row.empty else (float(total_capital) / 2.0)

    net_now = float(last_row["net_value"].iloc[0]) if not last_row.empty else float(total_capital)
    profit_usd = net_now - float(total_capital)
    total_hours = max(len(series), 0) * 4.0
    implied_apy = compute_implied_apy(profit_usd, float(total_capital), total_hours)

    display_perps_metrics(
        profit_usd=profit_usd,
        total_capital=float(total_capital),
        implied_apy=implied_apy,
        lst_symbol=lst_symbol,
        lst_usd_start=lst_usd_start,
        lst_usd_now=lst_usd_now,
        perp_notional_start=perp_sol_usd_start,
        perp_position_start=perp_pos_start,
        perp_position_now=perp_pos_now
    )

    # Charts
    df_apys = pd.merge_asof(
        funding_df.sort_values("time"),
        lst_staking_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    )
    # Only keep periods where staking data is available
    df_apys = df_apys.dropna(subset=["funding_pct", "staking_pct"])  # require both present
    if df_apys.empty:
        st.info("Staking data is not available for the selected period.")
    else:
        display_apy_chart(
            time_series=df_apys["time"],
            long_apy_series=df_apys["staking_pct"],
            short_apy_series=-df_apys["funding_pct"],  # Note: funding already includes sign
            short_label="Short Side APY (%)"
        )

        # Net APY over time (weighted by initial capital allocation ratios)
        L = max(float(leverage), 1.0)
        wallet_usd = float(total_capital) * L / (L + 1.0)
        perp_capital_initial = float(total_capital) - wallet_usd
        perp_short_notional_usd = perp_capital_initial * L
        wallet_ratio = wallet_usd / float(total_capital) if float(total_capital) > 0 else 0.0
        short_exposure_ratio = perp_short_notional_usd / float(total_capital) if float(total_capital) > 0 else 0.0

        df_apys["net_apy_pct"] = (
            df_apys["staking_pct"].fillna(0.0) * wallet_ratio
            + df_apys["funding_pct"].fillna(0.0) * short_exposure_ratio
        )
        
        display_net_apy_chart(
            time_series=df_apys["time"],
            net_apy_series=df_apys["net_apy_pct"]
        )

    # USD Values Over Time (hidden by default)
    display_usd_values_chart(
        time_series=series["time"],
        wallet_usd_series=series["lst_token_amount_usd"],
        position_usd_series=series["perp_wallet_value"],
        wallet_label="LST wallet (USD)",
        position_label="Perp wallet (USD)",
        additional_series={"Portfolio total (USD)": series["net_value"]}
    )

    # Metrics moved above

    # Breakdown table
    st.subheader("Breakdown")
    tbl = series.copy()
    tbl = tbl.rename(columns={
        "lst_token_amount": "LST tokens",
        "lst_token_price": "LST price (USD)",
        "lst_token_amount_usd": "LST wallet (USD)",
        "wallet_initial_usd": "Wallet initial (USD)",
        "perp_capital_initial_usd": "Perp capital initial (USD)",
        "perp_short_notional_usd": "Perp notional (start, USD)",
        "perp_position_value": "Perp position (MTM, USD)",
        "perp_wallet_value": "Perp wallet (USD)",
        "sol_price": "SOL price (USD)",
        "perp_sol_amount": "Perp size (SOL)",
        "perp_sol_amount_usd": "Perp notional (current, USD)",
        "perp_apy": "Perp funding APY (%)",
        "perp_interest": "Perp funding (4h, USD)",
        "perp_usd_accumulated": "Perp funding (cum, USD)",
        "net_value": "Portfolio total (USD)",
    })
    # Round for display
    tbl = tbl.round({
        "LST price (USD)": 6,
        "LST wallet (USD)": 2,
        "Perp wallet (USD)": 2,
        "SOL price (USD)": 6,
        "Perp funding (4h, USD)": 2,
        "Perp funding (cum, USD)": 2,
        "Portfolio total (USD)": 2,
    })
    display_breakdown_table(
        tbl[[
            "time",
            "LST price (USD)",
            "LST wallet (USD)",
            "Perp wallet (USD)",
            "SOL price (USD)",
            "Perp funding (4h, USD)",
            "Perp funding (cum, USD)",
            "Portfolio total (USD)",
        ]]
    )


if __name__ == "__main__":
    main()


