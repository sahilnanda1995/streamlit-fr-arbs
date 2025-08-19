from typing import List, Dict, Any

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
from .curated import find_best_spot_rate_across_leverages
from config.constants import SPOT_PERPS_CONFIG


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
) -> None:
    st.subheader("🧪 Backtesting (1M)")

    # Controls

    # Historical perps charts moved to Funding Rates page
    st.caption("Perps historical charts are available on the Funding Rates page.")

    # Spot Rate History (derived from best Asgard Spot vs Perps config)
    st.subheader("📈 Spot Rate History (Hourly)")
    row_sel_1, row_sel_2, row_sel_3 = st.columns([2, 1, 1])
    # Fill the controls after building strategy options, in order:
    # Strategy to backtest | Perps Exchange | Time Period

    # Build strategy choices from best configs per asset/direction
    strategy_options: List[Dict[str, Any]] = []
    for asset_type in ["SOL", "BTC"]:
        for dir_lower in ["long", "short"]:
            variants = SPOT_PERPS_CONFIG["SOL_ASSETS"] if asset_type == "SOL" else SPOT_PERPS_CONFIG["BTC_ASSETS"]
            best = find_best_spot_rate_across_leverages(
                token_config, rates_data, staking_data,
                variants, dir_lower, DEFAULT_TARGET_HOURS, max_leverage=5,
                logger=None,
            )
            if not best:
                continue
            label = f"{best['variant']}/USDC at {float(best['leverage']):.1f}x"
            strategy_options.append({
                "label": label,
                "asset_type": asset_type,
                "direction": dir_lower,
                "best": best,
            })

    if not strategy_options:
        st.info("No valid strategies available to backtest.")
        return

    with row_sel_1:
        selected_idx = st.selectbox(
            "Strategy to backtest",
            options=list(range(len(strategy_options))),
            format_func=lambda i: strategy_options[i]["label"],
            key="spot_hist_strategy",
        )
    with row_sel_2:
        perps_exchange = st.selectbox("Perps Exchange", ["Hyperliquid", "Drift"], index=0, key="spot_hist_perps")
    with row_sel_3:
        lookback_options = [("1 week", 168), ("2 weeks", 336), ("1 month", 720)]
        lookback_labels = [label for label, _ in lookback_options]
        selected_lookback = st.selectbox("Time Period", lookback_labels, index=2, key="spot_hist_limit")
        sh_limit = dict(lookback_options).get(selected_lookback, 720)

    choice = strategy_options[selected_idx]
    best = choice["best"]
    direction = choice["direction"].title()
    dir_lower = choice["direction"]
    proto_market = best.get("protocol", "")
    if "(" in proto_market and ")" in proto_market:
        proto = proto_market.split("(")[0]
        market = proto_market.split("(")[1].split(")")[0]
    else:
        proto = proto_market
        market = ""
    variant = best.get("variant")
    lev = float(best.get("leverage", 2))

    st.caption(f"Using: {variant} • {proto} ({market}) • {direction} • {lev}x")

    with st.spinner("Loading historical series..."):
        series_df = build_arb_history_series(
            token_config, variant, proto, market, dir_lower, lev, perps_exchange, int(sh_limit)
        )
    if series_df.empty:
        st.info("No historical data available for the selection.")
    else:
        import plotly.graph_objects as go
        df_plot = prepare_display_series(series_df, dir_lower)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["spot_rate_pct_display"], name="Spot %", mode="lines"))
        fig.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["funding_pct_display"], name="Perps %", mode="lines"))
        fig.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["net_arb_pct_display"], name="Net Arb %", mode="lines", line=dict(color="#16a34a")))
        fig.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Series: Spot Rate (APY%), Perps Funding (APY%), Net Arb (APY%) per 4 hours")

        st.subheader("💰 Earnings Calculator")
        total_cap = st.number_input("Total capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key="earn_total_cap")
        df_calc, spot_cap, perps_cap, implied_apy = compute_earnings_and_implied_apy(df_plot, dir_lower, total_cap, lev)

        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            st.metric("Spot interest (sum)", f"${df_calc['spot_interest_usd'].sum():,.2f}")
        with col_b:
            st.metric("Funding interest (sum)", f"${df_calc['funding_interest_usd'].sum():,.2f}")
        with col_c:
            st.metric("Total interest (sum)", f"${df_calc['total_interest_usd'].sum():,.2f}")
        with col_d:
            st.metric("Total APY (implied)", f"{implied_apy:.2f}%")

        st.markdown("**Breakdown**")
        # Build and style breakdown table using shared helpers
        tbl = build_breakdown_table_df(df_calc, dir_lower)
        styled_tbl = style_breakdown_table(tbl)
        st.dataframe(styled_tbl, use_container_width=True, hide_index=True)


