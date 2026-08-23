"""
Thin wrapper around the TwelveData API for fetching candle data.
"""
import os
import requests

API_KEY = os.environ.get("TWELVEDATA_API_KEY")
BASE_URL = "https://api.twelvedata.com/time_series"


def fetch_candles(symbol: str, interval: str = "1h", outputsize: int = 50):
    """
    Fetches recent candles for a symbol.
    Returns a list of dicts, oldest first: {datetime, open, high, low, close}
    Returns None on error (bad symbol, rate limit, network issue, etc.)
    """
    if not API_KEY:
        raise RuntimeError("TWELVEDATA_API_KEY not set.")

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": API_KEY,
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=10)
        data = resp.json()
    except Exception:
        return None

    if "values" not in data:
        return None

    candles = data["values"]
    candles.reverse()  # TwelveData returns newest first; we want oldest first
    parsed = []
    for c in candles:
        parsed.append({
            "datetime": c["datetime"],
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
        })
    return parsed
