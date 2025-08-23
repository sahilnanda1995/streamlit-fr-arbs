from typing import Dict, List, Any

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from api.endpoints import (
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates,
    fetch_hourly_staking,
)
from config.constants import SPOT_PERPS_CONFIG
from config import get_token_config
from data.spot_perps.helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)
from data.spot_perps.spot_history import build_spot_history_series
from data.spot_perps.spot_wallet_short import find_eligible_short_variants, build_wallet_short_series, compute_allocation_split
from data.money_markets_processing import get_staking_rate_by_mint


## Removed legacy local builders in favor of shared implementations


st.set_page_config(page_title="Delta Neutral LST + Spot", layout="wide")

def display_delta_neutral_lst_spot_page() -> None:
    st.title("Delta Neutral LST with Spot")
    st.caption("Compare spot short strategies against a simple wallet LST baseline. SOL-only universe; staking excluded from accrual math.")

    # Data (current rates just for context; not used directly here)
    with st.spinner("Loading data..."):
        _ = fetch_asgard_current_rates()
        staking_data = fetch_asgard_staking_rates()
        token_config = get_token_config()

    # Build eligible short variants (SOL universe only) that have at least 2x short leverage
    eligible_short_variants: Dict[str, Dict[str, Any]] = find_eligible_short_variants(token_config, SPOT_PERPS_CONFIG["SOL_ASSETS"])

    if not eligible_short_variants:
        st.info("No SOL variants have at least 2x short leverage available.")
        return

    # Wallet asset options: Prefer LST tokens (hasStakingYield in token_config); always include SOL as option
    wallet_options: List[str] = []
    for t in SPOT_PERPS_CONFIG["SOL_ASSETS"]:
        info = (token_config.get(t) or {})
        if info.get("hasStakingYield", False) and info.get("mint"):
            wallet_options.append(t)
    # Ensure SOL is available as a wallet option
    if "SOL" in SPOT_PERPS_CONFIG["SOL_ASSETS"] and "SOL" not in wallet_options:
        wallet_options.append("SOL")
    if not wallet_options:
        wallet_options = list(SPOT_PERPS_CONFIG["SOL_ASSETS"])  # fallback

    # Controls
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    def _format_wallet_option(sym: str) -> str:
        if sym == "SOL":
            return "SOL"
        info = (token_config.get(sym) or {})
        if info.get("hasStakingYield") and info.get("mint"):
            apy_dec = get_staking_rate_by_mint(staking_data, info.get("mint")) or 0.0
            try:
                apy_pct = float(apy_dec) * 100.0
            except Exception:
                apy_pct = 0.0
            return f"{sym}({apy_pct:.2f}%)"
        return sym

    with col1:
        wallet_asset = st.selectbox(
            "Wallet asset", options=wallet_options, index=0, key="lst_spot_wallet_asset", format_func=_format_wallet_option,
        )
    with col2:
        short_asset_names = sorted(list(eligible_short_variants.keys()))
        short_asset = st.selectbox(
            "Short asset", options=short_asset_names, index=0, key="lst_spot_short_asset",
        )
    with col3:
        lookback_options = [("1 week", 168), ("2 weeks", 336), ("1 month", 720), ("2 months", 1440), ("3 months", 2160)]
        lookback_labels = [label for label, _ in lookback_options]
        selected_lookback = st.selectbox("Time Period", lookback_labels, index=2, key="lst_spot_lookback")
        limit_hours = dict(lookback_options).get(selected_lookback, 720)
    with col4:
        base_usd = st.number_input("Capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key="lst_spot_base")

    proto = eligible_short_variants[short_asset]["protocol"]
    market = eligible_short_variants[short_asset]["market"]

    # Determine max leverage for short direction from the chosen short pair
    asset_pairs = get_protocol_market_pairs(token_config, short_asset)
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

    default_val = 2.0 if eff_max_f >= 2.0 else eff_max_f
    lev = st.slider(
        "Leverage (short)", min_value=1.0, max_value=float(eff_max_f), value=float(default_val), step=0.5,
        key="lst_spot_leverage",
    )

    # Descriptive caption reflecting capital split and effective short exposure
    _lev_f = float(lev)
    _base_f = float(base_usd)
    _wallet_amt = (max(_lev_f - 1.0, 0.0) / _lev_f) * _base_f if _lev_f > 0 else 0.0
    _used_cap = _base_f - _wallet_amt
    _perps_eff = max(_lev_f - 1.0, 0.0)
    st.markdown(
        f"<p style='font-size:0.9rem; margin-top:-4px; color: gray;'>"
        f"Dividing ${_base_f:,.0f}: ${_wallet_amt:,.0f} to wallet {wallet_asset} and ${_used_cap:,.0f} to short {short_asset} with {_perps_eff:.0f}x exposure to create a delta neutral position"
        f"</p>",
        unsafe_allow_html=True,
    )

    # Build time series
    with st.spinner("Building series..."):
        series = build_wallet_short_series(
            token_config, wallet_asset, short_asset, proto, market, float(lev), int(limit_hours), float(base_usd)
        )
    if series.empty:
        st.info("No historical data available for the selection.")
        return

    plot_df = series.copy()
    first_short_price_series = plot_df["short_asset_price"].dropna()
    start_short_price = float(first_short_price_series.iloc[0]) if not first_short_price_series.empty else float("nan")
    last_row = plot_df.dropna(subset=["wallet_asset_price", "short_asset_price", "usdc_principal_usd", "short_tokens_owed", "close_cost_usd", "net_value_usd", "wallet_value_usd"]).tail(1)

    lev_f = float(lev)
    base_f = float(base_usd)
    wallet_amount_usd, used_capital_usd, initial_short_borrow_usd = compute_allocation_split(base_f, lev_f)
    initial_usdc_lent = base_f

    if not last_row.empty:
        wallet_value_now = float(last_row["wallet_value_usd"].iloc[0])
        usdc_now = float(last_row["usdc_principal_usd"].iloc[0])
        tokens_owed_now = float(last_row["short_tokens_owed"].iloc[0])
        close_cost_now = float(last_row["close_cost_usd"].iloc[0])
        net_value_now = float(last_row["net_value_usd"].iloc[0])

        short_leg_pnl = net_value_now - used_capital_usd
        wallet_pnl = wallet_value_now - wallet_amount_usd
        total_pnl = short_leg_pnl + wallet_pnl

        st.markdown("**Metrics**")
        short_net_initial = float(initial_usdc_lent) - float(initial_short_borrow_usd)
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
            st.metric(f"{wallet_asset} value in wallet (initial)", f"${wallet_amount_usd:,.0f}")
        with w2:
            st.metric(f"{wallet_asset} value in wallet (now)", f"${wallet_value_now:,.0f}")

        # Row 3: Short position metrics
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            st.metric(f"{short_asset} borrowed value in short (initial)", f"${initial_short_borrow_usd:,.0f}")
        with s2:
            st.metric(f"{short_asset} borrowed value in short (now)", f"${close_cost_now:,.0f}")
        with s3:
            st.metric("Short position net value (initial)", f"${short_net_initial:,.0f}")
        with s4:
            st.metric("Short position net value (now)", f"${net_value_now:,.0f}")

    # Spot vs Wallet Staking APY, plus Net APY over time
    with st.spinner("Loading APY series..."):
        spot_rates = build_spot_history_series(token_config, short_asset, proto, market, "short", float(lev), int(limit_hours))
        # Wallet staking series (4H centered)
        wal_info = (token_config.get(wallet_asset) or {})
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
            # 4H centered aggregation
            d["time_4h"] = pd.to_datetime(d["time"]).dt.floor("4h") + pd.Timedelta(hours=2)
            wal_stk = d.groupby("time_4h", as_index=False)[["staking_pct"]].mean().rename(columns={"time_4h": "time"})
        else:
            wal_stk = pd.DataFrame(columns=["time", "staking_pct"])
        # Coerce dtypes and align when missing (e.g., SOL wallet -> zeros)
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
        # Merge series on nearest 4h bucket
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

    # USD values over time (hidden by default)
    show_usd = st.checkbox("Show USD Values Over Time", value=False)
    if show_usd:
        st.subheader("USD Values Over Time")
        fig_vals = go.Figure()
        # Wallet asset value over time
        fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["wallet_value_usd"], name=f"{wallet_asset} wallet (USD)", mode="lines"))
        # Short position net value over time
        fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["net_value_usd"], name="Short net value (USD)", mode="lines"))
        fig_vals.update_layout(height=320, hovermode="x unified", yaxis_title="USD ($)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_vals, use_container_width=True)

    # Breakdown table
    tbl = plot_df[[
        "time", "wallet_asset_price", "short_asset_price", "usdc_principal_usd", "short_tokens_owed", "close_cost_usd",
        "net_value_usd", "wallet_value_usd", "usdc_lend_apy", "asset_borrow_apy", "wallet_stk_pct", "borrow_stk_pct",
    ]].rename(columns={
        "wallet_asset_price": f"{wallet_asset} price (wallet)",
        "short_asset_price": f"{short_asset} price (short)",
        "usdc_principal_usd": "usdc lent",
        "short_tokens_owed": f"{short_asset} borrowed",
        "close_cost_usd": f"{short_asset} borrowed in usd",
        "net_value_usd": "spot position net value",
        "wallet_value_usd": "wallet hodl net value",
        "usdc_lend_apy": "usdc lend apy",
        "asset_borrow_apy": f"{short_asset} borrow apy",
        "wallet_stk_pct": f"{wallet_asset} staking apy",
        "borrow_stk_pct": f"{short_asset} staking apy",
    })
    tbl = tbl.round({
        f"{wallet_asset} price (wallet)": 6,
        f"{short_asset} price (short)": 6,
        "usdc lent": 2,
        f"{short_asset} borrowed": 6,
        f"{short_asset} borrowed in usd": 2,
        "spot position net value": 2,
        "wallet hodl net value": 2,
        "usdc lend apy": 3,
        f"{short_asset} borrow apy": 3,
        f"{wallet_asset} staking apy": 3,
        f"{short_asset} staking apy": 3,
    })
    # Breakdown table (hidden by default)
    show_tbl = st.checkbox("Show breakdown table", value=False)
    if show_tbl:
        st.dataframe(tbl, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    display_delta_neutral_lst_spot_page()


