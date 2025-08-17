from typing import Dict, List, Optional, Tuple

"""
Helper utilities for spot-perps calculations that do not depend on
`data.spot_arbitrage` to avoid circular imports.
"""


def get_protocol_market_pairs(token_config: dict, asset: str) -> List[Tuple[str, str, str]]:
    try:
        return [
            (bank_info["protocol"], bank_info["market"], bank_info["bank"])
            for bank_info in token_config[asset]["banks"]
        ]
    except (KeyError, TypeError):
        return []


def get_matching_usdc_bank(token_config: dict, protocol: str, market: str) -> Optional[str]:
    try:
        for usdc_bank_info in token_config["USDC"]["banks"]:
            if usdc_bank_info["protocol"] == protocol and usdc_bank_info["market"] == market:
                return usdc_bank_info["bank"]
    except (KeyError, TypeError):
        return None
    return None


# NOTE: compute_scaled_spot_rate_from_rates moved to calculations.py to avoid cycles


def compute_net_arb(spot_rate: float, funding_rate: float, spot_direction: str) -> float:
    if spot_direction.lower() == "long":
        return spot_rate - funding_rate
    return spot_rate + funding_rate


def compute_apy_from_net_arb(net_arb: float, target_hours: int) -> float:
    return abs(net_arb) * 365 * 24 / target_hours


# ==============================
# Max leverage helpers (per bank)
# ==============================

def get_bank_record_by_address(token_config: dict, bank_address: str) -> Optional[dict]:
    if not bank_address:
        return None
    try:
        for _, token_info in token_config.items():
            for bank in token_info.get("banks", []):
                if bank.get("bank") == bank_address:
                    return bank
    except (AttributeError, TypeError):
        return None
    return None


def get_bank_max_leverage_direction(bank_record: Optional[dict], direction: str) -> Optional[float]:
    if not bank_record:
        return None
    try:
        caps = bank_record.get("maxLeverage", {})
        raw = caps.get(direction.lower())
        if raw is None:
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def compute_effective_max_leverage(
    token_config: dict,
    asset_bank_address: str,
    usdc_bank_address: str,
    direction: str,
) -> float:
    """
    Effective cap is the minimum of the per-direction caps for the two legs in the position.
    Defaults to 1.0 when caps are missing.
    """
    DEFAULT_CAP = 1.0

    asset_rec = get_bank_record_by_address(token_config, asset_bank_address)
    usdc_rec = get_bank_record_by_address(token_config, usdc_bank_address)

    caps: List[float] = []
    for rec in [asset_rec, usdc_rec]:
        cap = get_bank_max_leverage_direction(rec, direction)
        if cap is not None:
            caps.append(cap)

    if not caps:
        return DEFAULT_CAP
    # Guard lower bound at 1.0
    return max(DEFAULT_CAP, min(caps))

