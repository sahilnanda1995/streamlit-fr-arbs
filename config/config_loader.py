"""
Token configuration management with singleton pattern.
"""

import json
from typing import Dict, Any

# Global cache for token configuration
_CONFIG_CACHE: Dict[str, Any] = {}

def get_token_config() -> Dict[str, Any]:
    """
    Get cached token configuration. Loads once, uses everywhere.

    Returns:
        Dict with uppercase token keys and their configuration
    """
    if 'data' not in _CONFIG_CACHE:
        try:
            with open('token_config.json', 'r') as f:
                raw_config = json.load(f)
            _CONFIG_CACHE['data'] = {k.upper(): v for k, v in raw_config.items()}
        except FileNotFoundError:
            _CONFIG_CACHE['data'] = {}

    return _CONFIG_CACHE['data']

def clear_config_cache():
    """Clear cache for testing purposes."""
    _CONFIG_CACHE.clear()
