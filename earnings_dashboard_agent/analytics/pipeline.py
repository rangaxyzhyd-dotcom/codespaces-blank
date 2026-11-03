"""Build source-attributed stock research snapshots from optional providers."""

import math
import os
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from analytics.indicators import average_directional_index, relative_strength_index, relative_volume, session_vwap
from analytics.scenarios import classify_scenario
from collectors.announcements import fetch_announcements
from collectors.common import DataSourceError, utc_now
from collectors.fundamentals import fetch_eps_consensus
from collectors.market_data import fetch_history, fetch_quarterly_financials, yahoo_symbol
from collectors.storage import fetch_cached, save_snapshot
from llm.client import generate_views

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECTOR_WATCH = {
    "SBIN": "Banking growth and margins",
    "LUPIN": "US business and margins",
    "SOLARINDS": "Defence orders and profitability",
    "BAJAJFINSV": "Lending and insurance performance",
    "MCX": "Transaction volumes and earnings growth",
    "LLOYDSME": "Production and commodity realizations",
    "LINDEINDIA": "Industrial gas demand",
    "EMCURE": "Pharmaceutical growth",
}
NII_NOTE = "11-13% growth range only when provider consensus is available; otherwise N/A"


def _na(source: str) -> dict[str, Any]:
    return {"value": "N/A", "source": source, "observed_at": None}


def _value(value: Any, source: str, observed_at: str | None) -> dict[str, Any]:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return _na(source)
    return {"value": value, "source": source, "observed_at": observed_at}


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    output = frame.copy()
    output.index = output.index.map(str)
    output = output.reset_index(names="date")
    output = output.astype(object).where(pd.notna(output), None)
    return output.to_dict(orient="records")


def _statement_payload(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        str(row): {str(column): (None if pd.isna(value) else float(value)) for column, value in frame.loc[row].items()}
        for row in frame.index
    }


def _frame_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
        frame = frame.set_index("date").sort_index()
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _latest_statement_metric(statement: dict[str, Any] | None, names: tuple[str, ...], source: str, observed_at: str | None):
    if not statement:
        return _na(source)
    for name in names:
        for row_name, periods in statement.items():
            if name.casefold() == row_name.casefold() and isinstance(periods, dict):
                available = [(period, value) for period, value in periods.items() if value is not None]
                if available:
                    period, value = sorted(available, key=lambda pair: pair[0], reverse=True)[0]
                    return _value({"amount": value, "period": period}, source, observed_at)
    return _na(source)


def _result_announcement(announcements: list[dict[str, Any]]) -> dict[str, Any] | None:
    terms = ("financial result", "quarterly result", "unaudited result", "audited result", "results for")
    matches = [item for item in announcements if any(term in str(item.get("title", "")).casefold() for term in terms)]
    return sorted(matches, key=lambda item: str(item.get("published", "")), reverse=True)[0] if matches else None


def _post_result_prices(daily: pd.DataFrame, announcement: dict[str, Any] | None, source: str, observed_at: str | None):
    na_pair = {"one_day": _na(source), "five_day": _na(source)}
    if daily.empty or not announcement:
        return na_pair
    event_time = pd.to_datetime(announcement.get("published"), errors="coerce", utc=True)
    if pd.isna(event_time) or "Close" not in daily:
        return na_pair
    closes = daily["Close"].dropna().sort_index()
    prior = closes[closes.index < event_time]
    following = closes[closes.index >= event_time]
    if prior.empty or len(following) < 1:
        return na_pair
    prior_close = float(prior.iloc[-1])
    returns = {}
    for label, offset in (("one_day", 0), ("five_day", 4)):
        if len(following) > offset:
            returns[label] = _value(round((float(following.iloc[offset]) / prior_close - 1) * 100, 2), source, observed_at)
        else:
            returns[label] = _na(source)
    return returns


def _raw_source(cache_key: str, symbol: str, source: str, ttl: int, loader):
    return fetch_cached(cache_key, symbol, source, ttl, loader)


