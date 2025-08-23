from typing import Dict, Any

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from api.endpoints import fetch_hourly_staking
from config.constants import SPOT_PERPS_CONFIG
from config import get_token_config
from data.spot_perps.helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)
from data.spot_perps.spot_history import build_spot_history_series
from data.spot_perps.spot_wallet_short import find_eligible_short_variants, build_wallet_short_series, compute_allocation_split


## Unused legacy helpers removed after refactor to shared builders


st.set_page_config(page_title="Delta Neutral: Spot-only", layout="wide")


def display_delta_neutral_spot_page() -> None:
    st.title("Delta Neutral all on Spot")
    st.caption("Compare spot short strategies against a simple HODL baseline. No perps or funding rates involved.")

    # Data
    with st.spinner("Loading configuration..."):
        token_config = get_token_config()

    # Build eligible asset variants using shared helper
    eligible_variants: Dict[str, Dict[str, Any]] = {}
    for asset_type in ["SOL", "BTC"]:
        variants = SPOT_PERPS_CONFIG["SOL_ASSETS"] if asset_type == "SOL" else SPOT_PERPS_CONFIG["BTC_ASSETS"]
        elig = find_eligible_short_variants(token_config, variants)
        for k, v in elig.items():
            eligible_variants[k] = {"asset_type": asset_type, **v}

    if not eligible_variants:
        st.info("No assets have at least 2x short leverage available.")
        return

    # Controls
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        eligible_names = sorted(list(eligible_variants.keys()))
        selected_variant = st.selectbox(
            "Asset",
            options=eligible_names,
            index=0,
            key="spot_only_asset",
        )
    with col2:
        lookback_options = [("1 week", 168), ("2 weeks", 336), ("1 month", 720), ("2 months", 1440), ("3 months", 2160)]
        lookback_labels = [label for label, _ in lookback_options]
        selected_lookback = st.selectbox("Time Period", lookback_labels, index=2, key="spot_only_lookback")
        limit_hours = dict(lookback_options).get(selected_lookback, 720)
    with col3:
        base_usd = st.number_input("Capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key="spot_only_base")

    variant = selected_variant
    proto = eligible_variants[variant]["protocol"]
    market = eligible_variants[variant]["market"]

    # Determine max leverage for short direction
    asset_pairs = get_protocol_market_pairs(token_config, variant)
    sel_asset_bank, sel_usdc_bank = None, None
    for p, m, bank in asset_pairs:
        if p == proto and (not market or m == market):
            sel_asset_bank = bank
            break
    sel_usdc_bank = get_matching_usdc_bank(token_config, proto, market)
    eff_max = 1.0
    if sel_asset_bank and sel_usdc_bank:
        eff_max = compute_effective_max_leverage(token_config, sel_asset_bank, sel_usdc_bank, "short")
    try:
        eff_max_f = max(float(eff_max or 1.0), 1.0)
    except Exception:
        eff_max_f = 1.0

    with col4:
        # Slider range based on effective max leverage for selected short asset
        default_val = 2.0 if eff_max_f >= 2.0 else eff_max_f
        lev = st.slider(
            "Leverage (short)", min_value=1.0, max_value=float(eff_max_f), value=float(default_val), step=0.5,
            key="spot_only_leverage",
        )
        st.caption(f"Max available short leverage: {eff_max_f:.2f}x")

    # Descriptive caption reflecting capital split and effective short exposure
    _lev_f = float(lev)
    _base_f = float(base_usd)
    _wallet_amt = (max(_lev_f - 1.0, 0.0) / _lev_f) * _base_f if _lev_f > 0 else 0.0
    _used_cap = _base_f - _wallet_amt
    _perps_eff = max(_lev_f - 1.0, 0.0)
    st.markdown(
        f"<p style='font-size:0.9rem; margin-top:-4px; color: #666;'>"
        f"Dividing ${_base_f:,.0f}: ${_wallet_amt:,.0f} on spot holding and ${_used_cap:,.0f} to place short with {_perps_eff:.0f}x exposure to create a delta neutral position"
        f"</p>",
        unsafe_allow_html=True,
    )

    # Build time series
    with st.spinner("Building series..."):
        # Reuse shared series builder with the same asset for wallet and short
        series = build_wallet_short_series(token_config, variant, variant, proto, market, float(lev), int(limit_hours), float(base_usd))
    if series.empty:
        st.info("No historical data available for the selection.")
        return

    # New metrics and table per requirements
    plot_df = series.copy()
    # Derive starting and latest values for cross-checkable PnL metrics
    first_price_series = plot_df["asset_price"].dropna() if "asset_price" in plot_df.columns else plot_df["wallet_asset_price"].dropna()
    start_price = float(first_price_series.iloc[0]) if not first_price_series.empty else float("nan")
    last_row = plot_df.dropna(subset=["usdc_principal_usd", "close_cost_usd", "net_value_usd"]).tail(1)

    lev_f = float(lev)
    base_f = float(base_usd)
    wallet_amount_usd, used_capital_usd, initial_asset_borrow_usd = compute_allocation_split(base_f, lev_f)
    initial_usdc_lent = base_f
    # hodl_tokens0 not required post-refactor

    if not last_row.empty:
        usdc_now = float(last_row["usdc_principal_usd"].iloc[0])
        close_cost_now = float(last_row["close_cost_usd"].iloc[0])
        net_value_now = float(last_row["net_value_usd"].iloc[0])
        hodl_value_now = float(last_row.get("hodl_value_usd", last_row.get("wallet_value_usd", pd.Series([float("nan")]))).iloc[0])

        short_leg_pnl = net_value_now - used_capital_usd
        hodl_pnl = hodl_value_now - wallet_amount_usd
        total_pnl = short_leg_pnl + hodl_pnl

        st.markdown("**Metrics**")
        # Only the requested metrics, plus implied APY after ROE
        short_net_initial = float(initial_usdc_lent) - float(initial_asset_borrow_usd)
        total_hours = float(len(plot_df) * 4.0)
        implied_apy = ((total_pnl / base_f) / (total_hours / (365.0 * 24.0)) * 100.0) if (base_f > 0 and total_hours > 0) else 0.0

        # Row 1: ROE and APY
        r1c1, r1c2 = st.columns([1, 3])
        with r1c1:
            st.metric("ROE", f"${total_pnl:,.2f}", delta=f"{(total_pnl/base_f*100.0):+.2f}%" if base_f > 0 else None)
        with r1c2:
            st.metric("Total APY (implied)", f"{implied_apy:.2f}%")

        # Row 2: Wallet metrics
        w1, w2 = st.columns([1, 3])
        with w1:
            st.metric(f"{variant} value in wallet (initial)", f"${wallet_amount_usd:,.0f}")
        with w2:
            st.metric(f"{variant} value in wallet (now)", f"${hodl_value_now:,.0f}")

        # Row 3: Short position metrics
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            st.metric(f"{variant} borrowed value in short (initial)", f"${initial_asset_borrow_usd:,.0f}")
        with s2:
            st.metric(f"{variant} borrowed value in short (now)", f"${close_cost_now:,.0f}")
        with s3:
            st.metric("Short position net value (initial)", f"${short_net_initial:,.0f}")
        with s4:
            st.metric("Short position net value (now)", f"${net_value_now:,.0f}")

    # USD values over time (hidden by default)
    show_usd = st.checkbox("Show USD Values Over Time", value=False)
    if show_usd:
        st.subheader("USD Values Over Time")
        fig_vals = go.Figure()
        # Wallet asset value over time
        wallet_series = plot_df.get("hodl_value_usd", plot_df.get("wallet_value_usd"))
        fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=wallet_series, name=f"{variant} wallet (USD)", mode="lines"))
        # Short position net value over time
        fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["net_value_usd"], name="Short net value (USD)", mode="lines"))
        fig_vals.update_layout(height=320, hovermode="x unified", yaxis_title="USD ($)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_vals, use_container_width=True)

    # Spot vs Wallet Staking APY, plus Net APY over time
    with st.spinner("Loading APY series..."):
        spot_rates = build_spot_history_series(token_config, variant, proto, market, "short", float(lev), int(limit_hours))
        # Wallet staking series (4H centered); wallet asset == variant
        wal_info = (token_config.get(variant) or {})
        wal_mint = wal_info.get("mint")
        wal_has_stk = bool(wal_info.get("hasStakingYield"))
        if wal_mint and wal_has_stk:
            try:
                stk_raw = fetch_hourly_staking(wal_mint, int(limit_hours)) or []
            except Exception:
                stk_raw = []
        else:
            stk_raw = []
        if stk_raw:
            d = pd.DataFrame(stk_raw)
            d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
            d["staking_pct"] = pd.to_numeric(d.get("avgApy", 0), errors="coerce") * 100.0
            d["time_4h"] = pd.to_datetime(d["time"]).dt.floor("4h") + pd.Timedelta(hours=2)
            wal_stk = d.groupby("time_4h", as_index=False)[["staking_pct"]].mean().rename(columns={"time_4h": "time"})
        else:
            wal_stk = pd.DataFrame(columns=["time", "staking_pct"])
        # Coerce and align
        if not spot_rates.empty:
            spot_rates = spot_rates.sort_values("time").copy()
            spot_rates["time"] = pd.to_datetime(spot_rates["time"], errors="coerce")
        if wal_stk.empty:
            wal_stk = spot_rates[["time"]].copy()
            wal_stk["staking_pct"] = 0.0
        else:
            wal_stk = wal_stk.sort_values("time").copy()
            wal_stk["time"] = pd.to_datetime(wal_stk["time"], errors="coerce")
    if not spot_rates.empty:
        apy_df = pd.merge_asof(
            spot_rates.sort_values("time"),
            wal_stk.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
        )
        apy_df["staking_pct"] = apy_df["staking_pct"].fillna(0.0)
        st.subheader("Long and Short Side APYs")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=apy_df["time"], y=apy_df["staking_pct"], name="Long Side APY (%)", mode="lines"))
        fig.add_trace(go.Scatter(x=apy_df["time"], y=-apy_df["spot_rate_pct"], name="Short Side APY (%)", mode="lines"))
        fig.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Net APY over Time")
        # Weighted by initial capital allocation ratios
        try:
            wallet_ratio = float(wallet_amount_usd) / float(base_usd) if float(base_usd) > 0 else 0.0
            short_ratio = float(used_capital_usd) / float(base_usd) if float(base_usd) > 0 else 0.0
        except Exception:
            wallet_ratio, short_ratio = 0.0, 0.0
        apy_df["net_apy_pct"] = apy_df["staking_pct"].fillna(0.0) * wallet_ratio - apy_df["spot_rate_pct"].fillna(0.0) * short_ratio
        fig_net = go.Figure()
        fig_net.add_trace(go.Scatter(x=apy_df["time"], y=apy_df["net_apy_pct"], name="Net APY (%)", mode="lines", line=dict(color="#16a34a")))
        fig_net.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_net, use_container_width=True)

    # Table with exact columns requested
    # Build table with flexible column names post-refactor
    tbl_cols = ["time", "usdc_principal_usd", "close_cost_usd", "usdc_lend_apy", "asset_borrow_apy", "wallet_stk_pct", "borrow_stk_pct", "net_value_usd"]
    # Include price and tokens if available
    if "asset_price" in plot_df.columns:
        tbl_cols.insert(1, "asset_price")
    elif "wallet_asset_price" in plot_df.columns:
        tbl_cols.insert(1, "wallet_asset_price")
    if "asset_tokens_owed" in plot_df.columns:
        tbl_cols.insert(3, "asset_tokens_owed")
    elif "short_tokens_owed" in plot_df.columns:
        tbl_cols.insert(3, "short_tokens_owed")
    # Include wallet value column
    if "hodl_value_usd" in plot_df.columns:
        tbl_cols.append("hodl_value_usd")
    elif "wallet_value_usd" in plot_df.columns:
        tbl_cols.append("wallet_value_usd")

    tbl = plot_df[tbl_cols].rename(columns={
        "asset_price": f"{variant} price",
        "wallet_asset_price": f"{variant} price",
        "usdc_principal_usd": "usdc lent",
        "asset_tokens_owed": f"{variant} borrowed",
        "short_tokens_owed": f"{variant} borrowed",
        "close_cost_usd": f"{variant} borrowed in usd",
        "usdc_lend_apy": "usdc lent apy",
        "asset_borrow_apy": f"{variant} borrow apy",
        "wallet_stk_pct": f"{variant} wallet staking apy",
        "borrow_stk_pct": f"{variant} borrow staking apy",
        "net_value_usd": "spot position net value",
        "hodl_value_usd": "wallet hodl net value",
        "wallet_value_usd": "wallet hodl net value",
    })
    tbl = tbl.round({
        f"{variant} price": 6,
        "usdc lent": 2,
        f"{variant} borrowed": 6,
        f"{variant} borrowed in usd": 2,
        "usdc lent apy": 3,
        f"{variant} borrow apy": 3,
        f"{variant} wallet staking apy": 3,
        f"{variant} borrow staking apy": 3,
        "spot position net value": 2,
        "wallet hodl net value": 2,
    })
    # Breakdown table (hidden by default)
    show_tbl = st.checkbox("Show breakdown table", value=False)
    if show_tbl:
        st.dataframe(tbl, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    display_delta_neutral_spot_page()


