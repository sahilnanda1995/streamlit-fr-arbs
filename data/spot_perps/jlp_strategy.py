from typing import Optional, Tuple, List, Dict, Any

import pandas as pd
import streamlit as st

from .helpers import compute_effective_max_leverage, get_protocol_market_pairs
from .spot_history import build_spot_history_series
from api.endpoints import fetch_hourly_rates, fetch_birdeye_history_price
import time


def _find_isolated_jlp_pair_banks(token_config: dict, protocol: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Locate the JLP and USDC bank addresses for the given protocol in the
    "Isolated JLP Market" as defined in token_config.
    Returns (jlp_bank, usdc_bank) or (None, None) if not found.
    """
    market_name = "Isolated JLP Market"

    # Find JLP bank
    jlp_bank = None
    for p, m, bank in get_protocol_market_pairs(token_config, "JLP"):
        if p == protocol and m == market_name:
            jlp_bank = bank
            break

    # Find USDC bank for the same protocol/market
    usdc_bank = None
    for p, m, bank in get_protocol_market_pairs(token_config, "USDC"):
        if p == protocol and m == market_name:
            usdc_bank = bank
            break

    return jlp_bank, usdc_bank


def display_jlp_strategy_section(token_config: dict) -> None:
    """
    Render the "JLP strategy" section showing historical spot APY% for the
    JLP/USDC long strategy in the Isolated JLP Market.
    """
    st.subheader("JLP strategy")

    # Controls
    col_a, col_b, col_c = st.columns([1, 1, 1])
    with col_a:
        protocol = st.selectbox("Protocol", ["kamino", "drift"], index=0, key="jlp_proto")
    with col_b:
        # Extend to 2 months (1440 hours) and default to 2 months
        points = st.selectbox("Points (hours)", [168, 336, 720, 1440], index=3, key="jlp_points")

    # Resolve banks and effective leverage cap for long direction
    jlp_bank, usdc_bank = _find_isolated_jlp_pair_banks(token_config, protocol)
    eff_max = 1.0
    if jlp_bank and usdc_bank:
        eff_max = compute_effective_max_leverage(token_config, jlp_bank, usdc_bank, "long")
    with col_c:
        leverage = st.slider(
            "Leverage (long)", min_value=1.0, max_value=float(eff_max), value=min(2.0, float(eff_max)), step=0.5, key="jlp_leverage"
        )

    if not jlp_bank or not usdc_bank:
        st.info("No matching JLP/USDC banks found for the selected protocol/market.")
        return

    # Build series (APY % per 4 hours centered)
    with st.spinner("Loading JLP/USDC series..."):
        df = build_spot_history_series(
            token_config,
            asset="JLP",
            protocol=protocol,
            market="Isolated JLP Market",
            direction="long",
            leverage=leverage,
            limit=int(points),
        )

    if df.empty:
        st.info("No historical data available for the selection.")
        return

    # Optional: Spot APY chart (hidden by default)
    show_spot_chart = st.checkbox("Show spot APY chart", value=False, key="jlp_show_spot_chart")
    if show_spot_chart:
        import plotly.graph_objects as go
        plot_df = df.copy()
        plot_df["time"] = pd.to_datetime(plot_df["time"])  # ensure dtype
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=plot_df["time"], y=plot_df["spot_rate_pct"], name="Spot % (APY)", mode="lines")
        )
        fig.update_layout(
            height=280,
            hovermode="x unified",
            yaxis_title="APY (%)",
            margin=dict(l=0, r=0, t=0, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("JLP/USDC long spot rate (APY%) per 4 hours")

    with st.expander("Show raw series"):
        st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Earnings breakdown: interest earned in JLP vs paid in USDC ---
    st.subheader("Earnings breakdown (JLP earned vs USDC paid)")
    base_usd = st.number_input(
        "Base notional (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key="jlp_base_usd"
    )

    # Fetch hourly lending/borrowing rates for JLP and USDC for the selected protocol
    with st.spinner("Computing earnings..."):
        jlp_hist: List[Dict[str, Any]] = fetch_hourly_rates(jlp_bank, protocol, int(points)) or []
        usdc_hist: List[Dict[str, Any]] = fetch_hourly_rates(usdc_bank, protocol, int(points)) or []

        def _to_hourly_df(records: List[Dict[str, Any]], prefix: str) -> pd.DataFrame:
            if not records:
                return pd.DataFrame(columns=["time", f"{prefix}_lend_pct", f"{prefix}_borrow_pct"])
            d = pd.DataFrame(records)
            # hourBucket is ISO string
            d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
            # Rates are in percentage already
            d[f"{prefix}_lend_pct"] = pd.to_numeric(d.get("avgLendingRate", 0), errors="coerce")
            d[f"{prefix}_borrow_pct"] = pd.to_numeric(d.get("avgBorrowingRate", 0), errors="coerce")
            return d[["time", f"{prefix}_lend_pct", f"{prefix}_borrow_pct"]].dropna().sort_values("time")

        df_jlp = _to_hourly_df(jlp_hist, "jlp")
        df_usdc = _to_hourly_df(usdc_hist, "usdc")
        earn_df = df_jlp.merge(df_usdc, on="time", how="inner")

        if earn_df.empty or base_usd <= 0:
            st.info("No earnings data available for the selection.")
            return

        jlp_collateral_usd = base_usd * float(leverage)
        usdc_borrowed_usd = base_usd * max(float(leverage) - 1.0, 0.0)
        bucket_factor_hourly = 1.0 / (365.0 * 24.0)

        earn_df["jlp_interest_usd"] = (
            jlp_collateral_usd * (earn_df["jlp_lend_pct"] / 100.0) * bucket_factor_hourly
        )
        earn_df["usdc_interest_usd"] = (
            - usdc_borrowed_usd * (earn_df["usdc_borrow_pct"] / 100.0) * bucket_factor_hourly
        )
        earn_df["total_interest_usd"] = earn_df["jlp_interest_usd"] + earn_df["usdc_interest_usd"]

        # --- JLP price history (Birdeye) and mark-to-market lent amount ---
        # Determine window in epoch seconds
        start_ts = int(pd.to_datetime(earn_df["time"].min()).timestamp())
        end_ts = int(pd.to_datetime(earn_df["time"].max()).timestamp())
        # Get JLP mint from token config
        jlp_mint = (token_config.get("JLP", {}) or {}).get("mint")
        price_points: List[Dict[str, Any]] = []
        if jlp_mint and start_ts and end_ts:
            price_points = fetch_birdeye_history_price(jlp_mint, start_ts, end_ts, bucket="1H") or []
        price_df = pd.DataFrame(price_points)
        if not price_df.empty:
            price_df["time"] = pd.to_datetime(price_df["t"], unit="s", utc=True).dt.tz_convert(None)
            price_df = price_df.sort_values("time")[ ["time", "price"] ].rename(columns={"price": "jlp_price"})
            # Align by nearest timestamp within 3 hours tolerance
            earn_df = pd.merge_asof(
                earn_df.sort_values("time"),
                price_df.sort_values("time"),
                on="time",
                direction="nearest",
                tolerance=pd.Timedelta("3H"),
            )
        else:
            earn_df["jlp_price"] = float("nan")

        # Compute token quantity at start based on first available price
        first_price = None
        if "jlp_price" in earn_df.columns:
            try:
                first_price = float(earn_df["jlp_price"].dropna().iloc[0])
            except Exception:
                first_price = None
        jlp_tokens = (jlp_collateral_usd / first_price) if (first_price and first_price > 0) else float("nan")
        # Start and current USD values
        earn_df["jlp_lent_usd_start"] = float(jlp_collateral_usd)
        earn_df["jlp_lent_usd_now"] = earn_df.get("jlp_price", pd.Series(dtype=float)) * jlp_tokens

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("JLP interest (sum)", f"${earn_df['jlp_interest_usd'].sum():,.2f}")
    with col2:
        st.metric("USDC interest (sum)", f"${earn_df['usdc_interest_usd'].sum():,.2f}")
    with col3:
        st.metric("Total interest (sum)", f"${earn_df['total_interest_usd'].sum():,.2f}")

    # Additional metrics: JLP lent USD at start and now
    col4, col5 = st.columns(2)
    with col4:
        start_usd = float(jlp_collateral_usd)
        st.metric("JLP lent (USD) at start", f"${start_usd:,.2f}")
    with col5:
        now_usd = float(earn_df["jlp_lent_usd_now"].dropna().iloc[-1]) if "jlp_lent_usd_now" in earn_df.columns and not earn_df["jlp_lent_usd_now"].dropna().empty else float("nan")
        st.metric("JLP lent (USD) now", (f"${now_usd:,.2f}" if pd.notna(now_usd) else "N/A"))

    # Profit metrics
    col6, col7 = st.columns(2)
    total_interest_sum = float(earn_df["total_interest_usd"].sum())
    if pd.notna(now_usd):
        # Profit = JLP now + total interest - base notional - USDC borrowed
        profit = now_usd + total_interest_sum - float(base_usd) - float(usdc_borrowed_usd)
        profit_pct = (profit / float(base_usd) * 100.0) if float(base_usd) > 0 else float("nan")
        with col6:
            st.metric("Profit", f"${profit:,.2f}")
        with col7:
            st.metric("Profit %", f"{profit_pct:.2f}%")
    else:
        with col6:
            st.metric("Profit", "N/A")
        with col7:
            st.metric("Profit %", "N/A")

    # 4H chart: JLP now vs USDC borrowed+interest, and the spread
    st.subheader("JLP vs USDC (4H)")
    res_for_chart = earn_df.copy()
    # Require price to compute JLP line
    res_for_chart = res_for_chart.dropna(subset=["jlp_price"]).copy()
    if not res_for_chart.empty and pd.notna(jlp_tokens):
        res_for_chart["time_4h"] = res_for_chart["time"].dt.floor("4H")
        resampled_c = (
            res_for_chart.groupby("time_4h", as_index=False)
            .agg({
                "jlp_price": "mean",
                "jlp_interest_usd": "sum",
                "usdc_interest_usd": "sum",
            })
        )
        # Center buckets by +2h
        resampled_c["time"] = pd.to_datetime(resampled_c["time_4h"]) + pd.Timedelta(hours=2)
        resampled_c = resampled_c.drop(columns=["time_4h"]).sort_values("time")
        # Compute JLP USD now from price and fixed token qty
        resampled_c["jlp_lent_usd_now"] = resampled_c["jlp_price"] * jlp_tokens
        # USDC borrowed + accrued interest (usdc_interest_usd is negative per hour)
        resampled_c["cum_usdc_interest_pos"] = (-resampled_c["usdc_interest_usd"]).cumsum()
        resampled_c["usdc_with_interest"] = float(usdc_borrowed_usd) + resampled_c["cum_usdc_interest_pos"]
        # Spread
        resampled_c["spread_usd"] = resampled_c["jlp_lent_usd_now"] - resampled_c["usdc_with_interest"]

        # Plot
        import plotly.graph_objects as go
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=resampled_c["time"], y=resampled_c["jlp_lent_usd_now"], name="JLP (USD)", mode="lines"))
        fig2.add_trace(go.Scatter(x=resampled_c["time"], y=resampled_c["usdc_with_interest"], name="USDC borrowed + interest (USD)", mode="lines"))
        fig2.add_trace(go.Scatter(x=resampled_c["time"], y=resampled_c["spread_usd"], name="Spread (USD)", mode="lines"))
        fig2.update_layout(height=300, hovermode="x unified", yaxis_title="USD", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Insufficient price data to build 4H chart.")

    # Display breakdown table
    show_tbl = st.checkbox("Show earnings breakdown table", value=False, key="jlp_show_tbl")
    if show_tbl:
        tmp = earn_df.copy()
        tmp["time_4h"] = tmp["time"].dt.floor("4H")
        resampled = (
            tmp.groupby("time_4h", as_index=False)
            .agg({
                "jlp_price": "mean",
                "jlp_lend_pct": "mean",
                "usdc_borrow_pct": "mean",
                "jlp_interest_usd": "sum",
                "usdc_interest_usd": "sum",
                "total_interest_usd": "sum",
            })
        )
        # Center buckets by +2h to align with charts
        resampled["time"] = pd.to_datetime(resampled["time_4h"]) + pd.Timedelta(hours=2)
        resampled = resampled.drop(columns=["time_4h"]).sort_values("time")

        # Constants per bucket
        resampled["usdc_borrowed_usd"] = float(usdc_borrowed_usd)
        if "jlp_price" in resampled.columns and pd.notna(jlp_tokens):
            resampled["jlp_lent_usd_now"] = resampled["jlp_price"] * jlp_tokens
        else:
            resampled["jlp_lent_usd_now"] = float("nan")

        tbl = resampled[[
            "time",
            "jlp_price",
            "jlp_lent_usd_now",
            "usdc_borrowed_usd",
            "jlp_lend_pct",
            "usdc_borrow_pct",
            "jlp_interest_usd",
            "usdc_interest_usd",
            "total_interest_usd",
        ]].copy()
        tbl = tbl.round({
            "jlp_price": 6,
            "jlp_lent_usd_now": 2,
            "usdc_borrowed_usd": 2,
            "jlp_lend_pct": 4,
            "usdc_borrow_pct": 4,
            "jlp_interest_usd": 2,
            "usdc_interest_usd": 2,
            "total_interest_usd": 2,
        })
        st.dataframe(tbl, use_container_width=True, hide_index=True)


