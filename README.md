# SPOT and Perps Arbitrage Dashboard

A multi-page Streamlit application for analyzing arbitrage opportunities between spot lending/borrowing markets and perpetual futures funding rates across multiple cryptocurrency exchanges and DeFi protocols.

## 🚀 Features

### 📊 Main Dashboard - Spot and Perps Arbitrage

- **💰 Spot vs Perps Opportunities**: Calculate arbitrage opportunities between spot markets and perpetual futures
- **🔄 Long/Short Positions**: Compare long and short spot positions against perps funding rates
- **📈 Multi-Asset Support**: SOL variants (SOL, JITOSOL, JUPSOL) and BTC variants (CBBTC, WBTC, XBTC)
- **⚖️ Leverage Analysis**: 2x leverage calculations with customizable parameters

### 📄 Individual Pages

#### 💰 Spot Hourly Fee Rates

- **Leverage Levels**: Calculate arbitrage opportunities for 1x-5x leverage
- **Asset Variants**: SOL variants (SOL, JITOSOL, JUPSOL) and BTC variants (CBBTC, WBTC, XBTC)
- **Formula**: `Fee Rate = (borrow_rate + staking_rate) * (leverage - 1) - (lend_rate + staking_rate) * leverage`

#### 💰 Money Markets

- **Current Rates**: Lending and borrowing rates across protocols
- **Staking Yields**: Staking rates for yield-bearing tokens
- **Protocol Coverage**: Marginfi, Kamino, Drift, Solend
- **Token Support**: 20+ tokens including SOL variants, BTC variants, stablecoins

#### 📈 Funding Rates

- **Interval Selection**: Choose from 1hr, 4hr, 8hr, 24hr, or 1yr intervals
- **Exchange Comparison**: Compare funding rates across Hyperliquid and Drift
- **Scaled Display**: Rates automatically scaled to selected interval
- **Raw Data**: Expand sections to view unprocessed API responses

## 📁 Project Structure

```
fr-arbs/
├── streamlit_app.py          # Main dashboard - Spot and Perps Arbitrage
├── pages/                    # Individual feature pages
│   ├── 1_Spot_Hourly_Fee_Rates.py    # Spot arbitrage calculations
│   ├── 2_Money_Markets.py            # Money markets display
│   └── 3_Funding_Rates.py            # Funding rates comparison
├── config/
│   ├── __init__.py
│   ├── constants.py          # Configuration constants and settings
│   └── config_loader.py      # Token configuration management
├── api/
│   ├── __init__.py
│   └── endpoints.py          # API endpoints for external services
├── data/
│   ├── __init__.py
│   ├── models.py             # Data models and type definitions
│   ├── processing.py         # Data transformation functions
│   ├── money_markets_processing.py  # Money markets data processing
│   ├── spot_arbitrage.py     # Spot arbitrage calculations
│   └── spot_perps_arbitrage.py      # Spot vs perps arbitrage logic
├── utils/
│   ├── __init__.py
│   └── formatting.py         # Display formatting utilities
├── sample-responses/         # Sample API responses for testing
│   ├── current-rates.json
│   ├── current-staking-rates.json
│   ├── drift-market-index.json
│   ├── drift-avg-endpoints.json
│   └── hyperliquid-funding-rates.json
├── token_config.json         # Token configuration for money markets
├── requirements.txt          # Python dependencies
└── README.md                # This file
```

## 🛠️ Installation

1. **Clone the repository** (or navigate to the project directory)

2. **Create and activate a virtual environment**:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## 🎯 Usage

### Running the Application

```bash
streamlit run streamlit_app.py
```

The application will open in your default web browser at `http://localhost:8501`.

### Navigation

The application uses Streamlit's multi-page structure:

- **🏠 Main Page**: Spot and Perps Arbitrage dashboard
- **💰 Spot Hourly Fee Rates**: Traditional spot arbitrage calculations
- **💰 Money Markets**: Current lending/borrowing rates display
- **📈 Funding Rates**: Perpetual funding rates comparison

### Main Dashboard - Spot and Perps Arbitrage

The main page provides a comprehensive view of arbitrage opportunities between spot markets and perpetual futures:

- **Asset Groups**: SOL variants and BTC variants
- **Position Types**: Long and Short spot positions
- **Exchange Coverage**: Hyperliquid, Binance, Drift, Bybit
- **Real-time Data**: Live rates from multiple APIs
- **Arbitrage Calculations**: Spot vs Perps and Perps vs Perps opportunities

### Individual Pages

#### 1. 💰 Spot Hourly Fee Rates

