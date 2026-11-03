"""FastAPI application for the earnings intelligence dashboard."""

import logging
import os
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from dotenv import load_dotenv

from analytics.pipeline import _placeholder_report
from collectors.market_data import load_watchlist
from collectors.storage import initialize_storage, load_snapshots

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)

TABLE_COLUMNS = [
    "Symbol and company", "Earnings announcement date", "Previous-quarter revenue / EBITDA / PAT",
    "Consensus revenue / EBITDA / PAT / EPS", "Actual results", "Surprise percentage (actual vs consensus)",
    "Previous four-quarter beat/miss history", "Management guidance", "Pre-results closing price",
    "Post-results 1-day / 5-day return", "Relative volume / RSI / ADX / session VWAP",
    "Bullish/bearish reaction scenario", "Final investment view",
]


def _watchlist() -> list[dict[str, str]]:
    return load_watchlist(Path(os.getenv("WATCHLIST_PATH", PROJECT_ROOT / "config" / "watchlist.csv")))


def _report_map() -> dict[str, dict[str, Any]]:
    return load_snapshots()


def _all_reports() -> list[dict[str, Any]]:
    snapshots = _report_map()
    reports = [snapshots.get(stock["symbol"], _placeholder_report(stock)) for stock in _watchlist()]
    return sorted(reports, key=lambda report: (report.get("priority") != "A", report.get("symbol", "")))


def _cell(value: Any) -> str:
    if isinstance(value, dict):
        if "value" in value:
            data = value["value"]
            rendered = " / ".join(str(part) for part in data.values()) if isinstance(data, dict) else str(data)
            return f"{rendered} [{value.get('source', 'source unavailable')}]"
        return "; ".join(f"{key}: {_cell(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "; ".join(_cell(item) for item in value) if value else "N/A"
    return "N/A" if value is None or value == "" else str(value)


def _export_row(report: dict[str, Any]) -> list[str]:
    previous, consensus = report.get("previous_quarter", {}), report.get("consensus", {})
    actual, surprises = report.get("actual_results", {}), report.get("surprise_pct", {})
    returns, technical = report.get("post_results_returns", {}), report.get("technical", {})
    scenario = report.get("reaction_scenario", {})

    def metrics(values, keys):
        return " | ".join(f"{key.upper()}: {_cell(values.get(key))}" for key in keys)

    return [
        f"{report.get('exchange', 'N/A')}:{report.get('symbol', 'N/A')} · {report.get('company', 'N/A')}",
        _cell(report.get("announcement_date")), metrics(previous, ("revenue", "ebitda", "pat")),
        metrics(consensus, ("revenue", "ebitda", "pat", "eps")), metrics(actual, ("revenue", "ebitda", "pat", "eps")),
        metrics(surprises, ("revenue", "ebitda", "pat", "eps")), _cell(report.get("beat_miss_history")),
        _cell(report.get("guidance")), _cell(report.get("pre_results_close")),
        f"1d: {_cell(returns.get('one_day'))} | 5d: {_cell(returns.get('five_day'))}",
        " | ".join(f"{key}: {_cell(technical.get(key))}" for key in ("relative_volume", "rsi_14", "adx_14", "session_vwap")),
        f"{scenario.get('label', 'N/A')}: {scenario.get('view', 'N/A')} ({scenario.get('basis', '')})",
        _cell(report.get("investment_view")),
    ]


@asynccontextmanager
async def lifespan(application: FastAPI):
    initialize_storage()
    if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
        try:
            from scheduler.runner import start_scheduler

            application.state.scheduler = start_scheduler(application.state.watchlist)
        except Exception:
            logger.exception("Scheduler did not start; dashboard remains available")
    yield
    scheduler = getattr(application.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    application = FastAPI(title="EarningsDashboardAgent", version="1.0.0", lifespan=lifespan)
    application.state.watchlist = _watchlist()
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(TEMPLATE_DIR / "index.html")

    @application.get("/stocks/{symbol}", include_in_schema=False)
    async def stock_brief(symbol: str):
        if symbol.upper() not in {stock["symbol"] for stock in application.state.watchlist}:
            raise HTTPException(status_code=404, detail="Symbol is not in the configured watchlist")
        return FileResponse(TEMPLATE_DIR / "brief.html")

    @application.get("/api/health")
    async def health():
        return {"status": "ok", "watchlist_count": len(application.state.watchlist)}

    @application.get("/api/stocks")
    async def stocks(priority: str | None = Query(default=None, pattern="^[AB]$"), search: str | None = None):
        reports = _all_reports()
        if priority:
            reports = [report for report in reports if report.get("priority") == priority]
        if search:
            query = search.casefold()
            reports = [report for report in reports if query in report.get("symbol", "").casefold() or query in report.get("company", "").casefold()]
        return {"stocks": reports, "count": len(reports), "columns": TABLE_COLUMNS}

    @application.get("/api/stocks/{symbol}")
    async def stock_detail(symbol: str):
        normalized = symbol.upper()
        if normalized not in {stock["symbol"] for stock in application.state.watchlist}:
            raise HTTPException(status_code=404, detail="Symbol is not in the configured watchlist")
        stock = next(item for item in application.state.watchlist if item["symbol"] == normalized)
        return _report_map().get(normalized) or _placeholder_report(stock)

    @application.post("/api/refresh", status_code=202)
    async def refresh(background_tasks: BackgroundTasks):
        from analytics.pipeline import refresh_watchlist

        background_tasks.add_task(refresh_watchlist, application.state.watchlist)
        return {"status": "refresh_started", "count": len(application.state.watchlist)}

    @application.get("/api/export.xlsx", include_in_schema=False)
    async def export_xlsx():
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Earnings dashboard"
        sheet.append(TABLE_COLUMNS)
        for report in _all_reports():
            sheet.append(_export_row(report))
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return StreamingResponse(
            stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=earnings_dashboard.xlsx"},
        )

    return application


app = create_app()