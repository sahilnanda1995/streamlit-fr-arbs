"""
Funding Rates page.
"""

import streamlit as st
import pandas as pd
from config.constants import (
    INTERVAL_OPTIONS,
    APP_TITLE,
    APP_DESCRIPTION,
    PAGE_TITLE
)
from api.endpoints import (
    fetch_loris_funding_data,
    fetch_drift_markets_24h,
)
from data.spot_perps.backtesting import _fetch_last_month_with_gap_check, _to_dataframe, _get_last_month_window_seconds
from api.endpoints import fetch_drift_funding_history
from config.constants import DRIFT_MARKET_INDEX
from data.processing import merge_funding_rate_data
from utils.formatting import (
    process_raw_data_for_display,
    create_styled_dataframe,
    format_dataframe_for_display
)


def main():
    """Main page logic for Funding Rates."""
    st.set_page_config(page_title="Historical Funding Rates", layout="wide")
    st.title("📈 Historical Funding Rates")
    st.write("Compare perpetual funding rates across exchanges with flexible time intervals.")

    # === DATA FETCHING ===
    from utils.funding_data_utils import display_funding_data_loading_section, handle_funding_data_error
    
    hyperliquid_data, drift_data = display_funding_data_loading_section()
    if hyperliquid_data is None or drift_data is None:
        return

    # === PERPS DATA MERGING ===
    merged_perps_data = merge_funding_rate_data(hyperliquid_data, drift_data)

    selected_interval = st.selectbox(
        "Select target funding interval:",
        list(INTERVAL_OPTIONS.keys()),
        index=0  # Default to 1 yr
    )
    target_hours = INTERVAL_OPTIONS[selected_interval]

    # Use the pre-merged perps data
    if not merged_perps_data:
        handle_funding_data_error()
    formatted_data = process_raw_data_for_display(merged_perps_data, target_hours)
    df = create_styled_dataframe(formatted_data)
    st.subheader(f"Funding Rates (%), scaled to {selected_interval}")
    styled_df = format_dataframe_for_display(df)
    st.dataframe(styled_df)
    from utils.funding_data_utils import display_funding_data_debug_section
    display_funding_data_debug_section(hyperliquid_data, drift_data)

    st.divider()
    st.subheader("📈 Historical Funding (1M)")
    col_hl, col_drift = st.columns(2)

    with col_hl:
        st.markdown("**Hyperliquid**")
        coin = st.selectbox("HL coin", ["SOL", "BTC"], index=0, key="fund_hl_coin")
        with st.spinner("Loading HL history..."):
            hl_hist = _fetch_last_month_with_gap_check(coin)
        df_hl = _to_dataframe(hl_hist, rate_key="fundingRate")
        if df_hl.empty:
            st.info("No Hyperliquid history available.")
        else:
            import plotly.graph_objects as go
            dfp = df_hl.copy()
            dfp["time"] = pd.to_datetime(dfp["time"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=dfp["time"], y=dfp["fundingRate"], name="Funding %", mode="lines"))
            fig.update_layout(height=260, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Hyperliquid funding APY (%)")
            mean_rate = dfp["fundingRate"].mean()
            median_rate = dfp["fundingRate"].median()
            st.caption(f"Mean: {mean_rate:.2f}% • Median: {median_rate:.2f}%")

    with col_drift:
        st.markdown("**Drift**")
        coin = st.selectbox("Drift coin", ["SOL", "BTC"], index=0, key="fund_drift_coin")
        idx = DRIFT_MARKET_INDEX.get(coin, 0)
        start_ts, end_ts = _get_last_month_window_seconds()
        with st.spinner("Loading Drift history..."):
            drift_hist = fetch_drift_funding_history(idx, start_ts, end_ts)
        df_drift = _to_dataframe(drift_hist, rate_key="fundingRate")
        if df_drift.empty:
            st.info("No Drift history available.")
        else:
            import plotly.graph_objects as go
            dfp = df_drift.copy()
            dfp["time"] = pd.to_datetime(dfp["time"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=dfp["time"], y=dfp["fundingRate"], name="Funding %", mode="lines"))
            fig.update_layout(height=260, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Drift funding APY (%)")
            mean_rate = dfp["fundingRate"].mean()
            median_rate = dfp["fundingRate"].median()
            st.caption(f"Mean: {mean_rate:.2f}% • Median: {median_rate:.2f}%")


if __name__ == "__main__":
    main()
