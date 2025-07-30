"""
Data models for the funding rate comparison application.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Union


@dataclass
class ExchangeInfo:
    """Information about funding rate from a specific exchange."""
    funding_rate: float
    funding_interval_hours: int

    @classmethod
    def from_dict(cls, data: Dict[str, Union[str, int, float]]) -> 'ExchangeInfo':
        """Create ExchangeInfo from API response dictionary."""
        return cls(
            funding_rate=float(data.get("fundingRate", 0)),
            funding_interval_hours=int(data.get("fundingIntervalHours", 1))
        )


@dataclass
class TokenEntry:
    """A token with funding information from multiple exchanges."""
    token_name: str
    exchanges: Dict[str, ExchangeInfo]

    def get_exchange_rate(self, exchange_name: str) -> Optional[ExchangeInfo]:
        """Get funding rate info for a specific exchange."""
        return self.exchanges.get(exchange_name)

    def has_exchange(self, exchange_name: str) -> bool:
        """Check if token has data for specific exchange."""
        return exchange_name in self.exchanges


@dataclass
class FundingRateRow:
    """A row in the funding rates display table."""
    token: str
    hyperliquid: Optional[float] = None
    binance: Optional[float] = None
    bybit: Optional[float] = None
    drift: Optional[float] = None

    def to_dict(self) -> Dict[str, Optional[float]]:
        """Convert to dictionary for DataFrame creation."""
        return {
            "Token": self.token,
            "Hyperliquid": self.hyperliquid,
            "Binance": self.binance,
            "Bybit": self.bybit,
            "Drift": self.drift
        }


# API response wrapper models have been removed in favor of direct functional approach


@dataclass
class MoneyMarketEntry:
    """A row in the money markets display table."""
    token: str
    protocol: str
    market_key: str
    lending_rate: Optional[float] = None
    borrow_rate: Optional[float] = None
    staking_rate: Optional[float] = None

    def to_dict(self) -> Dict[str, Union[str, Optional[float]]]:
        """Convert to dictionary for DataFrame creation."""
        return {
            "Token": self.token,
            "Protocol": self.protocol,
            "Market Key": self.market_key,
            "Lending Rate": self.lending_rate,
            "Borrow Rate": self.borrow_rate,
            "Staking Rate": self.staking_rate
        }
