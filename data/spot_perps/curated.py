from typing import Dict, List, Optional

import pandas as pd

from config.constants import DEFAULT_TARGET_HOURS
from .calculations import (
    get_perps_rates_for_asset,
)
from .helpers import compute_net_arb


def find_best_spot_rate_across_leverages(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    asset_variants: list,
    direction: str,
    target_hours: int,
    max_leverage: int = 5,
) -> Optional[dict]:
    from .calculations import calculate_spot_rate_with_direction
    from config.constants import SPOT_LEVERAGE_LEVELS

    best_rate = float('inf')
    best_info = None
    for leverage in [lev for lev in SPOT_LEVERAGE_LEVELS if lev <= max_leverage]:
        for variant in asset_variants:
            spot_rates = calculate_spot_rate_with_direction(
                token_config, rates_data, staking_data,
                variant, leverage, direction, target_hours
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
    perps_exchange: str = "Hyperliquid",
) -> pd.DataFrame:
    rows: List[Dict] = []
    row_group_id = 0

    from config.constants import SPOT_PERPS_CONFIG

    asset_configs = {
        "SOL": (SPOT_PERPS_CONFIG["SOL_ASSETS"], "SOL"),
        "BTC": (SPOT_PERPS_CONFIG["BTC_ASSETS"], "BTC"),
    }

    for asset_name, (asset_variants, asset_type) in asset_configs.items():
        perps_rates = get_perps_rates_for_asset(hyperliquid_data, drift_data, asset_type, target_hours)
        if "Hyperliquid" not in perps_rates and "Drift" not in perps_rates:
            continue

        hyperliquid_rate = perps_rates.get("Hyperliquid")
        drift_rate = perps_rates.get("Drift")

        for direction in ["Long", "Short"]:
            best_spot_info = find_best_spot_rate_across_leverages(
                token_config, rates_data, staking_data,
                asset_variants, direction.lower(), target_hours, max_leverage,
            )
            if best_spot_info is None:
                continue

            spot_rate = best_spot_info['rate']
            variant = best_spot_info['variant']

            hyperliquid_arb = None
            hyperliquid_calc = "N/A"
            hyperliquid_desc = ""
            if hyperliquid_rate is not None:
                hyperliquid_arb = compute_net_arb(spot_rate, hyperliquid_rate, direction)
                if direction == "Long":
                    hyperliquid_calc = f"({-spot_rate:.1f}%) + ({hyperliquid_rate:.1f}%) = {-hyperliquid_arb:.1f}%"
                    hyperliquid_desc = f"Long {variant} on Asgard {-spot_rate:.1f}% • Short {asset_name} on Hyperliquid {hyperliquid_rate:.1f}%"
                else:
                    hyperliquid_calc = f"({-spot_rate:.1f}%) + ({-hyperliquid_rate:.1f}%) = {-hyperliquid_arb:.1f}%"
                    hyperliquid_desc = f"Short {variant} on Asgard {-spot_rate:.1f}% • Long {asset_name} on Hyperliquid {-hyperliquid_rate:.1f}%"

            drift_arb = None
            drift_calc = "N/A"
            drift_desc = ""
            if drift_rate is not None:
                drift_arb = compute_net_arb(spot_rate, drift_rate, direction)
                if direction == "Long":
                    drift_calc = f"({-spot_rate:.1f}%) + ({drift_rate:.1f}%) = {-drift_arb:.1f}%"
                    drift_desc = f"Long {variant} on Asgard {-spot_rate:.1f}% • Short {asset_name} on Drift {drift_rate:.1f}%"
                else:
                    drift_calc = f"({-spot_rate:.1f}%) + ({-drift_rate:.1f}%) = {-drift_arb:.1f}%"
                    drift_desc = f"Short {variant} on Asgard {-spot_rate:.1f}% • Long {asset_name} on Drift {-drift_rate:.1f}%"

            spot_display = f"{best_spot_info['rate']:.1f}%(via {best_spot_info['variant']}/{best_spot_info['pair_asset']}) {best_spot_info['leverage']}x"

            row = {
                "Coin": asset_name,
                "Direction": f"Best {direction.lower()}",
                "Asgard Spot Margin Borrow Rate": spot_display,
                "Hyperliquid Funding Rate": f"{hyperliquid_rate:.1f}%" if hyperliquid_rate is not None else "N/A",
                "Asgard - Hyperliquid Arb": hyperliquid_calc,
                "Drift Funding Rate": f"{drift_rate:.1f}%" if drift_rate is not None else "N/A",
                "Asgard - Drift Arb": drift_calc,
                "Hyperliquid_Arb_Rate": hyperliquid_arb,
                "Drift_Arb_Rate": drift_arb,
                "Row_Group_ID": row_group_id,
                "Row_Type": "main",
            }
            rows.append(row)

            desc_row = {
                "Coin": "",
                "Direction": "",
                "Asgard Spot Margin Borrow Rate": "",
                "Hyperliquid Funding Rate": "",
                "Asgard - Hyperliquid Arb": hyperliquid_desc,
                "Drift Funding Rate": "",
                "Asgard - Drift Arb": drift_desc,
                "Hyperliquid_Arb_Rate": None,
                "Drift_Arb_Rate": None,
                "Row_Group_ID": row_group_id,
                "Row_Type": "description",
            }
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
    df_display = df_display.drop(['Hyperliquid_Arb_Rate', 'Drift_Arb_Rate', 'Row_Group_ID', 'Row_Type'], axis=1)
    return df_display


def display_curated_arbitrage_section(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    hyperliquid_data: dict,
    drift_data: dict,
    target_hours: int = DEFAULT_TARGET_HOURS,
    perps_exchange: str = "Hyperliquid",
) -> None:
    import streamlit as st

    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("📊 Asgard Spot vs Perps Arbitrage")
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

    curated_df = create_curated_arbitrage_table(
        token_config,
        rates_data,
        staking_data,
        hyperliquid_data,
        drift_data,
        target_hours,
        max_leverage,
        perps_exchange,
    )

    if curated_df.empty:
        st.info(f"No arbitrage opportunities found between Asgard and {perps_exchange}")
        st.markdown("<br>", unsafe_allow_html=True)
        return

    st.dataframe(
        curated_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Coin": st.column_config.TextColumn("Coin", pinned=True, width=80),
            "Direction": st.column_config.TextColumn("Direction", width=120),
            "Asgard Spot Margin Borrow Rate": st.column_config.TextColumn("Asgard Spot Margin Borrow Rate", width=300),
            "Hyperliquid Funding Rate": st.column_config.TextColumn("Hyperliquid Funding Rate", width=150),
            "Asgard - Hyperliquid Arb": st.column_config.TextColumn("Asgard - Hyperliquid Arb", width=400),
            "Drift Funding Rate": st.column_config.TextColumn("Drift Funding Rate", width=150),
            "Asgard - Drift Arb": st.column_config.TextColumn("Asgard - Drift Arb", width=400),
        },
    )

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


