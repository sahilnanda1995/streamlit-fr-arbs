from typing import Dict, Any, List, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from config import get_token_config
from config.constants import ASSET_VARIANTS
from api.endpoints import (
    fetch_birdeye_history_price,
    fetch_hourly_staking,
)
from data.spot_perps.spot_history import build_perps_history_series, build_spot_history_series
from data.spot_perps.spot_wallet_short import (
    find_eligible_short_variants,
    build_wallet_short_series,
    compute_allocation_split,
)
from data.spot_perps.helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)
from utils.dataframe_utils import aggregate_to_4h_buckets, compute_implied_apy, compute_capital_allocation_ratios
from utils.delta_neutral_ui import display_delta_neutral_metrics, display_apy_chart, display_net_apy_chart, display_usd_values_chart, display_breakdown_table


st.set_page_config(page_title="Delta Neutral: LST + Spot and LST + Perps", layout="wide")




def _build_perps_breakdown(
    price_df: pd.DataFrame,
    staking_df: pd.DataFrame,
    funding_df: pd.DataFrame,
    sol_price_df: pd.DataFrame,
    total_capital_usd: float,
    leverage: float,
) -> pd.DataFrame:
    L = max(float(leverage), 1.0)
    wallet_usd = float(total_capital_usd) * L / (L + 1.0)
    perps_capital_initial = float(total_capital_usd) - wallet_usd
    perp_short_notional_usd = perps_capital_initial * L

    base = price_df.copy()
    if base.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])

    merged = pd.merge_asof(base.sort_values("time"), staking_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
    merged = pd.merge_asof(merged.sort_values("time"), funding_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
    merged = pd.merge_asof(merged.sort_values("time"), sol_price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
    merged = merged.dropna(subset=["price"])  # require LST price
    if merged.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])

    first_price = float(pd.to_numeric(merged["price"], errors="coerce").dropna().iloc[0])
    lst_tokens = (wallet_usd / first_price) if first_price > 0 else 0.0

    merged = merged.dropna(subset=["sol_price"])  # require SOL price
    if merged.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])
    first_sol_price = float(pd.to_numeric(merged["sol_price"], errors="coerce").dropna().iloc[0]) if "sol_price" in merged.columns else float("nan")
    sol_size = (float(perp_short_notional_usd) / first_sol_price) if (first_sol_price and first_sol_price > 0) else 0.0

    out = merged.copy()
    out = out.rename(columns={"price": "lst_token_price"})
    out["lst_token_amount"] = float(lst_tokens)
    out["lst_token_amount_usd"] = out["lst_token_amount"] * out["lst_token_price"]
    out["perp_sol_amount"] = float(sol_size)
    out["perp_sol_amount_usd"] = out["perp_sol_amount"] * pd.to_numeric(out.get("sol_price", 0), errors="coerce").fillna(0.0)
    bucket_factor = 4.0 / (365.0 * 24.0)
    out["perp_apy"] = pd.to_numeric(out.get("funding_pct", 0), errors="coerce").fillna(0.0)
    out["perp_interest"] = float(perp_short_notional_usd) * (out["perp_apy"] / 100.0) * bucket_factor
    out["perp_usd_accumulated"] = out["perp_interest"].cumsum()
    out["perp_pnl_price"] = float(sol_size) * (float(first_sol_price) - pd.to_numeric(out.get("sol_price", 0), errors="coerce").fillna(0.0))
    out["perp_position_value"] = float(perps_capital_initial) + out["perp_pnl_price"]
    out["perp_wallet_value"] = out["perp_position_value"] + out["perp_usd_accumulated"]
    out["net_value"] = out["lst_token_amount_usd"] + out["perp_position_value"] + out["perp_usd_accumulated"]

    cols = [
        "time",
        "lst_token_amount",
        "lst_token_price",
        "lst_token_amount_usd",
        "wallet_initial_usd",
        "perp_capital_initial_usd",
        "perp_short_notional_usd",
        "perp_position_value",
        "perp_wallet_value",
        "sol_price",
        "perp_sol_amount",
        "perp_sol_amount_usd",
        "perp_apy",
        "perp_interest",
        "perp_usd_accumulated",
        "net_value",
    ]
    out["wallet_initial_usd"] = float(wallet_usd)
    out["perp_capital_initial_usd"] = float(perps_capital_initial)
    out["perp_short_notional_usd"] = float(perp_short_notional_usd)
    out = out[cols].copy()
    return out


