import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Funding Rate Viewer", layout="wide")
st.title("📈 Funding Rate Comparison")
st.write("Compare predicted funding rates across exchanges for various tokens, scaled to your chosen interval.")

# Dropdown to select desired interval
interval_options = {
    "1 hr": 1,
    "4 hr": 4,
    "8 hr": 8,
    "24 hr": 24,
    "1 yr (8760 hrs)": 8760
}
selected_interval = st.selectbox("Select target funding interval:", list(interval_options.keys()))
target_hours = interval_options[selected_interval]

# Function to get data from Hyperliquid API
def fetch_hyperliquid_data():
    url = "https://api-ui.hyperliquid.xyz/info"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Referer": "https://app.hyperliquid.xyz/fundingComparison"
    }
    body = {
        "type": "predictedFundings"
    }

    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()  # ✅ FIXED HERE
    except requests.exceptions.RequestException as e:
        st.error(f"Hyperliquid API call failed: {e}")
        return []

# Function to get data from Drift API
def fetch_drift_data():
    url = "https://mainnet-beta.api.drift.trade/markets24h"

    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Drift API call failed: {e}")
        return []

# Function to process Drift data and convert to compatible format
def process_drift_data(drift_data):
    processed_data = []

    # Handle the API response structure - data is in drift_data["data"]
    data_array = drift_data.get("data", [])

    for item in data_array:
        # Filter for perp markets only - check if "perp" key exists
        market_type = item.get("marketType", {})
        if "perp" not in market_type:
            continue

        symbol = item.get("symbol", "")
        # Filter for symbols ending with -PERP
        if not symbol.endswith("-PERP"):
            continue

        # Extract token name by removing -PERP suffix
        token_name = symbol.replace("-PERP", "")

        # Get avgFunding and convert from percentage to decimal
        avg_funding = item.get("avgFunding", 0)
        funding_rate_decimal = avg_funding / 100  # Convert percentage to decimal

        # Create entry in Hyperliquid-compatible format
        drift_entry = [
            token_name,
            [["DriftPerp", {"fundingRate": str(funding_rate_decimal), "fundingIntervalHours": 1}]]
        ]
        processed_data.append(drift_entry)

    return processed_data

# Function to merge Hyperliquid and Drift data
def merge_funding_data(hyperliquid_data, drift_data):
    # Create a dictionary for easy lookup of Hyperliquid data
    hl_dict = {entry[0]: entry for entry in hyperliquid_data}

    # Create a dictionary for Drift data
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

# Function to scale rate to desired interval and convert to percent
def scale_rate(rate, original_hours, target_hours):
    return rate * (target_hours / original_hours) * 100  # percentage

# Fetch data from both sources
hyperliquid_data = fetch_hyperliquid_data()
drift_data = fetch_drift_data()

# Process and merge data
processed_drift_data = process_drift_data(drift_data)
raw_data = merge_funding_data(hyperliquid_data, processed_drift_data)

# Parse and process
formatted_data = []
for token_entry in raw_data:
    token_name = token_entry[0]
    exchanges = token_entry[1]

    entry = {"Token": token_name, "Hyperliquid": None, "Binance": None, "Bybit": None, "Drift": None}

    for exchange_name, details in exchanges:
        if details is not None:
            try:
                rate = float(details.get("fundingRate", 0))
                interval = details.get("fundingIntervalHours", 1)
                scaled_percent = scale_rate(rate, interval, target_hours)

                if exchange_name == "HlPerp":
                    entry["Hyperliquid"] = scaled_percent
                elif exchange_name == "BinPerp":
                    entry["Binance"] = scaled_percent
                elif exchange_name == "BybitPerp":
                    entry["Bybit"] = scaled_percent
                elif exchange_name == "DriftPerp":
                    entry["Drift"] = scaled_percent
            except (ValueError, TypeError):
                continue

    formatted_data.append(entry)

# Create and display DataFrame
df = pd.DataFrame(formatted_data)
df = df.sort_values(by="Token")

st.subheader(f"Funding Rates (%), scaled to {selected_interval}")
# Convert only numeric columns to float (skip Token column)
for col in ["Hyperliquid", "Binance", "Bybit", "Drift"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

st.dataframe(df.style.format({col: "{:.4f}%" for col in df.columns if col != "Token"}))

# Optional raw JSON view
with st.expander("🔍 Show raw API response"):
    st.write("**Hyperliquid Data:**")
    st.json(hyperliquid_data)
    st.write("**Drift Data:**")
    st.json(drift_data)