- **SOL Variants Table**: Shows arbitrage opportunities for SOL, JITOSOL, JUPSOL
- **BTC Variants Table**: Shows arbitrage opportunities for CBBTC, WBTC, XBTC
- **Leverage Levels**: Displays hourly fee rates for 1x-5x leverage
- **Formula**: `Fee Rate = (borrow_rate + staking_rate) * (leverage - 1) - (lend_rate + staking_rate) * leverage`

#### 2. 💰 Money Markets

- **Current Rates**: Lending and borrowing rates across protocols
- **Staking Yields**: Staking rates for yield-bearing tokens
- **Protocol Coverage**: Marginfi, Kamino, Drift, Solend
- **Token Support**: 20+ tokens including SOL variants, BTC variants, stablecoins

#### 3. 📈 Funding Rates

- **Interval Selection**: Choose from 1hr, 4hr, 8hr, 24hr, or 1yr intervals
- **Exchange Comparison**: Compare funding rates across Hyperliquid and Drift
- **Scaled Display**: Rates automatically scaled to selected interval
- **Raw Data**: Expand sections to view unprocessed API responses

## 🔧 Architecture

### Multi-Page Design

The application follows Streamlit's multi-page structure for better organization:

- **Main Dashboard** (`streamlit_app.py`): Comprehensive spot vs perps arbitrage analysis
- **Feature Pages** (`pages/`): Specialized functionality for specific use cases
- **Shared Modules**: Common functionality shared across all pages

### Modular Design

The application follows a clean, modular architecture with clear separation of concerns:

- **UI Logic**: Streamlit interface with multi-page navigation
- **Configuration** (`config/`): Constants, settings, and token configuration management
- **API Layer** (`api/`): External service clients with proper error handling and caching
- **Data Layer** (`data/`): Data models, processing, and arbitrage calculations
- **Utilities** (`utils/`): Formatting and display helper functions

### Data Flow

1. **API Clients** fetch raw data from 4 external APIs (Hyperliquid, Drift, Asgard Current Rates, Asgard Staking Rates)
2. **Data Processing** transforms responses into standardized formats
3. **Arbitrage Calculations** compute opportunities for different scenarios:
   - Spot arbitrage with leverage
   - Spot vs Perps arbitrage
   - Perps vs Perps arbitrage
4. **Data Merging** combines data from multiple sources
5. **Formatting** scales rates and prepares for display
6. **UI Rendering** displays the final tables and controls

## 📊 API Documentation

### Hyperliquid API

- **Endpoint**: `https://api-ui.hyperliquid.xyz/info`
- **Method**: `POST`
- **Purpose**: Fetches predicted funding rates for perpetual contracts
- **Caching**: 5-minute TTL

### Drift API

- **Endpoint**: `https://mainnet-beta.api.drift.trade/markets24h`
- **Method**: `GET`
- **Purpose**: Provides ongoing funding rates for perpetual markets
- **Sample Response**: `sample-responses/drift-market-index.json`
- **Caching**: 5-minute TTL

### Asgard APIs

#### Current Lending and Borrowing Rates

- **Endpoint**: `https://historical-apy.asgard.finance/current-rates`
- **Method**: `GET`
- **Purpose**: Provides ongoing lending and borrowing rates across protocols
- **Sample Response**: `sample-responses/current-rates.json`
- **Caching**: 5-minute TTL

#### Current Staking Rates

- **Endpoint**: `https://historical-apy.asgard.finance/current-staking-rates`
- **Method**: `GET`
- **Purpose**: Provides current staking rates for different tokens
- **Sample Response**: `sample-responses/current-staking-rates.json`
- **Caching**: 5-minute TTL

## 🧪 Development

### Code Organization

The codebase is organized for maintainability and testing:

- **Type Safety**: Uses dataclasses and type hints throughout
- **Error Handling**: Comprehensive error handling in API endpoints
- **Caching**: Streamlit caching for API responses with 5-minute TTL
- **Documentation**: Docstrings for all functions and classes
- **Modular Design**: Clear separation between UI, API, data processing, and utilities

### Adding New Features

To add new functionality:

1. **New Page**: Create a new file in `pages/` directory
2. **New API**: Add function in `api/endpoints.py` with `@st.cache_data(ttl=300)` decorator
3. **New Processing**: Add logic in appropriate `data/` module
4. **Configuration**: Update constants in `config/constants.py` if needed

### Adding New Exchanges

To add support for a new exchange:

1. Add a new function in `api/endpoints.py` with `@st.cache_data(ttl=300)` decorator
2. Add API configuration constants to `config/constants.py`
3. Add processing logic in `data/processing.py` to handle the exchange data format
4. Update exchange name mappings in `config/constants.py`
5. Modify display logic in `utils/formatting.py` if needed

