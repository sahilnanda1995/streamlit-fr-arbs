from typing import List, Dict, Any, Optional

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from api.endpoints import (
    fetch_hyperliquid_funding_history,
    fetch_drift_funding_history,
)
from config.constants import (
    DEFAULT_TARGET_HOURS,
    DRIFT_MARKET_INDEX,
    BACKTEST_COINS,
    BACKTEST_CAPTION,
)
from utils.formatting import scale_funding_rate_to_percentage
from .helpers import get_matching_usdc_bank, get_protocol_market_pairs
from .spot_history import build_spot_history_series, build_arb_history_series
from .backtesting_utils import (
    prepare_display_series,
    compute_earnings_and_implied_apy,
    build_breakdown_table_df,
    style_breakdown_table,
)



def _now_ms() -> int:
    return int(time.time() * 1000)


def _one_month_ago_ms(now_ms: int) -> int:
    dt_now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    dt_prev = dt_now - timedelta(days=30)
    return int(dt_prev.timestamp() * 1000)


def _latest_time_ms(entries: List[Dict[str, Any]]) -> int:
    if not entries:
        return 0
    try:
        return max(int(e.get("time", 0)) for e in entries)
    except Exception:
        return 0


def _to_dataframe(entries: List[Dict[str, Any]], rate_key: str = "fundingRate") -> pd.DataFrame:
    if not entries:
        return pd.DataFrame(columns=["time", rate_key])
    df = pd.DataFrame(entries)
    # Convert numeric strings to floats
    if rate_key in df.columns:
        df[rate_key] = pd.to_numeric(df[rate_key], errors="coerce")
    if "premium" in df.columns:
        df["premium"] = pd.to_numeric(df["premium"], errors="coerce")
    # Convert ms to datetime
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(None)
    df = df.sort_values("time")
    # Convert hourly decimal funding rate to yearly APY percentage via shared helper
    df[rate_key] = scale_funding_rate_to_percentage(df[rate_key], 1, DEFAULT_TARGET_HOURS)
    return df


def _get_last_month_window_seconds() -> (float, float):
    end = round(datetime.now().timestamp(), 3)
    start = round(end - (30 * 24 * 3600), 3)
    return start, end


def _render_backtest_chart(title: str, entries: List[Dict[str, Any]], rate_key: str = "fundingRate") -> None:
    st.markdown(f"**{title}**")
    df = _to_dataframe(entries, rate_key=rate_key)
    if df.empty:
        st.info(f"No {title} funding history available for the selected period.")
        return
    st.line_chart(df.set_index("time")[rate_key].round(3), height=260)
    st.caption(BACKTEST_CAPTION)
    with st.expander(f"Show raw {title} funding history"):
        st.json(entries)


def _fetch_last_month_with_gap_check(coin: str) -> List[Dict[str, Any]]:
    """
    Fetch up to the last month of funding history. Because the API limits
    the number of points, we paginate by repeatedly advancing startTime to
    the last received timestamp until the latest point is within 4 hours of now
    or no new data is returned.
    """
    now_ms = _now_ms()
    four_hours_ms = 4 * 60 * 60 * 1000
    start_ms = _one_month_ago_ms(now_ms)

    all_entries: List[Dict[str, Any]] = []
    seen_times: set = set()
    next_start = start_ms

    for _ in range(12):  # safety cap on pagination depth
        page = fetch_hyperliquid_funding_history(coin=coin, start_time_ms=next_start)
        if not page:
            break

        new_added = 0
        for e in page:
            t = int(e.get("time", 0))
            if t and t not in seen_times:
                all_entries.append(e)
                seen_times.add(t)
                new_added += 1

        latest_ms = _latest_time_ms(all_entries)
        if latest_ms and (now_ms - latest_ms) <= four_hours_ms:
            break
        if new_added == 0:
            break
        # Advance start to the last seen point + 1ms to avoid duplicate
        next_start = latest_ms + 1 if latest_ms else next_start

    # Ensure chronological order
    all_entries.sort(key=lambda e: e.get("time", 0))
    return all_entries


