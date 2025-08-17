import requests
import streamlit as st
from typing import List, Dict, Any

# Create a persistent session for connection reuse
session = requests.Session()

@st.cache_data(ttl=300)
def fetch_hourly_rates(bank_address: str, protocol: str, limit: int = 720) -> List[Dict[str, Any]]:
    try:
        url = f"https://historical-apy.asgard.finance/rates/hourly-data/{bank_address}/{protocol.lower()}"
        response = session.get(url, params={"limit": limit}, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return []
        records = data.get("data", {}).get("records", [])
        if isinstance(records, list):
            return records
        return []
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching hourly rates: {str(e)}")
        return []
    except ValueError:
        st.error("Error parsing hourly rates response")
        return []


@st.cache_data(ttl=300)
def fetch_hourly_staking(mint_address: str, limit: int = 720) -> List[Dict[str, Any]]:
    try:
        url = f"https://historical-apy.asgard.finance/staking/hourly-data/{mint_address}"
        response = session.get(url, params={"limit": limit}, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return []
        records = data.get("data", {}).get("records", [])
        if isinstance(records, list):
            return records
        return []
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching hourly staking: {str(e)}")
        return []
    except ValueError:
        st.error("Error parsing hourly staking response")
        return []
"""
Functional API endpoints for fetching data from external services.
"""
from config.constants import (
    HYPERLIQUID_API_URL,
    HYPERLIQUID_CORE_API_URL,
    HYPERLIQUID_HEADERS,
    HYPERLIQUID_REQUEST_BODY,
    DRIFT_API_URL,
    DRIFT_FUNDING_HISTORY_URL,
    ASGARD_CURRENT_RATES_URL,
    ASGARD_STAKING_RATES_URL,
    LORIS_FUNDING_API_URL
)

@st.cache_data(ttl=300)
def fetch_hyperliquid_funding_history(coin: str = "BTC", start_time_ms: int = 0) -> List[Dict[str, Any]]:
    """
    Fetch historical funding rates from Hyperliquid core API.

    Args:
        coin: Asset symbol (e.g., "BTC")
        start_time_ms: Epoch milliseconds start time

    Returns:
        List of dicts with keys: coin, fundingRate, premium, time
    """
    try:
        payload = {"type": "fundingHistory", "coin": coin}
        if start_time_ms > 0:
            payload["startTime"] = start_time_ms
        response = session.post(
            url=HYPERLIQUID_CORE_API_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        return []
    except requests.exceptions.Timeout:
        st.error("Hyperliquid funding history request timed out")
        return []
    except requests.exceptions.RequestException as e:
        st.error(f"Hyperliquid funding history request failed: {str(e)}")
        return []
    except ValueError:
        st.error("Invalid JSON from Hyperliquid funding history API")
        return []


@st.cache_data(ttl=300)
def fetch_drift_funding_history(market_index: int, start_ts: float, end_ts: float) -> List[Dict[str, Any]]:
    """
    Fetch Drift funding rates history for one market in [start_ts, end_ts] seconds.

    Returns a list of entries, each containing at least { "time": ms, "fundingRate": float }.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://app.drift.trade/',
        'Origin': 'https://app.drift.trade',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site'
    }
    try:
        params = {
            'marketIndex': market_index,
            'from': f"{start_ts:.3f}",
            'to': f"{end_ts:.3f}"
        }
        response = session.get(DRIFT_FUNDING_HISTORY_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('status') != 'ok':
            st.error("Invalid response from Drift funding history API")
            return []
        # Expected structure: { status: 'ok', fundingRates: [ ... ] }
        entries = data.get('fundingRates') or data.get('data') or []
        normalized: List[Dict[str, Any]] = []
        for e in entries:
            ts_seconds = e.get('ts') or e.get('time') or 0
            fr_raw = e.get('fundingRate')
            oracle_twap_raw = e.get('oraclePriceTwap')
            try:
                ts_ms = int(float(ts_seconds) * 1000)
            except (TypeError, ValueError):
                continue
            try:
                fr_num = float(fr_raw)
                oracle_num = float(oracle_twap_raw)
            except (TypeError, ValueError):
                continue
            # Convert to hourly decimal: (fundingRate / 1e9) / (oraclePriceTwap / 1e6)
            if oracle_num == 0:
                continue
            hourly_decimal = (fr_num / 1e9) / (oracle_num / 1e6)
            normalized.append({
                'time': ts_ms,
                'fundingRate': hourly_decimal,
            })
        return normalized
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching Drift funding history: {str(e)}")
        return []
    except ValueError:
        st.error("Error parsing Drift funding history response")
        return []


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_hyperliquid_funding_data() -> List[Dict[str, Any]]:
    """
    Fetch predicted funding rates from Hyperliquid API.

    Returns:
        List of funding data or empty list if request failed
    """
    try:
        response = session.post(
            url=HYPERLIQUID_API_URL,
            headers=HYPERLIQUID_HEADERS,
            json=HYPERLIQUID_REQUEST_BODY,
            timeout=5
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        st.error("Hyperliquid API request timed out after 5 seconds")
        return []

    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to Hyperliquid API endpoint")
        return []

    except requests.exceptions.HTTPError as e:
        st.error(f"Hyperliquid API HTTP error: {e.response.status_code}: {e.response.reason}")
        return []

    except requests.exceptions.RequestException as e:
        st.error(f"Hyperliquid API request failed: {str(e)}")
        return []

    except ValueError as e:
        st.error(f"Invalid JSON response from Hyperliquid API: {str(e)}")
        return []


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_drift_markets_24h() -> Dict[str, Any]:
    """
    Fetch 24h market data from Drift API.

    Returns:
        Market data dictionary or empty dict if request failed
    """
    try:
        response = session.get(url=DRIFT_API_URL, timeout=5)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        st.error("Drift API request timed out after 5 seconds")
        return {}

    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to Drift API endpoint")
        return {}

    except requests.exceptions.HTTPError as e:
        st.error(f"Drift API HTTP error: {e.response.status_code}: {e.response.reason}")
        return {}

    except requests.exceptions.RequestException as e:
        st.error(f"Drift API request failed: {str(e)}")
        return {}

    except ValueError as e:
        st.error(f"Invalid JSON response from Drift API: {str(e)}")
        return {}


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_loris_funding_data() -> Dict[str, Any]:
    """
    Fetch 24h market data from Loris API.

    Returns:
        Market data dictionary or empty dict if request failed
    """
    try:
        response = session.get(url=LORIS_FUNDING_API_URL, timeout=5)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        st.error("Loris API request timed out after 5 seconds")
        return {}

    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to Loris API endpoint")
        return {}

    except requests.exceptions.HTTPError as e:
        st.error(f"Loris API HTTP error: {e.response.status_code}: {e.response.reason}")
        return {}

    except requests.exceptions.RequestException as e:
        st.error(f"Loris API request failed: {str(e)}")
        return {}

    except ValueError as e:
        st.error(f"Invalid JSON response from Loris API: {str(e)}")
        return {}


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_asgard_current_rates() -> List[Dict[str, Any]]:
    """
    Fetch current lending and borrowing rates from Asgard API.

    Returns:
        List of rates data or empty list if request failed
    """
    try:
        response = session.get(url=ASGARD_CURRENT_RATES_URL, timeout=5)
        response.raise_for_status()
        response_data = response.json()

        if response_data is not None and isinstance(response_data, dict):
            return response_data.get("data", [])
        return []

    except requests.exceptions.Timeout:
        st.error("Asgard current rates API request timed out after 5 seconds")
        return []

    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to Asgard current rates API endpoint")
        return []

    except requests.exceptions.HTTPError as e:
        st.error(f"Asgard current rates API HTTP error: {e.response.status_code}: {e.response.reason}")
        return []

    except requests.exceptions.RequestException as e:
        st.error(f"Asgard current rates API request failed: {str(e)}")
        return []

    except ValueError as e:
        st.error(f"Invalid JSON response from Asgard current rates API: {str(e)}")
        return []


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_asgard_staking_rates() -> List[Dict[str, Any]]:
    """
    Fetch current staking rates from Asgard API.

    Returns:
        List of staking data or empty list if request failed
    """
    try:
        response = session.get(url=ASGARD_STAKING_RATES_URL, timeout=5)
        response.raise_for_status()
        response_data = response.json()

        if response_data is not None and isinstance(response_data, dict):
            # Extract the 'data' field from the response
            return response_data.get("data", [])
        return []

    except requests.exceptions.Timeout:
        st.error("Asgard staking rates API request timed out after 5 seconds")
        return []

    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to Asgard staking rates API endpoint")
        return []

    except requests.exceptions.HTTPError as e:
        st.error(f"Asgard staking rates API HTTP error: {e.response.status_code}: {e.response.reason}")
        return []

    except requests.exceptions.RequestException as e:
        st.error(f"Asgard staking rates API request failed: {str(e)}")
        return []

    except ValueError as e:
        st.error(f"Invalid JSON response from Asgard staking rates API: {str(e)}")
        return []
