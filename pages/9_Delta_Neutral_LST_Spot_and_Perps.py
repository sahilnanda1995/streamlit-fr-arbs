"""
Streamlit page for Delta Neutral: LST + margin short and LST + perp short comparison
Clean flow: Section 1 calculations → Section 2 calculations → Summary using stored values
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from typing import Dict, Any, List, Optional, Tuple

from config import get_token_config
from config.constants import DRIFT_MARKET_INDEX, ASSET_VARIANTS, SPOT_PERPS_CONFIG
from api.endpoints import (
    fetch_birdeye_history_price,
    fetch_hourly_staking,
    fetch_drift_funding_history,
    fetch_asgard_staking_rates,
)
from data.spot_perps.helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)
from data.spot_perps.spot_history import build_spot_history_series, build_perps_history_series
from data.spot_perps.spot_wallet_short import find_eligible_short_variants, build_wallet_short_series, compute_allocation_split
from data.money_markets_processing import get_staking_rate_by_mint
from utils.dataframe_utils import aggregate_to_4h_buckets, compute_implied_apy, compute_capital_allocation_ratios, fetch_and_process_staking_series, compute_weighted_net_apy
from utils.delta_neutral_ui import display_delta_neutral_metrics, display_perps_metrics, display_apy_chart, display_net_apy_chart, display_usd_values_chart, display_breakdown_table


st.set_page_config(page_title="Delta Neutral: LST + margin short and LST + perp short", layout="wide")


def _load_lst_options(token_config: Dict[str, Any]) -> List[str]:
    """Load LST options - same logic as page 7"""
    sol_variants = ASSET_VARIANTS.get("SOL", [])
    options: List[str] = []
    for t in sol_variants:
        info = (token_config.get(t) or {})
        if info.get("mint"):
            options.append(t)
    return options or sol_variants


def _fetch_funding_series(perps_exchange: str, lookback_hours: int) -> pd.DataFrame:
    """Fetch funding series - same as page 7"""
    return build_perps_history_series(perps_exchange.strip(), "SOL", int(lookback_hours))


def _build_breakdown(
    price_df: pd.DataFrame,
    staking_df: pd.DataFrame,
    funding_df: pd.DataFrame,
    sol_price_df: pd.DataFrame,
    total_capital_usd: float,
    leverage: float,
) -> pd.DataFrame:
    """Build perps breakdown - same as page 7"""
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

    merged = pd.merge_asof(
        base.sort_values("time"),
        staking_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    )
    merged = pd.merge_asof(
        merged.sort_values("time"),
        funding_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    )
    merged = pd.merge_asof(
        merged.sort_values("time"),
        sol_price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h")
    )
    merged = merged.dropna(subset=["price"])  # require LST price

    if merged.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])

    # Ensure SOL price exists before using it for initial size
    merged = merged.dropna(subset=["sol_price"])  # require SOL price
    if merged.empty:
        return pd.DataFrame(columns=[
            "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
            "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
            "perp_apy", "perp_interest", "net_value",
        ])

    # Initial tokens and sizes from first available prices
    first_price = float(pd.to_numeric(merged["price"], errors="coerce").dropna().iloc[0])
    lst_tokens_initial = (wallet_usd / first_price) if first_price > 0 else 0.0
    merged["lst_token_amount"] = float(lst_tokens_initial)
    merged["lst_token_price"] = merged["price"]
    merged["lst_token_amount_usd"] = merged["lst_token_amount"] * merged["lst_token_price"]

    first_sol_price = float(pd.to_numeric(merged["sol_price"], errors="coerce").dropna().iloc[0])
    perp_sol_initial = (perp_short_notional_usd / first_sol_price) if first_sol_price > 0 else 0.0
    merged["perp_sol_amount"] = float(perp_sol_initial)
    merged["perp_sol_amount_usd"] = merged["perp_sol_amount"] * pd.to_numeric(merged["sol_price"], errors="coerce").fillna(0.0)

    # Funding APY and 4h bucket interest on notional
    merged["perp_apy"] = pd.to_numeric(merged.get("funding_pct", 0), errors="coerce").fillna(0.0)
    bucket_factor = 4.0 / (365.0 * 24.0)
    merged["perp_interest"] = float(perp_short_notional_usd) * (merged["perp_apy"] / 100.0) * bucket_factor
    merged["perp_usd_accumulated"] = merged["perp_interest"].cumsum()

    # Price PnL for short leg and position/wallet values
    merged["perp_pnl_price"] = float(perp_sol_initial) * (float(first_sol_price) - pd.to_numeric(merged["sol_price"], errors="coerce").fillna(0.0))
    merged["perp_position_value"] = float(perps_capital_initial) + merged["perp_pnl_price"]
    merged["perp_wallet_value"] = merged["perp_position_value"] + merged["perp_usd_accumulated"]

    # Net portfolio value includes funding accumulation
    merged["net_value"] = merged["lst_token_amount_usd"] + merged["perp_wallet_value"]

    return merged[[
        "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
        "perp_position_value", "perp_wallet_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
        "perp_apy", "perp_interest", "perp_usd_accumulated", "net_value",
    ]].sort_values("time")


def main():
    st.title("Delta Neutral: LST + margin short and LST + perp short")

    # Shared configuration
    token_config = get_token_config()
    col1, col2 = st.columns([1, 1])
    with col1:
        lookback_choice = st.selectbox(
            "Time period", ["3 months", "2 months", "1 month", "2 weeks", "1 week"],
            index=1, key="combined_lookback"
        )
    with col2:
        total_capital = st.number_input(
            "Total capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0,
            key="combined_total_capital"
        )

    lookback_map = {"1 week": 168, "2 weeks": 336, "1 month": 720, "2 months": 1440, "3 months": 2160}
    lookback_hours = lookback_map.get(lookback_choice, 720)

    # Storage variables for calculated values
    spot_total_pnl = 0.0
    spot_implied_apy = 0.0
    spot_base_capital = float(total_capital)
    spot_net_apy_series = pd.DataFrame()

    perps_total_pnl = 0.0
    perps_implied_apy = 0.0
    perps_base_capital = float(total_capital)
    perps_net_apy_series = pd.DataFrame()

    # === SECTION 1: LST + margin short (page 8 logic) ===
    st.subheader("Delta Neutral: LST + margin short")

    # Same controls as page 8
    eligible_short_variants = find_eligible_short_variants(token_config, SPOT_PERPS_CONFIG["SOL_ASSETS"])

    if not eligible_short_variants:
        st.info("No SOL variants have at least 2x short leverage available.")
    else:
        wallet_options: List[str] = []
        for t in SPOT_PERPS_CONFIG["SOL_ASSETS"]:
            info = (token_config.get(t) or {})
            if info.get("hasStakingYield", False) and info.get("mint"):
                wallet_options.append(t)
        if "SOL" in SPOT_PERPS_CONFIG["SOL_ASSETS"] and "SOL" not in wallet_options:
            wallet_options.append("SOL")
        if not wallet_options:
            wallet_options = list(SPOT_PERPS_CONFIG["SOL_ASSETS"])

        col1, col2, col3 = st.columns([1, 1, 1])

        def _format_wallet_option(sym: str) -> str:
            if sym == "SOL":
                return "SOL"
            info = (token_config.get(sym) or {})
            if info.get("hasStakingYield") and info.get("mint"):
                try:
                    staking_data = fetch_asgard_staking_rates() or {}
                    apy_dec = get_staking_rate_by_mint(staking_data, info.get("mint")) or 0.0
                    apy_pct = float(apy_dec) * 100.0
                    return f"{sym}({apy_pct:.2f}%)"
                except Exception:
                    return sym
            return sym

        with col1:
            wallet_asset = st.selectbox(
                "Wallet asset", options=wallet_options, index=0,
                key="combined_spot_wallet_asset", format_func=_format_wallet_option
            )
        with col2:
            short_asset_names = sorted(list(eligible_short_variants.keys()))
            short_asset = st.selectbox(
                "Short asset", options=short_asset_names, index=0,
                key="combined_spot_short_asset"
            )
        with col3:
            lev_spot = st.slider("Leverage", min_value=1.0, max_value=5.0, value=2.0, step=0.5, key="combined_spot_lev")

        proto = eligible_short_variants[short_asset]["protocol"]
        market = eligible_short_variants[short_asset]["market"]

        # Build and calculate everything for spot section
        with st.spinner("Building LST + margin short series..."):
            spot_series = build_wallet_short_series(
                token_config, wallet_asset, short_asset, proto, market,
                float(lev_spot), int(lookback_hours), float(total_capital)
            )

        if not spot_series.empty:
            # Calculate all metrics (page 8 logic)
            plot_df = spot_series.copy()
            last_row = plot_df.dropna(subset=["wallet_asset_price", "short_asset_price", "usdc_principal_usd", "short_tokens_owed", "close_cost_usd", "net_value_usd", "wallet_value_usd"]).tail(1)

            if not last_row.empty:
                lev_f = float(lev_spot)
                base_f = float(total_capital)
                wallet_amount_usd, used_capital_usd, initial_short_borrow_usd = compute_allocation_split(base_f, lev_f)

                wallet_value_now = float(last_row["wallet_value_usd"].iloc[0])
                net_value_now = float(last_row["net_value_usd"].iloc[0])
                short_leg_pnl = net_value_now - used_capital_usd
                wallet_pnl = wallet_value_now - wallet_amount_usd

                # Store calculated values
                spot_total_pnl = short_leg_pnl + wallet_pnl
                spot_base_capital = base_f
                total_hours = float(len(plot_df) * 4.0)
                spot_implied_apy = compute_implied_apy(spot_total_pnl, base_f, total_hours)

                # Display metrics
                display_delta_neutral_metrics(
                    total_pnl=spot_total_pnl,
                    base_capital=base_f,
                    implied_apy=spot_implied_apy,
                    wallet_asset=wallet_asset,
                    wallet_amount_initial=wallet_amount_usd,
                    wallet_value_now=wallet_value_now,
                    short_asset=short_asset,
                    short_borrow_initial=initial_short_borrow_usd,
                    short_borrow_now=float(last_row["close_cost_usd"].iloc[0]),
                    short_net_initial=float(total_capital) - float(initial_short_borrow_usd),
                    short_net_now=net_value_now - wallet_value_now
                )

            # Calculate and store net APY series
            staking_series = fetch_and_process_staking_series(token_config, wallet_asset, lookback_hours)
            spot_history_series = build_spot_history_series(
                token_config, short_asset, proto, market, "long", float(lev_spot), lookback_hours
            )

            if not staking_series.empty and not spot_history_series.empty:
                apy_df_spot = pd.merge_asof(
                    staking_series.sort_values("time"),
                    spot_history_series.sort_values("time"),
                    on="time", direction="nearest", tolerance=pd.Timedelta("3h")
                ).dropna(subset=["staking_pct", "spot_rate_pct"])

                if not apy_df_spot.empty:
                    display_apy_chart(
                        time_series=apy_df_spot["time"],
                        long_apy_series=apy_df_spot["staking_pct"],
                        short_apy_series=apy_df_spot["spot_rate_pct"],
                        title="Long and Short Side APYs (LST + margin short)"
                    )

                    wallet_ratio_spot, short_ratio_spot = compute_capital_allocation_ratios(
                        wallet_amount_usd, used_capital_usd, float(total_capital)
                    )
                    apy_df_spot["net_apy_pct"] = compute_weighted_net_apy(
                        apy_df_spot["staking_pct"], apy_df_spot["spot_rate_pct"], wallet_ratio_spot, short_ratio_spot
                    )

                    # Store net APY series
                    spot_net_apy_series = apy_df_spot[["time", "net_apy_pct"]].copy()

                    display_net_apy_chart(
                        time_series=apy_df_spot["time"],
                        net_apy_series=apy_df_spot["net_apy_pct"],
                        title="Net APY over Time (LST + margin short)"
                    )

            # USD values and breakdown
            display_usd_values_chart(
                time_series=plot_df["time"],
                wallet_usd_series=plot_df["wallet_value_usd"],
                position_usd_series=plot_df["net_value_usd"],
                wallet_label=f"{wallet_asset} wallet (USD)",
                position_label="Short net value (USD)"
            )

            tbl_cols = ["time", "usdc_principal_usd", "close_cost_usd", "usdc_lend_apy", "asset_borrow_apy", "wallet_stk_pct", "borrow_stk_pct", "net_value_usd"]
            if "wallet_asset_price" in plot_df.columns:
                tbl_cols.insert(1, "wallet_asset_price")
            if "short_tokens_owed" in plot_df.columns:
                tbl_cols.insert(3, "short_tokens_owed")
            if "wallet_value_usd" in plot_df.columns:
                tbl_cols.append("wallet_value_usd")

            tbl = plot_df[tbl_cols].rename(columns={
                "wallet_asset_price": f"{wallet_asset} price",
                "usdc_principal_usd": "usdc lent",
                "short_tokens_owed": f"{short_asset} borrowed",
                "close_cost_usd": f"{short_asset} borrowed in usd",
                "net_value_usd": "spot position net value",
                "wallet_value_usd": f"{wallet_asset} wallet value",
            })
            display_breakdown_table(tbl, "Show breakdown table (LST + margin short)")

    st.divider()

    # === SECTION 2: LST + perp short (page 7 logic) ===
    st.subheader("Delta Neutral: LST + perp short")
    st.caption("Capital split and short notional are driven by selected perps leverage. LST yield accrues via price; funding on perps applies to short notional.")

    lst_options = _load_lst_options(token_config)
    if not lst_options:
        st.info("No LST tokens available in configuration.")
    else:
        colp1, colp2, colp3 = st.columns([1, 1, 1])
        with colp1:
            lst_symbol = st.selectbox("LST Token", lst_options, index=0)
        with colp2:
            perps_exchange = st.selectbox("Perps Exchange", ["Hyperliquid", "Drift"], index=0)
        with colp3:
            leverage_perp = st.slider("Perps leverage", min_value=1.0, max_value=5.0, value=2.0, step=0.5, key="combined_perps_lev")

        # Build and calculate everything for perps section (page 7 logic)
        with st.spinner("Loading LST + perp short series..."):
            try:
                end_ts = pd.Timestamp.utcnow()
                start_ts = end_ts - pd.Timedelta(hours=int(lookback_hours))
                start = int(start_ts.timestamp())
                end = int(end_ts.timestamp())

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

                lst_staking_df = fetch_and_process_staking_series(token_config, lst_symbol, lookback_hours)

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

                funding_df = _fetch_funding_series(perps_exchange, lookback_hours)

            except Exception as e:
                st.error(f"Failed to load historical series: {e}")
                funding_df = pd.DataFrame()
                lst_price_df = pd.DataFrame()
                sol_price_df = pd.DataFrame()
                lst_staking_df = pd.DataFrame()

        # SOL staking override
        try:
            if lst_symbol == "SOL" and not funding_df.empty:
                lst_staking_df = funding_df[["time"]].copy()
                lst_staking_df["staking_pct"] = 0.0
        except Exception:
            pass

        if lst_price_df.empty or funding_df.empty or sol_price_df.empty:
            st.warning("Required data is currently unavailable for LST + perp short.")
        else:
            # Calculate all perps metrics (page 7 logic)
            perps_series = _build_breakdown(
                lst_price_df, lst_staking_df, funding_df, sol_price_df,
                total_capital, leverage_perp
            )

            if not perps_series.empty:
                first_row = perps_series.head(1)
                last_row = perps_series.tail(1)
                lst_usd_start = float(first_row["lst_token_amount_usd"].iloc[0]) if not first_row.empty else 0.0
                lst_usd_now = float(last_row["lst_token_amount_usd"].iloc[0]) if not last_row.empty else 0.0
                perp_pos_start = float(first_row["perp_position_value"].iloc[0]) if not first_row.empty else (float(total_capital) / 2.0)
                perp_pos_now = float(last_row["perp_position_value"].iloc[0]) if not last_row.empty else perp_pos_start
                perp_sol_usd_start = float(first_row["perp_sol_amount_usd"].iloc[0]) if not first_row.empty else (float(total_capital) / 2.0)

                net_now = float(last_row["net_value"].iloc[0]) if not last_row.empty else float(total_capital)

                # Store calculated values
                perps_total_pnl = net_now - float(total_capital)
                perps_base_capital = float(total_capital)
                total_hours = max(len(perps_series), 0) * 4.0
                perps_implied_apy = compute_implied_apy(perps_total_pnl, float(total_capital), total_hours)

                # Display metrics
                display_perps_metrics(
                    profit_usd=perps_total_pnl,
                    total_capital=float(total_capital),
                    implied_apy=perps_implied_apy,
                    lst_symbol=lst_symbol,
                    lst_usd_start=lst_usd_start,
                    lst_usd_now=lst_usd_now,
                    perp_notional_start=perp_sol_usd_start,
                    perp_position_start=perp_pos_start,
                    perp_position_now=perp_pos_now
                )

            # Calculate and store net APY series
            funding_df = funding_df.sort_values("time").copy()
            funding_df["time"] = pd.to_datetime(funding_df["time"], errors="coerce")
            lst_staking_df = lst_staking_df.sort_values("time").copy()
            lst_staking_df["time"] = pd.to_datetime(lst_staking_df["time"], errors="coerce")
            df_apys = pd.merge_asof(
                funding_df,
                lst_staking_df, on="time", direction="nearest", tolerance=pd.Timedelta("3h")
            )
            df_apys = df_apys.dropna(subset=["funding_pct", "staking_pct"])

            if not df_apys.empty:
                display_apy_chart(
                    time_series=df_apys["time"],
                    long_apy_series=df_apys["staking_pct"],
                    short_apy_series=df_apys["funding_pct"],
                    short_label="Short Side APY (%)"
                )

                L = max(float(leverage_perp), 1.0)
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

                # Store net APY series
                perps_net_apy_series = df_apys_perps[["time", "net_apy_pct"]].copy()

                display_net_apy_chart(
                    time_series=df_apys_perps["time"],
                    net_apy_series=df_apys_perps["net_apy_pct"],
                    title="Net APY over Time (LST + perp short)"
                )

            # USD values and breakdown
            if not perps_series.empty:
                display_usd_values_chart(
                    time_series=perps_series["time"],
                    wallet_usd_series=perps_series["lst_token_amount_usd"],
                    position_usd_series=perps_series["perp_wallet_value"],
                    title="USD Values Over Time (LST + perp short)",
                    checkbox_label="Show USD Values Over Time (LST + perp short)",
                    wallet_label=f"{lst_symbol} wallet (USD)",
                    position_label="Perp wallet (USD)",
                    additional_series={"Portfolio total (USD)": perps_series["net_value"]}
                )

                tbl_perps = perps_series[[
                    "time", "lst_token_amount", "lst_token_price", "lst_token_amount_usd",
                    "perp_position_value", "sol_price", "perp_sol_amount", "perp_sol_amount_usd",
                    "perp_apy", "perp_interest", "net_value"
                ]].rename(columns={
                    "lst_token_amount": f"{lst_symbol} tokens",
                    "lst_token_price": f"{lst_symbol} price",
                    "lst_token_amount_usd": f"{lst_symbol} value (USD)",
                    "perp_position_value": "Perp position value",
                    "perp_sol_amount": "SOL perp amount",
                    "perp_sol_amount_usd": "SOL perp value (USD)",
                    "perp_apy": "Funding APY (%)",
                    "perp_interest": "Funding interest (USD)",
                    "net_value": "Net position value"
                })
                display_breakdown_table(tbl_perps, "Show breakdown table (LST + perp short)")

    st.divider()

    # === SUMMARY SECTION (using only stored values) ===
    st.subheader("Net APY Comparison (LST + margin short vs LST + perp short)")

    # Use only stored values - no recalculation
    if not spot_net_apy_series.empty and not perps_net_apy_series.empty:
        fig_cmp = go.Figure()
        fig_cmp.add_trace(go.Scatter(x=spot_net_apy_series["time"], y=spot_net_apy_series["net_apy_pct"], name="LST + margin short Net APY (%)", mode="lines"))
        fig_cmp.add_trace(go.Scatter(x=perps_net_apy_series["time"], y=perps_net_apy_series["net_apy_pct"], name="LST + perp short Net APY (%)", mode="lines"))
        fig_cmp.update_layout(height=300, hovermode="x unified", yaxis_title="APY (%)", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_cmp, use_container_width=True)

        # Summary metrics using only stored values
        st.subheader("Strategy Comparison Summary")

        # LST + margin short row
        st.markdown("**LST + margin short**")
        try:
            mean_apy_spot = float(spot_net_apy_series["net_apy_pct"].mean(skipna=True))
            std_spot = float(spot_net_apy_series["net_apy_pct"].std(skipna=True))

            col1, col2 = st.columns(2)
            with col1:
                roe_delta_spot = f"{(spot_total_pnl/spot_base_capital*100.0):+.2f}%" if spot_base_capital > 0 else None
                st.metric("ROE", f"${spot_total_pnl:,.2f}", delta=roe_delta_spot)
            with col2:
                st.metric("Total APY (implied)", f"{spot_implied_apy:.2f}%")

            st.write(f"**Std Deviation of Delta neutral LST + margin short:** {std_spot:.2f}%")
        except Exception:
            st.info("Metrics unavailable")

        st.divider()

        # LST + perp short row
        st.markdown("**LST + perp short**")
        try:
            mean_apy_perps = float(perps_net_apy_series["net_apy_pct"].mean(skipna=True))
            std_perps = float(perps_net_apy_series["net_apy_pct"].std(skipna=True))

            col1, col2 = st.columns(2)
            with col1:
                roe_delta_perps = f"{(perps_total_pnl/perps_base_capital*100.0):+.2f}%" if perps_base_capital > 0 else None
                st.metric("ROE", f"${perps_total_pnl:,.2f}", delta=roe_delta_perps)
            with col2:
                st.metric("Total APY (implied)", f"{perps_implied_apy:.2f}%")

            st.write(f"**Std Deviation of Delta neutral LST + perp short:** {std_perps:.2f}%")
        except Exception:
            st.info("Metrics unavailable")

        st.divider()

        # Volatility comparison using stored values
        try:
            std_spot_calc = float(spot_net_apy_series["net_apy_pct"].std(skipna=True))
            std_perps_calc = float(perps_net_apy_series["net_apy_pct"].std(skipna=True))
            if std_spot_calc > 0:
                volatility_ratio = std_perps_calc / std_spot_calc
                st.info(f"Strategy with perp short is {volatility_ratio:.0f}x more volatile than with margin short")
        except Exception:
            pass
    else:
        st.info("Net APY series are not available with the current selections.")


if __name__ == "__main__":
    main()
