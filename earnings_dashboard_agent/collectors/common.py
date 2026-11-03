"""Shared source metadata, rate limiting, and error types."""

import threading
import time
from datetime import datetime, timezone


class DataSourceError(RuntimeError):
    """Raised when a configured external data source cannot provide data."""


_rate_lock = threading.Lock()
_last_request_at = 0.0


def rate_limit(min_interval_seconds: float = 1.2) -> None:
    """Apply a process-wide delay between outbound data requests."""
    global _last_request_at
    with _rate_lock:
        now = time.monotonic()
        delay = min_interval_seconds - (now - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        _last_request_at = time.monotonic()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")