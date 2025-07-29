"""
Data merging functions for combining funding rate data from multiple exchanges.
"""

from typing import List, Dict, Set


def merge_funding_data(hyperliquid_data: List[List], drift_data: List[List]) -> List[List]:
    """
    Merge Hyperliquid and Drift funding data into unified dataset.

    Args:
        hyperliquid_data: List of [token, exchanges] from Hyperliquid
        drift_data: List of [token, exchanges] from Drift

    Returns:
        Merged list with combined exchange data for each token
    """
    # Create dictionaries for easy lookup
    hl_dict = {entry[0]: entry for entry in hyperliquid_data}
    drift_dict = {entry[0]: entry for entry in drift_data}

    merged_data = []

    # Process all tokens from both sources
    all_tokens = set(hl_dict.keys()) | set(drift_dict.keys())

    for token in all_tokens:
        if token in hl_dict and token in drift_dict:
            # Token exists in both sources - merge exchanges
            hl_entry = hl_dict[token]
            drift_entry = drift_dict[token]

            # Combine exchange data
            combined_exchanges = hl_entry[1] + drift_entry[1]
            merged_entry = [token, combined_exchanges]
            merged_data.append(merged_entry)

        elif token in hl_dict:
            # Token only in Hyperliquid
            merged_data.append(hl_dict[token])

        elif token in drift_dict:
            # Token only in Drift
            merged_data.append(drift_dict[token])

    return merged_data


def get_unique_tokens(data_sources: List[List[List]]) -> Set[str]:
    """
    Get unique token names from multiple data sources.

    Args:
        data_sources: List of data sources, each containing [token, exchanges] entries

    Returns:
        Set of unique token names
    """
    all_tokens = set()

    for data_source in data_sources:
        for entry in data_source:
            token_name = entry[0]
            all_tokens.add(token_name)

    return all_tokens


def create_token_lookup(token_data: List[List]) -> Dict[str, List]:
    """
    Create dictionary lookup for token data.

    Args:
        token_data: List of [token, exchanges] entries

    Returns:
        Dictionary mapping token names to their exchange data
    """
    return {entry[0]: entry for entry in token_data}


def combine_exchange_data(exchange_lists: List[List]) -> List:
    """
    Combine multiple exchange data lists into one.

    Args:
        exchange_lists: List of exchange data lists to combine

    Returns:
        Combined list of all exchange entries
    """
    combined = []
    for exchange_list in exchange_lists:
        combined.extend(exchange_list)
    return combined


def merge_multiple_sources(*data_sources: List[List]) -> List[List]:
    """
    Merge funding data from multiple sources (extensible for future exchanges).

    Args:
        *data_sources: Variable number of data sources to merge

    Returns:
        Merged dataset with all exchanges
    """
    if not data_sources:
        return []

    if len(data_sources) == 1:
        return data_sources[0]

    # Create lookups for all sources
    source_lookups = [create_token_lookup(source) for source in data_sources]

    # Get all unique tokens
    all_tokens = get_unique_tokens(list(data_sources))

    merged_data = []

    for token in all_tokens:
        # Collect exchange data from all sources that have this token
        all_exchanges = []

        for lookup in source_lookups:
            if token in lookup:
                all_exchanges.extend(lookup[token][1])

        if all_exchanges:
            merged_data.append([token, all_exchanges])

    return merged_data
