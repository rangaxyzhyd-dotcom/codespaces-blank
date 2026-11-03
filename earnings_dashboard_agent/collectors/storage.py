"""SQLite cache, raw-pull audit log, and current stock snapshots."""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from collectors.common import utc_now

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def database_path() -> Path:
    return Path(os.getenv("DATA_DB_PATH", PROJECT_ROOT / "data" / "earnings.db"))


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_storage() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_pulls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                pulled_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS raw_pulls_symbol_time ON raw_pulls(symbol, pulled_at);
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                expires_at REAL NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stock_snapshots (
                symbol TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seen_announcements (
                event_key TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )


def _encode(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def store_raw_pull(symbol: str, source: str, payload: Any) -> str:
    pulled_at = utc_now()
    with connect() as connection:
        connection.execute(
            "INSERT INTO raw_pulls(symbol, source, pulled_at, payload) VALUES (?, ?, ?, ?)",
            (symbol, source, pulled_at, _encode(payload)),
        )
    return pulled_at


def get_cached(cache_key: str) -> dict[str, Any] | None:
    initialize_storage()
    with connect() as connection:
        row = connection.execute(
            "SELECT source, fetched_at, expires_at, payload FROM cache_entries WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if row is None or row["expires_at"] < time.time():
        return None
    return {"source": row["source"], "observed_at": row["fetched_at"], "payload": json.loads(row["payload"])}


def put_cached(cache_key: str, symbol: str, source: str, payload: Any, ttl_seconds: int) -> dict[str, Any]:
    fetched_at = store_raw_pull(symbol, source, payload)
    with connect() as connection:
        connection.execute(
            """INSERT INTO cache_entries(cache_key, source, fetched_at, expires_at, payload)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET
               source=excluded.source, fetched_at=excluded.fetched_at,
               expires_at=excluded.expires_at, payload=excluded.payload""",
            (cache_key, source, fetched_at, time.time() + ttl_seconds, _encode(payload)),
        )
    return {"source": source, "observed_at": fetched_at, "payload": payload}


def fetch_cached(
    cache_key: str,
    symbol: str,
    source: str,
    ttl_seconds: int,
    fetcher: Callable[[], Any],
) -> dict[str, Any]:
    cached = get_cached(cache_key)
    if cached:
        return cached
    try:
        payload = fetcher()
    except Exception as error:
        store_raw_pull(symbol, source, {"error": str(error), "type": type(error).__name__})
        raise
    return put_cached(cache_key, symbol, source, payload, ttl_seconds)


def save_snapshot(symbol: str, payload: dict[str, Any]) -> str:
    fetched_at = utc_now()
    with connect() as connection:
        connection.execute(
            """INSERT INTO stock_snapshots(symbol, fetched_at, payload) VALUES (?, ?, ?)
               ON CONFLICT(symbol) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload""",
            (symbol, fetched_at, _encode(payload)),
        )
    return fetched_at


def load_snapshots() -> dict[str, dict[str, Any]]:
    initialize_storage()
    with connect() as connection:
        rows = connection.execute("SELECT symbol, fetched_at, payload FROM stock_snapshots").fetchall()
    return {row["symbol"]: {**json.loads(row["payload"]), "snapshot_at": row["fetched_at"]} for row in rows}


def unseen_announcement(symbol: str, announcement: dict[str, Any]) -> bool:
    event_key = f"{symbol}:{announcement.get('id') or announcement.get('link') or announcement.get('title')}"
    with connect() as connection:
        existing = connection.execute("SELECT 1 FROM seen_announcements WHERE event_key = ?", (event_key,)).fetchone()
        if existing:
            return False
        connection.execute(
            "INSERT INTO seen_announcements(event_key, symbol, first_seen, payload) VALUES (?, ?, ?, ?)",
            (event_key, symbol, utc_now(), _encode(announcement)),
        )
    return True