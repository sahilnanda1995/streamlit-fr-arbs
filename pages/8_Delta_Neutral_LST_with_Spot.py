from typing import Dict, List, Any

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from api.endpoints import (
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates,
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
    col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
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
        selected_lookback = st.selectbox("Time Period", lookback_labels, index=3, key="lst_spot_lookback")
        limit_hours = dict(lookback_options).get(selected_lookback, 1440)
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
    st.caption(f"Max available short leverage: {eff_max_f:.2f}x")

    # Descriptive caption reflecting capital split and effective short exposure
    _lev_f = float(lev)
    _base_f = float(base_usd)
    _wallet_amt = (max(_lev_f - 1.0, 0.0) / _lev_f) * _base_f if _lev_f > 0 else 0.0
    _used_cap = _base_f - _wallet_amt
    _perps_eff = max(_lev_f - 1.0, 0.0)
    st.markdown(
        f"<p style='font-size:0.9rem; margin-top:-4px; color: #666;'>"
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

        # Row 1
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        with r1c1:
            st.metric("ROE", f"${total_pnl:,.2f}", delta=f"{(total_pnl/base_f*100.0):+.2f}%" if base_f > 0 else None)
        with r1c2:
            st.metric("Total APY (implied)", f"{implied_apy:.2f}%")
        with r1c3:
            st.metric(f"{wallet_asset} value in wallet (initial)", f"${wallet_amount_usd:,.0f}")
        with r1c4:
            st.metric(f"{wallet_asset} value in wallet (now)", f"${wallet_value_now:,.0f}")

        # Row 2
        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        with r2c1:
            st.metric(f"{short_asset} borrowed value in short (initial)", f"${initial_short_borrow_usd:,.0f}")
        with r2c2:
            st.metric(f"{short_asset} borrowed value in short (now)", f"${close_cost_now:,.0f}")
        with r2c3:
            st.metric("Short position net value (initial)", f"${short_net_initial:,.0f}")
        with r2c4:
            st.metric("Short position net value (now)", f"${net_value_now:,.0f}")

    # Spot rate APY over time for the SHORT asset (negated), calculations unaffected
    with st.spinner("Loading spot rates..."):
        spot_rates = build_spot_history_series(token_config, short_asset, proto, market, "short", float(lev), int(limit_hours))
    if not spot_rates.empty:
        st.subheader("Spot Rate APY over Time (Short asset)")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=spot_rates["time"], y=-spot_rates["spot_rate_pct"], name=f"{short_asset} Spot APY (negated, %)", mode="lines"))
        fig.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # USD values over time
    st.subheader("USD Values Over Time")
    fig_vals = go.Figure()
    # Wallet asset value over time
    fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["wallet_value_usd"], name=f"{wallet_asset} wallet (USD)", mode="lines"))
    # Borrowed asset value (USD close cost)
    fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["close_cost_usd"], name=f"{short_asset} borrowed (USD)", mode="lines"))
    # Short position net value over time
    fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=plot_df["net_value_usd"], name="Short net value (USD)", mode="lines"))
    # User total net value = wallet + short net
    fig_vals.add_trace(go.Scatter(x=plot_df["time"], y=(plot_df["wallet_value_usd"] + plot_df["net_value_usd"]), name="Portfolio total (USD)", mode="lines", line=dict(color="#16a34a")))
    fig_vals.update_layout(height=320, hovermode="x unified", yaxis_title="USD ($)", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig_vals, use_container_width=True)

    # Breakdown table
    tbl = plot_df[[
        "time", "wallet_asset_price", "short_asset_price", "usdc_principal_usd", "short_tokens_owed", "close_cost_usd",
        "net_value_usd", "wallet_value_usd",
    ]].rename(columns={
        "wallet_asset_price": f"{wallet_asset} price (wallet)",
        "short_asset_price": f"{short_asset} price (short)",
        "usdc_principal_usd": "usdc lent",
        "short_tokens_owed": f"{short_asset} borrowed",
        "close_cost_usd": f"{short_asset} borrowed in usd",
        "net_value_usd": "spot position net value",
        "wallet_value_usd": "wallet hodl net value",
    })
    tbl = tbl.round({
        f"{wallet_asset} price (wallet)": 6,
        f"{short_asset} price (short)": 6,
        "usdc lent": 2,
        f"{short_asset} borrowed": 6,
        f"{short_asset} borrowed in usd": 2,
        "spot position net value": 2,
        "wallet hodl net value": 2,
    })
    st.dataframe(tbl, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    display_delta_neutral_lst_spot_page()


