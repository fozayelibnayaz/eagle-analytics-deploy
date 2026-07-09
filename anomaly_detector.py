"""
anomaly_detector.py — Eagle 3D Streaming Analytics Hub
========================================================
Detects sudden spikes, drops, and flat-lines in daily KPIs.
Sends instant Telegram alerts if anomalies are found.
Reads from MongoDB daily_kpis collection.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from mongo_client import find_all
from reporting_engine import send_telegram


# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────
SPIKE_MULTIPLIER  = 3.0    # today > 3× 7-day average → spike
DROP_MULTIPLIER   = 0.30   # today < 30% of 7-day average → drop
FLATLINE_DAYS     = 5      # N consecutive days of exactly 0 → flatline
LOOKBACK_DAYS     = 14
METRICS_TO_CHECK  = [
    ("signups",  "Signups"),
    ("uploads",  "Uploads"),
    ("payments", "Payments"),
]


# ─────────────────────────────────────────────────────────────────
# CORE
# ─────────────────────────────────────────────────────────────────
def _load_recent_kpis() -> pd.DataFrame:
    rows = find_all("daily_kpis", sort=[("date", 1)])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    cutoff = pd.Timestamp(date.today() - timedelta(days=LOOKBACK_DAYS + 1))
    return df[df["date"] >= cutoff].copy()


def _detect_metric(df: pd.DataFrame, col: str, label: str) -> List[Dict[str, Any]]:
    """Run anomaly checks for one metric column."""
    if col not in df.columns or df.empty:
        return []

    anomalies: List[Dict[str, Any]] = []
    series = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(float)
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

    if len(series) < 8:
        return []

    today_val = float(series.iloc[-1])
    today_date = dates[-1]
    prev7 = series.iloc[-8:-1]
    avg7 = float(prev7.mean()) if len(prev7) else 0.0

    # Spike
    if avg7 > 0 and today_val > avg7 * SPIKE_MULTIPLIER:
        anomalies.append({
            "metric":  label,
            "type":    "spike",
            "date":    today_date,
            "today":   today_val,
            "avg7":    round(avg7, 2),
            "message": f"🚀 *{label} SPIKE* on {today_date}: {int(today_val)} vs 7-day avg {avg7:.1f} ({today_val/avg7:.1f}× normal)",
        })

    # Drop
    if avg7 > 5 and today_val < avg7 * DROP_MULTIPLIER:
        anomalies.append({
            "metric":  label,
            "type":    "drop",
            "date":    today_date,
            "today":   today_val,
            "avg7":    round(avg7, 2),
            "message": f"📉 *{label} DROP* on {today_date}: {int(today_val)} vs 7-day avg {avg7:.1f} ({(today_val/avg7*100 if avg7 else 0):.0f}% of normal)",
        })

    # Flatline (N consecutive zeros)
    last_n = series.iloc[-FLATLINE_DAYS:]
    if len(last_n) == FLATLINE_DAYS and float(last_n.sum()) == 0.0:
        anomalies.append({
            "metric":  label,
            "type":    "flatline",
            "date":    today_date,
            "today":   0,
            "avg7":    round(avg7, 2),
            "message": f"⚠️ *{label} FLATLINE*: 0 for {FLATLINE_DAYS} consecutive days ending {today_date}",
        })

    return anomalies


def detect_anomalies() -> List[Dict[str, Any]]:
    df = _load_recent_kpis()
    if df.empty:
        return []
    out: List[Dict[str, Any]] = []
    for col, label in METRICS_TO_CHECK:
        out.extend(_detect_metric(df, col, label))
    return out


def detect_and_alert() -> List[Dict[str, Any]]:
    """Detect anomalies and send Telegram alert for each. Returns list of alerts sent."""
    anomalies = detect_anomalies()
    if not anomalies:
        return []

    header = f"🚨 *Eagle 3D Streaming — Anomaly Alerts*\n_{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_\n\n"
    body = "\n\n".join(a["message"] for a in anomalies)
    send_telegram(header + body)

    return anomalies


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Running anomaly detection...")
    results = detect_anomalies()
    if not results:
        print("✅ No anomalies detected")
    else:
        print(f"⚠️  {len(results)} anomalies found:")
        for a in results:
            print(f"  - {a['metric']:10s} {a['type']:10s} date={a['date']} today={a['today']} avg7={a['avg7']}")
