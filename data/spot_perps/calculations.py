from typing import Dict, List, Optional, Callable

from data.money_markets_processing import get_staking_rate_by_mint, get_rates_by_bank_address
from config.constants import DEFAULT_TARGET_HOURS
from .helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_effective_max_leverage,
)


def compute_scaled_spot_rate_from_rates(
    lend_rates: Dict,
    borrow_rates: Dict,
    lend_staking_rate_decimal: float,
    borrow_staking_rate_decimal: float,
    leverage: float,
    target_hours: int,
) -> float:
    # Re-implement here to avoid circular import with data.spot_arbitrage
    # lend_rates/borrow_rates contain APY percentages (e.g., 5.0 means 5%)
    lend_rate = (lend_rates or {}).get("lendingRate", 0.0) or 0.0
    borrow_rate = (borrow_rates or {}).get("borrowingRate", 0.0) or 0.0
    # Convert staking rates from decimal to percentage
    lend_staking_pct = (lend_staking_rate_decimal or 0.0) * 100.0
    borrow_staking_pct = (borrow_staking_rate_decimal or 0.0) * 100.0
    # Net rates
    net_lend = lend_rate + lend_staking_pct
    net_borrow = borrow_rate + borrow_staking_pct
    # Fee rate APY (%)
    fee_rate_pct = net_borrow * (leverage - 1.0) - net_lend * leverage
    # Hourly percentage rate
    hourly_rate_pct = fee_rate_pct / (365.0 * 24.0)
    # Scale to target hours (still percentage)
    return hourly_rate_pct * target_hours


def calculate_spot_rate_with_direction(
    token_config: dict,
    rates_data: dict,
    staking_data: dict,
    asset: str,
    leverage: float = 2.0,
    direction: str = "long",  # "long" or "short"
    target_hours: int = DEFAULT_TARGET_HOURS,
    logger: Optional[Callable[[str], None]] = None,
) -> Dict[str, float]:
    spot_rates: Dict[str, float] = {}

    asset_pairs = get_protocol_market_pairs(token_config, asset)
    asset_mint = token_config[asset]["mint"]
    asset_staking_rate = get_staking_rate_by_mint(staking_data, asset_mint) or 0.0

    for protocol, market, asset_bank in asset_pairs:
        usdc_bank = get_matching_usdc_bank(token_config, protocol, market)
        if not usdc_bank:
            continue

        if direction == "long":
            lend_rates = get_rates_by_bank_address(rates_data, asset_bank)
            borrow_rates = get_rates_by_bank_address(rates_data, usdc_bank)
            lend_staking_rate = asset_staking_rate
            borrow_staking_rate = get_staking_rate_by_mint(staking_data, token_config["USDC"]["mint"]) or 0.0
        else:
            lend_rates = get_rates_by_bank_address(rates_data, usdc_bank)
            borrow_rates = get_rates_by_bank_address(rates_data, asset_bank)
            lend_staking_rate = get_staking_rate_by_mint(staking_data, token_config["USDC"]["mint"]) or 0.0
            borrow_staking_rate = asset_staking_rate

        if not lend_rates or not borrow_rates:
            if logger is not None:
                missing_parts = []
                if not lend_rates:
                    missing_parts.append("lending")
                if not borrow_rates:
                    missing_parts.append("borrowing")
                missing_str = "/".join(missing_parts)
                logger(
                    f"Skipping {asset} {direction.upper()} at {protocol} ({market}): missing {missing_str} data."
                )
            continue

        lend_rate = lend_rates.get("lendingRate")
        borrow_rate = borrow_rates.get("borrowingRate")
        if lend_rate is None or borrow_rate is None:
            if logger is not None:
                missing_parts = []
                if lend_rate is None:
                    missing_parts.append("lending")
                if borrow_rate is None:
                    missing_parts.append("borrowing")
                missing_str = "/".join(missing_parts)
                logger(
                    f"Skipping {asset} {direction.upper()} at {protocol} ({market}): {missing_str} rate not available."
                )
            continue

        # Enforce per-bank max leverage caps (default to 1.0 if missing)
        effective_max = compute_effective_max_leverage(
            token_config,
            asset_bank if direction == "long" else usdc_bank,
            usdc_bank if direction == "long" else asset_bank,
            direction,
        )
        if leverage > effective_max:
            continue

        try:
            scaled_rate = compute_scaled_spot_rate_from_rates(
                lend_rates,
                borrow_rates,
                lend_staking_rate,
                borrow_staking_rate,
                leverage,
                target_hours,
            )
            spot_rates[f"{protocol}({market})"] = scaled_rate
        except ValueError:
            continue

    return spot_rates


def get_perps_rates_for_asset(
    hyperliquid_data: dict,
    drift_data: dict,
    asset: str,
    target_hours: int = DEFAULT_TARGET_HOURS,
) -> Dict[str, float]:
    from data.processing import merge_funding_rate_data
    from utils.formatting import scale_funding_rate_to_percentage
    from config.constants import EXCHANGE_NAME_MAPPING

    merged_data = merge_funding_rate_data(hyperliquid_data, drift_data)
    perps_rates: Dict[str, float] = {}
    for token_entry in merged_data:
        if token_entry[0] == asset:
            for exchange_name, details in token_entry[1]:
                if details is None:
                    continue
                try:
                    rate = details.get("fundingRate", 0)
                    scaled_percent = scale_funding_rate_to_percentage(rate, 1, target_hours)
                    display_name = EXCHANGE_NAME_MAPPING.get(exchange_name) or exchange_name
                    perps_rates[display_name] = scaled_percent
                except (ValueError, TypeError):
                    continue
            break
    return perps_rates


def calculate_spot_vs_perps_arb(
    spot_rate: float,
    perps_rates: Dict[str, float],
    spot_direction: str,
) -> Optional[float]:
    if not perps_rates:
        return None
    net_arbs: List[float] = []
    for _, funding_rate in perps_rates.items():
        if spot_direction == "Long":
            net_arbs.append(spot_rate - funding_rate)
        else:
            net_arbs.append(spot_rate + funding_rate)
    if not net_arbs:
        return None
    best_arb = min(net_arbs)
    return best_arb if best_arb < 0 else None


def calculate_perps_vs_perps_arb(perps_rates: Dict[str, float]) -> Optional[float]:
    if len(perps_rates) < 2:
        return None
    exchanges = list(perps_rates.keys())
    diffs: List[float] = []
    for i in range(len(exchanges)):
        for j in range(i + 1, len(exchanges)):
            diffs.append(perps_rates[exchanges[i]] - perps_rates[exchanges[j]])
    if not diffs:
        return None
    best_arb = min(diffs)
    return best_arb if best_arb < 0 else None


