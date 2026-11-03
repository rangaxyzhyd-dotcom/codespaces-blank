"""Send optional SMTP result alerts and daily research digests."""

import os
import smtplib
from email.message import EmailMessage
from typing import Any


def send_email(subject: str, body: str) -> None:
    required = ("SMTP_HOST", "SMTP_FROM", "ALERT_EMAIL")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Email settings missing: {', '.join(missing)}")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = os.environ["ALERT_EMAIL"]
    message.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20) as server:
        server.starttls()
        username, password = os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD")
        if username and password:
            server.login(username, password)
        server.send_message(message)


def _recommendation(report: dict[str, Any]) -> str:
    view = report.get("investment_view", {})
    return str(view.get("value", "N/A") if isinstance(view, dict) else view)


def send_result_alert(report: dict[str, Any], announcement: dict[str, Any]) -> None:
    scenario = report.get("reaction_scenario", {})
    symbol = report.get("symbol", "N/A")
    body = "\n".join([
        f"{report.get('company', symbol)} ({symbol}) results release detected.",
        f"Announcement: {announcement.get('title', 'N/A')}",
        f"Published: {announcement.get('published', 'N/A')}",
        f"Screening scenario: {scenario.get('label', 'N/A')} - {scenario.get('view', 'N/A')}",
        f"Model commentary: {scenario.get('commentary', 'N/A')}",
        f"Investment view: {_recommendation(report)}",
        "",
        "Screening thresholds are not return predictions. This is not financial advice.",
    ])
    send_email(f"Results release: {symbol} | {scenario.get('label', 'N/A')}", body)


def send_daily_digest(reports: list[dict[str, Any]]) -> None:
    lines = ["EarningsDashboardAgent daily digest", ""]
    for report in reports:
        scenario = report.get("reaction_scenario", {})
        lines.append(
            f"{report.get('exchange')}:{report.get('symbol')} ({report.get('company')}) | "
            f"Priority {report.get('priority')} | {scenario.get('label', 'N/A')} | "
            f"View: {_recommendation(report)}"
        )
    lines.extend(["", "Screening thresholds are not return predictions. This is not financial advice."])
    send_email("EarningsDashboardAgent daily digest", "\n".join(lines))