"""
Configuration constants for the funding rate comparison application.
"""

# Funding interval options for user selection
INTERVAL_OPTIONS = {
    "1 yr": 8760,
    "1 hr": 1,
    "4 hr": 4,
    "8 hr": 8,
    "24 hr": 24
}

# Default target hours (1 year)
DEFAULT_TARGET_HOURS = INTERVAL_OPTIONS["1 yr"]

# API Configuration
HYPERLIQUID_API_URL = "https://api-ui.hyperliquid.xyz/info"
DRIFT_API_URL = "https://mainnet-beta.api.drift.trade/markets24h"

# Asgard API Configuration
ASGARD_CURRENT_RATES_URL = "https://historical-apy.asgard.finance/current-rates"
ASGARD_STAKING_RATES_URL = "https://historical-apy.asgard.finance/current-staking-rates"

# HTTP Headers for Hyperliquid API
HYPERLIQUID_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://app.hyperliquid.xyz/fundingComparison"
}

# API Request payloads
HYPERLIQUID_REQUEST_BODY = {
    "type": "predictedFundings"
}

# Exchange name mappings
EXCHANGE_NAME_MAPPING = {
    "HlPerp": "Hyperliquid",
    "BinPerp": "Binance",
    "BybitPerp": "Bybit",
    "DriftPerp": "Drift"
}

# Column names for DataFrame display
DISPLAY_COLUMNS = ["Hyperliquid", "Binance", "Bybit", "Drift"]

# Money Markets columns
MONEY_MARKETS_COLUMNS = ["Token", "Protocol", "Market Key", "Lending Rate", "Borrow Rate", "Staking Rate"]

# Data processing constants
PERCENTAGE_CONVERSION_FACTOR = 100
PERP_SYMBOL_SUFFIX = "-PERP"

# UI Configuration
APP_TITLE = "📈 SPOT and Perps Arbitrage"
APP_DESCRIPTION = "Checkout the arbitrage opportunities between Spot and Perps."
PAGE_TITLE = "SPOT and Perps Arbitrage"

# Spot Arbitrage Configuration
SPOT_ASSET_GROUPS = {
    "SOL_VARIANTS": ["SOL", "JITOSOL", "JUPSOL"],
    "BTC_VARIANTS": ["CBBTC", "WBTC", "XBTC"]
}
SPOT_BORROW_ASSET = "USDC"
SPOT_LEVERAGE_LEVELS = [1, 2, 3, 4, 5]

# Spot and Perps Arbitrage Configuration
SPOT_PERPS_CONFIG = {
    "BTC_ASSETS": ["CBBTC", "WBTC", "XBTC"],
    "SOL_ASSETS": ["SOL", "JITOSOL", "JUPSOL"],
    "PERPS_EXCHANGES": ["Hyperliquid", "Binance", "Drift", "Bybit"],
    "DEFAULT_SPOT_LEVERAGE": 2,
    "SPOT_DIRECTIONS": ["Long", "Short"],
    "PERPS_ASSET_MAPPING": {
        "BTC": "BTC",  # Use "BTC" to find funding rates for BTC assets
        "SOL": "SOL"   # Use "SOL" to find funding rates for SOL assets
    }
}
