from typing import List, Dict, Optional, Tuple

import pandas as pd
from datetime import datetime

from api.endpoints import fetch_hourly_rates, fetch_hourly_staking
from data.spot_perps.helpers import get_matching_usdc_bank, get_protocol_market_pairs
from data.spot_perps.helpers import compute_effective_max_leverage


def _find_banks_for_pair(token_config: dict, asset: str, protocol: str, market: str) -> Tuple[Optional[str], Optional[str]]:
    asset_pairs = get_protocol_market_pairs(token_config, asset)
    asset_bank = None
    for p, m, bank in asset_pairs:
        if p == protocol and m == market:
            asset_bank = bank
            break
    usdc_bank = get_matching_usdc_bank(token_config, protocol, market)
    return asset_bank, usdc_bank


def _to_df(records: List[Dict], rate_field: str, is_decimal: bool = False) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["time", rate_field])
    df = pd.DataFrame(records)
    # hourBucket is ISO; convert to naive datetime
    df["time"] = pd.to_datetime(df["hourBucket"], utc=True).dt.tz_convert(None)
    if is_decimal:
        df[rate_field] = pd.to_numeric(df[rate_field], errors="coerce") * 100.0
    else:
        df[rate_field] = pd.to_numeric(df[rate_field], errors="coerce")
    return df[["time", rate_field]].sort_values("time")


def build_spot_history_series(
    token_config: dict,
    asset: str,
    protocol: str,
    market: str,
    direction: str,
    leverage: float,
    limit: int = 720,
) -> pd.DataFrame:
    """
    Builds a per-hour historical spot rate series as APY (%), using hourly averages.
    direction: "long" or "short"
    """
    asset_bank, usdc_bank = _find_banks_for_pair(token_config, asset, protocol, market)
    if not asset_bank or not usdc_bank:
        return pd.DataFrame(columns=["time", "spot_rate_pct"]).astype({"spot_rate_pct": float})

    asset_mint = token_config[asset]["mint"]
    usdc_mint = token_config["USDC"]["mint"]

    asset_rates = fetch_hourly_rates(asset_bank, protocol, limit)
    usdc_rates = fetch_hourly_rates(usdc_bank, protocol, limit)

    # Only fetch staking if the token config indicates staking yield availability
    asset_has_staking = bool(token_config.get(asset, {}).get("hasStakingYield", False))
    usdc_has_staking = bool(token_config.get("USDC", {}).get("hasStakingYield", False))
    asset_stk = fetch_hourly_staking(asset_mint, limit) if asset_has_staking else []
    usdc_stk = fetch_hourly_staking(usdc_mint, limit) if usdc_has_staking else []

    # Build dataframes
    asset_lend = _to_df(asset_rates, "avgLendingRate", is_decimal=False)
    asset_borrow = _to_df(asset_rates, "avgBorrowingRate", is_decimal=False)
    usdc_lend = _to_df(usdc_rates, "avgLendingRate", is_decimal=False)
    usdc_borrow = _to_df(usdc_rates, "avgBorrowingRate", is_decimal=False)
    asset_stk_df = _to_df(asset_stk, "avgApy", is_decimal=True)
    usdc_stk_df = _to_df(usdc_stk, "avgApy", is_decimal=True)

    # Merge
    df = pd.DataFrame({"time": pd.to_datetime(sorted(set(asset_lend["time"]).intersection(usdc_borrow["time"])))} )
    df = df.merge(asset_lend, on="time", how="left").rename(columns={"avgLendingRate": "asset_lend"})
    df = df.merge(asset_borrow, on="time", how="left").rename(columns={"avgBorrowingRate": "asset_borrow"})
    df = df.merge(usdc_lend, on="time", how="left").rename(columns={"avgLendingRate": "usdc_lend"})
    df = df.merge(usdc_borrow, on="time", how="left").rename(columns={"avgBorrowingRate": "usdc_borrow"})
    df = df.merge(asset_stk_df, on="time", how="left").rename(columns={"avgApy": "asset_stk"})
    df = df.merge(usdc_stk_df, on="time", how="left").rename(columns={"avgApy": "usdc_stk"})

    # Direction mapping
    if direction.lower() == "long":
        lend_pct = df["asset_lend"]
        borrow_pct = df["usdc_borrow"]
        lend_stk_pct = df["asset_stk"].fillna(0.0)
        borrow_stk_pct = df["usdc_stk"].fillna(0.0)
        eff_max = compute_effective_max_leverage(token_config, asset_bank, usdc_bank, "long")
    else:
        lend_pct = df["usdc_lend"]
        borrow_pct = df["asset_borrow"]
        lend_stk_pct = df["usdc_stk"].fillna(0.0)
        borrow_stk_pct = df["asset_stk"].fillna(0.0)
        eff_max = compute_effective_max_leverage(token_config, asset_bank, usdc_bank, "short")

    # Compute fee_rate% per row
    net_lend = lend_pct.fillna(0.0) + lend_stk_pct
    net_borrow = borrow_pct.fillna(0.0) + borrow_stk_pct
    fee_rate_pct = net_borrow * (leverage - 1.0) - net_lend * leverage

    # Enforce cap: mark out-of-cap as NaN
    if leverage > eff_max:
        df["spot_rate_pct"] = float("nan")
    else:
        df["spot_rate_pct"] = fee_rate_pct

    return df[["time", "spot_rate_pct"]].sort_values("time")


