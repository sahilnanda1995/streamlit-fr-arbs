from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st

from api.endpoints import (
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates,
    fetch_birdeye_history_price,
)
from config.constants import DEFAULT_TARGET_HOURS, SPOT_PERPS_CONFIG
from config import get_token_config
from data.spot_perps.curated import find_best_spot_rate_across_leverages
from data.spot_perps.helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)
from api.endpoints import fetch_hourly_rates


def _parse_protocol_market(proto_market: str) -> Tuple[str, str]:
    if "(" in proto_market and ")" in proto_market:
        proto = proto_market.split("(")[0]
        market = proto_market.split("(")[1].split(")")[0]
    else:
        proto = proto_market
        market = ""
    return proto, market


def _find_pair_banks(token_config: dict, asset: str, protocol: str, market: str) -> Tuple[Optional[str], Optional[str]]:
    # Find matching asset/usdc banks for protocol+market
    asset_pairs = get_protocol_market_pairs(token_config, asset)
    asset_bank = None
    for p, m, bank in asset_pairs:
        if p == protocol and (not market or m == market):
            asset_bank = bank
            break
    usdc_bank = get_matching_usdc_bank(token_config, protocol, market)
    return asset_bank, usdc_bank


def _build_short_vs_hodl_series(
    token_config: dict,
    asset_symbol: str,
    protocol: str,
    market: str,
    leverage: float,
    points_hours: int,
    base_usd: float,
) -> pd.DataFrame:
    # Fetch hourly lending/borrowing for asset/usdc and aggregate to 4H (centered)
    asset_bank, usdc_bank = _find_pair_banks(token_config, asset_symbol, protocol, market)
    if not asset_bank or not usdc_bank:
        return pd.DataFrame(columns=[
            "time", "usdc_lend_apy", "asset_borrow_apy", "asset_price",
            "usdc_principal_usd", "asset_tokens_owed", "close_cost_usd",
            "net_value_usd", "hodl_value_usd",
        ])

    try:
        asset_hist = fetch_hourly_rates(asset_bank, protocol, int(points_hours)) or []
        usdc_hist = fetch_hourly_rates(usdc_bank, protocol, int(points_hours)) or []
    except Exception:
        asset_hist, usdc_hist = [], []

    def _to_df(records: List[Dict[str, Any]], lend_key: str, borrow_key: str) -> pd.DataFrame:
        if not records:
            return pd.DataFrame(columns=["time", lend_key, borrow_key])
        d = pd.DataFrame(records)
        d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
        d[lend_key] = pd.to_numeric(d.get("avgLendingRate", 0), errors="coerce")
        d[borrow_key] = pd.to_numeric(d.get("avgBorrowingRate", 0), errors="coerce")
        return d[["time", lend_key, borrow_key]].sort_values("time")

    df_asset = _to_df(asset_hist, "asset_lend_apy", "asset_borrow_apy")
    df_usdc = _to_df(usdc_hist, "usdc_lend_apy", "usdc_borrow_apy")

    # Aggregate hourly to 4H centered buckets
    def _agg_4h(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
        if df.empty:
            return df
        d = df.copy()
        d["time_4h"] = d["time"].dt.floor("4H")
        d = (
            d.groupby("time_4h", as_index=False)[cols].mean()
            .assign(time=lambda x: pd.to_datetime(x["time_4h"]) + pd.Timedelta(hours=2))
            .drop(columns=["time_4h"])
        )
        return d

    df_asset_4h = _agg_4h(df_asset, ["asset_lend_apy", "asset_borrow_apy"]) if not df_asset.empty else df_asset
    df_usdc_4h = _agg_4h(df_usdc, ["usdc_lend_apy", "usdc_borrow_apy"]) if not df_usdc.empty else df_usdc
    earn = pd.merge(df_asset_4h, df_usdc_4h, on="time", how="inner")
    if earn.empty:
        return pd.DataFrame(columns=[
            "time", "usdc_lend_apy", "asset_borrow_apy", "asset_price",
            "usdc_principal_usd", "asset_tokens_owed", "close_cost_usd",
            "net_value_usd", "hodl_value_usd",
        ])

    # Price series (4H)
    mint = (token_config.get(asset_symbol, {}) or {}).get("mint")
    start_ts = int(pd.to_datetime(earn["time"].min()).timestamp())
    end_ts = int(pd.to_datetime(earn["time"].max()).timestamp())
    try:
        price_points = fetch_birdeye_history_price(mint, start_ts, end_ts, bucket="4H") if (mint and start_ts and end_ts) else []
    except Exception:
        price_points = []
    price_df = pd.DataFrame(price_points)
    if not price_df.empty:
        price_df["time"] = pd.to_datetime(price_df["t"], unit="s", utc=True).dt.tz_convert(None)
        price_df = price_df.sort_values("time")[ ["time", "price" ] ].rename(columns={"price": "asset_price"})
        earn = pd.merge_asof(earn.sort_values("time"), price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3H"))
    else:
        earn["asset_price"] = float("nan")

    earn = earn.dropna(subset=["asset_price"])  # require price for comparison
    if earn.empty:
        return pd.DataFrame(columns=[
            "time", "usdc_lend_apy", "asset_borrow_apy", "asset_price",
            "usdc_principal_usd", "asset_tokens_owed", "close_cost_usd",
            "net_value_usd", "hodl_value_usd",
        ])

    # Growth factors per 4h bucket
    bucket_factor_4h = 4.0 / (365.0 * 24.0)
    earn = earn.sort_values("time").reset_index(drop=True)
    earn["usdc_growth_factor"] = 1.0 + (earn["usdc_lend_apy"] / 100.0) * bucket_factor_4h
    earn["asset_borrow_growth_factor"] = 1.0 + (earn["asset_borrow_apy"] / 100.0) * bucket_factor_4h
    earn["usdc_growth_cum_shifted"] = earn["usdc_growth_factor"].cumprod().shift(1).fillna(1.0)
    earn["asset_borrow_growth_cum_shifted"] = earn["asset_borrow_growth_factor"].cumprod().shift(1).fillna(1.0)

    # Leverage split per requirement:
    # wallet_amount = (L - 1) / L * T, used_capital = T - wallet_amount = T / L
    # Short position: USDC lent = L * used_capital = T; asset borrowed (USD) = (L - 1) * used_capital = T * (L - 1) / L
    first_price = float(earn["asset_price"].iloc[0]) if not earn["asset_price"].dropna().empty else float("nan")
    lev_f = float(leverage)
    base_f = float(base_usd)
    wallet_amount_usd = (max(lev_f - 1.0, 0.0) / lev_f) * base_f if lev_f > 0 else 0.0
    used_capital_usd = base_f - wallet_amount_usd  # equals base / L
    initial_usdc_lent = base_f  # equals L * used_capital
    initial_asset_borrow_usd = (max(lev_f - 1.0, 0.0) / lev_f) * base_f
    initial_tokens_owed = (initial_asset_borrow_usd / first_price) if (first_price and first_price > 0) else float("nan")

    # Evolve through time
    earn["usdc_principal_usd"] = float(initial_usdc_lent) * earn["usdc_growth_cum_shifted"]
    earn["asset_tokens_owed"] = float(initial_tokens_owed) * earn["asset_borrow_growth_cum_shifted"]
    earn["close_cost_usd"] = earn["asset_tokens_owed"] * earn["asset_price"]
    earn["net_value_usd"] = earn["usdc_principal_usd"] - earn["close_cost_usd"]

    # HODL baseline: wallet holds asset worth wallet_amount_usd
    hodl_tokens = (float(wallet_amount_usd) / first_price) if (first_price and first_price > 0) else float("nan")
    earn["hodl_value_usd"] = hodl_tokens * earn["asset_price"]

    return earn[[
        "time", "usdc_lend_apy", "asset_borrow_apy", "asset_price",
        "usdc_principal_usd", "asset_tokens_owed", "close_cost_usd",
        "net_value_usd", "hodl_value_usd",
    ]]


def display_delta_neutral_spot_page() -> None:
    st.title("Delta Neutral all on Spot (Short vs HODL)")
    st.caption("Compare spot short strategies against a simple HODL baseline. No perps or funding rates involved.")

    # Data
    with st.spinner("Loading data..."):
        rates_data = fetch_asgard_current_rates()
        staking_data = fetch_asgard_staking_rates()
        token_config = get_token_config()

    # Build strategy choices from best SHORT configs per asset
    strategy_options: List[Dict[str, Any]] = []
    for asset_type in ["SOL", "BTC"]:
        variants = SPOT_PERPS_CONFIG["SOL_ASSETS"] if asset_type == "SOL" else SPOT_PERPS_CONFIG["BTC_ASSETS"]
        best = find_best_spot_rate_across_leverages(
            token_config, rates_data, staking_data,
            variants, "short", DEFAULT_TARGET_HOURS, max_leverage=5,
            logger=None,
        )
        if not best:
            continue
        label = f"{best['variant']}/USDC at {float(best['leverage']):.1f}x"
        strategy_options.append({
            "label": label,
            "asset_type": asset_type,
            "best": best,
        })

    if not strategy_options:
        st.info("No valid spot short strategies available.")
        return

    # Controls
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        selected_idx = st.selectbox(
            "Strategy",
            options=list(range(len(strategy_options))),
            format_func=lambda i: strategy_options[i]["label"],
            key="spot_only_strategy",
        )
    with col2:
        lookback_options = [("1 week", 168), ("2 weeks", 336), ("1 month", 720)]
        lookback_labels = [label for label, _ in lookback_options]
        selected_lookback = st.selectbox("Time Period", lookback_labels, index=2, key="spot_only_lookback")
        limit_hours = dict(lookback_options).get(selected_lookback, 720)
    with col3:
        base_usd = st.number_input("Capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key="spot_only_base")

    choice = strategy_options[selected_idx]
    best = choice["best"]
    proto_market = best.get("protocol", "")
    proto, market = _parse_protocol_market(proto_market)
    variant = best.get("variant")

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

    with col4:
        lev = st.slider(
            "Leverage (short)", min_value=1.0, max_value=float(eff_max), value=min(float(best.get("leverage", 2.0)), float(eff_max)), step=0.5,
            key="spot_only_leverage",
        )

    st.caption(f"Using: {variant} • {proto} ({market}) • Short • {lev:.1f}x")

    # Build time series
    with st.spinner("Building series..."):
        series = _build_short_vs_hodl_series(token_config, variant, proto, market, float(lev), int(limit_hours), float(base_usd))
    if series.empty:
        st.info("No historical data available for the selection.")
        return

    # New metrics and table per requirements
    plot_df = series.copy()
    # Derive starting and latest values for cross-checkable PnL metrics
    first_price_series = plot_df["asset_price"].dropna()
    start_price = float(first_price_series.iloc[0]) if not first_price_series.empty else float("nan")
    last_row = plot_df.dropna(subset=["asset_price", "usdc_principal_usd", "asset_tokens_owed", "close_cost_usd", "net_value_usd", "hodl_value_usd"]).tail(1)

    lev_f = float(lev)
    base_f = float(base_usd)
    wallet_amount_usd = (max(lev_f - 1.0, 0.0) / lev_f) * base_f if lev_f > 0 else 0.0
    used_capital_usd = base_f - wallet_amount_usd
    initial_usdc_lent = base_f
    initial_asset_borrow_usd = (max(lev_f - 1.0, 0.0) / lev_f) * base_f
    hodl_tokens0 = (wallet_amount_usd / start_price) if (start_price and start_price > 0) else float("nan")

    if not last_row.empty:
        asset_price_now = float(last_row["asset_price"].iloc[0])
        usdc_now = float(last_row["usdc_principal_usd"].iloc[0])
        tokens_owed_now = float(last_row["asset_tokens_owed"].iloc[0])
        close_cost_now = float(last_row["close_cost_usd"].iloc[0])
        net_value_now = float(last_row["net_value_usd"].iloc[0])
        hodl_value_now = float(last_row["hodl_value_usd"].iloc[0])

        short_leg_pnl = net_value_now - used_capital_usd
        hodl_pnl = hodl_value_now - wallet_amount_usd
        total_pnl = short_leg_pnl + hodl_pnl

        st.markdown("**Metrics**")
        # Only the requested metrics, in the specified order
        short_net_initial = float(initial_usdc_lent) - float(initial_asset_borrow_usd)

        # Row 1
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        with r1c1:
            st.metric("ROE", f"${total_pnl:,.2f}", delta=f"{(total_pnl/base_f*100.0):+.2f}%" if base_f > 0 else None)
        with r1c2:
            st.metric("Asset USD in wallet (initial)", f"${wallet_amount_usd:,.2f}")
        with r1c3:
            st.metric("Asset value in wallet (now)", f"${hodl_value_now:,.2f}")
        with r1c4:
            st.metric("Asset borrowed value in short (initial)", f"${initial_asset_borrow_usd:,.2f}")

        # Row 2
        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            st.metric("Asset borrowed value in short (now)", f"${close_cost_now:,.2f}")
        with r2c2:
            st.metric("Short position net value (initial)", f"${short_net_initial:,.2f}")
        with r2c3:
            st.metric("Short position net value (now)", f"${net_value_now:,.2f}")

    # Table with exact columns requested
    tbl = plot_df[[
        "time", "asset_price", "usdc_principal_usd", "asset_tokens_owed", "close_cost_usd",
        "usdc_lend_apy", "asset_borrow_apy", "net_value_usd", "hodl_value_usd",
    ]].rename(columns={
        "asset_price": "asset price",
        "usdc_principal_usd": "usdc lent",
        "asset_tokens_owed": "asset borrowed",
        "close_cost_usd": "asset borrowed in usd",
        "usdc_lend_apy": "usdc lent apy",
        "asset_borrow_apy": "asset borrow apy",
        "net_value_usd": "spot position net value",
        "hodl_value_usd": "wallet hodl net value",
    })
    tbl = tbl.round({
        "asset price": 6,
        "usdc lent": 2,
        "asset borrowed": 6,
        "asset borrowed in usd": 2,
        "usdc lent apy": 3,
        "asset borrow apy": 3,
        "spot position net value": 2,
        "wallet hodl net value": 2,
    })
    st.dataframe(tbl, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    display_delta_neutral_spot_page()


