from typing import Dict, List, Tuple, Optional, Any

import time
import pandas as pd
import streamlit as st

from .helpers import compute_effective_max_leverage, get_protocol_market_pairs
from api.endpoints import fetch_hourly_rates, fetch_birdeye_history_price


def _find_pair_banks_for_two_assets(
    token_config: dict,
    base_asset: str,
    quote_asset: str,
    protocol: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Find the first (base_bank, quote_bank, market) pair for given base/quote/protocol
    where both assets share the same protocol+market.
    """
    base_pairs = get_protocol_market_pairs(token_config, base_asset)
    quote_pairs = get_protocol_market_pairs(token_config, quote_asset)
    if not base_pairs or not quote_pairs:
        return None, None, None
    quote_by_key = {(p, m): b for p, m, b in quote_pairs if p == protocol}
    for p, m, bank in base_pairs:
        if p != protocol:
            continue
        quote_bank = quote_by_key.get((p, m))
        if quote_bank:
            return bank, quote_bank, m
    return None, None, None


def _get_supported_protocols_for_pair(token_config: dict, base_asset: str, quote_asset: str) -> List[str]:
    """
    Return list of protocols where a matching base/quote bank exists on the same market.
    """
    protos: List[str] = []
    base_pairs = get_protocol_market_pairs(token_config, base_asset)
    quote_pairs = get_protocol_market_pairs(token_config, quote_asset)
    quote_keys = {(p, m) for p, m, _ in quote_pairs}
    for p, m, _ in base_pairs:
        if (p, m) in quote_keys and p not in protos:
            protos.append(p)
    return protos


def display_pair_strategy_section(token_config: dict, base_symbol: str, quote_symbol: str) -> None:
    """
    Generalized Strategy section for a base/quote long strategy where both assets are variable.
    We deposit base, borrow quote. Both accrue interest at their respective APYs (base lend, quote borrow).
    Price series are fetched for both assets and applied with next-bucket compounding semantics.
    """
    st.subheader(f"{base_symbol}/{quote_symbol} strategy")

    # Controls
    col_a, col_b, col_c, col_d = st.columns([1, 1, 1, 1])
    with col_a:
        base_usd = st.number_input(
            "Input Amount (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key=f"{base_symbol}_{quote_symbol}_base_usd"
        )
    # Normalize keys for token_config lookups (config loader uppercases keys)
    base_key = base_symbol.upper()
    quote_key = quote_symbol.upper()

    supported = _get_supported_protocols_for_pair(token_config, base_key, quote_key)
    with col_b:
        if not supported:
            st.info("No common protocol+market found for this pair.")
            return
        protocol = st.selectbox("Protocol", supported, index=0, key=f"{base_symbol}_{quote_symbol}_proto")
    with col_c:
        lookback_options = [
            ("2 months", 1440),
            ("1 month", 720),
            ("15 days", 360),
            ("1 week", 168),
        ]
        lookback_labels = [label for label, _ in lookback_options]
        selected_label = st.selectbox("Time Period", lookback_labels, index=0, key=f"{base_symbol}_{quote_symbol}_points")
        points_map = {label: hours for label, hours in lookback_options}
        points = points_map.get(selected_label, 720)

    base_bank, quote_bank, market_name = _find_pair_banks_for_two_assets(token_config, base_key, quote_key, protocol)
    eff_max = 1.0
    if base_bank and quote_bank:
        # use "long" direction cap for both legs
        eff_max = compute_effective_max_leverage(token_config, base_bank, quote_bank, "long")
    with col_d:
        if float(eff_max) <= 1.0:
            leverage = 1.0
            st.metric("Leverage (long)", "1.0x")
            st.caption("Leverage capped at 1.0x for this pair/protocol.")
        else:
            leverage = st.slider(
                "Leverage (long)", min_value=1.0, max_value=float(eff_max), value=min(2.0, float(eff_max)), step=0.5,
                key=f"{base_symbol}_{quote_symbol}_leverage",
            )

    if not base_bank or not quote_bank:
        st.info("No matching base/quote banks found for the selected protocol/market.")
        return

    # Analyze gating
    col_x, _ = st.columns([1, 3])
    analyze_clicked = col_x.button("Analyze", key=f"{base_symbol}_{quote_symbol}_analyze_btn")
    analyzed_state_key = f"{base_symbol}_{quote_symbol}_analyzed"
    if analyze_clicked:
        st.session_state[analyzed_state_key] = True
    if not st.session_state.get(analyzed_state_key, False):
        st.info("Click Analyze to fetch data and render the strategy analysis.")
        return

    def _render_refresh_button():
        btn = st.button("Refresh / Retry", key=f"{base_symbol}_{quote_symbol}_refresh_btn")
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

    # Pre-compute notionals
    base_collateral_usd = float(base_usd) * float(leverage)
    quote_borrowed_usd = float(base_usd) * max(float(leverage) - 1.0, 0.0)

    # Fetch hourly lending/borrowing
    try:
        with st.spinner("Loading rates..."):
            base_hist: List[Dict[str, Any]] = fetch_hourly_rates(base_bank, protocol, int(points)) or []
            quote_hist: List[Dict[str, Any]] = fetch_hourly_rates(quote_bank, protocol, int(points)) or []
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

    df_base = _to_hourly_df(base_hist, "base")
    df_quote = _to_hourly_df(quote_hist, "quote")
    if df_base.empty or df_quote.empty:
        st.info("No historical rates available for the selection.")
        return

    # Aggregate hourly APR% to 4H buckets (centered +2h)
    df_base = df_base.copy()
    df_base["time_4h"] = df_base["time"].dt.floor("4H")
    df_base = (
        df_base.groupby("time_4h", as_index=False)["base_lend_apy"].mean()
        .assign(time=lambda d: pd.to_datetime(d["time_4h"]) + pd.Timedelta(hours=2))
        .drop(columns=["time_4h"])
    )
    df_quote = df_quote.copy()
    df_quote["time_4h"] = df_quote["time"].dt.floor("4H")
    df_quote = (
        df_quote.groupby("time_4h", as_index=False)["quote_borrow_apy"].mean()
        .assign(time=lambda d: pd.to_datetime(d["time_4h"]) + pd.Timedelta(hours=2))
        .drop(columns=["time_4h"])
    )

    earn_df = pd.merge(df_base, df_quote, on="time", how="inner").sort_values("time").reset_index(drop=True)
    if earn_df.empty or base_usd <= 0:
        st.info("No earnings data available for the selection.")
        return

    # 4-hour bucket factor
    bucket_factor_4h = 4.0 / (365.0 * 24.0)
    # Growth factors with next-bucket application
    earn_df["base_growth_factor"] = 1.0 + (earn_df["base_lend_apy"] / 100.0) * bucket_factor_4h
    earn_df["quote_growth_factor"] = 1.0 + (earn_df["quote_borrow_apy"] / 100.0) * bucket_factor_4h
    earn_df["base_growth_cum_shifted"] = earn_df["base_growth_factor"].cumprod().shift(1).fillna(1.0)
    earn_df["quote_growth_cum_shifted"] = earn_df["quote_growth_factor"].cumprod().shift(1).fillna(1.0)

    # Fetch price series for both assets (4H) with 1 rps pacing
    base_mint = (token_config.get(base_key, {}) or {}).get("mint")
    quote_mint = (token_config.get(quote_key, {}) or {}).get("mint")
    start_ts = int(pd.to_datetime(earn_df["time"].min()).timestamp())
    end_ts = int(pd.to_datetime(earn_df["time"].max()).timestamp())

    base_price_df = pd.DataFrame()
    quote_price_df = pd.DataFrame()
    try:
        if base_mint and start_ts and end_ts:
            points_base = fetch_birdeye_history_price(base_mint, start_ts, end_ts, bucket="4H")
            base_price_df = pd.DataFrame(points_base)
        # Respect 1 rps limit before the second call
        time.sleep(1.1)
        if quote_mint and start_ts and end_ts:
            points_quote = fetch_birdeye_history_price(quote_mint, start_ts, end_ts, bucket="4H")
            quote_price_df = pd.DataFrame(points_quote)
    except Exception:
        pass

    if not base_price_df.empty:
        base_price_df["time"] = pd.to_datetime(base_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
        base_price_df = base_price_df.sort_values("time")[ ["time", "price"] ].rename(columns={"price": "base_price"})
        earn_df = pd.merge_asof(earn_df.sort_values("time"), base_price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3H"))
    else:
        earn_df["base_price"] = float("nan")

    if not quote_price_df.empty:
        quote_price_df["time"] = pd.to_datetime(quote_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
        quote_price_df = quote_price_df.sort_values("time")[ ["time", "price"] ].rename(columns={"price": "quote_price"})
        earn_df = pd.merge_asof(earn_df.sort_values("time"), quote_price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3H"))
    else:
        earn_df["quote_price"] = float("nan")

    # Initial token amounts using first observed prices
    base_first_price = None
    quote_first_price = None
    if "base_price" in earn_df.columns:
        try:
            base_first_price = float(earn_df["base_price"].dropna().iloc[0])
        except Exception:
            base_first_price = None
    if "quote_price" in earn_df.columns:
        try:
            quote_first_price = float(earn_df["quote_price"].dropna().iloc[0])
        except Exception:
            quote_first_price = None
    base_tokens0 = (base_collateral_usd / base_first_price) if (base_first_price and base_first_price > 0) else float("nan")
    quote_tokens0 = (quote_borrowed_usd / quote_first_price) if (quote_first_price and quote_first_price > 0) else float("nan")

    # Tokens with next-bucket compounding
    earn_df["base_tokens"] = float(base_tokens0) * earn_df["base_growth_cum_shifted"]
    earn_df["quote_tokens"] = float(quote_tokens0) * earn_df["quote_growth_cum_shifted"]

    # Values in USD
    earn_df["base_value_usd"] = earn_df.get("base_price", pd.Series(dtype=float)) * earn_df["base_tokens"]
    earn_df["quote_value_usd"] = earn_df.get("quote_price", pd.Series(dtype=float)) * earn_df["quote_tokens"]

    # Interest series (token deltas valued at current prices)
    earn_df["base_tokens_prev"] = earn_df["base_tokens"].shift(1).fillna(float(base_tokens0))
    earn_df["base_interest_tokens"] = earn_df["base_tokens"] - earn_df["base_tokens_prev"]
    earn_df["base_interest_usd"] = earn_df["base_interest_tokens"] * earn_df.get("base_price", pd.Series(dtype=float))

    earn_df["quote_tokens_prev"] = earn_df["quote_tokens"].shift(1).fillna(float(quote_tokens0))
    earn_df["quote_interest_tokens"] = earn_df["quote_tokens"] - earn_df["quote_tokens_prev"]
    # Borrow interest should be negative
    earn_df["quote_interest_usd"] = - (earn_df["quote_interest_tokens"] * earn_df.get("quote_price", pd.Series(dtype=float)))

    earn_df["total_interest_usd"] = earn_df["base_interest_usd"] + earn_df["quote_interest_usd"]
    earn_df["net_value_usd"] = earn_df["base_value_usd"] - earn_df["quote_value_usd"]

    # Metrics (two rows)
    row1_col1, row1_col2, row1_col3 = st.columns(3)
    with row1_col1:
        st.metric(f"{base_symbol} interest (sum)", f"${earn_df['base_interest_usd'].sum():,.2f}")
    with row1_col2:
        st.metric(f"{quote_symbol} interest (sum)", f"${earn_df['quote_interest_usd'].sum():,.2f}")
    with row1_col3:
        st.metric("Total interest (sum)", f"${earn_df['total_interest_usd'].sum():,.2f}")

    start_base_usd = float(base_collateral_usd)
    now_base_usd = float(earn_df["base_value_usd"].dropna().iloc[-1]) if not earn_df["base_value_usd"].dropna().empty else float("nan")
    start_quote_usd = float(quote_borrowed_usd)
    now_quote_usd = float(earn_df["quote_value_usd"].dropna().iloc[-1]) if not earn_df["quote_value_usd"].dropna().empty else float("nan")
    now_net_value = float(earn_df["net_value_usd"].dropna().iloc[-1]) if not earn_df["net_value_usd"].dropna().empty else float("nan")

    row2_col1, row2_col2, row2_col3, row2_col4, row2_col5 = st.columns(5)
    with row2_col1:
        st.metric(f"{base_symbol} value (USD) at start", f"${start_base_usd:,.2f}")
    with row2_col2:
        st.metric(f"{base_symbol} value (USD) now", (f"${now_base_usd:,.2f}" if pd.notna(now_base_usd) else "N/A"))
    with row2_col3:
        st.metric(f"{quote_symbol} borrowed (USD) at start", f"${start_quote_usd:,.2f}")
    with row2_col4:
        st.metric(f"{quote_symbol} borrowed (USD) now", (f"${now_quote_usd:,.2f}" if pd.notna(now_quote_usd) else "N/A"))
    with row2_col5:
        if pd.notna(now_net_value) and float(base_usd) > 0:
            profit = now_net_value - float(base_usd)
            profit_pct = (profit / float(base_usd) * 100.0)
            st.metric("Profit", f"${profit:,.2f}", delta=f"{profit_pct:+.2f}%", delta_color="normal")
        else:
            st.metric("Profit", "N/A")

    # Combined chart
    st.text(f"{base_symbol}/{quote_symbol} spot chart")
    res_for_chart = earn_df.dropna(subset=["base_price", "quote_price"]).copy()
    if not res_for_chart.empty:
        plot_df = res_for_chart.sort_values("time")
        plot_df = plot_df[["time", "base_value_usd", "quote_value_usd", "net_value_usd"]]

        import plotly.graph_objects as go
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["base_value_usd"], name=f"{base_symbol} value (USD)", mode="lines", line=dict(color="#00CC96")))
        fig2.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["quote_value_usd"], name=f"{quote_symbol} borrowed + interest (USD)", mode="lines", line=dict(color="#EF553B")))
        fig2.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["net_value_usd"], name="Net value (USD)", mode="lines", line=dict(color="#636EFA", width=2)))
        fig2.update_layout(height=300, hovermode="x unified", yaxis_title="USD", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Insufficient price data to build 4H chart.")

    # Breakdown table
    show_tbl = st.checkbox("Show earnings breakdown table", value=False, key=f"{base_symbol}_{quote_symbol}_show_tbl")
    if show_tbl:
        resampled = (
            earn_df.groupby("time", as_index=False)
            .agg({
                "base_price": "mean",
                "quote_price": "mean",
                "base_tokens": "last",
                "quote_tokens": "last",
                "base_value_usd": "mean",
                "quote_value_usd": "mean",
                "base_lend_apy": "mean",
                "quote_borrow_apy": "mean",
                "base_interest_usd": "sum",
                "quote_interest_usd": "sum",
                "total_interest_usd": "sum",
                "net_value_usd": "last",
            })
            .sort_values("time")
        )

        tbl = resampled[[
            "time",
            "base_price",
            "quote_price",
            "base_tokens",
            "quote_tokens",
            "base_value_usd",
            "quote_value_usd",
            "net_value_usd",
            "base_lend_apy",
            "quote_borrow_apy",
            "base_interest_usd",
            "quote_interest_usd",
            "total_interest_usd",
        ]].copy()
        tbl = tbl.round({
            "base_price": 6,
            "quote_price": 6,
            "base_tokens": 6,
            "quote_tokens": 6,
            "base_value_usd": 2,
            "quote_value_usd": 2,
            "net_value_usd": 2,
            "base_lend_apy": 4,
            "quote_borrow_apy": 4,
            "base_interest_usd": 2,
            "quote_interest_usd": 2,
            "total_interest_usd": 2,
        })

        st.dataframe(
            tbl,
            use_container_width=True,
            hide_index=True,
            column_config={
                "time": st.column_config.DatetimeColumn("Time", width="small"),
                "base_price": st.column_config.NumberColumn(f"{base_symbol} price", width="small", format="%.6f"),
                "quote_price": st.column_config.NumberColumn(f"{quote_symbol} price", width="small", format="%.6f"),
                "base_tokens": st.column_config.NumberColumn(f"{base_symbol} amount", width="small", format="%.6f"),
                "quote_tokens": st.column_config.NumberColumn(f"{quote_symbol} amount", width="small", format="%.6f"),
                "base_value_usd": st.column_config.NumberColumn(f"{base_symbol} value (USD)", width="small", format="$%.2f"),
                "quote_value_usd": st.column_config.NumberColumn(f"{quote_symbol} borrowed (USD)", width="small", format="$%.2f"),
                "net_value_usd": st.column_config.NumberColumn("Net value (USD)", width="small", format="$%.2f"),
                "base_lend_apy": st.column_config.NumberColumn(f"{base_symbol} APY", width="small", format="%.2f%%"),
                "quote_borrow_apy": st.column_config.NumberColumn(f"{quote_symbol} borrow APY", width="small", format="%.2f%%"),
                "base_interest_usd": st.column_config.NumberColumn(f"{base_symbol} interest (USD)", width="small", format="$%.2f"),
                "quote_interest_usd": st.column_config.NumberColumn(f"{quote_symbol} interest (USD)", width="small", format="$%.2f"),
                "total_interest_usd": st.column_config.NumberColumn("Total interest (USD)", width="small", format="$%.2f"),
            },
        )


def display_weth_cbbtc_strategy_section(token_config: dict) -> None:
    display_pair_strategy_section(token_config, "wETH", "CBBTC")


def display_sol_cbbtc_strategy_section(token_config: dict) -> None:
    display_pair_strategy_section(token_config, "SOL", "CBBTC")


def display_jitosol_cbbtc_strategy_section(token_config: dict) -> None:
    display_pair_strategy_section(token_config, "JitoSOL", "CBBTC")


