"""
Shared UI components for Delta Neutral pages.
Extracts common patterns to reduce code duplication.
"""

from typing import Optional, Dict, Any, List
import pandas as pd
import streamlit as st
import plotly.graph_objects as go


def display_delta_neutral_metrics(
    total_pnl: float,
    base_capital: float, 
    implied_apy: float,
    wallet_asset: str,
    wallet_amount_initial: float,
    wallet_value_now: float,
    short_asset: str,
    short_borrow_initial: float,
    short_borrow_now: float,
    short_net_initial: float,
    short_net_now: float,
    show_delta: bool = True
) -> None:
    """
    Display the standard 3-row metrics layout used across Delta Neutral pages.
    
    Args:
        total_pnl: Total profit/loss in USD
        base_capital: Initial capital for percentage calculation
        implied_apy: Calculated implied APY percentage
        wallet_asset: Name of wallet asset (e.g., "SOL", "jito SOL")
        wallet_amount_initial: Initial wallet amount in USD
        wallet_value_now: Current wallet value in USD
        short_asset: Name of short asset (e.g., "SOL", "jito SOL")
        short_borrow_initial: Initial borrowed value in USD
        short_borrow_now: Current borrowed value in USD
        short_net_initial: Initial short position net value in USD
        short_net_now: Current short position net value in USD
        show_delta: Whether to show delta percentage for ROE
    """
    st.markdown("**Metrics**")
    
    # Row 1: ROE and APY
    r1c1, r1c2 = st.columns([1, 3])
    with r1c1:
        delta_str = f"{(total_pnl/base_capital*100.0):+.2f}%" if (show_delta and base_capital > 0) else None
        st.metric("ROE", f"${total_pnl:,.2f}", delta=delta_str)
    with r1c2:
        st.metric("Total APY (implied)", f"{implied_apy:.2f}%")

    # Row 2: Wallet metrics
    w1, w2 = st.columns([1, 3])
    with w1:
        st.metric(f"{wallet_asset} value in wallet (initial)", f"${wallet_amount_initial:,.0f}")
    with w2:
        st.metric(f"{wallet_asset} value in wallet (now)", f"${wallet_value_now:,.0f}")

    # Row 3: Short position metrics
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric(f"{short_asset} borrowed value in short (initial)", f"${short_borrow_initial:,.0f}")
    with s2:
        st.metric(f"{short_asset} borrowed value in short (now)", f"${short_borrow_now:,.0f}")
    with s3:
        st.metric("Short position net value (initial)", f"${short_net_initial:,.0f}")
    with s4:
        st.metric("Short position net value (now)", f"${short_net_now:,.0f}")


def display_apy_chart(
    time_series: pd.Series,
    long_apy_series: pd.Series,
    short_apy_series: pd.Series,
    title: str = "Long and Short Side APYs",
    long_label: str = "Long Side APY (%)",
    short_label: str = "Short Side APY (%)",
    height: int = 300
) -> None:
    """
    Display the standard APY chart with long and short side APY lines.
    
    Args:
        time_series: Time axis data
        long_apy_series: Long side APY percentage values
        short_apy_series: Short side APY percentage values (will be negated if needed)
        title: Chart title
        long_label: Label for long side line
        short_label: Label for short side line
        height: Chart height in pixels
    """
    st.subheader(title)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_series, y=long_apy_series, name=long_label, mode="lines"))
    fig.add_trace(go.Scatter(x=time_series, y=-short_apy_series, name=short_label, mode="lines"))
    fig.update_layout(
        height=height, 
        hovermode="x unified", 
        yaxis_title="APY (%)", 
        margin=dict(l=0, r=0, t=0, b=0)
    )
    st.plotly_chart(fig, use_container_width=True)


def display_net_apy_chart(
    time_series: pd.Series,
    net_apy_series: pd.Series,
    title: str = "Net APY over Time",
    height: int = 300
) -> None:
    """
    Display the standard Net APY chart.
    
    Args:
        time_series: Time axis data
        net_apy_series: Net APY percentage values
        title: Chart title
        height: Chart height in pixels
    """
    st.subheader(title)
    fig_net = go.Figure()
    fig_net.add_trace(go.Scatter(
        x=time_series, 
        y=net_apy_series, 
        name="Net APY (%)", 
        mode="lines", 
        line=dict(color="#16a34a")
    ))
    fig_net.update_layout(
        height=height, 
        hovermode="x unified", 
        yaxis_title="APY (%)", 
        margin=dict(l=0, r=0, t=0, b=0)
    )
    st.plotly_chart(fig_net, use_container_width=True)


