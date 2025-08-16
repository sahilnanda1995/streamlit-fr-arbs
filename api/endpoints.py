"""
Functional API endpoints for fetching data from external services.
"""

import requests
import streamlit as st
from typing import List, Dict, Any
from config.constants import (
    HYPERLIQUID_API_URL,
    HYPERLIQUID_HEADERS,
    HYPERLIQUID_REQUEST_BODY,
    DRIFT_API_URL,
    ASGARD_CURRENT_RATES_URL,
    ASGARD_STAKING_RATES_URL,
    LORIS_FUNDING_API_URL
)

# Create a persistent session for connection reuse
session = requests.Session()


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
