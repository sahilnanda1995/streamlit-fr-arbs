"""
Spot-Perps functionality split into multiple modules for readability.
Exports a stable public API to be imported by UI and other modules.
"""

from .helpers import (
    get_protocol_market_pairs,
    get_matching_usdc_bank,
    compute_net_arb,
    compute_apy_from_net_arb,
)

from .calculations import (
    calculate_spot_rate_with_direction,
    get_perps_rates_for_asset,
    calculate_spot_vs_perps_arb,
    calculate_perps_vs_perps_arb,
    compute_scaled_spot_rate_from_rates,
)

from .curated import (
    create_curated_arbitrage_table,
    find_best_spot_rate_across_leverages,
    display_curated_arbitrage_section,
)

from .explorer import (
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
from .backtesting import (
    display_backtesting_section,
)
from .asset_strategy import (
    display_asset_strategy_section,
    display_alp_strategy_section,
)

__all__ = [
    # helpers
    "get_protocol_market_pairs",
    "get_matching_usdc_bank",
    "compute_net_arb",
    "compute_apy_from_net_arb",
    # calculations
    "calculate_spot_rate_with_direction",
    "get_perps_rates_for_asset",
    "calculate_spot_vs_perps_arb",
    "calculate_perps_vs_perps_arb",
    # curated
    "create_curated_arbitrage_table",
    "find_best_spot_rate_across_leverages",
    "display_curated_arbitrage_section",
    # explorer
    "display_spot_perps_opportunities_section",
    "create_spot_perps_opportunities_table",
    "display_all_possible_arbitrage_opportunities",
    "display_spot_perps_breakdowns",
    "display_table_arbitrage_calculation_breakdown",
    "create_arbitrage_opportunities_summary",
    "display_arbitrage_opportunities_summary",
    "format_spot_perps_dataframe",
    "display_asset_top_opportunities",
    # backtesting
    "display_backtesting_section",
    # generic asset strategy
    "display_asset_strategy_section",
    # alp strategy
    "display_alp_strategy_section",
]


