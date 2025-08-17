from typing import Dict, List, Optional, Tuple

from data.spot_arbitrage import calculate_hourly_fee_rates


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


def compute_scaled_spot_rate_from_rates(
    lend_rates: Dict,
    borrow_rates: Dict,
    lend_staking_rate_decimal: float,
    borrow_staking_rate_decimal: float,
    leverage: float,
    target_hours: int,
) -> float:
    hourly_rate = calculate_hourly_fee_rates(
        lend_rates,
        borrow_rates,
        lend_staking_rate_decimal,
        borrow_staking_rate_decimal,
        leverage,
    )
    return hourly_rate * target_hours


def compute_net_arb(spot_rate: float, funding_rate: float, spot_direction: str) -> float:
    if spot_direction.lower() == "long":
        return spot_rate - funding_rate
    return spot_rate + funding_rate


def compute_apy_from_net_arb(net_arb: float, target_hours: int) -> float:
    return abs(net_arb) * 365 * 24 / target_hours


