"""
HTTP utilities for making API requests with robust error handling.
"""

import requests
import streamlit as st
from typing import Dict, Optional, Any


def make_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 30
) -> Optional[Dict[str, Any]]:
    """
    Make HTTP request with comprehensive error handling.

    Args:
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        headers: Optional request headers
        json_data: Optional JSON payload for POST requests
        timeout: Request timeout in seconds

    Returns:
        JSON response data or None if request failed
    """
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            timeout=timeout
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        error_msg = f"Request timeout after {timeout} seconds"
        st.error(f"API request timed out: {error_msg}")
        return None

    except requests.exceptions.ConnectionError:
        error_msg = "Failed to connect to API endpoint"
        st.error(f"Connection error: {error_msg}")
        return None

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP {e.response.status_code}: {e.response.reason}"
        st.error(f"HTTP error: {error_msg}")
        return None

    except requests.exceptions.RequestException as e:
        error_msg = f"Request failed: {str(e)}"
        st.error(f"Request error: {error_msg}")
        return None

    except ValueError as e:
        error_msg = f"Invalid JSON response: {str(e)}"
        st.error(f"JSON decode error: {error_msg}")
        return None


def get_request(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> Optional[Dict[str, Any]]:
    """
    Make GET request.

    Args:
        url: Request URL
        headers: Optional request headers
        timeout: Request timeout in seconds

    Returns:
        JSON response data or None if request failed
    """
    return make_request("GET", url, headers=headers, timeout=timeout)


def post_request(
    url: str,
    json_data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30
) -> Optional[Dict[str, Any]]:
    """
    Make POST request.

    Args:
        url: Request URL
        json_data: Optional JSON payload
        headers: Optional request headers
        timeout: Request timeout in seconds

    Returns:
        JSON response data or None if request failed
    """
    return make_request("POST", url, headers=headers, json_data=json_data, timeout=timeout)
