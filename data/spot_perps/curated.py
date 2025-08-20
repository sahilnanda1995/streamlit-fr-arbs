from typing import Dict, List, Optional, Callable, Tuple

import pandas as pd

from config.constants import DEFAULT_TARGET_HOURS, SPOT_PERPS_CONFIG
from .calculations import (
    get_perps_rates_for_asset,
    calculate_spot_rate_with_direction,
)
from .helpers import (
    compute_net_arb,
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)
from .spot_history import build_arb_history_series
from .backtesting_utils import (
    prepare_display_series,
    compute_earnings_and_implied_apy,
)


EXCHANGES: List[str] = ["Hyperliquid", "Lighter", "Drift"]


def _compute_exchange_fields(
    exchange_name: str,
    funding_rate: Optional[float],
    spot_rate: float,
    direction: str,
    asset_name: str,
    variant: str,
    leverage: float,
) -> Dict[str, Optional[float]]:
    """
    Compute display fields for a single exchange given spot and funding rates.

    Returns a dict with keys:
      - funding_text (float | None)
      - arb_value (float | None)
      - calc_text (str)
      - desc_text (str)
    """
    if funding_rate is None:
        return {
            "funding_text": None,
            "arb_value": None,
            "calc_text": "N/A",
            "desc_text": "",
        }

    # Compute effective perps funding based on spot leverage
    # Long: perps notional ~ L; Short: perps notional ~ max(L-1, 0)
    perps_factor = leverage if direction == "Long" else max(float(leverage) - 1.0, 0.0)
    effective_funding = funding_rate * perps_factor

    arb_value = compute_net_arb(spot_rate, effective_funding, direction)
    if direction == "Long":
        calc_text = f"({-spot_rate:.1f}%) + ({effective_funding:.1f}%) = {-arb_value:.1f}%"
        desc_text = (
            f"Long {variant} on Asgard {-spot_rate:.1f}% • Short {asset_name} on {exchange_name} {effective_funding:.1f}% (effective)"
        )
    else:
        calc_text = f"({-spot_rate:.1f}%) + ({-effective_funding:.1f}%) = {-arb_value:.1f}%"
        desc_text = (
            f"Short {variant} on Asgard {-spot_rate:.1f}% • Long {asset_name} on {exchange_name} {-effective_funding:.1f}% (effective)"
        )

    # If not profitable (arb_value >= 0), update description accordingly
    if arb_value is None or arb_value >= 0:
        desc_text = "No Arb Available(Not Profitable)"

    return {
        # Store effective funding (unsigned; display sign handled later)
        "funding_text": effective_funding,
        "arb_value": arb_value,
        "calc_text": calc_text,
        "desc_text": desc_text,
    }


