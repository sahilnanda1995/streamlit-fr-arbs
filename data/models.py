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


@dataclass
class APIResponse:
    """Base class for API response handling."""
    success: bool
    data: Optional[List] = None
    error: Optional[str] = None


@dataclass
class HyperliquidResponse(APIResponse):
    """Hyperliquid API response structure."""
    pass


@dataclass
class DriftResponse(APIResponse):
    """Drift API response structure."""

    def get_perp_markets(self) -> List[Dict]:
        """Extract perpetual markets from Drift response."""
        if not self.success or not self.data:
            return []

        # Drift API returns data in nested structure
        market_data = self.data.get("data", []) if isinstance(self.data, dict) else self.data

        perp_markets = []
        for item in market_data:
            market_type = item.get("marketType", {})
            symbol = item.get("symbol", "")

            # Filter for perp markets
            if "perp" in market_type and symbol.endswith("-PERP"):
                perp_markets.append(item)

        return perp_markets
