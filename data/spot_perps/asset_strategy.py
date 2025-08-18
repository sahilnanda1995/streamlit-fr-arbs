from typing import Dict, List, Tuple, Optional, Any

import pandas as pd
import streamlit as st

from .helpers import compute_effective_max_leverage, get_protocol_market_pairs
from .spot_history import build_spot_history_series
from api.endpoints import fetch_hourly_rates, fetch_birdeye_history_price


def _find_pair_banks(
    token_config: dict,
    asset: str,
    protocol: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Find the first (asset_bank, usdc_bank, market) pair for given asset/protocol
    where both asset and USDC share the same protocol+market.
    """
    asset_pairs = get_protocol_market_pairs(token_config, asset)
    usdc_pairs = get_protocol_market_pairs(token_config, "USDC")
    if not asset_pairs or not usdc_pairs:
        return None, None, None
    usdc_by_key = {(p, m): b for p, m, b in usdc_pairs if p == protocol}
    for p, m, bank in asset_pairs:
        if p != protocol:
            continue
        usdc_bank = usdc_by_key.get((p, m))
        if usdc_bank:
            return bank, usdc_bank, m
    return None, None, None


def _get_supported_protocols(token_config: dict, asset: str) -> List[str]:
    """
    Return list of protocols where a matching USDC bank exists for the asset.
    """
    protos: List[str] = []
    asset_pairs = get_protocol_market_pairs(token_config, asset)
    usdc_pairs = get_protocol_market_pairs(token_config, "USDC")
    usdc_keys = {(p, m) for p, m, _ in usdc_pairs}
    for p, m, _ in asset_pairs:
        if (p, m) in usdc_keys and p not in protos:
            protos.append(p)
    return protos or ["kamino", "drift"]


def display_asset_strategy_section(token_config: dict, asset_symbol: str) -> None:
    """
    Generalized Strategy section for an asset/USDC long strategy.
    Includes: optional spot APY chart, earnings metrics, 4H combined chart,
    and a 4H breakdown table.
    """
    st.subheader(f"{asset_symbol} strategy")

    # Controls
    col_a, col_b, col_c = st.columns([1, 1, 1])
    supported = _get_supported_protocols(token_config, asset_symbol)
    with col_a:
        protocol = st.selectbox("Protocol", supported, index=0, key=f"{asset_symbol}_proto")
    with col_b:
        points = st.selectbox("Points (hours)", [168, 336, 720, 1440], index=3, key=f"{asset_symbol}_points")

    asset_bank, usdc_bank, market_name = _find_pair_banks(token_config, asset_symbol, protocol)
    eff_max = 1.0
    if asset_bank and usdc_bank:
        eff_max = compute_effective_max_leverage(token_config, asset_bank, usdc_bank, "long")
    with col_c:
        leverage = st.slider(
            "Leverage (long)", min_value=1.0, max_value=float(eff_max), value=min(2.0, float(eff_max)), step=0.5,
            key=f"{asset_symbol}_leverage",
        )

    if not asset_bank or not usdc_bank:
        st.info("No matching asset/USDC banks found for the selected protocol/market.")
        return

    # Build spot APY series (4H centered)
    with st.spinner("Loading series..."):
        df = build_spot_history_series(
            token_config,
            asset=asset_symbol,
            protocol=protocol,
            market=market_name or "",
            direction="long",
            leverage=leverage,
            limit=int(points),
        )

    if df.empty:
        st.info("No historical data available for the selection.")
        return

    # Spot APY chart (hidden by default)
    show_spot_chart = st.checkbox("Show spot APY chart", value=False, key=f"{asset_symbol}_show_spot_chart")
    if show_spot_chart:
        import plotly.graph_objects as go
        plot_df = df.copy()
        plot_df["time"] = pd.to_datetime(plot_df["time"])  # ensure dtype
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=plot_df["time"], y=plot_df["spot_rate_pct"], name="Spot % (APY)", mode="lines")
        )
        fig.update_layout(height=280, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"{asset_symbol}/USDC long spot rate (APY%) per 4 hours")

    # Earnings breakdown inputs
    st.subheader("Earnings breakdown")
    base_usd = st.number_input(
        "Base notional (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key=f"{asset_symbol}_base_usd"
    )

    # Fetch hourly lending/borrowing
    with st.spinner("Computing earnings..."):
        asset_hist: List[Dict[str, Any]] = fetch_hourly_rates(asset_bank, protocol, int(points)) or []
        usdc_hist: List[Dict[str, Any]] = fetch_hourly_rates(usdc_bank, protocol, int(points)) or []

        def _to_hourly_df(records: List[Dict[str, Any]], prefix: str) -> pd.DataFrame:
            if not records:
                return pd.DataFrame(columns=["time", f"{prefix}_lend_pct", f"{prefix}_borrow_pct"])
            d = pd.DataFrame(records)
            d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
            d[f"{prefix}_lend_pct"] = pd.to_numeric(d.get("avgLendingRate", 0), errors="coerce")
            d[f"{prefix}_borrow_pct"] = pd.to_numeric(d.get("avgBorrowingRate", 0), errors="coerce")
            return d[["time", f"{prefix}_lend_pct", f"{prefix}_borrow_pct"]].dropna().sort_values("time")

        df_asset = _to_hourly_df(asset_hist, "asset")
        df_usdc = _to_hourly_df(usdc_hist, "usdc")
        earn_df = df_asset.merge(df_usdc, on="time", how="inner")
        if earn_df.empty or base_usd <= 0:
            st.info("No earnings data available for the selection.")
            return

        asset_collateral_usd = base_usd * float(leverage)
        usdc_borrowed_usd = base_usd * max(float(leverage) - 1.0, 0.0)
        bucket_factor_hourly = 1.0 / (365.0 * 24.0)

        earn_df["asset_interest_usd"] = asset_collateral_usd * (earn_df["asset_lend_pct"] / 100.0) * bucket_factor_hourly
        earn_df["usdc_interest_usd"] = - usdc_borrowed_usd * (earn_df["usdc_borrow_pct"] / 100.0) * bucket_factor_hourly
        earn_df["total_interest_usd"] = earn_df["asset_interest_usd"] + earn_df["usdc_interest_usd"]

        # Price series (1H) for asset
        mint = (token_config.get(asset_symbol, {}) or {}).get("mint")
        start_ts = int(pd.to_datetime(earn_df["time"].min()).timestamp())
        end_ts = int(pd.to_datetime(earn_df["time"].max()).timestamp())
        price_points = fetch_birdeye_history_price(mint, start_ts, end_ts, bucket="2H") if (mint and start_ts and end_ts) else []
        price_df = pd.DataFrame(price_points)
        if not price_df.empty:
            price_df["time"] = pd.to_datetime(price_df["t"], unit="s", utc=True).dt.tz_convert(None)
            price_df = price_df.sort_values("time")[ ["time", "price"] ].rename(columns={"price": "asset_price"})
            earn_df = pd.merge_asof(
                earn_df.sort_values("time"), price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3H")
            )
        else:
            earn_df["asset_price"] = float("nan")

        # Tokens and MTM
        first_price = None
        if "asset_price" in earn_df.columns:
            try:
                first_price = float(earn_df["asset_price"].dropna().iloc[0])
            except Exception:
                first_price = None
        asset_tokens = (asset_collateral_usd / first_price) if (first_price and first_price > 0) else float("nan")
        earn_df["asset_lent_usd_now"] = earn_df.get("asset_price", pd.Series(dtype=float)) * asset_tokens

    # Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(f"{asset_symbol} interest (sum)", f"${earn_df['asset_interest_usd'].sum():,.2f}")
    with col2:
        st.metric("USDC interest (sum)", f"${earn_df['usdc_interest_usd'].sum():,.2f}")
    with col3:
        st.metric("Total interest (sum)", f"${earn_df['total_interest_usd'].sum():,.2f}")

    col4, col5 = st.columns(2)
    with col4:
        start_usd = float(asset_collateral_usd)
        st.metric(f"{asset_symbol} lent (USD) at start", f"${start_usd:,.2f}")
    with col5:
        now_usd = float(earn_df["asset_lent_usd_now"].dropna().iloc[-1]) if "asset_lent_usd_now" in earn_df.columns and not earn_df["asset_lent_usd_now"].dropna().empty else float("nan")
        st.metric(f"{asset_symbol} lent (USD) now", (f"${now_usd:,.2f}" if pd.notna(now_usd) else "N/A"))

    col6, col7 = st.columns(2)
    total_interest_sum = float(earn_df["total_interest_usd"].sum())
    if pd.notna(now_usd):
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

    # 4H combined chart
    st.subheader(f"{asset_symbol} vs USDC (4H)")
    res_for_chart = earn_df.dropna(subset=["asset_price"]).copy()
    if not res_for_chart.empty and pd.notna(asset_tokens):
        res_for_chart["time_4h"] = res_for_chart["time"].dt.floor("4H")
        resampled_c = (
            res_for_chart.groupby("time_4h", as_index=False)
            .agg({
                "asset_price": "mean",
                "asset_interest_usd": "sum",
                "usdc_interest_usd": "sum",
            })
        )
        resampled_c["time"] = pd.to_datetime(resampled_c["time_4h"]) + pd.Timedelta(hours=2)
        resampled_c = resampled_c.drop(columns=["time_4h"]).sort_values("time")
        resampled_c["asset_lent_usd_now"] = resampled_c["asset_price"] * asset_tokens
        resampled_c["cum_usdc_interest_pos"] = (-resampled_c["usdc_interest_usd"]).cumsum()
        resampled_c["usdc_with_interest"] = float(usdc_borrowed_usd) + resampled_c["cum_usdc_interest_pos"]
        resampled_c["spread_usd"] = resampled_c["asset_lent_usd_now"] - resampled_c["usdc_with_interest"]

        import plotly.graph_objects as go
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=resampled_c["time"], y=resampled_c["asset_lent_usd_now"], name=f"{asset_symbol} (USD)", mode="lines", line=dict(color="#00CC96")))
        fig2.add_trace(go.Scatter(x=resampled_c["time"], y=resampled_c["usdc_with_interest"], name="USDC borrowed + interest (USD)", mode="lines", line=dict(color="#EF553B")))
        fig2.add_trace(go.Scatter(x=resampled_c["time"], y=resampled_c["spread_usd"], name="Net value (USD)", mode="lines", line=dict(color="#636EFA", width=2)))
        fig2.update_layout(height=300, hovermode="x unified", yaxis_title="USD", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Insufficient price data to build 4H chart.")

    # 4H breakdown table
    show_tbl = st.checkbox("Show earnings breakdown table", value=False, key=f"{asset_symbol}_show_tbl")
    if show_tbl:
        tmp = earn_df.copy()
        tmp["time_4h"] = tmp["time"].dt.floor("4H")
        resampled = (
            tmp.groupby("time_4h", as_index=False)
            .agg({
                "asset_price": "mean",
                "asset_lent_usd_now": "mean",
                "usdc_borrow_pct": "mean",
                "asset_lend_pct": "mean",
                "asset_interest_usd": "sum",
                "usdc_interest_usd": "sum",
                "total_interest_usd": "sum",
            })
        )
        resampled["time"] = pd.to_datetime(resampled["time_4h"]) + pd.Timedelta(hours=2)
        resampled = resampled.drop(columns=["time_4h"]).sort_values("time")
        resampled["usdc_borrowed_usd"] = float(usdc_borrowed_usd)

        tbl = resampled[[
            "time",
            "asset_price",
            "asset_lent_usd_now",
            "usdc_borrowed_usd",
            "asset_lend_pct",
            "usdc_borrow_pct",
            "asset_interest_usd",
            "usdc_interest_usd",
            "total_interest_usd",
        ]].copy()
        tbl = tbl.round({
            "asset_price": 6,
            "asset_lent_usd_now": 2,
            "usdc_borrowed_usd": 2,
            "asset_lend_pct": 4,
            "usdc_borrow_pct": 4,
            "asset_interest_usd": 2,
            "usdc_interest_usd": 2,
            "total_interest_usd": 2,
        })
        st.dataframe(tbl, use_container_width=True, hide_index=True)


def display_alp_strategy_section(token_config: dict) -> None:
    display_asset_strategy_section(token_config, "ALP")