### Adding New Tokens

To add support for new tokens:

1. Add token configuration to `token_config.json`
2. Include mint address, protocol mappings, and bank addresses
3. Update processing logic in `data/money_markets_processing.py` if needed

### Testing

The functional structure makes testing easy:

- **Unit Tests**: Each module can be tested independently
- **API Mocking**: HTTP utilities support easy mocking for tests
- **Data Validation**: Business models provide type safety and validation
- **Caching**: Function-level caching with Streamlit's `@st.cache_data`

## 📝 Configuration

Key configuration values in `config/constants.py`:

- **Interval Options**: Available time intervals for scaling (1hr, 4hr, 8hr, 24hr, 1yr)
- **API URLs**: Endpoints for each service
- **Exchange Mappings**: Internal names to display names
- **UI Settings**: Application title, descriptions, etc.
- **Asset Groups**: SOL variants and BTC variants for arbitrage calculations
- **Leverage Levels**: Available leverage options for calculations

Token configuration in `token_config.json`:

- **301 lines** of token configuration
- Maps tokens to mint addresses, protocols, markets, and bank addresses
- Supports 20+ tokens across 4 DeFi protocols

## 🤝 Contributing

When contributing:

1. Follow the existing modular structure
2. Add proper type hints and docstrings
3. Update constants rather than hardcoding values
4. Test with different interval selections and leverage levels for fee rate calculations
5. Ensure error handling is maintained
6. Update token configuration for new tokens
7. Consider adding new pages for major features

## 📈 Performance

- **Caching**: API responses are cached using `@st.cache_data` with 5-minute TTL
- **Sequential Processing**: API calls are made sequentially (parallelization is a future enhancement)
- **Error Recovery**: Graceful handling of API failures with fallback displays
- **Memory Efficient**: Minimal data retention between requests
- **Type Safety**: Comprehensive type hints prevent runtime errors

## 🔍 Key Features Explained

### Spot and Perps Arbitrage

The main dashboard calculates arbitrage opportunities between spot markets and perpetual futures:

- **Long Position**: Lend asset, borrow USDC, compare against perps funding
- **Short Position**: Lend USDC, borrow asset, compare against perps funding
- **Perps vs Perps**: Compare funding rates across different exchanges
- **Real-time Updates**: Live data from multiple sources

### Spot Arbitrage Fee Rate Calculation

The spot arbitrage page calculates opportunities using the formula:

```
Fee Rate = (borrow_rate + staking_rate) * (leverage - 1) - (lend_rate + staking_rate) * leverage
Hourly Fee Rate = Fee Rate / (365 * 24)
```

This shows the potential fee rate (cost or profit) from borrowing one asset and lending another at different leverage levels. Positive values indicate a cost, while negative values indicate a profit opportunity.

### Money Markets Integration

The application integrates data from multiple DeFi protocols:

- **Marginfi**: Main market lending/borrowing
- **Kamino**: Main market and isolated markets
- **Drift**: Perpetual funding rates
- **Solend**: Traditional lending protocol

### Token Coverage

The application supports 20+ tokens including:

- **SOL Variants**: SOL, JITOSOL, JUPSOL, mSOL, CGNTSOL, ezSOL, kySOL
- **BTC Variants**: CBBTC, WBTC, XBTC
- **Stablecoins**: USDC, USDT, FDUSD, USDS, USDG
- **Other**: JLP, wETH, sSOL, dSOL

## 📦 Dependencies

The application uses minimal dependencies:

- **streamlit**: Web application framework with multi-page support
- **requests**: HTTP client for API calls
- **pandas**: Data manipulation and display

## 🔧 Technical Details

### Multi-Page Structure

- **Main Page**: Comprehensive spot vs perps arbitrage dashboard
- **Feature Pages**: Specialized functionality for specific use cases
- **Shared Resources**: Common modules and configuration across all pages

### Caching Strategy

- **API Responses**: 5-minute TTL using `@st.cache_data`
- **Session Reuse**: Persistent HTTP session for connection efficiency
- **Error Handling**: Graceful degradation with user-friendly error messages

### Data Processing

- **Type Safety**: Comprehensive type hints and dataclasses
- **Error Recovery**: Fallback displays when APIs are unavailable
- **Data Validation**: Input validation and sanitization
- **Formatting**: Consistent display formatting across all sections

### Security

- **No API Keys**: All endpoints are public APIs
- **Input Validation**: All user inputs are validated
- **Error Handling**: No sensitive information in error messages