def build_stock_report(stock: dict[str, str], persist: bool = True) -> dict[str, Any]:
    symbol = stock["symbol"].upper()
    exchange = stock["exchange"].upper()
    if symbol.startswith("REPLACE_"):
        return _placeholder_report(stock)

    errors: list[str] = []
    prices = statements = announcements = eps_records = None
    price_source = f"Yahoo Finance OHLCV ({yahoo_symbol(symbol, exchange)})"
    statement_source = f"Yahoo Finance quarterly income statement ({yahoo_symbol(symbol, exchange)})"
    announcement_source = f"{exchange} corporate announcements and Yahoo Finance RSS"
    eps_source = "Finnhub earnings API; EPS only"

    try:
        result = _raw_source(
            f"prices:{exchange}:{symbol}:1d", symbol, price_source, 900,
            lambda: _frame_records(fetch_history(symbol, exchange, "6mo", "1d")),
        )
        prices = _frame_from_records(result["payload"])
        price_at = result["observed_at"]
    except Exception as error:
        errors.append(str(error))
        price_at = None
    try:
        result = _raw_source(
            f"prices:{exchange}:{symbol}:5m", symbol, price_source + " intraday", 900,
            lambda: _frame_records(fetch_history(symbol, exchange, "1d", "5m")),
        )
        intraday = _frame_from_records(result["payload"])
        intraday_at = result["observed_at"]
    except Exception as error:
        intraday = pd.DataFrame()
        intraday_at = None
        errors.append(str(error))
    try:
        result = _raw_source(
            f"financials:{exchange}:{symbol}", symbol, statement_source, 86400,
            lambda: _statement_payload(fetch_quarterly_financials(symbol, exchange)),
        )
        statements = result["payload"]
        statement_at = result["observed_at"]
    except Exception as error:
        statement_at = None
        errors.append(str(error))
    try:
        result = _raw_source(
            f"announcements:{exchange}:{symbol}", symbol, announcement_source, 900,
            lambda: fetch_announcements(symbol, exchange),
        )
        announcements = result["payload"]
        announcement_at = result["observed_at"]
    except Exception as error:
        announcement_at = None
        errors.append(str(error))
    try:
        result = _raw_source(
            f"finnhub_eps:{exchange}:{symbol}", symbol, eps_source, 21600,
            lambda: fetch_eps_consensus(symbol, exchange),
        )
        eps_records = result["payload"]
        eps_at = result["observed_at"]
    except Exception as error:
        eps_at = None
        errors.append(str(error))

    latest = _result_announcement(announcements or [])
    actuals = {
        "revenue": _latest_statement_metric(statements, ("Total Revenue", "Operating Revenue"), statement_source, statement_at),
        "ebitda": _latest_statement_metric(statements, ("EBITDA",), statement_source, statement_at),
        "pat": _latest_statement_metric(statements, ("Net Income", "Net Income Common Stockholders"), statement_source, statement_at),
    }
    eps_record = max(
        eps_records or [],
        key=lambda item: (int(item.get("year") or 0), int(item.get("quarter") or 0), str(item.get("period") or "")),
        default={},
    )
    actuals["eps"] = _value(eps_record.get("actual"), eps_source, eps_at)
    previous_quarter = {key: actuals[key] for key in ("revenue", "ebitda", "pat")}
    consensus_eps = eps_record.get("estimate")
    consensus = {
        "revenue": _na("N/A: no configured provider returns revenue consensus"),
        "ebitda": _na("N/A: no configured provider returns EBITDA consensus"),
        "pat": _na("N/A: no configured provider returns PAT consensus"),
        "eps": _value(consensus_eps, eps_source, eps_at) if consensus_eps is not None else _na(eps_source),
    }

    technical = {key: _na(price_source) for key in ("relative_volume", "rsi_14", "adx_14", "session_vwap")}
    pre_results_close = _na(price_source + "; requires verified results date")
    post_returns = {"one_day": _na(price_source), "five_day": _na(price_source)}
    if prices is not None and not prices.empty:
        if "Volume" in prices:
            relative = relative_volume(prices["Volume"].dropna())
            technical["relative_volume"] = _value(round(relative, 3) if relative is not None else None, price_source, price_at)
        if "Close" in prices:
            rsi = relative_strength_index(prices["Close"])
            technical["rsi_14"] = _value(round(float(rsi.iloc[-1]), 2) if pd.notna(rsi.iloc[-1]) else None, price_source, price_at)
        try:
            adx = average_directional_index(prices)
            technical["adx_14"] = _value(round(float(adx.iloc[-1]), 2) if pd.notna(adx.iloc[-1]) else None, price_source, price_at)
        except ValueError:
            pass
        if "Close" in prices and not prices["Close"].dropna().empty:
            close = float(prices["Close"].dropna().iloc[-1])
            technical["latest_close"] = _value(close, price_source, price_at)
        vwap = session_vwap(intraday)
        technical["session_vwap"] = _value(round(vwap, 2) if vwap is not None else None, price_source + " 5-minute bars", intraday_at)
        if latest:
            post_returns = _post_result_prices(prices, latest, price_source, price_at)
            event_date = pd.to_datetime(latest.get("published"), errors="coerce", utc=True)
            before_event = prices.loc[prices.index < event_date] if not pd.isna(event_date) else pd.DataFrame()
            if not before_event.empty and "Close" in before_event:
                pre_results_close = _value(float(before_event["Close"].dropna().iloc[-1]), price_source, price_at)

    metrics = {key: _surprise(actuals[key], consensus[key]) for key in actuals}
    pat_pct = metrics["pat"].get("value") if isinstance(metrics["pat"].get("value"), (int, float)) else None
    ebitda_pct = metrics["ebitda"].get("value") if isinstance(metrics["ebitda"].get("value"), (int, float)) else None
    classification = classify_scenario(pat_pct, ebitda_pct, None, None)
    report = {
        **stock,
        "announcement_date": _value(latest.get("published"), latest.get("source", announcement_source), announcement_at) if latest else _na(announcement_source),
        "previous_quarter": previous_quarter,
        "consensus": consensus,
        "actual_results": actuals,
        "surprise_pct": metrics,
        "beat_miss_history": _na("N/A: verified four-quarter consensus history unavailable"),
        "guidance": _na("N/A: management guidance has not been extracted from a cited filing"),
        "pre_results_close": pre_results_close,
        "post_results_returns": post_returns,
        "technical": technical,
        "reaction_scenario": classification,
        "investment_view": _na("LLM view pending; configure a provider and API key"),
        "announcements": announcements or [],
        "errors": errors,
        "sector_watch": SECTOR_WATCH.get(symbol, "General earnings, cash flow, and guidance"),
        "bank_metrics": {"net_interest_income": _na("N/A: no verified source configured"), "nii_yoy_growth": _na(NII_NOTE), "nim": _na("N/A: no verified source configured"), "loan_growth": _na("N/A: no verified source configured"), "deposit_growth": _na("N/A: no verified source configured")} if symbol in {"SBIN", "BAJAJFINSV"} else None,
        "sources": {"prices": price_source, "statements": statement_source, "announcements": announcement_source, "consensus": eps_source},
        "updated_at": utc_now(),
    }
    fact_hash = hashlib.sha256(json.dumps({key: report[key] for key in ("actual_results", "consensus", "guidance", "announcements", "reaction_scenario")}, sort_keys=True, default=str).encode()).hexdigest()[:20]
    try:
        generated = _raw_source(
            f"llm:{symbol}:{fact_hash}", symbol, f"LLM generated view ({os.getenv('LLM_PROVIDER', 'groq')})", 86400,
            lambda: generate_views(report),
        )["payload"]
        report["reaction_scenario"]["commentary"] = generated["scenario_commentary"]
        report["investment_view"] = _value(generated["investment_view"], generated["source"], utc_now())
    except Exception as error:
        report["errors"].append(str(error))
    if persist:
        save_snapshot(symbol, report)
    return report


