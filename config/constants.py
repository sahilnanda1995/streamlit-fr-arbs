"""
Configuration constants for the funding rate comparison application.
"""

# Funding interval options for user selection
INTERVAL_OPTIONS = {
    "1 hr": 1,
    "4 hr": 4,
    "8 hr": 8,
    "24 hr": 24,
    "1 yr (8760 hrs)": 8760
}

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
DEFAULT_FUNDING_INTERVAL_HOURS = 1
PERP_SYMBOL_SUFFIX = "-PERP"

# UI Configuration
APP_TITLE = "📈 SPOT and Perps Arbitrage"
APP_DESCRIPTION = "Calculate the arbitrage opportunities between Spot and Perps."
PAGE_TITLE = "SPOT and Perps Arbitrage"
