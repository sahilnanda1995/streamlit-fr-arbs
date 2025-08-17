"""
Backwards-compatible shim for spot-perps logic.

This module re-exports functionality from the new modular package `data.spot_perps`
so that existing imports continue to work after the refactor.
"""

from dataclasses import dataclass
from typing import Dict, Optional

# Re-export public API
from data.spot_perps import (  # noqa: F401
    # helpers
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_scaled_spot_rate_from_rates,
    compute_net_arb,
    compute_apy_from_net_arb,
    # calculations
    calculate_spot_rate_with_direction,
    get_perps_rates_for_asset,
    calculate_spot_vs_perps_arb,
    calculate_perps_vs_perps_arb,
    # curated
    create_curated_arbitrage_table,
    find_best_spot_rate_across_leverages,
    display_curated_arbitrage_section,
    # explorer
    display_spot_perps_opportunities_section,
    create_spot_perps_opportunities_table,
    display_all_possible_arbitrage_opportunities,
    display_spot_perps_breakdowns,
    display_table_arbitrage_calculation_breakdown,
    create_arbitrage_opportunities_summary,
    display_arbitrage_opportunities_summary,
    format_spot_perps_dataframe,
    display_asset_top_opportunities,
)


@dataclass
class SpotPerpsOpportunity:
    spot_direction: str  # "Long" or "Short"
    asset: str
    spot_rates: Dict[str, float]  # {protocol: rate}
    perps_rates: Dict[str, float]  # {exchange: rate}
    spot_vs_perps_arb: Optional[float]
    perps_vs_perps_arb: Optional[float]