def find_best_spot_rate_across_leverages(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    asset_variants: list,
    direction: str,
    target_hours: int,
    max_leverage: int = 5,
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    from .calculations import calculate_spot_rate_with_direction
    from config.constants import SPOT_LEVERAGE_LEVELS

    best_rate = float('inf')
    best_info = None
    for leverage in [lev for lev in SPOT_LEVERAGE_LEVELS if lev <= max_leverage]:
        for variant in asset_variants:
            spot_rates = calculate_spot_rate_with_direction(
                token_config, rates_data, staking_data,
                variant, leverage, direction, target_hours,
                logger=logger,
            )
            for protocol, rate in spot_rates.items():
                if rate is not None and rate < best_rate:
                    best_rate = rate
                    best_info = {
                        'rate': rate,
                        'variant': variant,
                        'protocol': protocol,
                        'leverage': leverage,
                        'pair_asset': 'USDC',
                    }
    return best_info


def find_best_config_by_historical_roe(
    token_config: dict,
    asset_variants: list,
    direction: str,
    max_leverage: int,
    lookback_hours: int,
    total_cap: float,
    perps_exchanges: Optional[List[str]] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """
    Search across variants, protocol/markets, leverages, and perps exchanges to find
    the configuration with the best ROE over the historical lookback window.
    """
    from config.constants import SPOT_LEVERAGE_LEVELS

    candidates_perps = perps_exchanges or ["Hyperliquid", "Drift"]
    best: Optional[dict] = None
    best_roe_pct: float = float("-inf")

    dir_lower = direction.lower()

    for variant in asset_variants:
        pairs: List[Tuple[str, str, str]] = get_protocol_market_pairs(token_config, variant)
        for protocol, market, asset_bank in pairs:
            usdc_bank = get_matching_usdc_bank(token_config, protocol, market)
            if not usdc_bank:
                if logger:
                    logger(f"Skipping {variant} at {protocol}({market}): missing USDC bank")
                continue

            # Effective max leverage guard
            eff_max = compute_effective_max_leverage(
                token_config,
                asset_bank if dir_lower == "long" else usdc_bank,
                usdc_bank if dir_lower == "long" else asset_bank,
                dir_lower,
            )

            for leverage in [lev for lev in SPOT_LEVERAGE_LEVELS if lev <= max_leverage]:
                # Enforce min 2.0x spot leverage for short direction
                if dir_lower == "short" and float(leverage) < 2.0:
                    continue
                if float(leverage) > float(eff_max):
                    continue

                for perps_ex in candidates_perps:
                    # Build historical arbitrage series
                    series_df = build_arb_history_series(
                        token_config,
                        variant,
                        protocol,
                        market,
                        dir_lower,
                        float(leverage),
                        perps_ex,
                        int(lookback_hours),
                    )
                    if series_df.empty:
                        continue

                    df_plot = prepare_display_series(series_df, dir_lower)
                    df_calc, _, _, _ = compute_earnings_and_implied_apy(
                        df_plot, dir_lower, float(total_cap), float(leverage)
                    )
                    profit_usd = float(df_calc["total_interest_usd"].sum())
                    roe_pct = (profit_usd / float(total_cap) * 100.0) if float(total_cap) > 0 else 0.0

                    # Only consider positive ROE
                    if roe_pct > 0 and roe_pct > best_roe_pct:
                        best_roe_pct = roe_pct
                        best = {
                            "variant": variant,
                            "protocol": protocol,
                            "market": market,
                            "leverage": float(leverage),
                            "perps_exchange": perps_ex,
                            "roe_pct": float(roe_pct),
                            "profit_usd": float(profit_usd),
                            "pair_asset": "USDC",
                        }

    return best


def enumerate_configs_by_historical_roe(
    token_config: dict,
    asset_type: str,
    asset_variants: list,
    direction: str,
    max_leverage: int,
    lookback_hours: int,
    total_cap: float,
    perps_exchanges: Optional[List[str]] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> List[dict]:
    """
    Enumerate all feasible strategies for given asset/direction and compute ROE using
    historical backtesting utilities. Returns list of dicts sorted by ROE desc.
    """
    from config.constants import SPOT_LEVERAGE_LEVELS

    candidates_perps = perps_exchanges or ["Hyperliquid", "Drift"]
    results: List[dict] = []
    dir_lower = direction.lower()

    for variant in asset_variants:
        pairs: List[Tuple[str, str, str]] = get_protocol_market_pairs(token_config, variant)
        for protocol, market, asset_bank in pairs:
            usdc_bank = get_matching_usdc_bank(token_config, protocol, market)
            if not usdc_bank:
                if logger:
                    logger(f"Skipping {variant} at {protocol}({market}): missing USDC bank")
                continue

            eff_max = compute_effective_max_leverage(
                token_config,
                asset_bank if dir_lower == "long" else usdc_bank,
                usdc_bank if dir_lower == "long" else asset_bank,
                dir_lower,
            )

            for leverage in [lev for lev in SPOT_LEVERAGE_LEVELS if lev <= max_leverage]:
                # Enforce min 2.0x spot leverage for short direction
                if dir_lower == "short" and float(leverage) < 2.0:
                    continue
                if float(leverage) > float(eff_max):
                    continue
                for perps_ex in candidates_perps:
                    series_df = build_arb_history_series(
                        token_config,
                        variant,
                        protocol,
                        market,
                        dir_lower,
                        float(leverage),
                        perps_ex,
                        int(lookback_hours),
                    )
                    if series_df.empty:
                        continue
                    df_plot = prepare_display_series(series_df, dir_lower)
                    df_calc, _, _, _ = compute_earnings_and_implied_apy(
                        df_plot, dir_lower, float(total_cap), float(leverage)
                    )
                    profit_usd = float(df_calc["total_interest_usd"].sum())
                    roe_pct = (profit_usd / float(total_cap) * 100.0) if float(total_cap) > 0 else 0.0

                    # Build label including perps leg with effective notional factor
                    perps_factor = float(leverage) if dir_lower == "long" else max(float(leverage) - 1.0, 0.0)
                    perps_dir = "Short" if dir_lower == "long" else "Long"
                    label = (
                        f"{direction} {variant}/USDC at {float(leverage):.1f}x - "
                        f"{perps_dir} {asset_type} {perps_ex} at {perps_factor:.1f}x"
                    )

                    if roe_pct > 0:
                        results.append({
                            "label": label,
                            "asset_type": asset_type,
                            "variant": variant,
                            "protocol": protocol,
                            "market": market,
                            "direction": dir_lower,
                            "leverage": float(leverage),
                            "perps_exchange": perps_ex,
                            "roe_pct": float(roe_pct),
                            "profit_usd": float(profit_usd),
                        })

    # Sort by ROE descending
    results.sort(key=lambda x: x.get("roe_pct", 0.0), reverse=True)
    return results

def create_curated_arbitrage_table(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS,
    max_leverage: int = 5,
    logger: Optional[Callable[[str], None]] = None,
    lookback_hours: int = 720,
    total_capital_usd: float = 100_000.0,
    perps_exchanges: Optional[List[str]] = None,
) -> pd.DataFrame:
    rows: List[Dict] = []
    row_group_id = 0

    from config.constants import SPOT_PERPS_CONFIG

    asset_configs = {
        "SOL": (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL"),
        "BTC": (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC"),
    }

    for asset_name, (asset_variants, asset_type) in asset_configs.items():
        perps_rates = get_perps_rates_for_asset(
            hyperliquid_data, drift_data, asset_type, target_hours
        )
        if (
            "Hyperliquid" not in perps_rates
            and "Drift" not in perps_rates
            and "Lighter" not in perps_rates
        ):
            continue

        for direction in ["Long", "Short"]:
            # Choose best configuration by historical ROE instead of best spot APY
            best_cfg = find_best_config_by_historical_roe(
                token_config=token_config,
                asset_variants=asset_variants,
                direction=direction,
                max_leverage=max_leverage,
                lookback_hours=lookback_hours,
                total_cap=total_capital_usd,
                perps_exchanges=perps_exchanges or ["Hyperliquid", "Drift"],
                logger=logger,
            )
            if best_cfg is None:
                continue

            variant = best_cfg['variant']
            leverage = float(best_cfg['leverage'])
            proto = best_cfg['protocol']
            market = best_cfg['market']

            # Compute current spot rate for display (keeps existing column semantics)
            variant_spot_rates = calculate_spot_rate_with_direction(
                token_config, rates_data, staking_data,
                variant, leverage, direction.lower(), target_hours,
            )
            spot_key = f"{proto}({market})"
            spot_rate = variant_spot_rates.get(spot_key)
            if spot_rate is None:
                # Fallback: skip if we cannot compute display spot rate
                if logger:
                    logger(f"Skipping {variant} {direction} {spot_key}: no current spot rate for display")
                continue

            # Dynamic per-exchange computations
            exchange_fields: Dict[str, Dict[str, Optional[float]]] = {}
            for exchange_name in EXCHANGES:
                rate_value = perps_rates.get(exchange_name)
                exchange_fields[exchange_name] = _compute_exchange_fields(
                    exchange_name,
                    rate_value,
                    spot_rate,
                    direction,
                    asset_name,
                    variant,
                    leverage,
                )

            # Display format: "Long JUPSOL/USDC at 2.0x -> 10.7%"
            spot_display = (
                f"{direction} {variant}/{ 'USDC' } at {leverage:.1f}x -> {-spot_rate:.1f}%"
            )

            row = {
                "Coin": asset_name,
                "Asgard Spot Margin Borrow Rate": spot_display,
                "Best ROE (period)": f"{best_cfg['roe_pct']:.2f}%",
                "Row_Group_ID": row_group_id,
                "Row_Type": "main",
            }
            for ex in EXCHANGES:
                fields = exchange_fields.get(ex, {})
                display_text = "N/A"
                if fields.get("funding_text") is not None:
                    # Perps leg direction and effective notional factor
                    perps_dir = "Short" if direction == "Long" else "Long"
                    perps_factor = leverage if direction == "Long" else max(float(leverage) - 1.0, 0.0)
                    # Effective funding sign per spot direction
                    eff_funding_display = fields.get("funding_text") if direction == "Long" else -fields.get("funding_text")
                    display_text = f"{perps_dir} {asset_name} at {perps_factor:.1f}x -> {eff_funding_display:.1f}%"
                row[f"{ex} Funding Rate"] = display_text
                row[f"Asgard - {ex} Arb"] = fields.get("calc_text", "N/A")
                row[f"{ex}_Arb_Rate"] = fields.get("arb_value")
            rows.append(row)

            desc_row = {
                "Coin": "",
                "Asgard Spot Margin Borrow Rate": "",
                "Row_Group_ID": row_group_id,
                "Row_Type": "description",
            }
            for ex in EXCHANGES:
                fields = exchange_fields.get(ex, {})
                desc_row[f"{ex} Funding Rate"] = ""
                desc_row[f"Asgard - {ex} Arb"] = fields.get("desc_text", "")
                desc_row[f"{ex}_Arb_Rate"] = None
            rows.append(desc_row)
            row_group_id += 1

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df_display = df.copy()
    prev_coin = None
    for i, row in df_display.iterrows():
        if row['Row_Type'] == 'main':
            if row['Coin'] == prev_coin:
                df_display.at[i, 'Coin'] = ""
            prev_coin = row['Coin']
    hidden_cols = [f"{ex}_Arb_Rate" for ex in EXCHANGES] + ["Row_Group_ID", "Row_Type"]
    df_display = df_display.drop(hidden_cols, axis=1)
    return df_display


def display_curated_arbitrage_section(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS,
) -> None:
    import streamlit as st
    from .backtesting import display_backtesting_section

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.subheader("📊 Spot vs Perps Delta Neutral Strategies")
    with col2:
        max_leverage = st.slider(
            "Max Leverage",
            min_value=1,
            max_value=5,
            value=5,
            step=1,
            help="Maximum leverage level to consider for curated arbitrage analysis",
        )
    with col3:
        lookback_choice = st.selectbox("Lookback", ["1 week", "2 weeks", "1 month"], index=2)
    lookback_map = {"1 week": 168, "2 weeks": 336, "1 month": 720}
    lookback_hours = lookback_map.get(lookback_choice, 720)

    total_capital_usd = st.number_input("Total capital (USD)", min_value=0.0, value=100_000.0, step=1_000.0, key="curated_total_cap")

    st.caption(f"Best rates across all variants, protocols, and leverage levels (1x-{max_leverage}x)")

    # Sidebar: missing data diagnostics option
    show_missing = st.sidebar.checkbox(
        "🔎 Show missing data diagnostics",
        value=False,
        help="Display which rows were skipped due to missing lending/borrowing or rate fields",
    )
    logs: List[str] = []

    curated_df = create_curated_arbitrage_table(
        token_config,
        rates_data,
        staking_data,
        hyperliquid_data,
        drift_data,
        target_hours,
        max_leverage,
        logger=(logs.append if show_missing else None),
        lookback_hours=lookback_hours,
        total_capital_usd=total_capital_usd,
        perps_exchanges=["Hyperliquid", "Drift"],
    )

    if curated_df.empty:
        st.info("No arbitrage opportunities found between Asgard and perps exchanges")
        st.markdown("<br>", unsafe_allow_html=True)
        return

    column_config = {
        "Coin": st.column_config.TextColumn("Coin", pinned=True, width=80),
        "Asgard Spot Margin Borrow Rate": st.column_config.TextColumn(
            "Asgard Spot Margin Borrow Rate", width=360
        ),
        "Best ROE (period)": st.column_config.TextColumn("Best ROE (period)", width=140),
    }
    for ex in EXCHANGES:
        column_config[f"{ex} Funding Rate"] = st.column_config.TextColumn(
            f"{ex} Funding Rate", width=150
        )
        column_config[f"Asgard - {ex} Arb"] = st.column_config.TextColumn(
            f"Asgard - {ex} Arb", width=400
        )

    st.dataframe(
        curated_df,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )

    if show_missing and logs:
        with st.expander("🔎 Missing data (Curated)"):
            for line in logs:
                st.write("- ", line)

    with st.expander("ℹ️ How to read this table"):
        st.markdown(
            """
            **Asgard Spot Margin Borrow Rate**: Best yearly rate across variants, protocols, and leverage levels

            **Format**: `Long VARIANT/PAIR at Lx -> RATE%`
            - Example: `Long JUPSOL/USDC at 2.0x -> 10.7%` means 10.7% yearly rate using JUPSOL/USDC pair at 2.0x

            **Arbitrage Calculation (using effective funding):**
            - Long: Asgard rate - (Perps funding × L) = Net arbitrage
            - Short: Asgard rate + (Perps funding × max(L-1, 0)) = Net arbitrage
            """
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Build all strategies by ROE to feed backtesting selector
    asset_configs = {
        "SOL": (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL"),
        "BTC": (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC"),
    }
    all_strategies: List[dict] = []
    for asset_name, (asset_variants, _) in asset_configs.items():
        for direction in ["Long", "Short"]:
            all_strategies += enumerate_configs_by_historical_roe(
                token_config=token_config,
                asset_type=asset_name,
                asset_variants=asset_variants,
                direction=direction,
                max_leverage=max_leverage,
                lookback_hours=lookback_hours,
                total_cap=total_capital_usd,
                perps_exchanges=["Hyperliquid", "Drift"],
                logger=(logs.append if show_missing else None),
            )

    # Backtesting section below curated with precomputed strategies
    display_backtesting_section(
        token_config,
        rates_data,
        staking_data,
        hyperliquid_data,
        drift_data,
        strategies_by_roe=all_strategies,
    )


