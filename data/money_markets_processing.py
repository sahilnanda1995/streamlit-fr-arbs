"""
Data processing for money markets functionality.
"""

import json
from typing import Dict, List, Optional
from data.models import MoneyMarketEntry


def load_token_config() -> Dict:
    """Load token configuration from JSON file."""
    try:
        with open('token_config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_rates_by_bank_address(rates_data: List[Dict], bank_address: str) -> Optional[Dict]:
    """Find rates data for a specific bank address."""
    if not rates_data:
        return None

    for rate_entry in rates_data:
        if rate_entry.get("address") == bank_address:
            return rate_entry
    return None


def get_staking_rate_by_mint(staking_data: List[Dict], mint_address: str) -> Optional[float]:
    """Find staking rate for a specific mint address."""
    if not staking_data:
        return None

    for staking_entry in staking_data:
        if staking_entry.get("address") == mint_address:
            return staking_entry.get("apy")
    return None


def process_money_markets_data(rates_data: List[Dict], staking_data: List[Dict]) -> List[MoneyMarketEntry]:
    """
    Process raw money markets data into structured format.

    Args:
        rates_data: List of lending/borrowing rates from current-rates endpoint
        staking_data: List of staking rates from current-staking-rates endpoint

    Returns:
        List of MoneyMarketEntry objects
    """
    token_config = load_token_config()
    money_markets = []

    for token_symbol, token_info in token_config.items():
        mint = token_info.get("mint")
        staking_rate = get_staking_rate_by_mint(staking_data, mint)

        for bank_info in token_info.get("banks", []):
            bank_address = bank_info.get("bank")
            rates = get_rates_by_bank_address(rates_data, bank_address)

            entry = MoneyMarketEntry(
                token=token_symbol,
                protocol=bank_info.get("protocol", ""),
                market_key=bank_info.get("market", ""),
                lending_rate=rates.get("lendingRate") if rates else None,
                borrow_rate=rates.get("borrowingRate") if rates else None,
                staking_rate=staking_rate
            )
            money_markets.append(entry)

    return money_markets


def merge_money_markets_data(rates_data: List[Dict], staking_data: List[Dict]) -> List[List]:
    """
    Merge money markets data into the same format as funding rates for consistency.

    Args:
        rates_data: Rates data from Asgard API
        staking_data: Staking data from Asgard API

    Returns:
        List of processed money markets data
    """
    money_markets = process_money_markets_data(rates_data, staking_data)

    # Convert to list format similar to funding rates
    processed_data = []
    for entry in money_markets:
        processed_data.append([
            entry.token,
            [
                ["protocol", entry.protocol],
                ["market_key", entry.market_key],
                ["lending_rate", entry.lending_rate],
                ["borrow_rate", entry.borrow_rate],
                ["staking_rate", entry.staking_rate]
            ]
        ])

    return processed_data
