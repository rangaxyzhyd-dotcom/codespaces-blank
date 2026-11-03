"""IST market-hours collection, results alerts, and daily digest jobs."""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler

from alerts.email_notifier import send_daily_digest, send_result_alert
from analytics.pipeline import refresh_watchlist
from collectors.storage import unseen_announcement

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
RESULT_TERMS = ("financial result", "quarterly result", "unaudited result", "audited result", "results for")


def _is_market_hours(now: datetime | None = None) -> bool:
    current = now.astimezone(IST) if now else datetime.now(IST)
    return current.weekday() < 5 and (current.hour, current.minute) >= (9, 15) and (current.hour, current.minute) <= (15, 30)


def _is_recent(announcement: dict, now: datetime | None = None) -> bool:
    try:
        published = pd.Timestamp(announcement.get("published"))
        if pd.isna(published):
            return False
        if published.tzinfo is None:
            published = published.tz_localize(IST)
        else:
            published = published.tz_convert(IST)
        current = now or datetime.now(IST)
        current = current.replace(tzinfo=IST) if current.tzinfo is None else current.astimezone(IST)
        days_ago = (current.date() - published.date()).days
        return 0 <= days_ago <= 2
    except (TypeError, ValueError):
        return False


def run_market_cycle(watchlist: list[dict[str, str]]) -> None:
    if not _is_market_hours():
        return
    reports = refresh_watchlist(watchlist)
    for report in reports:
        for announcement in report.get("announcements", []):
            title = str(announcement.get("title", "")).casefold()
            if any(term in title for term in RESULT_TERMS) and _is_recent(announcement):
                try:
                    if unseen_announcement(report["symbol"], announcement):
                        send_result_alert(report, announcement)
                except Exception:
                    logger.exception("Result alert failed for %s", report.get("symbol"))


def run_daily_digest(watchlist: list[dict[str, str]]) -> None:
    reports = refresh_watchlist(watchlist)
    try:
        send_daily_digest(reports)
    except Exception:
        logger.exception("Daily email digest failed")


def start_scheduler(watchlist: list[dict[str, str]]) -> BackgroundScheduler:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    scheduler = BackgroundScheduler(timezone=IST, job_defaults={"coalesce": True, "max_instances": 1})
    poll_minutes = max(1, int(os.getenv("MARKET_POLL_MINUTES", "5")))
    scheduler.add_job(run_market_cycle, "cron", args=[watchlist], day_of_week="mon-fri", hour="9-15", minute=f"*/{poll_minutes}", id="market-cycle")
    scheduler.add_job(
        run_daily_digest, "cron", args=[watchlist], day_of_week="mon-fri",
        hour=int(os.getenv("DIGEST_HOUR_IST", "16")), minute=int(os.getenv("DIGEST_MINUTE_IST", "0")), id="daily-digest",
    )
    scheduler.start()
    logger.info("Market polling and digest scheduled in Asia/Kolkata")
    return scheduler