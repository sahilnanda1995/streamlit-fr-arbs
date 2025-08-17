from typing import List, Dict, Any, Tuple

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from api.endpoints import (
    fetch_hyperliquid_funding_history,
    fetch_drift_funding_history,
)
from config.constants import DEFAULT_TARGET_HOURS, DRIFT_MARKET_INDEX
from utils.formatting import scale_funding_rate_to_percentage


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
    coins = ["BTC", "SOL", "ETH"]
    coin = st.selectbox("Select coin", options=coins, index=1 if "BTC" in coins else 0)

    # Hyperliquid
    st.markdown("**Hyperliquid**")
    with st.spinner("Loading Hyperliquid funding history..."):
        hl_history = _fetch_last_month_with_gap_check(coin)
    hl_df = _to_dataframe(hl_history, rate_key="fundingRate")
    if hl_df.empty:
        st.info("No Hyperliquid funding history available for the selected period.")
    else:
        st.line_chart(hl_df.set_index("time")["fundingRate"], height=260)
        st.caption("Funding Rate shown as APY (%) over the past 1 month")
        with st.expander("Show raw Hyperliquid funding history"):
            st.json(hl_history)

    st.divider()

    # Drift
    st.markdown("**Drift**")
    market_index = DRIFT_MARKET_INDEX.get(coin, DRIFT_MARKET_INDEX.get("BTC", 1))
    end_time = round(datetime.now().timestamp(), 3)
    start_time = round(end_time - (30 * 24 * 3600), 3)
    with st.spinner("Loading Drift funding history..."):
        drift_history = fetch_drift_funding_history(market_index, start_time, end_time)
    drift_df = _to_dataframe(drift_history, rate_key="fundingRate")
    if drift_df.empty:
        st.info("No Drift funding history available for the selected period.")
    else:
        st.line_chart(drift_df.set_index("time")["fundingRate"], height=260)
        st.caption("Funding Rate shown as APY (%) over the past 1 month")
        with st.expander("Show raw Drift funding history"):
            st.json(drift_history)


