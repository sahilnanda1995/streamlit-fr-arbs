"""
Custom Backtesting: interactively backtest any SOL/BTC spot-variant strategy.
Lets you choose variant, protocol/market, direction, leverage, perps exchange, and lookback.
"""

import streamlit as st
import pandas as pd

from config import get_token_config
from config.constants import ASSET_VARIANTS
from data.spot_perps.spot_history import build_arb_history_series
from data.spot_perps.backtesting_utils import (
    prepare_display_series,
    compute_earnings_and_implied_apy,
    build_breakdown_table_df,
    style_breakdown_table,
)
from data.spot_perps.helpers import get_protocol_market_pairs


def _get_variant_choices(asset_type: str) -> list:
    return ASSET_VARIANTS.get(asset_type, [])


def _get_protocol_market_options(token_config: dict, variant: str) -> list:
    pairs = get_protocol_market_pairs(token_config, variant)
    # unique (protocol, market) in stable order
    seen = set()
    opts = []
    for proto, market, _ in pairs:
        key = (proto, market)
        if key not in seen:
            seen.add(key)
            opts.append(key)
    return opts


def main():
    st.set_page_config(page_title="Custom Backtesting", layout="wide")
    st.title("🧪 Custom Backtesting")
    st.write("Backtest any SOL/BTC spot-variant strategy with configurable parameters.")

    token_config = get_token_config()

    # Controls
    col_a, col_b, col_c = st.columns([1, 1, 1])
    with col_a:
        asset_type = st.selectbox("Asset Type", ["SOL", "BTC"], index=0)

    variants = _get_variant_choices(asset_type)
    if not variants:
        st.info("No variants available for the selected asset type.")
        return

    with col_b:
        variant = st.selectbox("Spot Variant", variants, index=0)

    proto_market_options = _get_protocol_market_options(token_config, variant)
    if not proto_market_options:
        st.info("No protocol/market pairs available for this variant.")
        return

    with col_c:
        selected_pair = st.selectbox(
            "Protocol / Market",
            options=[f"{p} ({m})" for p, m in proto_market_options],
            index=0,
        )
    # Parse back protocol and market
    if "(" in selected_pair and ")" in selected_pair:
        protocol = selected_pair.split("(")[0].strip()
        market = selected_pair.split("(")[1].split(")")[0].strip()
    else:
        protocol = selected_pair
        market = ""

    col_d, col_e, col_f = st.columns([1, 1, 1])
    with col_d:
        direction_label = st.selectbox("Direction", ["Long", "Short"], index=0)
        dir_lower = direction_label.lower()
    with col_e:
        leverage = st.slider("Leverage", min_value=1.0, max_value=5.0, value=2.0, step=0.5)
    with col_f:
        perps_exchange = st.selectbox("Perps Exchange", ["Hyperliquid", "Drift"], index=0)

    row2_a, row2_b = st.columns([1, 1])
    with row2_a:
        lookback_options = [("1 week", 168), ("2 weeks", 336), ("1 month", 720)]
        lookback_labels = [label for label, _ in lookback_options]
        selected_lookback = st.selectbox("Time Period", lookback_labels, index=2)
        limit = dict(lookback_options).get(selected_lookback, 720)
    with row2_b:
        total_cap = st.number_input("Total capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0)

    # Build series
    with st.spinner("Loading historical series..."):
        series_df = build_arb_history_series(
            token_config, variant, protocol, market, dir_lower, float(leverage), perps_exchange, int(limit)
        )

    if series_df.empty:
        st.info("No historical data available for the selection.")
        return

    # Plot series (display-only inversions consistent with backtesting page)
    import plotly.graph_objects as go

    df_plot = prepare_display_series(series_df, dir_lower)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["spot_rate_pct_display"], name="Spot %", mode="lines"))
    fig.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["funding_pct_display"], name="Perps %", mode="lines"))
    fig.add_trace(go.Scatter(x=df_plot["time"], y=df_plot["net_arb_pct_display"], name="Net Arb %", mode="lines", line=dict(color="#16a34a")))
    fig.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Series: Spot Rate (APY%), Perps Funding (APY%), Net Arb (APY%) per 4 hours")

    # Earnings calculator (same semantics as backtesting page)
    st.subheader("💰 Earnings Calculator")
    # Match existing backtesting: allocate half to spot (no leverage) and half to perps times leverage
    df_calc, spot_cap, perps_cap, implied_apy = compute_earnings_and_implied_apy(df_plot, dir_lower, total_cap, float(leverage))

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
    tbl = build_breakdown_table_df(df_calc, dir_lower)
    styled_tbl = style_breakdown_table(tbl)
    st.dataframe(styled_tbl, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()


