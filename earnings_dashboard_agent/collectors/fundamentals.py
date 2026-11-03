"""Optional Finnhub EPS consensus adapter."""

import os

import requests

from collectors.common import DataSourceError, rate_limit


def fetch_eps_consensus(symbol: str, exchange: str) -> list[dict[str, object]]:
    """Fetch available reported/estimated EPS records; never infer other metrics."""
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise DataSourceError("FINNHUB_API_KEY is not configured")
    symbol_format = os.getenv("FINNHUB_SYMBOL_FORMAT", "{symbol}")
    provider_symbol = symbol_format.format(symbol=symbol, exchange=exchange)
    rate_limit(float(os.getenv("DATA_MIN_REQUEST_INTERVAL", "1.2")))
    try:
        response = requests.get(
            "https://finnhub.io/api/v1/stock/earnings",
            params={"symbol": provider_symbol, "token": api_key},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise DataSourceError(f"Finnhub EPS consensus request failed for {provider_symbol}: {error}") from error
    if not isinstance(payload, list):
        raise DataSourceError("Finnhub EPS consensus response had an unexpected format")
    return payload