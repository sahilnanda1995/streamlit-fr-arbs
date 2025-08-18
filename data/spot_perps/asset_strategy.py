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
    col_a, col_b, col_c, col_d = st.columns([1, 1, 1, 1])
    with col_a:
      base_usd = st.number_input(
        "Input Amount (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key=f"{asset_symbol}_base_usd"
    )
    supported = _get_supported_protocols(token_config, asset_symbol)
    with col_b:
        protocol = st.selectbox("Protocol", supported, index=0, key=f"{asset_symbol}_proto")
    with col_c:
        points = st.selectbox("Points (hours)", [168, 336, 720, 1440], index=3, key=f"{asset_symbol}_points")

    asset_bank, usdc_bank, market_name = _find_pair_banks(token_config, asset_symbol, protocol)
    eff_max = 1.0
    if asset_bank and usdc_bank:
        eff_max = compute_effective_max_leverage(token_config, asset_bank, usdc_bank, "long")
    with col_d:
        leverage = st.slider(
            "Leverage (long)", min_value=1.0, max_value=float(eff_max), value=min(2.0, float(eff_max)), step=0.5,
            key=f"{asset_symbol}_leverage",
        )

    if not asset_bank or not usdc_bank:
        st.info("No matching asset/USDC banks found for the selected protocol/market.")
        return

    # Actions: require explicit Analyze; Refresh/Retry only shown on failures
    col_x, _ = st.columns([1, 3])
    analyze_clicked = col_x.button("Analyze", key=f"{asset_symbol}_analyze_btn")

    analyzed_state_key = f"{asset_symbol}_analyzed"
    if analyze_clicked:
        st.session_state[analyzed_state_key] = True

    if not st.session_state.get(analyzed_state_key, False):
        st.info("Click Analyze to fetch data and render the strategy analysis.")
        return

    def _render_refresh_button():
        btn = st.button("Refresh / Retry", key=f"{asset_symbol}_refresh_btn")
        if btn:
            try:
                st.cache_data.clear()
            except Exception:
                pass
            st.session_state[analyzed_state_key] = True
            try:
                st.rerun()
            except Exception:
                try:
                    st.experimental_rerun()  # type: ignore[attr-defined]
                except Exception:
                    pass

    # Initialize variables to satisfy static analysis on early-return paths
    df: pd.DataFrame = pd.DataFrame()
    earn_df: pd.DataFrame = pd.DataFrame()
    asset_tokens: float = float("nan")
    # Pre-compute notional amounts used in later blocks
    asset_collateral_usd = float(base_usd) * float(leverage)
    usdc_borrowed_usd = float(base_usd) * max(float(leverage) - 1.0, 0.0)

    # Build spot APY series (4H centered)
    try:
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
    except Exception:
        st.error("Failed to load spot series.")
        _render_refresh_button()
        return

    if df.empty:
        st.info("No historical data available for the selection.")
        return

    # Fetch hourly lending/borrowing
    try:
        with st.spinner("Computing earnings..."):
            asset_hist: List[Dict[str, Any]] = fetch_hourly_rates(asset_bank, protocol, int(points)) or []
            usdc_hist: List[Dict[str, Any]] = fetch_hourly_rates(usdc_bank, protocol, int(points)) or []
    except Exception:
        st.error("Failed to load hourly rates.")
        _render_refresh_button()
        return

    def _to_hourly_df(records: List[Dict[str, Any]], prefix: str) -> pd.DataFrame:
        if not records:
            return pd.DataFrame(columns=["time", f"{prefix}_lend_apy", f"{prefix}_borrow_apy"])
        d = pd.DataFrame(records)
        d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
        d[f"{prefix}_lend_apy"] = pd.to_numeric(d.get("avgLendingRate", 0), errors="coerce")
        d[f"{prefix}_borrow_apy"] = pd.to_numeric(d.get("avgBorrowingRate", 0), errors="coerce")
        return d[["time", f"{prefix}_lend_apy", f"{prefix}_borrow_apy"]].sort_values("time")

    df_asset = _to_hourly_df(asset_hist, "asset")
    df_usdc = _to_hourly_df(usdc_hist, "usdc")
    # Aggregate hourly APR% to 4H buckets (centered +2h)
    if not df_asset.empty:
        df_asset = df_asset.copy()
        df_asset["time_4h"] = df_asset["time"].dt.floor("4H")
        df_asset = (
            df_asset.groupby("time_4h", as_index=False)["asset_lend_apy"].mean()
            .assign(time=lambda d: pd.to_datetime(d["time_4h"]) + pd.Timedelta(hours=2))
            .drop(columns=["time_4h"])
        )
    if not df_usdc.empty:
        df_usdc = df_usdc.copy()
        df_usdc["time_4h"] = df_usdc["time"].dt.floor("4H")
        df_usdc = (
            df_usdc.groupby("time_4h", as_index=False)["usdc_borrow_apy"].mean()
            .assign(time=lambda d: pd.to_datetime(d["time_4h"]) + pd.Timedelta(hours=2))
            .drop(columns=["time_4h"])
        )
    earn_df = pd.merge(df_asset, df_usdc, on="time", how="inner")
    if earn_df.empty or base_usd <= 0:
        st.info("No earnings data available for the selection.")
        return

    # 4-hour bucket factor
    bucket_factor_4h = 4.0 / (365.0 * 24.0)

    earn_df = earn_df.sort_values("time").reset_index(drop=True)
    # Build per-bucket growth factors and apply starting NEXT bucket (shifted cumprod)
    earn_df["asset_growth_factor"] = 1.0 + (earn_df["asset_lend_apy"] / 100.0) * bucket_factor_4h
    earn_df["usdc_growth_factor"] = 1.0 + (earn_df["usdc_borrow_apy"] / 100.0) * bucket_factor_4h
    earn_df["asset_growth_cum_shifted"] = earn_df["asset_growth_factor"].cumprod().shift(1).fillna(1.0)
    earn_df["usdc_growth_cum_shifted"] = earn_df["usdc_growth_factor"].cumprod().shift(1).fillna(1.0)

    # Price series (4H) for asset
    mint = (token_config.get(asset_symbol, {}) or {}).get("mint")
    start_ts = int(pd.to_datetime(earn_df["time"].min()).timestamp())
    end_ts = int(pd.to_datetime(earn_df["time"].max()).timestamp())
    try:
        price_points = fetch_birdeye_history_price(mint, start_ts, end_ts, bucket="4H") if (mint and start_ts and end_ts) else []
    except Exception:
        price_points = []
    price_df = pd.DataFrame(price_points)
    if not price_df.empty:
        price_df["time"] = pd.to_datetime(price_df["t"], unit="s", utc=True).dt.tz_convert(None)
        price_df = price_df.sort_values("time")[ ["time", "price"] ].rename(columns={"price": "asset_price"})
        earn_df = pd.merge_asof(
            earn_df.sort_values("time"), price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3H")
        )
    else:
        earn_df["asset_price"] = float("nan")

    # Tokens, principal and MTM using next-bucket application
    first_price = None
    if "asset_price" in earn_df.columns:
        try:
            first_price = float(earn_df["asset_price"].dropna().iloc[0])
        except Exception:
            first_price = None
    asset_tokens0 = (asset_collateral_usd / first_price) if (first_price and first_price > 0) else float("nan")
    # Asset tokens grow from next bucket onward
    earn_df["asset_tokens"] = float(asset_tokens0) * earn_df["asset_growth_cum_shifted"]
    earn_df["asset_lent_usd_now"] = earn_df.get("asset_price", pd.Series(dtype=float)) * earn_df["asset_tokens"]
    # Asset interest as token delta applied starting next bucket, valued at current price
    earn_df["asset_tokens_prev"] = earn_df["asset_tokens"].shift(1).fillna(float(asset_tokens0))
    earn_df["asset_interest_tokens"] = earn_df["asset_tokens"] - earn_df["asset_tokens_prev"]
    earn_df["asset_interest_usd"] = earn_df["asset_interest_tokens"] * earn_df.get("asset_price", pd.Series(dtype=float))
    # USDC principal grows from next bucket onward
    earn_df["usdc_principal_usd"] = float(usdc_borrowed_usd) * earn_df["usdc_growth_cum_shifted"]
    earn_df["usdc_principal_prev"] = float(usdc_borrowed_usd) * earn_df["usdc_growth_cum_shifted"].shift(1).fillna(1.0)
    earn_df["usdc_interest_usd"] = - (earn_df["usdc_principal_usd"] - earn_df["usdc_principal_prev"])
    # Total net interest (for display)
    earn_df["total_interest_usd"] = earn_df["asset_interest_usd"] + earn_df["usdc_interest_usd"]
    # Net value series: asset value minus outstanding USDC principal
    earn_df["net_value_usd"] = earn_df["asset_lent_usd_now"] - earn_df["usdc_principal_usd"]

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
    now_net_value = float(earn_df["net_value_usd"].dropna().iloc[-1]) if "net_value_usd" in earn_df.columns and not earn_df["net_value_usd"].dropna().empty else float("nan")
    if pd.notna(now_net_value):
        profit = now_net_value - float(base_usd)
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

    # 4H combined chart (earn_df is already 4H)
    st.text(f"{asset_symbol}/USDC spot chart")
    res_for_chart = earn_df.dropna(subset=["asset_price"]).copy()
    if not res_for_chart.empty:
        plot_df = res_for_chart.sort_values("time")
        plot_df = plot_df[["time", "asset_lent_usd_now", "usdc_principal_usd", "net_value_usd"]]

        import plotly.graph_objects as go
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["asset_lent_usd_now"], name=f"{asset_symbol} (USD)", mode="lines", line=dict(color="#00CC96")))
        fig2.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["usdc_principal_usd"], name="USDC borrowed + interest (USD)", mode="lines", line=dict(color="#EF553B")))
        fig2.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["net_value_usd"], name="Net value (USD)", mode="lines", line=dict(color="#636EFA", width=2)))
        fig2.update_layout(height=300, hovermode="x unified", yaxis_title="USD", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Insufficient price data to build 4H chart.")

    # 4H breakdown table (earn_df is already 4H)
    show_tbl = st.checkbox("Show earnings breakdown table", value=False, key=f"{asset_symbol}_show_tbl")
    if show_tbl:
        resampled = (
            earn_df.groupby("time", as_index=False)
            .agg({
                "asset_price": "mean",
                "asset_lent_usd_now": "mean",
                "asset_tokens": "last",
                "usdc_borrow_apy": "mean",
                "asset_lend_apy": "mean",
                "asset_interest_usd": "sum",
                "usdc_interest_usd": "sum",
                "total_interest_usd": "sum",
                "usdc_principal_usd": "last",
                "net_value_usd": "last",
            })
            .sort_values("time")
        )
        # Current outstanding USDC principal per bucket
        resampled["usdc_borrowed"] = resampled["usdc_principal_usd"]

        tbl = resampled[[
            "time",
            "asset_price",
            "asset_tokens",
            "asset_lent_usd_now",
            "usdc_borrowed",
            "net_value_usd",
            "asset_lend_apy",
            "usdc_borrow_apy",
            "asset_interest_usd",
            "usdc_interest_usd",
            "total_interest_usd",
        ]].copy()
        tbl = tbl.rename(columns={
            "asset_tokens": "asset_lent_tokens",
            "net_value_usd": "net_value",
        })
        tbl = tbl.round({
            "asset_price": 6,
            "asset_lent_tokens": 6,
            "asset_lent_usd_now": 2,
            "usdc_borrowed": 2,
            "net_value": 2,
            "asset_lend_apy": 4,
            "usdc_borrow_apy": 4,
            "asset_interest_usd": 2,
            "usdc_interest_usd": 2,
            "total_interest_usd": 2,
        })
        st.dataframe(
            tbl,
            use_container_width=True,
            hide_index=True,
            column_config={
                "time": st.column_config.DatetimeColumn("Time", width="small"),
                "asset_price": st.column_config.NumberColumn(f"{asset_symbol} price", width="small", format="%.6f"),
                "asset_lent_tokens": st.column_config.NumberColumn(f"{asset_symbol} amount", width="small", format="%.6f"),
                "asset_lent_usd_now": st.column_config.NumberColumn(f"{asset_symbol} value (USD)", width="small", format="$%.2f"),
                "usdc_borrowed": st.column_config.NumberColumn("USDC principal (USD)", width="small", format="$%.2f"),
                "net_value": st.column_config.NumberColumn("Net value (USD)", width="small", format="$%.2f"),
                "asset_lend_apy": st.column_config.NumberColumn(f"{asset_symbol} APY", width="small", format="%.2f%%"),
                "usdc_borrow_apy": st.column_config.NumberColumn("USDC borrow APY", width="small", format="%.2f%%"),
                "asset_interest_usd": st.column_config.NumberColumn(f"{asset_symbol} interest (USD)", width="small", format="$%.2f"),
                "usdc_interest_usd": st.column_config.NumberColumn("USDC interest (USD)", width="small", format="$%.2f"),
                "total_interest_usd": st.column_config.NumberColumn("Total interest (USD)", width="small", format="$%.2f"),
            },
        )

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

def display_alp_strategy_section(token_config: dict) -> None:
    display_asset_strategy_section(token_config, "ALP")


