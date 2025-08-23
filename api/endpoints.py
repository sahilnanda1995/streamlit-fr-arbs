import requests
import time
import streamlit as st
from typing import List, Dict, Any, Optional, Callable
from contextlib import contextmanager

# Create a persistent session for connection reuse
session = requests.Session()
_BIRDEYE_LAST_CALL_TS: float = 0.0  # simple 1 rps throttle


def handle_api_error(error: Exception, api_name: str, fallback_value: Any) -> Any:
    """Common error handler for API requests."""
    if isinstance(error, requests.exceptions.Timeout):
        st.error(f"{api_name} request timed out")
    elif isinstance(error, requests.exceptions.ConnectionError):
        st.error(f"Failed to connect to {api_name}")
    elif isinstance(error, requests.exceptions.HTTPError):
        st.error(f"{api_name} HTTP error: {error.response.status_code}: {error.response.reason}")
    elif isinstance(error, requests.exceptions.RequestException):
        st.error(f"{api_name} request failed: {str(error)}")
    elif isinstance(error, ValueError):
        st.error(f"Error parsing {api_name} response")
    else:
        st.error(f"Error with {api_name}: {str(error)}")
    return fallback_value


def make_request_with_retry(
    request_func: Callable,
    api_name: str,
    fallback_value: Any,
    max_attempts: int = 10,
    initial_backoff: float = 1.2,
    backoff_multiplier: float = 1.5
) -> Any:
    """Make HTTP request with retry logic and exponential backoff."""
    attempts = 0
    backoff = initial_backoff
    
    while attempts < max_attempts:
        try:
            return request_func()
        except (requests.exceptions.RequestException, ValueError) as e:
            attempts += 1
            if isinstance(e, requests.exceptions.Timeout):
                st.warning(f"{api_name} request timed out; retrying...")
            if attempts >= max_attempts:
                st.error(f"{api_name} request failed after retries")
                return fallback_value
            time.sleep(backoff)
            backoff *= backoff_multiplier
    
    return fallback_value


@contextmanager
def session_manager():
    """Context manager for session cleanup."""
    try:
        yield session
    finally:
        # Session cleanup happens automatically on app shutdown
        pass

@st.cache_data(ttl=300)
def fetch_hourly_rates(bank_address: str, protocol: str, limit: int = 720) -> List[Dict[str, Any]]:
    def _make_request():
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
    
    try:
        return _make_request()
    except Exception as e:
        return handle_api_error(e, "Hourly rates", [])


@st.cache_data(ttl=300)
def fetch_hourly_staking(mint_address: str, limit: int = 720) -> List[Dict[str, Any]]:
    def _make_request():
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
    
    try:
        return _make_request()
    except Exception as e:
        return handle_api_error(e, "Hourly staking", [])
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
    LORIS_FUNDING_API_URL,
    BIRDEYE_HISTORY_URL,
    BIRDEYE_API_KEY,
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
    def _make_request():
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
    
    try:
        return _make_request()
    except Exception as e:
        return handle_api_error(e, "Hyperliquid funding history", [])


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
    def _make_request():
        response = session.post(
            url=HYPERLIQUID_API_URL,
            headers=HYPERLIQUID_HEADERS,
            json=HYPERLIQUID_REQUEST_BODY,
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    
    try:
        return _make_request()
    except Exception as e:
        return handle_api_error(e, "Hyperliquid API", [])


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_drift_markets_24h() -> Dict[str, Any]:
    """
    Fetch 24h market data from Drift API.

    Returns:
        Market data dictionary or empty dict if request failed
    """
    def _make_request():
        response = session.get(url=DRIFT_API_URL, timeout=5)
        response.raise_for_status()
        return response.json()
    
    try:
        return _make_request()
    except Exception as e:
        return handle_api_error(e, "Drift API", {})


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_loris_funding_data() -> Dict[str, Any]:
    """
    Fetch 24h market data from Loris API.

    Returns:
        Market data dictionary or empty dict if request failed
    """
    def _make_request():
        response = session.get(url=LORIS_FUNDING_API_URL, timeout=8)
        response.raise_for_status()
        data = response.json()
        # Ensure dict structure to match processing expectations
        if isinstance(data, dict):
            return data
        # If list or other, wrap minimally so downstream code won't crash
        return {"funding_rates": {}, "exchanges": {"exchange_names": []}}
    
    return make_request_with_retry(_make_request, "Loris API", {})


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_asgard_current_rates() -> List[Dict[str, Any]]:
    """Fetch current lending and borrowing rates from Asgard API with retries."""
    def _make_request():
        response = session.get(url=ASGARD_CURRENT_RATES_URL, timeout=12)
        response.raise_for_status()
        response_data = response.json()
        if response_data is not None and isinstance(response_data, dict):
            return response_data.get("data", [])
        return []
    
    return make_request_with_retry(_make_request, "Asgard current rates", [], backoff_multiplier=1.7)


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_asgard_staking_rates() -> List[Dict[str, Any]]:
    """Fetch current staking rates from Asgard API with retries."""
    def _make_request():
        response = session.get(url=ASGARD_STAKING_RATES_URL, timeout=12)
        response.raise_for_status()
        response_data = response.json()
        if response_data is not None and isinstance(response_data, dict):
            return response_data.get("data", [])
        return []
    
    return make_request_with_retry(_make_request, "Asgard staking rates", [], backoff_multiplier=1.7)


@st.cache_data(ttl=300)
def fetch_birdeye_history_price(
    mint_address: str,
    time_from: int,
    time_to: int,
    bucket: str = "4H",
) -> List[Dict[str, Any]]:
    """
    Fetch historical price series from Birdeye for a token mint.

    Returns list of points with at least {t: seconds, price: float} when available.
    """
    def _make_request_with_rate_limit():
        headers = {
            "X-API-KEY": BIRDEYE_API_KEY,
            "accept": "application/json",
            "x-chain": "solana",
        }
        params = {
            "address": mint_address,
            "address_type": "token",
            "type": bucket,
            "time_from": time_from,
            "time_to": time_to,
            "ui_amount_mode": "raw",
        }
        # Enforce 1 rps pacing across the app
        global _BIRDEYE_LAST_CALL_TS
        now = time.time()
        elapsed = now - _BIRDEYE_LAST_CALL_TS
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        resp = session.get(BIRDEYE_HISTORY_URL, headers=headers, params=params, timeout=12)
        _BIRDEYE_LAST_CALL_TS = time.time()
        if resp.status_code == 429:
            raise requests.exceptions.RequestException("Rate limited")
        resp.raise_for_status()
        data = resp.json()
        items = (((data or {}).get("data") or {}).get("items") or [])
        points: List[Dict[str, Any]] = []
        for it in items:
            t_raw = it.get("unixTime")
            v_raw = it.get("value")
            try:
                t = int(t_raw)
                p = float(v_raw)
            except (TypeError, ValueError):
                continue
            points.append({"t": t, "price": p})
        return points
    
    return make_request_with_retry(_make_request_with_rate_limit, "Birdeye price", [], backoff_multiplier=1.7)