def _surprise(actual: dict[str, Any], consensus: dict[str, Any]) -> dict[str, Any]:
    actual_value = actual.get("value")
    consensus_value = consensus.get("value")
    if not isinstance(actual_value, (int, float)) or not isinstance(consensus_value, (int, float)) or consensus_value == 0:
        return _na("N/A: actual and consensus values are both required")
    return _value(round((actual_value - consensus_value) / abs(consensus_value) * 100, 2), "Computed from cited actual and consensus values", utc_now())


def _placeholder_report(stock: dict[str, str]) -> dict[str, Any]:
    fields = ("revenue", "ebitda", "pat", "eps")
    source = "N/A: replace this placeholder watchlist row"
    return {
        **stock,
        "announcement_date": _na(source),
        "previous_quarter": {key: _na(source) for key in fields[:3]},
        "consensus": {key: _na(source) for key in fields},
        "actual_results": {key: _na(source) for key in fields[:3]},
        "surprise_pct": {key: _na(source) for key in fields[:3]},
        "beat_miss_history": _na(source),
        "guidance": _na(source),
        "pre_results_close": _na(source),
        "post_results_returns": {"one_day": _na(source), "five_day": _na(source)},
        "technical": {key: _na(source) for key in ("relative_volume", "rsi_14", "adx_14", "session_vwap")},
        "reaction_scenario": classify_scenario(None, None, None, None),
        "investment_view": _na(source),
        "announcements": [],
        "errors": [],
        "sector_watch": SECTOR_WATCH.get(stock["symbol"], "General earnings, cash flow, and guidance"),
        "bank_metrics": None,
        "sources": {},
        "updated_at": utc_now(),
    }


def refresh_watchlist(watchlist: list[dict[str, str]]) -> list[dict[str, Any]]:
    reports = []
    for stock in watchlist:
        try:
            reports.append(build_stock_report(stock))
        except Exception as error:
            report = _placeholder_report(stock)
            report["errors"] = [f"Unexpected report failure: {error}"]
            reports.append(report)
    return reports