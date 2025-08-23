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
from data.spot_perps.backtesting import _to_dataframe, _get_last_month_window_seconds


def _agg_4h(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    d["time_4h"] = pd.to_datetime(d["time"]).dt.floor("4h")
    d = (
        d.groupby("time_4h", as_index=False)[cols].mean()
        .assign(time=lambda x: pd.to_datetime(x["time_4h"]) + pd.Timedelta(hours=2))
        .drop(columns=["time_4h"])
    )
    return d


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
    # Build funding history for SOL as APY (%) time series
    perps_exchange = perps_exchange.strip()
    if perps_exchange == "Hyperliquid":
        # Use helper that paginates up to ~1 month; then restrict to lookback
        from data.spot_perps.backtesting import _fetch_last_month_with_gap_check
        entries = _fetch_last_month_with_gap_check("SOL")
        df = _to_dataframe(entries, rate_key="fundingRate")  # APY % over 1y
        if df.empty:
            return df
        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(hours=int(lookback_hours))
        df = df[df["time"] >= cutoff.tz_localize(None)]
        return _agg_4h(df, ["fundingRate"]).rename(columns={"fundingRate": "funding_pct"})
    else:
        # Drift
        start_sec, end_sec = _get_last_month_window_seconds()
        # Trim to requested lookback
        end_ts = pd.Timestamp.utcnow()
        start_ts = end_ts - pd.Timedelta(hours=int(lookback_hours))
        start_f = max(start_sec, round(start_ts.timestamp(), 3))
        end_f = min(end_sec, round(end_ts.timestamp(), 3))
        idx = DRIFT_MARKET_INDEX.get("SOL", 0)
        entries = fetch_drift_funding_history(idx, start_f, end_f)
        df = _to_dataframe(entries, rate_key="fundingRate")  # APY %
        if df.empty:
            return df
        return _agg_4h(df, ["fundingRate"]).rename(columns={"fundingRate": "funding_pct"})


def _fetch_lst_price_and_staking(token_config: Dict[str, Any], lst_symbol: str, lookback_hours: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    info = token_config.get(lst_symbol, {}) or {}
    lst_mint = info.get("mint")
    if not lst_mint:
        return pd.DataFrame(columns=["time", "price"]), pd.DataFrame(columns=["time", "staking_pct"])

    end_ts = pd.Timestamp.utcnow()
    start_ts = end_ts - pd.Timedelta(hours=int(lookback_hours))
    start = int(start_ts.timestamp())
    end = int(end_ts.timestamp())

    # Price series from Birdeye (4H)
    try:
        price_points = fetch_birdeye_history_price(lst_mint, start, end, bucket="4H") or []
    except Exception:
        price_points = []
    price_df = pd.DataFrame(price_points)
    if not price_df.empty:
        price_df["time"] = pd.to_datetime(price_df["t"], unit="s", utc=True).dt.tz_convert(None)
        price_df = price_df.sort_values("time")[ ["time", "price" ] ]
    else:
        price_df = pd.DataFrame(columns=["time", "price"])

    # Staking APY hourly, convert to % and aggregate to 4H
    try:
        staking_raw = fetch_hourly_staking(info.get("mint"), int(lookback_hours)) if info.get("hasStakingYield") else []
    except Exception:
        staking_raw = []
    if staking_raw:
        d = pd.DataFrame(staking_raw)
        d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
        d["staking_pct"] = pd.to_numeric(d.get("avgApy", 0), errors="coerce") * 100.0
        staking_df = _agg_4h(d[["time", "staking_pct"]], ["staking_pct"])
    else:
        staking_df = pd.DataFrame(columns=["time", "staking_pct"])

    return price_df, staking_df


def _fetch_sol_price(token_config: Dict[str, Any], lookback_hours: int) -> pd.DataFrame:
    sol_mint = (token_config.get("SOL", {}) or {}).get("mint")
    if not sol_mint:
        return pd.DataFrame(columns=["time", "sol_price"])
    end_ts = pd.Timestamp.utcnow()
    start_ts = end_ts - pd.Timedelta(hours=int(lookback_hours))
    start = int(start_ts.timestamp())
    end = int(end_ts.timestamp())
    try:
        points = fetch_birdeye_history_price(sol_mint, start, end, bucket="4H") or []
    except Exception:
        points = []
    df = pd.DataFrame(points)
    if df.empty:
        return pd.DataFrame(columns=["time", "sol_price"])
    df["time"] = pd.to_datetime(df["t"], unit="s", utc=True).dt.tz_convert(None)
    df = df.sort_values("time")[ ["time", "price" ] ].rename(columns={"price": "sol_price"})
    return df


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
        lookback_choice = st.selectbox("Time Period", ["1 week", "2 weeks", "1 month"], index=2)
        lookback_map = {"1 week": 168, "2 weeks": 336, "1 month": 720}
        lookback_hours = int(lookback_map.get(lookback_choice, 720))
    with col_d:
        total_capital = st.number_input("Total Capital (USD)", min_value=0.0, value=1000.0, step=100.0)
    leverage = st.slider("Perps leverage", min_value=1.0, max_value=5.0, value=2.0, step=0.5)

    # Data
    with st.spinner("Loading series..."):
        try:
            lst_price_df, lst_staking_df = _fetch_lst_price_and_staking(token_config, lst_symbol, lookback_hours)
            funding_df = _fetch_funding_series(perps_exchange, lookback_hours)
            sol_price_df = _fetch_sol_price(token_config, lookback_hours)
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

    # Charts
    st.subheader("Funding vs Staking APY")
    df_apys = pd.merge_asof(
        funding_df.sort_values("time"),
        lst_staking_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    ).dropna(subset=["funding_pct"])  # staking may be NaN
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=df_apys["time"], y=df_apys["funding_pct"], name=f"{perps_exchange} Funding %", mode="lines"))
    if "staking_pct" in df_apys.columns:
        fig1.add_trace(go.Scatter(x=df_apys["time"], y=df_apys["staking_pct"], name=f"{lst_symbol} Staking %", mode="lines"))
    fig1.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig1, use_container_width=True)

    st.subheader("USD Values Over Time")
    fig2 = go.Figure()
    # Wallet USD value (LST leg)
    fig2.add_trace(go.Scatter(x=series["time"], y=series["lst_token_amount_usd"], name="LST wallet (USD)", mode="lines"))
    # Perp wallet USD (perp position + funding accumulation)
    fig2.add_trace(go.Scatter(x=series["time"], y=series["perp_wallet_value"], name="Perp wallet (USD)", mode="lines"))
    # Net USD value
    fig2.add_trace(go.Scatter(x=series["time"], y=series["net_value"], name="Portfolio total (USD)", mode="lines", line=dict(color="#16a34a")))
    fig2.update_layout(height=320, hovermode="x unified", yaxis_title="USD ($)", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig2, use_container_width=True)

    # Metrics
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
    implied_apy = ((profit_usd / float(total_capital)) / (total_hours / (365.0 * 24.0)) * 100.0) if (float(total_capital) > 0 and total_hours > 0) else 0.0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("ROE (USD)", f"${profit_usd:,.2f}", delta=f"{(profit_usd/float(total_capital)*100.0):+.2f}%")
    with c2:
        st.metric("Implied APY", f"{implied_apy:.2f}%")
    with c3:
        st.metric(f"{lst_symbol} wallet start (USD)", f"${lst_usd_start:,.2f}")
    with c4:
        st.metric(f"{lst_symbol} wallet now (USD)", f"${lst_usd_now:,.2f}")

    d1, d2, d3 = st.columns(3)
    with d1:
        st.metric("Perp notional start (USD)", f"${perp_sol_usd_start:,.2f}")
    with d2:
        st.metric("Perp position MTM start (USD)", f"${perp_pos_start:,.2f}")
    with d3:
        st.metric("Perp position MTM now (USD)", f"${perp_pos_now:,.2f}")

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
    show_tbl = st.checkbox("Show breakdown table", value=True)
    if show_tbl:
        st.dataframe(
            tbl[[
                "time",
                "LST price (USD)",
                "LST wallet (USD)",
                "Perp wallet (USD)",
                "SOL price (USD)",
                "Perp funding (4h, USD)",
                "Perp funding (cum, USD)",
                "Portfolio total (USD)",
            ]],
            use_container_width=True,
            hide_index=True,
        )


if __name__ == "__main__":
    main()


