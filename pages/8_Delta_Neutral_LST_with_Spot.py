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
from utils.dataframe_utils import aggregate_to_4h_buckets, compute_implied_apy, compute_capital_allocation_ratios, fetch_and_process_staking_series
from utils.delta_neutral_ui import display_delta_neutral_metrics, display_apy_chart, display_net_apy_chart, display_usd_values_chart, display_breakdown_table


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

        short_net_initial = float(initial_usdc_lent) - float(initial_short_borrow_usd)
        total_hours = float(len(plot_df) * 4.0)
        implied_apy = compute_implied_apy(total_pnl, base_f, total_hours)

        display_delta_neutral_metrics(
            total_pnl=total_pnl,
            base_capital=base_f,
            implied_apy=implied_apy,
            wallet_asset=wallet_asset,
            wallet_amount_initial=wallet_amount_usd,
            wallet_value_now=wallet_value_now,
            short_asset=short_asset,
            short_borrow_initial=initial_short_borrow_usd,
            short_borrow_now=close_cost_now,
            short_net_initial=short_net_initial,
            short_net_now=net_value_now
        )

    # Spot vs Wallet Staking APY, plus Net APY over time
    with st.spinner("Loading APY series..."):
        spot_rates = build_spot_history_series(token_config, short_asset, proto, market, "short", float(lev), int(limit_hours))
        # Wallet staking series using shared helper
        wal_stk = fetch_and_process_staking_series(token_config, wallet_asset, limit_hours)
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
        display_apy_chart(
            time_series=apy_df["time"],
            long_apy_series=apy_df["staking_pct"],
            short_apy_series=apy_df["spot_rate_pct"]
        )

        # Weighted by initial capital allocation ratios
        try:
            wallet_ratio, short_ratio = compute_capital_allocation_ratios(
                float(wallet_amount_usd), float(used_capital_usd), float(base_usd)
            )
        except Exception:
            wallet_ratio, short_ratio = 0.0, 0.0
        apy_df["net_apy_pct"] = apy_df["staking_pct"].fillna(0.0) * wallet_ratio - apy_df["spot_rate_pct"].fillna(0.0) * short_ratio
        
        display_net_apy_chart(
            time_series=apy_df["time"],
            net_apy_series=apy_df["net_apy_pct"]
        )

    # USD values over time (hidden by default)
    display_usd_values_chart(
        time_series=plot_df["time"],
        wallet_usd_series=plot_df["wallet_value_usd"],
        position_usd_series=plot_df["net_value_usd"],
        wallet_label=f"{wallet_asset} wallet (USD)",
        position_label="Short net value (USD)"
    )

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
    display_breakdown_table(tbl)


if __name__ == "__main__":
    display_delta_neutral_lst_spot_page()


