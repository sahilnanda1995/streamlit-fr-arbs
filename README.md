# Funding Rate Arbitrage Dashboard

A Streamlit application for comparing predicted funding rates across multiple cryptocurrency exchanges (Hyperliquid, Binance, Bybit, and Drift) for various tokens.

## 🚀 Features

- **Multi-Exchange Support**: Compare funding rates from Hyperliquid, Binance, Bybit, and Drift
- **Flexible Intervals**: Scale funding rates to different time intervals (1hr, 4hr, 8hr, 24hr, 1yr)
- **Real-time Data**: Fetches live funding rate data from exchange APIs
- **Clean Interface**: Easy-to-read table with percentage-based funding rates
- **Raw Data Access**: View raw API responses for debugging and analysis

## 📁 Project Structure

```
fr-arbs/
├── streamlit_app.py          # Main Streamlit application (UI only)
├── config/
│   ├── __init__.py
│   └── constants.py          # Configuration constants and settings
├── api/
│   ├── __init__.py
│   ├── base.py              # Base API client with error handling
│   ├── hyperliquid.py       # Hyperliquid API client
│   └── drift.py             # Drift API client
├── data/
│   ├── __init__.py
│   ├── models.py            # Data models and type definitions
│   ├── processing.py        # Data transformation functions
│   └── merger.py            # Data merging logic
├── utils/
│   ├── __init__.py
│   └── formatting.py        # Display formatting utilities
├── sample-responses/        # Sample API responses for testing
│   ├── drift-market-index.json
│   └── drift-avg-endpoints.json
├── requirements.txt         # Python dependencies
└── README.md               # This file
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

### Using the Interface

1. **Select Interval**: Choose your desired funding rate interval from the dropdown
2. **View Data**: The table shows scaled funding rates as percentages for each token across exchanges
3. **Raw Data**: Expand the "Show raw API response" section to view unprocessed API data

## 🔧 Architecture

### Modular Design

The application follows a clean, modular architecture with clear separation of concerns:

- **UI Logic** (`streamlit_app.py`): Pure Streamlit interface components
- **Configuration** (`config/`): All constants and settings in one place
- **API Layer** (`api/`): External service clients with proper error handling
- **Data Layer** (`data/`): Data models, processing, and merging logic
- **Utilities** (`utils/`): Formatting and helper functions

### Data Flow

1. **API Clients** fetch raw data from exchange APIs
2. **Data Processing** transforms responses into standardized format
3. **Data Merging** combines data from multiple sources
4. **Formatting** scales rates and prepares for display
5. **UI Rendering** displays the final table and controls

## 📊 API Documentation

### Hyperliquid API

- **Endpoint**: `https://api-ui.hyperliquid.xyz/info`
- **Method**: `POST`
- **Purpose**: Fetches predicted funding rates for perpetual contracts

### Drift API

#### Market 24Hr Data

- **Endpoint**: `https://mainnet-beta.api.drift.trade/markets24h`
- **Method**: `GET`
- **Purpose**: Provides ongoing funding rates for perpetual markets
- **Sample Response**: `sample-responses/drift-market-index.json`

#### Average Funding Rates

- **Endpoint**: `https://mainnet-beta.api.drift.trade/stats/avgFundingRates`
- **Method**: `GET`
- **Purpose**: Historical average funding rate statistics
- **Sample Response**: `sample-responses/drift-avg-endpoints.json`

## 🧪 Development

### Code Organization

The codebase is organized for maintainability and testing:

- **Type Safety**: Uses dataclasses and type hints throughout
- **Error Handling**: Comprehensive error handling in API clients
- **Caching**: Streamlit caching for API responses
- **Documentation**: Docstrings for all functions and classes

### Adding New Exchanges

To add support for a new exchange:

1. Create a new client in `api/new_exchange.py`
2. Extend the base client: `class NewExchangeClient(BaseAPIClient)`
3. Add processing logic in `data/processing.py`
4. Update constants in `config/constants.py`
5. Modify display logic in `utils/formatting.py`

### Testing

The modular structure makes testing easy:

- **Unit Tests**: Each module can be tested independently
- **API Mocking**: Base client supports easy mocking for tests
- **Data Validation**: Models provide type safety and validation

## 📝 Configuration

Key configuration values in `config/constants.py`:

- **Interval Options**: Available time intervals for scaling
- **API URLs**: Endpoints for each exchange
- **Exchange Mappings**: Internal names to display names
- **UI Settings**: Application title, descriptions, etc.

## 🤝 Contributing

When contributing:

1. Follow the existing modular structure
2. Add proper type hints and docstrings
3. Update constants rather than hardcoding values
4. Test with different interval selections
5. Ensure error handling is maintained

## 📈 Performance

- **Caching**: API responses are cached using `@st.cache_data`
- **Parallel Processing**: API calls could be parallelized (future enhancement)
- **Error Recovery**: Graceful handling of API failures
- **Memory Efficient**: Minimal data retention between requests
