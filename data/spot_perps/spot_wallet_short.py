from typing import Dict, Any, List, Tuple, Optional

import pandas as pd

from api.endpoints import (
    fetch_hourly_rates,
    fetch_birdeye_history_price,
    fetch_hourly_staking,
)
from data.spot_perps.helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)
from utils.dataframe_utils import records_to_dataframe, aggregate_to_4h_buckets


def find_eligible_short_variants(token_config: dict, variants: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    For each variant, find protocol/market pair with highest effective short leverage >= 2x.
    Returns mapping: variant -> { protocol, market, eff_cap }
    """
    eligible: Dict[str, Dict[str, Any]] = {}
    for variant_name in variants:
        best_pair = None
        best_cap = 0.0
        asset_pairs = get_protocol_market_pairs(token_config, variant_name)
        for p, m, asset_bank in asset_pairs:
            usdc_bank = get_matching_usdc_bank(token_config, p, m)
            if not usdc_bank:
                continue
            eff_cap = compute_effective_max_leverage(token_config, asset_bank, usdc_bank, "short")
            if eff_cap is not None and float(eff_cap) >= 2.0 and float(eff_cap) > float(best_cap):
                best_cap = float(eff_cap)
                best_pair = (p, m)
        if best_pair is not None:
            eligible[variant_name] = {
                "protocol": best_pair[0],
                "market": best_pair[1],
                "eff_cap": best_cap,
            }
    return eligible


def compute_allocation_split(total_capital_usd: float, leverage: float) -> Tuple[float, float, float]:
    """
    Returns: wallet_amount_usd, used_capital_usd, short_borrow_usd
    """
    lev_f = float(leverage)
    base_f = float(total_capital_usd)
    wallet_amount_usd = (max(lev_f - 1.0, 0.0) / lev_f) * base_f if lev_f > 0 else 0.0
    used_capital_usd = base_f - wallet_amount_usd  # equals base / L
    short_borrow_usd = (max(lev_f - 1.0, 0.0) / lev_f) * base_f
    return wallet_amount_usd, used_capital_usd, short_borrow_usd


def build_wallet_short_series(
    token_config: dict,
    wallet_asset_symbol: str,
    short_asset_symbol: str,
    protocol: str,
    market: str,
    leverage: float,
    points_hours: int,
    base_usd: float,
) -> pd.DataFrame:
    """
    Builds 4H-centered series for a delta-neutral spot strategy with a wallet asset and a shorted spot asset.
    Staking yields are excluded from accrual math; only borrow/lend APYs are applied.
    Returns DataFrame with columns:
      time, wallet_asset_price, short_asset_price, usdc_principal_usd, short_tokens_owed, close_cost_usd, net_value_usd, wallet_value_usd
    """
    # Find banks for the short asset and USDC in the selected protocol+market
    asset_pairs = get_protocol_market_pairs(token_config, short_asset_symbol)
    short_asset_bank = None
    for p, m, bank in asset_pairs:
        if p == protocol and (not market or m == market):
            short_asset_bank = bank
            break
    usdc_bank = get_matching_usdc_bank(token_config, protocol, market)
    if not short_asset_bank or not usdc_bank:
        return pd.DataFrame(columns=[
            "time", "wallet_asset_price", "short_asset_price",
            "usdc_principal_usd", "short_tokens_owed", "close_cost_usd",
            "net_value_usd", "wallet_value_usd",
        ])

    # Fetch hourly rates and aggregate to 4H
    try:
        short_hist = fetch_hourly_rates(short_asset_bank, protocol, int(points_hours)) or []
        usdc_hist = fetch_hourly_rates(usdc_bank, protocol, int(points_hours)) or []
    except Exception:
        short_hist, usdc_hist = [], []

    df_short = records_to_dataframe(short_hist, "time", ["asset_lend_apy", "asset_borrow_apy"])  # rates for short asset
    df_usdc = records_to_dataframe(usdc_hist, "time", ["usdc_lend_apy", "usdc_borrow_apy"])  # rates for usdc
    df_short_4h = aggregate_to_4h_buckets(df_short, "time", ["asset_lend_apy", "asset_borrow_apy"]) if not df_short.empty else df_short
    df_usdc_4h = aggregate_to_4h_buckets(df_usdc, "time", ["usdc_lend_apy", "usdc_borrow_apy"]) if not df_usdc.empty else df_usdc
    earn = pd.merge(df_short_4h, df_usdc_4h, on="time", how="inner")
    if earn.empty:
        return pd.DataFrame(columns=[
            "time", "wallet_asset_price", "short_asset_price",
            "usdc_principal_usd", "short_tokens_owed", "close_cost_usd",
            "net_value_usd", "wallet_value_usd",
        ])

    # Price series for wallet and short assets
    wallet_mint = (token_config.get(wallet_asset_symbol, {}) or {}).get("mint")
    short_mint = (token_config.get(short_asset_symbol, {}) or {}).get("mint")
    start_ts = int(pd.to_datetime(earn["time"].min()).timestamp())
    end_ts = int(pd.to_datetime(earn["time"].max()).timestamp())
    try:
        wallet_price_points = fetch_birdeye_history_price(wallet_mint, start_ts, end_ts, bucket="4H") if (wallet_mint and start_ts and end_ts) else []
    except Exception:
        wallet_price_points = []
    try:
        short_price_points = fetch_birdeye_history_price(short_mint, start_ts, end_ts, bucket="4H") if (short_mint and start_ts and end_ts) else []
    except Exception:
        short_price_points = []
    wallet_price_df = pd.DataFrame(wallet_price_points)
    short_price_df = pd.DataFrame(short_price_points)
    if not wallet_price_df.empty:
        wallet_price_df["time"] = pd.to_datetime(wallet_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
        wallet_price_df = wallet_price_df.sort_values("time")[ ["time", "price" ] ].rename(columns={"price": "wallet_asset_price"})
    else:
        wallet_price_df = pd.DataFrame(columns=["time", "wallet_asset_price"])
    if not short_price_df.empty:
        short_price_df["time"] = pd.to_datetime(short_price_df["t"], unit="s", utc=True).dt.tz_convert(None)
        short_price_df = short_price_df.sort_values("time")[ ["time", "price" ] ].rename(columns={"price": "short_asset_price"})
    else:
        short_price_df = pd.DataFrame(columns=["time", "short_asset_price"])

    # Merge prices and filter to rows where both prices exist
    earn = pd.merge_asof(earn.sort_values("time"), wallet_price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
    earn = pd.merge_asof(earn.sort_values("time"), short_price_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
    earn = earn.dropna(subset=["wallet_asset_price", "short_asset_price"])  # require both prices
    if earn.empty:
        return pd.DataFrame(columns=[
            "time", "wallet_asset_price", "short_asset_price",
            "usdc_principal_usd", "short_tokens_owed", "close_cost_usd",
            "net_value_usd", "wallet_value_usd",
        ])

    # Staking APY series (percentage) for wallet and short assets
    def _staking_series(mint: Optional[str]) -> pd.DataFrame:
        if not mint:
            return pd.DataFrame(columns=["time", "staking_pct"])
        try:
            records = fetch_hourly_staking(mint, int(points_hours)) or []
        except Exception:
            records = []
        if not records:
            return pd.DataFrame(columns=["time", "staking_pct"])
        d = pd.DataFrame(records)
        # hourBucket iso → naive datetime
        d["time"] = pd.to_datetime(d["hourBucket"], utc=True).dt.tz_convert(None)
        d["staking_pct"] = pd.to_numeric(d.get("avgApy", 0), errors="coerce") * 100.0
        # 4H centered aggregation
        return aggregate_to_4h_buckets(d, "time", ["staking_pct"])

    wallet_mint = (token_config.get(wallet_asset_symbol, {}) or {}).get("mint")
    short_mint = (token_config.get(short_asset_symbol, {}) or {}).get("mint")
    wallet_has_stk = bool((token_config.get(wallet_asset_symbol, {}) or {}).get("hasStakingYield", False))
    short_has_stk = bool((token_config.get(short_asset_symbol, {}) or {}).get("hasStakingYield", False))
    wal_stk_df = _staking_series(wallet_mint) if wallet_has_stk else pd.DataFrame(columns=["time", "staking_pct"])
    short_stk_df = _staking_series(short_mint) if short_has_stk else pd.DataFrame(columns=["time", "staking_pct"])
    # Merge staking into earn (nearest within tolerance)
    if not wal_stk_df.empty:
        earn = pd.merge_asof(earn.sort_values("time"), wal_stk_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
        earn = earn.rename(columns={"staking_pct": "wallet_stk_pct"})
    else:
        earn["wallet_stk_pct"] = 0.0
    if not short_stk_df.empty:
        earn = pd.merge_asof(earn.sort_values("time"), short_stk_df.sort_values("time"), on="time", direction="nearest", tolerance=pd.Timedelta("3h"))
        # If wallet staking already added, this merge will add another 'staking_pct' column; rename after
        if "staking_pct" in earn.columns:
            earn = earn.rename(columns={"staking_pct": "borrow_stk_pct"})
    else:
        earn["borrow_stk_pct"] = 0.0

    # Allocation split
    wallet_amount_usd, used_capital_usd, short_borrow_usd = compute_allocation_split(base_usd, leverage)

    # Enforce lookback window BEFORE growth so compounding starts at selected period start
    try:
        cutoff_time = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(hours=int(points_hours))
        earn = earn[earn["time"] >= cutoff_time]
    except Exception:
        pass

    # Growth factors per 4h bucket (staking excluded; only borrow/lend APY)
    bucket_factor_4h = 4.0 / (365.0 * 24.0)
    earn = earn.sort_values("time").reset_index(drop=True)
    earn["usdc_growth_factor"] = 1.0 + (earn["usdc_lend_apy"] / 100.0) * bucket_factor_4h
    earn["asset_borrow_growth_factor"] = 1.0 + (earn["asset_borrow_apy"] / 100.0) * bucket_factor_4h
    earn["usdc_growth_cum_shifted"] = earn["usdc_growth_factor"].cumprod().shift(1).fillna(1.0)
    earn["asset_borrow_growth_cum_shifted"] = earn["asset_borrow_growth_factor"].cumprod().shift(1).fillna(1.0)

    first_short_price = float(earn["short_asset_price"].iloc[0]) if not earn["short_asset_price"].dropna().empty else float("nan")
    first_wallet_price = float(earn["wallet_asset_price"].iloc[0]) if not earn["wallet_asset_price"].dropna().empty else float("nan")
    initial_usdc_lent = float(base_usd)
    initial_short_tokens_owed = (float(short_borrow_usd) / first_short_price) if (first_short_price and first_short_price > 0) else float("nan")
    wallet_tokens = (float(wallet_amount_usd) / first_wallet_price) if (first_wallet_price and first_wallet_price > 0) else float("nan")

    # Evolve through time
    earn["usdc_principal_usd"] = float(initial_usdc_lent) * earn["usdc_growth_cum_shifted"]
    earn["short_tokens_owed"] = float(initial_short_tokens_owed) * earn["asset_borrow_growth_cum_shifted"]
    earn["close_cost_usd"] = earn["short_tokens_owed"] * earn["short_asset_price"]
    earn["net_value_usd"] = earn["usdc_principal_usd"] - earn["close_cost_usd"]
    earn["wallet_value_usd"] = float(wallet_tokens) * earn["wallet_asset_price"]

    # Include APY columns so pages can show them without re-deriving
    out = earn.copy()
    out["usdc_lend_apy"] = pd.to_numeric(out.get("usdc_lend_apy", 0), errors="coerce")
    out["asset_borrow_apy"] = pd.to_numeric(out.get("asset_borrow_apy", 0), errors="coerce")
    out["wallet_stk_pct"] = pd.to_numeric(out.get("wallet_stk_pct", 0), errors="coerce").fillna(0.0)
    out["borrow_stk_pct"] = pd.to_numeric(out.get("borrow_stk_pct", 0), errors="coerce").fillna(0.0)

    # Lookback already enforced pre-growth

    return out[[
        "time",
        "wallet_asset_price",
        "short_asset_price",
        "usdc_principal_usd",
        "short_tokens_owed",
        "close_cost_usd",
        "net_value_usd",
        "wallet_value_usd",
        "usdc_lend_apy",
        "asset_borrow_apy",
        "wallet_stk_pct",
        "borrow_stk_pct",
    ]]


