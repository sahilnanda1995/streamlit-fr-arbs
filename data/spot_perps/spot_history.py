from typing import List, Dict, Optional, Tuple

import pandas as pd
from pandas import Timedelta
import time

from api.endpoints import (
    fetch_hourly_rates,
    fetch_hourly_staking,
    fetch_hyperliquid_funding_history,
    fetch_drift_funding_history,
)
from data.spot_perps.helpers import get_matching_usdc_bank, get_protocol_market_pairs
from data.spot_perps.helpers import compute_effective_max_leverage
from config.constants import DEFAULT_TARGET_HOURS, DRIFT_MARKET_INDEX, ASSET_VARIANTS
from utils.formatting import scale_funding_rate_to_percentage

# Simple in-memory caches to avoid recomputing/refetching within a session
_PERPS_SERIES_CACHE: Dict[Tuple[str, str, int], pd.DataFrame] = {}
_SPOT_SERIES_CACHE: Dict[Tuple[str, str, str, str, float, int], pd.DataFrame] = {}


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


def _resample_to_4h_center(df: pd.DataFrame, value_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    work = work.set_index("time")
    # 4-hour buckets aligned to midnight; centralize by adding +2h
    agg = work[value_cols].resample("4h").mean()
    agg.index = agg.index + Timedelta(hours=2)
    agg = agg.reset_index().rename(columns={"index": "time"})
    return agg


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
    cache_key = (asset, protocol, market, direction.lower(), float(leverage), int(limit))
    if cache_key in _SPOT_SERIES_CACHE:
        return _SPOT_SERIES_CACHE[cache_key]

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

    # If the asset has staking yield, restrict to periods where asset staking series is available
    required_stk_cols = ["asset_stk"] if asset_has_staking else []
    if required_stk_cols:
        df = df.dropna(subset=required_stk_cols)

    # Direction mapping
    if direction.lower() == "long":
        lend_pct = df["asset_lend"]
        borrow_pct = df["usdc_borrow"]
        lend_stk_pct = df["asset_stk"].infer_objects(copy=False).fillna(0.0)
        borrow_stk_pct = df["usdc_stk"].infer_objects(copy=False).fillna(0.0)
        eff_max = compute_effective_max_leverage(token_config, asset_bank, usdc_bank, "long")
    else:
        lend_pct = df["usdc_lend"]
        borrow_pct = df["asset_borrow"]
        lend_stk_pct = df["usdc_stk"].infer_objects(copy=False).fillna(0.0)
        borrow_stk_pct = df["asset_stk"].infer_objects(copy=False).fillna(0.0)
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

    df = df[["time", "spot_rate_pct"]].sort_values("time")
    df = _resample_to_4h_center(df, ["spot_rate_pct"])  # 4H centered buckets
    # Enforce lookback window explicitly by time (post-resample)
    try:
        cutoff_time = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(hours=int(limit))
        df = df[df["time"] >= cutoff_time]
    except Exception:
        pass
    _SPOT_SERIES_CACHE[cache_key] = df
    return df


def _infer_asset_type(variant: str) -> Optional[str]:
    for typ, variants in ASSET_VARIANTS.items():
        if variant in variants:
            return typ
    return None


def _build_hl_perps_series(asset_type: str, limit: int) -> pd.DataFrame:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(limit) * 3600 * 1000
    # Basic pagination: fetch from start and ensure sorted
    entries: List[Dict] = []
    next_start = start_ms
    seen = set()
    for _ in range(6):
        page = fetch_hyperliquid_funding_history(coin=asset_type, start_time_ms=next_start)
        if not page:
            break
        added = 0
        for e in page:
            t = int(e.get("time", 0))
            if t and t not in seen:
                entries.append(e)
                seen.add(t)
                added += 1
        if added == 0:
            break
        latest = max(int(e.get("time", 0)) for e in entries)
        next_start = latest + 1
    # to df and convert to APY%
    if not entries:
        return pd.DataFrame(columns=["time", "funding_pct"])
    df = pd.DataFrame(entries)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(None)
    df = df.sort_values("time")
    df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["funding_pct"] = scale_funding_rate_to_percentage(df["fundingRate"], 1, DEFAULT_TARGET_HOURS)
    df = df[["time", "funding_pct"]]
    df = _resample_to_4h_center(df, ["funding_pct"])  # 4H centered buckets
    return df


def _build_drift_perps_series(asset_type: str, limit: int) -> pd.DataFrame:
    idx = DRIFT_MARKET_INDEX.get(asset_type)
    if idx is None:
        return pd.DataFrame(columns=["time", "funding_pct"])
    end = round(time.time(), 3)
    start = round(end - (int(limit) * 3600), 3)
    entries = fetch_drift_funding_history(idx, start, end)
    if not entries:
        return pd.DataFrame(columns=["time", "funding_pct"])
    df = pd.DataFrame(entries)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(None)
    df = df.sort_values("time")
    df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["funding_pct"] = scale_funding_rate_to_percentage(df["fundingRate"], 1, DEFAULT_TARGET_HOURS)
    df = df[["time", "funding_pct"]]
    df = _resample_to_4h_center(df, ["funding_pct"])  # 4H centered buckets
    return df


def build_perps_history_series(perps_exchange: str, asset_type: str, limit: int = 720) -> pd.DataFrame:
    cache_key = (perps_exchange, asset_type, int(limit))
    if cache_key in _PERPS_SERIES_CACHE:
        return _PERPS_SERIES_CACHE[cache_key]
    if perps_exchange == "Hyperliquid":
        df = _build_hl_perps_series(asset_type, limit)
        _PERPS_SERIES_CACHE[cache_key] = df
        return df
    if perps_exchange == "Drift":
        df = _build_drift_perps_series(asset_type, limit)
        _PERPS_SERIES_CACHE[cache_key] = df
        return df
    # For unsupported exchanges, return empty
    df_empty = pd.DataFrame(columns=["time", "funding_pct"])
    _PERPS_SERIES_CACHE[cache_key] = df_empty
    return df_empty


def build_arb_history_series(
    token_config: dict,
    variant: str,
    protocol: str,
    market: str,
    direction: str,
    leverage: float,
    perps_exchange: str,
    limit: int = 720,
) -> pd.DataFrame:
    """
    Build historical arbitrage series with three lines:
      - spot_rate_pct (APY%)
      - funding_pct (APY%)
      - net_arb_pct (APY%)
    """
    asset_type = _infer_asset_type(variant) or "SOL"
    spot_df = build_spot_history_series(
        token_config, variant, protocol, market, direction, leverage, limit
    )
    perps_df = build_perps_history_series(perps_exchange, asset_type, limit)
    if spot_df.empty or perps_df.empty:
        return pd.DataFrame(columns=["time", "spot_rate_pct", "funding_pct", "net_arb_pct"])
    df = spot_df.merge(perps_df, on="time", how="inner")

    # Apply effective funding factor to perps funding rate
    dir_lower = direction.lower()
    effective_factor = float(leverage) if dir_lower == "long" else max(float(leverage) - 1.0, 0.0)
    df["funding_pct"] = df["funding_pct"] * effective_factor

    # Net arbitrage uses effective funding rate
    if dir_lower == "long":
        df["net_arb_pct"] = df["spot_rate_pct"] - df["funding_pct"]
    else:
        df["net_arb_pct"] = df["spot_rate_pct"] + df["funding_pct"]

    # Only consider buckets where spot rate is available
    df = df.dropna(subset=["spot_rate_pct"])  # ensures ROE, charts, and tables use valid spot buckets only

    return df[["time", "spot_rate_pct", "funding_pct", "net_arb_pct"]].sort_values("time")


