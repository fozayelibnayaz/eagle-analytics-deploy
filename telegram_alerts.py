"""
telegram_alerts.py — Eagle 3D Streaming Analytics Hub
=======================================================
Thin wrapper around reporting_engine.send_telegram + helpers for the
Streamlit "Alerts" page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from reporting_engine import send_telegram


def send_alert(title: str, body: str, emoji: str = "🚨") -> bool:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    msg = f"{emoji} *{title}*\n_{ts}_\n\n{body}"
    return send_telegram(msg)


def send_daily_summary(text: str) -> bool:
    return send_alert("Daily Summary", text, emoji="📊")


def send_kpi_report(text: str) -> bool:
    return send_alert("KPI Report", text, emoji="📈")


def send_anomaly_alert(text: str) -> bool:
    return send_alert("Anomaly Detected", text, emoji="⚠️")


def send_pipeline_status(status: str, details: Optional[str] = None) -> bool:
    icon = "✅" if str(status).lower() in ("ok", "success", "healthy") else "❌"
    body = details or "(no details)"
    return send_alert(f"Pipeline {status}", body, emoji=icon)