def display_usd_values_chart(
    time_series: pd.Series,
    wallet_usd_series: pd.Series,
    position_usd_series: pd.Series,
    wallet_label: str,
    position_label: str,
    title: str = "USD Values Over Time",
    checkbox_label: str = "Show USD Values Over Time",
    additional_series: Optional[Dict[str, pd.Series]] = None,
    show_by_default: bool = False,
    height: int = 320
) -> None:
    """
    Display the optional USD values chart with checkbox toggle.
    
    Args:
        time_series: Time axis data
        wallet_usd_series: Wallet USD value series
        position_usd_series: Position USD value series
        wallet_label: Label for wallet line
        position_label: Label for position line
        title: Chart title
        checkbox_label: Label for the show/hide checkbox
        additional_series: Optional additional series to plot
        show_by_default: Whether checkbox is checked by default
        height: Chart height in pixels
    """
    show_usd = st.checkbox(checkbox_label, value=show_by_default)
    if show_usd:
        st.subheader(title)
        fig_vals = go.Figure()
        fig_vals.add_trace(go.Scatter(x=time_series, y=wallet_usd_series, name=wallet_label, mode="lines"))
        fig_vals.add_trace(go.Scatter(x=time_series, y=position_usd_series, name=position_label, mode="lines"))
        
        # Add any additional series
        if additional_series:
            for label, series in additional_series.items():
                fig_vals.add_trace(go.Scatter(x=time_series, y=series, name=label, mode="lines"))
        
        fig_vals.update_layout(
            height=height, 
            hovermode="x unified", 
            yaxis_title="USD ($)", 
            margin=dict(l=0, r=0, t=0, b=0)
        )
        st.plotly_chart(fig_vals, use_container_width=True)


def display_breakdown_table(
    table_data: pd.DataFrame,
    checkbox_label: str = "Show breakdown table",
    show_by_default: bool = False
) -> None:
    """
    Display the optional breakdown table with checkbox toggle.
    
    Args:
        table_data: DataFrame to display
        checkbox_label: Label for the show/hide checkbox
        show_by_default: Whether checkbox is checked by default
    """
    show_tbl = st.checkbox(checkbox_label, value=show_by_default)
    if show_tbl:
        st.dataframe(table_data, use_container_width=True, hide_index=True)


def display_perps_metrics(
    profit_usd: float,
    total_capital: float,
    implied_apy: float,
    lst_symbol: str,
    lst_usd_start: float,
    lst_usd_now: float,
    perp_notional_start: float,
    perp_position_start: float,
    perp_position_now: float
) -> None:
    """
    Display metrics layout specific to LST + Perps pages.
    
    Args:
        profit_usd: Total profit in USD
        total_capital: Total initial capital
        implied_apy: Calculated implied APY
        lst_symbol: LST token symbol
        lst_usd_start: Initial LST USD value
        lst_usd_now: Current LST USD value
        perp_notional_start: Initial perps notional value
        perp_position_start: Initial perps position MTM value
        perp_position_now: Current perps position MTM value
    """
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("ROE (USD)", f"${profit_usd:,.2f}", delta=f"{(profit_usd/total_capital*100.0):+.2f}%")
    with c2:
        st.metric("Implied APY", f"{implied_apy:.2f}%")
    with c3:
        st.metric(f"{lst_symbol} wallet start (USD)", f"${lst_usd_start:,.2f}")
    with c4:
        st.metric(f"{lst_symbol} wallet now (USD)", f"${lst_usd_now:,.2f}")

    d1, d2, d3 = st.columns(3)
    with d1:
        st.metric("Perp notional start (USD)", f"${perp_notional_start:,.2f}")
    with d2:
        st.metric("Perp position MTM start (USD)", f"${perp_position_start:,.2f}")
    with d3:
        st.metric("Perp position MTM now (USD)", f"${perp_position_now:,.2f}")