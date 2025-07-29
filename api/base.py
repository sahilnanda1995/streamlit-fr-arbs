"""
Base API client with common functionality for external service requests.
"""

import requests
import streamlit as st
from typing import Dict, Optional, Any
from data.models import APIResponse


class BaseAPIClient:
    """Base API client with common request handling and error management."""

    def __init__(self, base_url: str, default_timeout: int = 30):
        """
        Initialize base API client.

        Args:
            base_url: Base URL for the API
            default_timeout: Default request timeout in seconds
        """
        self.base_url = base_url
        self.default_timeout = default_timeout

    def _make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> APIResponse:
        """
        Make HTTP request with error handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            headers: Optional request headers
            json_data: Optional JSON payload for POST requests
            timeout: Optional request timeout

        Returns:
            APIResponse object with success status and data/error
        """
        try:
            timeout = timeout or self.default_timeout

            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                timeout=timeout
            )
            response.raise_for_status()

            return APIResponse(
                success=True,
                data=response.json()
            )

        except requests.exceptions.Timeout:
            error_msg = f"Request timeout after {timeout} seconds"
            st.error(f"API request timed out: {error_msg}")
            return APIResponse(success=False, error=error_msg)

        except requests.exceptions.ConnectionError:
            error_msg = "Failed to connect to API endpoint"
            st.error(f"Connection error: {error_msg}")
            return APIResponse(success=False, error=error_msg)

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.reason}"
            st.error(f"HTTP error: {error_msg}")
            return APIResponse(success=False, error=error_msg)

        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            st.error(f"Request error: {error_msg}")
            return APIResponse(success=False, error=error_msg)

        except ValueError as e:
            error_msg = f"Invalid JSON response: {str(e)}"
            st.error(f"JSON decode error: {error_msg}")
            return APIResponse(success=False, error=error_msg)

    def get(self, endpoint: str = "", **kwargs) -> APIResponse:
        """Make GET request to endpoint."""
        url = f"{self.base_url}{endpoint}" if endpoint else self.base_url
        return self._make_request("GET", url, **kwargs)

    def post(self, endpoint: str = "", **kwargs) -> APIResponse:
        """Make POST request to endpoint."""
        url = f"{self.base_url}{endpoint}" if endpoint else self.base_url
        return self._make_request("POST", url, **kwargs)
