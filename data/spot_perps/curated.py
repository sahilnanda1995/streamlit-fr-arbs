from typing import Dict, List, Optional, Callable

import pandas as pd

from config.constants import DEFAULT_TARGET_HOURS
from .calculations import (
    get_perps_rates_for_asset,
)
from .helpers import compute_net_arb


EXCHANGES: List[str] = ["Hyperliquid", "Lighter", "Drift"]


def _compute_exchange_fields(
    exchange_name: str,
    funding_rate: Optional[float],
    spot_rate: float,
    direction: str,
    asset_name: str,
    variant: str,
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

    arb_value = compute_net_arb(spot_rate, funding_rate, direction)
    if direction == "Long":
        calc_text = f"({-spot_rate:.1f}%) + ({funding_rate:.1f}%) = {-arb_value:.1f}%"
        desc_text = (
            f"Long {variant} on Asgard {-spot_rate:.1f}% • Short {asset_name} on {exchange_name} {funding_rate:.1f}%"
        )
    else:
        calc_text = f"({-spot_rate:.1f}%) + ({-funding_rate:.1f}%) = {-arb_value:.1f}%"
        desc_text = (
            f"Short {variant} on Asgard {-spot_rate:.1f}% • Long {asset_name} on {exchange_name} {-funding_rate:.1f}%"
        )

    # If not profitable (arb_value >= 0), update description accordingly
    if arb_value is None or arb_value >= 0:
        desc_text = "No Arb Available(Not Profitable)"

    return {
        "funding_text": funding_rate,
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


def create_curated_arbitrage_table(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS,
    max_leverage: int = 5,
    logger: Optional[Callable[[str], None]] = None,
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
            best_spot_info = find_best_spot_rate_across_leverages(
                token_config, rates_data, staking_data,
                asset_variants, direction.lower(), target_hours, max_leverage,
                logger=logger,
            )
            if best_spot_info is None:
                continue

            spot_rate = best_spot_info['rate']
            variant = best_spot_info['variant']

            # Dynamic per-exchange computations
            exchange_fields: Dict[str, Dict[str, Optional[float]]] = {}
            for exchange_name in EXCHANGES:
                rate_value = perps_rates.get(exchange_name)
                exchange_fields[exchange_name] = _compute_exchange_fields(
                    exchange_name, rate_value, spot_rate, direction, asset_name, variant
                )

            spot_display = f"{-best_spot_info['rate']:.1f}%(via {best_spot_info['variant']}/{best_spot_info['pair_asset']}) {best_spot_info['leverage']}x"

            row = {
                "Coin": asset_name,
                "Direction": f"Best {direction.lower()}",
                "Asgard Spot Margin Borrow Rate": spot_display,
                "Row_Group_ID": row_group_id,
                "Row_Type": "main",
            }
            for ex in EXCHANGES:
                fields = exchange_fields.get(ex, {})
                display_text = "N/A"
                if fields.get("funding_text") is not None:
                  if direction == "Long":
                    display_text = f"{fields.get('funding_text'):.1f}%"
                  else:
                    display_text = f"{-fields.get('funding_text'):.1f}%"
                row[f"{ex} Funding Rate"] = display_text
                row[f"Asgard - {ex} Arb"] = fields.get("calc_text", "N/A")
                row[f"{ex}_Arb_Rate"] = fields.get("arb_value")
            rows.append(row)

            desc_row = {
                "Coin": "",
                "Direction": "",
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

    col1, col2 = st.columns([3, 1])
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
    )

    if curated_df.empty:
        st.info("No arbitrage opportunities found between Asgard and perps exchanges")
        st.markdown("<br>", unsafe_allow_html=True)
        return

    column_config = {
        "Coin": st.column_config.TextColumn("Coin", pinned=True, width=80),
        "Direction": st.column_config.TextColumn("Direction", width=120),
        "Asgard Spot Margin Borrow Rate": st.column_config.TextColumn(
            "Asgard Spot Margin Borrow Rate", width=300
        ),
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

            **Format**: `Rate%(via variant/pair) leverage`
            - Example: `10%(via JUPSOL/USDC) 2x` means 10% yearly rate using JUPSOL/USDC pair at 2x leverage

            **Arbitrage Calculation**:
            - Long: Asgard rate - Perps funding = Net arbitrage
            - Short: Asgard rate + Perps funding = Net arbitrage
            """
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Backtesting section below curated
    display_backtesting_section(
        token_config,
        rates_data,
        staking_data,
        hyperliquid_data,
        drift_data,
    )


