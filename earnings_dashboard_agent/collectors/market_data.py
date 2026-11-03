"""Watchlist parsing and Yahoo Finance market-price collection."""

import csv
import os
from pathlib import Path

import pandas as pd

from collectors.common import DataSourceError, rate_limit

REQUIRED_WATCHLIST_COLUMNS = {"symbol", "company", "exchange", "priority"}


def load_watchlist(path: str | Path) -> list[dict[str, str]]:
    """Read and validate the exchange-aware watchlist."""
    with Path(path).open(newline="", encoding="utf-8") as watchlist_file:
        reader = csv.DictReader(watchlist_file)
        if not REQUIRED_WATCHLIST_COLUMNS.issubset(reader.fieldnames or []):
            missing = ", ".join(sorted(REQUIRED_WATCHLIST_COLUMNS - set(reader.fieldnames or [])))
            raise ValueError(f"Watchlist is missing required columns: {missing}")
        rows = []
        for line_number, row in enumerate(reader, start=2):
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            exchange = (row.get("exchange") or "").strip().upper()
            priority = (row.get("priority") or "").strip().upper()
            if exchange not in {"NSE", "BSE"}:
                raise ValueError(f"Invalid exchange {exchange!r} on CSV line {line_number}")
            if priority not in {"A", "B"}:
                raise ValueError(f"Invalid priority {priority!r} on CSV line {line_number}")
            rows.append({
                "symbol": symbol,
                "company": (row.get("company") or "").strip(),
                "exchange": exchange,
                "priority": priority,
            })
    return sorted(rows, key=lambda item: (item["priority"] != "A", item["symbol"]))


def yahoo_symbol(symbol: str, exchange: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized or normalized.startswith("REPLACE_"):
        raise ValueError("A real, non-placeholder symbol is required")
    suffix = ".NS" if exchange.strip().upper() == "NSE" else ".BO"
    return normalized if normalized.endswith((".NS", ".BO")) else f"{normalized}{suffix}"


def fetch_history(symbol: str, exchange: str = "NSE", period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV history via yfinance; provider failures are explicit."""
    ticker_symbol = yahoo_symbol(symbol, exchange)
    try:
        import yfinance as yf

        rate_limit(float(os.getenv("DATA_MIN_REQUEST_INTERVAL", "1.2")))
        history = yf.Ticker(ticker_symbol).history(period=period, interval=interval, auto_adjust=False)
    except Exception as error:
        raise DataSourceError(f"Yahoo Finance request failed for {ticker_symbol}: {error}") from error
    if history.empty:
        raise DataSourceError(f"Yahoo Finance returned no OHLCV data for {ticker_symbol}")
    return history


def fetch_quarterly_financials(symbol: str, exchange: str = "NSE") -> pd.DataFrame:
    """Fetch reported quarterly statements; missing line items are not inferred."""
    ticker_symbol = yahoo_symbol(symbol, exchange)
    try:
        import yfinance as yf

        rate_limit(float(os.getenv("DATA_MIN_REQUEST_INTERVAL", "1.2")))
        result = yf.Ticker(ticker_symbol).quarterly_income_stmt
    except Exception as error:
        raise DataSourceError(f"Yahoo Finance financial statements failed for {ticker_symbol}: {error}") from error
    if result is None or result.empty:
        raise DataSourceError(f"Yahoo Finance returned no quarterly statements for {ticker_symbol}")
    return result