def main():
    st.title("Delta Neutral: LST + Spot and LST + Perps")

    token_config = get_token_config()

    # Global controls
    col_a, col_b = st.columns([1, 1])
    with col_a:
        lookback_choice = st.selectbox("Time Period", ["1 week", "2 weeks", "1 month", "2 months", "3 months"], index=2)
        lookback_map = {"1 week": 168, "2 weeks": 336, "1 month": 720, "2 months": 1440, "3 months": 2160}
        lookback_hours = int(lookback_map.get(lookback_choice, 720))
    with col_b:
        total_capital = st.number_input("Total Capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0)

    st.markdown("---")

    # Section 1: LST + Spot
    st.subheader("Delta Neutral LST with Spot")
    # Eligible short variants (SOL only)
    eligible_short_variants = find_eligible_short_variants(token_config, ASSET_VARIANTS.get("SOL", []))
    if not eligible_short_variants:
        st.info("No SOL variants have at least 2x short leverage available.")
    else:
        # Wallet options (prefer LSTs) and include SOL
        wallet_options: List[str] = []
        for t in ASSET_VARIANTS.get("SOL", []):
            info = (token_config.get(t) or {})
            if info.get("hasStakingYield", False) and info.get("mint"):
                wallet_options.append(t)
        if "SOL" in ASSET_VARIANTS.get("SOL", []) and "SOL" not in wallet_options:
            wallet_options.append("SOL")
        if not wallet_options:
            wallet_options = list(ASSET_VARIANTS.get("SOL", []))

        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            wallet_asset = st.selectbox("Wallet asset", wallet_options, index=0)
        with col2:
            short_asset = st.selectbox("Short asset", sorted(list(eligible_short_variants.keys())), index=0)
        with col3:
            base_usd_spot = total_capital

        # Leverage bounds for short asset
        proto = eligible_short_variants[short_asset]["protocol"]
        market = eligible_short_variants[short_asset]["market"]
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
        lev_spot = st.slider("Leverage (short)", min_value=1.0, max_value=float(eff_max_f), value=float(2.0 if eff_max_f >= 2.0 else eff_max_f), step=0.5, key="combined_spot_lev")
        st.caption(f"Max available short leverage: {eff_max_f:.2f}x")

        # Build series and metrics
        with st.spinner("Building LST+Spot series..."):
            series_spot = build_wallet_short_series(token_config, wallet_asset, short_asset, proto, market, float(lev_spot), int(lookback_hours), float(base_usd_spot))
        if series_spot.empty:
            st.info("No historical data available for LST + Spot selection.")
        else:
            # APY series for chart and net APY
            with st.spinner("Loading APY series (LST+Spot)..."):
                spot_rates = build_spot_history_series(token_config, short_asset, proto, market, "short", float(lev_spot), int(lookback_hours))
                wal_info = (token_config.get(wallet_asset) or {})
                wal_mint = wal_info.get("mint")
                wal_has_stk = bool(wal_info.get("hasStakingYield"))
                if wal_mint and wal_has_stk:
                    try:
                        stk_raw = fetch_hourly_staking(wal_mint, int(lookback_hours)) or []
                    except Exception:
                        stk_raw = []
                else:
                    stk_raw = []
                if stk_raw:
                    d = pd.DataFrame(stk_raw)
                    d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
                    d["staking_pct"] = pd.to_numeric(d.get("avgApy", 0), errors="coerce") * 100.0
                    wal_stk = aggregate_to_4h_buckets(d, "time", ["staking_pct"])
                else:
                    wal_stk = spot_rates[["time"]].copy() if not spot_rates.empty else pd.DataFrame(columns=["time"])
                    wal_stk["staking_pct"] = 0.0
                # Align
                if not spot_rates.empty:
                    spot_rates = spot_rates.sort_values("time").copy()
                    spot_rates["time"] = pd.to_datetime(spot_rates["time"], errors="coerce")
                wal_stk = wal_stk.sort_values("time").copy()
                wal_stk["time"] = pd.to_datetime(wal_stk["time"], errors="coerce")
                apy_df_spot = pd.merge_asof(spot_rates, wal_stk, on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
                apy_df_spot["staking_pct"] = apy_df_spot["staking_pct"].fillna(0.0)

            # Metrics rows (reuse layout from dedicated page)
            last_row = series_spot.dropna(subset=["usdc_principal_usd", "close_cost_usd", "net_value_usd"]).tail(1)
            wallet_amount_usd, used_capital_usd, _short_usd = compute_allocation_split(float(base_usd_spot), float(lev_spot))
            hodl_now = float(last_row.get("wallet_value_usd", pd.Series([0.0])).iloc[0]) if not last_row.empty else 0.0
            net_now = float(last_row.get("net_value_usd", pd.Series([0.0])).iloc[0]) if not last_row.empty else 0.0
            short_net_initial = float(base_usd_spot) - float(_short_usd)
            total_hours = float(len(series_spot) * 4.0)
            total_pnl = (hodl_now - wallet_amount_usd) + (net_now - (float(base_usd_spot) - wallet_amount_usd))
            implied_apy_spot = compute_implied_apy(total_pnl, float(base_usd_spot), total_hours)

            display_delta_neutral_metrics(
                total_pnl=total_pnl,
                base_capital=float(base_usd_spot),
                implied_apy=implied_apy_spot,
                wallet_asset=wallet_asset,
                wallet_amount_initial=wallet_amount_usd,
                wallet_value_now=hodl_now,
                short_asset=short_asset,
                short_borrow_initial=_short_usd,
                short_borrow_now=float(last_row.get('close_cost_usd', pd.Series([0.0])).iloc[0]) if not last_row.empty else 0.0,
                short_net_initial=short_net_initial,
                short_net_now=net_now,
                show_delta=False
            )

            # APY charts for LST+Spot
            if not apy_df_spot.empty:
                display_apy_chart(
                    time_series=apy_df_spot["time"],
                    long_apy_series=apy_df_spot["staking_pct"],
                    short_apy_series=apy_df_spot["spot_rate_pct"],
                    title="Long and Short Side APYs (LST+Spot)"
                )

                # Net APY over Time (weighted)
                try:
                    wallet_ratio_spot = float(wallet_amount_usd) / float(base_usd_spot) if float(base_usd_spot) > 0 else 0.0
                    short_ratio_spot = float(used_capital_usd) / float(base_usd_spot) if float(base_usd_spot) > 0 else 0.0
                except Exception:
                    wallet_ratio_spot, short_ratio_spot = 0.0, 0.0
                apy_df_spot["net_apy_pct"] = apy_df_spot["staking_pct"].fillna(0.0) * wallet_ratio_spot - apy_df_spot["spot_rate_pct"].fillna(0.0) * short_ratio_spot
                
                display_net_apy_chart(
                    time_series=apy_df_spot["time"],
                    net_apy_series=apy_df_spot["net_apy_pct"],
                    title="Net APY over Time (LST+Spot)"
                )

            # USD values and breakdown (hidden by default) for LST+Spot
            display_usd_values_chart(
                time_series=series_spot["time"],
                wallet_usd_series=series_spot["wallet_value_usd"],
                position_usd_series=series_spot["net_value_usd"],
                wallet_label=f"{wallet_asset} wallet (USD)",
                position_label="Short net value (USD)",
                title="USD Values Over Time (LST+Spot)",
                checkbox_label="Show USD Values Over Time (LST+Spot)"
            )

            tbl_spot = series_spot[[
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
            tbl_spot = tbl_spot.round({
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
            display_breakdown_table(tbl_spot, "Show breakdown table (LST+Spot)")

    st.markdown("---")

    # Section 2: LST + Perps
    st.subheader("Delta Neutral with LST and Perps")
    lst_options = [t for t in ASSET_VARIANTS.get("SOL", []) if (token_config.get(t) or {}).get("mint")]
    colp1, colp2, colp3 = st.columns([1, 1, 1])
    with colp1:
        lst_symbol = st.selectbox("LST Token", lst_options, index=0)
    with colp2:
        perps_exchange = st.selectbox("Perps Exchange", ["Hyperliquid", "Drift"], index=0)
    with colp3:
        leverage = st.slider("Perps leverage", min_value=1.0, max_value=5.0, value=2.0, step=0.5, key="combined_perps_lev")

    with st.spinner("Loading LST + Perps series..."):
        try:
            # Get time range
            end_ts = pd.Timestamp.utcnow()
            start_ts = end_ts - pd.Timedelta(hours=int(lookback_hours))
            start = int(start_ts.timestamp())
            end = int(end_ts.timestamp())
            
            # LST price using existing API
            info = token_config.get(lst_symbol, {}) or {}
            lst_mint = info.get("mint")
            if lst_mint:
                price_points = fetch_birdeye_history_price(lst_mint, start, end, bucket="4H") or []
                lst_price_df = pd.DataFrame(price_points)
                if not lst_price_df.empty:
                    lst_price_df["time"] = pd.to_datetime(lst_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
                    lst_price_df = lst_price_df.sort_values("time")[["time", "price"]]
                else:
                    lst_price_df = pd.DataFrame(columns=["time", "price"])
            else:
                lst_price_df = pd.DataFrame(columns=["time", "price"])
                
            # LST staking using existing utilities
            if lst_mint and info.get("hasStakingYield"):
                staking_raw = fetch_hourly_staking(lst_mint, int(lookback_hours)) or []
                if staking_raw:
                    d = pd.DataFrame(staking_raw)
                    d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
                    d["staking_pct"] = pd.to_numeric(d.get("avgApy", 0), errors="coerce") * 100.0
                    # 4H centered aggregation
                    lst_staking_df = aggregate_to_4h_buckets(d, "time", ["staking_pct"])
                else:
                    lst_staking_df = pd.DataFrame(columns=["time", "staking_pct"])
            else:
                lst_staking_df = pd.DataFrame(columns=["time", "staking_pct"])
                
            # SOL price using existing API
            sol_mint = (token_config.get("SOL", {}) or {}).get("mint")
            if sol_mint:
                sol_points = fetch_birdeye_history_price(sol_mint, start, end, bucket="4H") or []
                sol_price_df = pd.DataFrame(sol_points)
                if not sol_price_df.empty:
                    sol_price_df["time"] = pd.to_datetime(sol_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
                    sol_price_df = sol_price_df.sort_values("time")[["time", "price"]].rename(columns={"price": "sol_price"})
                else:
                    sol_price_df = pd.DataFrame(columns=["time", "sol_price"])
            else:
                sol_price_df = pd.DataFrame(columns=["time", "sol_price"])
                
            # Funding series using existing builder
            funding_df = build_perps_history_series(perps_exchange, "SOL", lookback_hours)
            
        except Exception as e:
            st.error(f"Failed to load historical series: {e}")
            return
    # If SOL is selected as LST, force staking to zero over funding timeline
    try:
        if lst_symbol == "SOL" and not funding_df.empty:
            lst_staking_df = funding_df[["time"]].copy()
            lst_staking_df["staking_pct"] = 0.0
    except Exception:
        pass
    if lst_price_df.empty or funding_df.empty or sol_price_df.empty:
        st.warning("Required data is currently unavailable for LST + Perps.")
    else:
        # Build APY chart (ensure time dtype alignment)
        funding_df = funding_df.sort_values("time").copy()
        funding_df["time"] = pd.to_datetime(funding_df["time"], errors="coerce")
        lst_staking_df = lst_staking_df.sort_values("time").copy()
        lst_staking_df["time"] = pd.to_datetime(lst_staking_df["time"], errors="coerce")
        df_apys = pd.merge_asof(
            funding_df,
            lst_staking_df, on="time", direction="nearest", tolerance=pd.Timedelta("3h")
        )
        df_apys = df_apys.dropna(subset=["funding_pct", "staking_pct"])  # require both present
        if df_apys.empty:
            st.info("Staking data not available for selected period.")
        else:
            display_apy_chart(
                time_series=df_apys["time"],
                long_apy_series=df_apys["staking_pct"],
                short_apy_series=-df_apys["funding_pct"],  # Note: funding already includes sign
                short_label="Short Side APY (%)"
            )

        # Net APY for LST+Perps (weighted by initial capital and short notional exposure)
        L = max(float(leverage), 1.0)
        wallet_usd = float(total_capital) * L / (L + 1.0)
        perps_capital_initial = float(total_capital) - wallet_usd
        perp_short_notional_usd = perps_capital_initial * L
        wallet_ratio = wallet_usd / float(total_capital) if float(total_capital) > 0 else 0.0
        short_exposure_ratio = perp_short_notional_usd / float(total_capital) if float(total_capital) > 0 else 0.0
        df_apys_perps = df_apys.copy()
        df_apys_perps["net_apy_pct"] = (
            df_apys_perps["staking_pct"].fillna(0.0) * wallet_ratio
            + df_apys_perps["funding_pct"].fillna(0.0) * short_exposure_ratio
        )

        # USD values and breakdown (hidden by default) for LST+Perps
        series_perps = _build_perps_breakdown(lst_price_df, lst_staking_df, funding_df, sol_price_df, float(total_capital), float(leverage))
        if not series_perps.empty:
            display_usd_values_chart(
                time_series=series_perps["time"],
                wallet_usd_series=series_perps["lst_token_amount_usd"],
                position_usd_series=series_perps["perp_wallet_value"],
                wallet_label="LST wallet (USD)",
                position_label="Perp wallet (USD)",
                title="USD Values Over Time (LST+Perps)",
                checkbox_label="Show USD Values Over Time (LST+Perps)",
                additional_series={"Portfolio total (USD)": series_perps["net_value"]}
            )

        if not series_perps.empty:
            tbl = series_perps.copy().rename(columns={
                "lst_token_amount": "LST tokens",
                "lst_token_price": "LST price (USD)",
                "lst_token_amount_usd": "LST wallet (USD)",
                "wallet_initial_usd": "Wallet initial (USD)",
                "perp_capital_initial_usd": "Perp capital initial (USD)",
                "perp_short_notional_usd": "Perp notional (start, USD)",
                "perp_position_value": "Perp position (MTM, USD)",
                "perp_wallet_value": "Perp wallet (USD)",
                "sol_price": "SOL price (USD)",
                "perp_sol_amount": "Perp size (SOL)",
                "perp_sol_amount_usd": "Perp notional (current, USD)",
                "perp_apy": "Perp funding APY (%)",
                "perp_interest": "Perp funding (4h, USD)",
                "perp_usd_accumulated": "Perp funding (cum, USD)",
                "net_value": "Portfolio total (USD)",
            })
            tbl = tbl.round({
                "LST price (USD)": 6,
                "LST wallet (USD)": 2,
                "Perp wallet (USD)": 2,
                "SOL price (USD)": 6,
                "Perp funding (4h, USD)": 2,
                "Perp funding (cum, USD)": 2,
                "Portfolio total (USD)": 2,
            })
            display_breakdown_table(
                tbl[[
                    "time",
                    "LST price (USD)",
                    "LST wallet (USD)",
                    "Perp wallet (USD)",
                    "SOL price (USD)",
                    "Perp funding (4h, USD)",
                    "Perp funding (cum, USD)",
                    "Portfolio total (USD)",
                ]],
                "Show breakdown table (LST+Perps)"
            )

    st.markdown("---")

    # Bottom chart: Net APY from both sections
    st.subheader("Net APY Comparison (LST+Spot vs LST+Perps)")
    # Build LST+Spot net APY (weighted by initial capital allocation ratios)
    net_spot = pd.DataFrame(columns=["time", "net_apy_pct"])
    try:
        if not apy_df_spot.empty:
            wallet_amount, used_capital, _ = compute_allocation_split(float(base_usd_spot), float(lev_spot))
            wallet_ratio_spot, short_ratio_spot = compute_capital_allocation_ratios(
                wallet_amount, used_capital, float(base_usd_spot)
            )
            net_spot = apy_df_spot[["time"]].copy()
            net_spot["net_apy_pct"] = apy_df_spot["staking_pct"].fillna(0.0) * wallet_ratio_spot - apy_df_spot["spot_rate_pct"].fillna(0.0) * short_ratio_spot
    except Exception:
        pass

    net_perps = pd.DataFrame(columns=["time", "net_apy_pct"])
    try:
        if not df_apys_perps.empty:
            net_perps = df_apys_perps[["time", "net_apy_pct"]].copy()
    except Exception:
        pass

    if net_spot.empty and net_perps.empty:
        st.info("Net APY series are not available with the current selections.")
    else:
        fig_cmp = go.Figure()
        if not net_spot.empty:
            fig_cmp.add_trace(go.Scatter(x=net_spot["time"], y=net_spot["net_apy_pct"], name="LST+Spot Net APY (%)", mode="lines"))
        if not net_perps.empty:
            fig_cmp.add_trace(go.Scatter(x=net_perps["time"], y=net_perps["net_apy_pct"], name="LST+Perps Net APY (%)", mode="lines"))
        fig_cmp.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_cmp, use_container_width=True)

        # Std deviation summary at bottom
        try:
            std_spot = float(net_spot["net_apy_pct"].std(skipna=True)) if not net_spot.empty else None
        except Exception:
            std_spot = None
        try:
            std_perps = float(net_perps["net_apy_pct"].std(skipna=True)) if not net_perps.empty else None
        except Exception:
            std_perps = None
        parts = []
        if std_spot is not None:
            parts.append(f"LST+Spot: {std_spot:.2f}%")
        if std_perps is not None:
            parts.append(f"LST+Perps: {std_perps:.2f}%")
        if parts:
            st.caption("Std deviation — " + " | ".join(parts))


if __name__ == "__main__":
    main()