def display_backtesting_section(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    strategies_by_roe: Optional[List[Dict[str, Any]]] = None,
) -> None:
    st.subheader("🧪 Backtesting (1M)")

    # Controls

    # Historical perps charts moved to Funding Rates page
    st.caption("Perps historical charts are available on the Funding Rates page.")

    # Spot Rate History (derived from curated strategies)
    st.subheader("📈 Spot Rate History (Hourly)")
    if not strategies_by_roe or len(strategies_by_roe) == 0:
        st.info("No strategies available to backtest. Please select filters above or ensure curated section loaded.")
        return
    row_sel_1, row_sel_3 = st.columns([3, 1])
    # Controls: Strategy to backtest | Time Period

    # Use curated-provided strategies only

    with row_sel_1:
        labels = [s.get("label", "") for s in strategies_by_roe]
        selected_idx = st.selectbox(
            "Strategy to backtest",
            options=list(range(len(labels))),
            format_func=lambda i: labels[i],
            key="spot_hist_strategy",
        )
    with row_sel_3:
        lookback_options = [("1 week", 168), ("2 weeks", 336), ("1 month", 720)]
        lookback_labels = [label for label, _ in lookback_options]
        selected_lookback = st.selectbox("Time Period", lookback_labels, index=2, key="spot_hist_limit")
        sh_limit = dict(lookback_options).get(selected_lookback, 720)

    choice = strategies_by_roe[selected_idx]
    direction = choice["direction"].title()
    dir_lower = choice["direction"]
    proto = choice["protocol"]
    market = choice["market"]
    variant = choice["variant"]
    lev = float(choice.get("leverage", 2))
    perps_exchange = choice.get("perps_exchange", "Hyperliquid")

    st.caption(f"Using: {variant} • {proto} ({market}) • {direction} • {lev}x • Perps: {perps_exchange}")

    with st.spinner("Loading historical series..."):
        series_df = build_arb_history_series(
            token_config, variant, proto, market, dir_lower, lev, perps_exchange, int(sh_limit)
        )
    if series_df.empty:
        st.info("No historical data available for the selection.")
    else:
        import plotly.graph_objects as go
        df_plot = prepare_display_series(series_df, dir_lower)

        # Chart 1: Spot vs FR APY
        st.markdown("**Spot vs FR APY**")
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["spot_rate_pct_display"], name="Spot %", mode="lines"))
        fig1.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["funding_pct_display"], name="Perps %", mode="lines"))
        fig1.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig1, use_container_width=True)
        st.caption("Series: Spot Rate (APY%), Perps Funding (APY%) per 4 hours")

        # Chart 2: Net yield
        st.markdown("**Net yield**")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["net_arb_pct_display"], name="Net Arb %", mode="lines", line=dict(color="#16a34a")))
        fig2.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig2, use_container_width=True)
        st.caption("Series: Net Arb (APY%) per 4 hours")

        st.subheader("💰 Earnings Calculator")
        total_cap = st.number_input("Total capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key="earn_total_cap")
        df_calc, spot_cap, perps_cap, implied_apy = compute_earnings_and_implied_apy(df_plot, dir_lower, total_cap, lev)

        # ROE over selected time period (first metric): Profit and Profit %
        profit_usd = float(df_calc["total_interest_usd"].sum())
        roe_pct = (profit_usd / total_cap * 100.0) if total_cap > 0 else 0.0
        roe_label = f"ROE ({selected_lookback})"

        col_roe, col_a, col_b, col_c = st.columns(4)
        with col_roe:
            st.metric(roe_label, f"${profit_usd:,.2f}", delta=f"{roe_pct:.2f}%")
        with col_a:
            st.metric("Total APY (implied)", f"{implied_apy:.2f}%")
        with col_b:
            st.metric("Funding interest (sum)", f"${df_calc['funding_interest_usd'].sum():,.2f}")
        with col_c:
            st.metric("Spot interest (sum)", f"${df_calc['spot_interest_usd'].sum():,.2f}")

        st.markdown("**Breakdown**")
        # Build and style breakdown table using shared helpers
        tbl = build_breakdown_table_df(df_calc, dir_lower)
        styled_tbl = style_breakdown_table(tbl)
        st.dataframe(styled_tbl, use_container_width=True, hide_index=True)


