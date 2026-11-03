"""Rate-limited public corporate-announcement adapters."""

import os
from datetime import date, timedelta
from xml.etree import ElementTree

import requests

from collectors.common import DataSourceError, rate_limit

_SESSION = requests.Session()
_HEADERS = {
    "User-Agent": "EarningsDashboardAgent/1.0 (research dashboard; contact: configure CONTACT_EMAIL)",
    "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*",
}


def _nse_announcements(symbol: str) -> list[dict[str, str]]:
    landing = _SESSION.get("https://www.nseindia.com/", headers=_HEADERS, timeout=15)
    landing.raise_for_status()
    rate_limit(float(os.getenv("DATA_MIN_REQUEST_INTERVAL", "1.2")))
    response = _SESSION.get(
        "https://www.nseindia.com/api/corporate-announcements",
        params={"index": "equities", "symbol": symbol},
        headers={**_HEADERS, "Referer": "https://www.nseindia.com/market-data/corporate-actions"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise DataSourceError("NSE announcement response had an unexpected format")
    return [{
        "id": str(item.get("seq_id") or item.get("attchmntFile") or item.get("desc", "")),
        "title": str(item.get("desc") or item.get("subject") or ""),
        "published": str(item.get("an_dt") or item.get("exchdisstime") or ""),
        "link": str(item.get("attchmntFile") or ""),
        "source": "NSE corporate announcements",
    } for item in payload]


def _bse_announcements(symbol: str) -> list[dict[str, str]]:
    today = date.today()
    params = {
        "strCat": "-1",
        "strPrevDate": (today - timedelta(days=30)).strftime("%Y%m%d"),
        "strScrip": symbol,
        "strSearch": "P",
        "strToDate": today.strftime("%Y%m%d"),
    }
    rate_limit(float(os.getenv("DATA_MIN_REQUEST_INTERVAL", "1.2")))
    response = _SESSION.get(
        "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w",
        params=params,
        headers={**_HEADERS, "Referer": "https://www.bseindia.com/"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        payload = payload.get("Table", [])
    if not isinstance(payload, list):
        raise DataSourceError("BSE announcement response had an unexpected format")
    return [{
        "id": str(item.get("NEWSID") or item.get("SCRIP_CD") or item.get("DT_TM", "")),
        "title": str(item.get("HEADLINE") or item.get("NEWSSUB") or item.get("SUBCATNAME") or ""),
        "published": str(item.get("DT_TM") or item.get("NEWS_DT") or ""),
        "link": str(item.get("ATTACHMENTNAME") or item.get("NSURL") or ""),
        "source": "BSE corporate announcements",
    } for item in payload]


def _rss_headlines(symbol: str, limit: int) -> list[dict[str, str]]:
    response = _SESSION.get(
        "https://feeds.finance.yahoo.com/rss/2.0/headline",
        params={"s": f"{symbol}.NS", "region": "IN", "lang": "en-IN"},
        headers=_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    return [{
        "id": item.findtext("guid", default="").strip(),
        "title": item.findtext("title", default="").strip(),
        "published": item.findtext("pubDate", default="").strip(),
        "link": item.findtext("link", default="").strip(),
        "source": "Yahoo Finance RSS",
    } for item in root.findall(".//item")[:limit]]


def fetch_announcements(symbol: str, exchange: str = "NSE", limit: int = 10) -> list[dict[str, str]]:
    """Fetch public exchange announcements and headlines; never hides provider errors."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol or normalized_symbol.startswith("REPLACE_"):
        raise ValueError("A real, non-placeholder symbol is required")
    if limit < 1:
        return []
    items = []
    errors = []
    exchange_fetcher = _nse_announcements if exchange.upper() == "NSE" else _bse_announcements
    source_fetchers = (lambda: exchange_fetcher(normalized_symbol), lambda: _rss_headlines(normalized_symbol, limit))
    for source_index, source_fetcher in enumerate(source_fetchers):
        try:
            if source_index > 0:
                rate_limit(float(os.getenv("DATA_MIN_REQUEST_INTERVAL", "1.2")))
            items.extend(source_fetcher())
        except (requests.RequestException, ValueError, ElementTree.ParseError, DataSourceError) as error:
            errors.append(str(error))
    if not items and errors:
        raise DataSourceError(f"Announcement sources failed for {normalized_symbol}: {'; '.join(errors)}")
    unique = {item.get("id") or item.get("link") or item.get("title"): item for item in items}
    return list(unique.values())[:limit]