# API package for external service clients

from .endpoints import (
    fetch_hyperliquid_funding_data,
    fetch_drift_markets_24h,
    fetch_asgard_current_rates,
    fetch_asgard_staking_rates
)

__all__ = [
    'fetch_hyperliquid_funding_data',
    'fetch_drift_markets_24h',
    'fetch_asgard_current_rates',
    'fetch_asgard_staking_rates'
]
