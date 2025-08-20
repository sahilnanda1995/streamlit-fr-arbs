"""
Configuration constants for the funding rate comparison application.
Loads sensitive values strictly from Streamlit secrets (no fallbacks).
"""

import streamlit as st  # type: ignore

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

# API Configuration (required from secrets)
HYPERLIQUID_API_URL = st.secrets["api"]["HYPERLIQUID_API_URL"]
HYPERLIQUID_CORE_API_URL = st.secrets["api"]["HYPERLIQUID_CORE_API_URL"]
DRIFT_FUNDING_HISTORY_URL = st.secrets["api"]["DRIFT_FUNDING_HISTORY_URL"]
DRIFT_API_URL = st.secrets["api"]["DRIFT_API_URL"]

# Loris consolidated funding API
LORIS_FUNDING_API_URL = st.secrets["api"]["LORIS_FUNDING_API_URL"]

# Asgard API Configuration
ASGARD_CURRENT_RATES_URL = st.secrets["api"]["ASGARD_CURRENT_RATES_URL"]
ASGARD_STAKING_RATES_URL = st.secrets["api"]["ASGARD_STAKING_RATES_URL"]
ASGARD_HISTORICAL_RATES_URL = st.secrets["api"]["ASGARD_HISTORICAL_RATES_URL"]
ASGARD_HISTORICAL_STAKING_RATES_URL = st.secrets["api"]["ASGARD_HISTORICAL_STAKING_RATES_URL"]

# Birdeye price API
BIRDEYE_HISTORY_URL = "https://public-api.birdeye.so/defi/history_price"
# NOTE: Provided by user for this project scope
BIRDEYE_API_KEY = "4260d80716404833a7e798ec2cc16593"

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

# Exchanges: single source of truth mapping internal keys to display names
EXCHANGES = {
    "hyperliquid_1_perp": "Hyperliquid",
    "binance_1_perp": "Binance",
    "bybit_1_perp": "Bybit",
    "lighter_1_perp": "Lighter",
    "DriftPerp": "Drift",
}

# Derived views
EXCHANGE_NAME_MAPPING = EXCHANGES
DISPLAY_COLUMNS = [EXCHANGES[k] for k in [
    "hyperliquid_1_perp",
    "binance_1_perp",
    "bybit_1_perp",
    "lighter_1_perp",
    "DriftPerp",
]]

# Money Markets columns
MONEY_MARKETS_COLUMNS = ["Token", "Protocol", "Market Key", "Lending Rate", "Borrow Rate", "Staking Rate"]

# Data processing constants
PERCENTAGE_CONVERSION_FACTOR = 100
PERP_SYMBOL_SUFFIX = "-PERP"

# Loris funding data constants
BPS_TO_DECIMAL = 10000
LORIS_ALLOWED_EXCHANGES = [
    key for key in EXCHANGES.keys() if key != "DriftPerp"
]

# UI Configuration
APP_TITLE = "Delta Neutral Strategies"
APP_DESCRIPTION = "Checkout the delta neutral opportunities between Spot and Perps."
PAGE_TITLE = "Delta Neutral Strategies"

# Asset variants (single source)
ASSET_VARIANTS = {
    "SOL": ["SOL", "JITOSOL", "JUPSOL", "INF"],
    "BTC": ["CBBTC", "WBTC", "XBTC"],
}

# Spot Arbitrage Configuration (derived)
SPOT_ASSET_GROUPS = {
    "SOL_VARIANTS": ASSET_VARIANTS["SOL"],
    "BTC_VARIANTS": ASSET_VARIANTS["BTC"],
}
SPOT_BORROW_ASSET = "USDC"
SPOT_LEVERAGE_LEVELS = [round(x * 0.5, 1) for x in range(2, 11)]  # [1.0, 1.5, ..., 5.0]

# Spot and Perps Arbitrage Configuration
SPOT_PERPS_CONFIG = {
    "BTC_ASSETS": ASSET_VARIANTS["BTC"],
    "SOL_ASSETS": ASSET_VARIANTS["SOL"],
    "PERPS_EXCHANGES": DISPLAY_COLUMNS,
    "DEFAULT_SPOT_LEVERAGE": 2,
    "SPOT_DIRECTIONS": ["Long", "Short"],
    "PERPS_ASSET_MAPPING": {
        "BTC": "BTC",
        "SOL": "SOL",
    },
}

# Drift market index mapping (per Drift conventions)
DRIFT_MARKET_INDEX = {
    "SOL": 0,
    "BTC": 1,
    "ETH": 2,
}

# Backtesting configuration
BACKTEST_COINS = ["BTC", "SOL", "ETH"]
BACKTEST_CAPTION = "Funding Rate shown as APY (%) over the past 1 month"

# Birdeye price API
BIRDEYE_HISTORY_URL = st.secrets["api"]["BIRDEYE_HISTORY_URL"]
BIRDEYE_API_KEY = st.secrets["api"]["BIRDEYE_API_KEY"]
