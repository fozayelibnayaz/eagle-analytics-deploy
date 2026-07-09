"""
all_alerts.py — Eagle 3D Streaming Analytics Hub
==================================================
Sends every alert to the main Telegram group.
"""

from __future__ import annotations

import time
from datetime import datetime


def _send(name: str, msg: str, idx: int, total: int) -> bool:
    if not msg or not msg.strip():
        print(f"  [{idx}/{total}] {name}: EMPTY — skipped")
        return False
    try:
        from reporting_engine import send_telegram
        ok = send_telegram(msg)
        status = "SENT" if ok else "FAILED"
        print(f"  [{idx}/{total}] {name}: {status} ({len(msg)} chars)")
        return ok
    except Exception as e:
        print(f"  [{idx}/{total}] {name}: ERROR {e}")
        return False


def run_all() -> int:
    print("=" * 60)
    print(f"ALL ALERTS — {datetime.utcnow().isoformat()}")
    print("=" * 60)

    alerts = []

    try:
        from comprehensive_alerts import (
            alert_kpi_detailed, alert_ga4, alert_youtube, alert_linkedin,
            alert_stripe, alert_customer_success, alert_cross_platform,
            alert_ai_insights,
        )
        print("\nBuilding 8 comprehensive sections...")
        alerts.extend([
            ("KPI Detailed",      alert_kpi_detailed()),
            ("GA4 Traffic",       alert_ga4()),
            ("YouTube",           alert_youtube()),
            ("LinkedIn",          alert_linkedin()),
            ("Stripe + Revenue",  alert_stripe()),
            ("Customer Success",  alert_customer_success()),
            ("Cross-Platform",    alert_cross_platform()),
            ("AI Insights",       alert_ai_insights()),
        ])
    except Exception as e:
        print(f"Comprehensive alerts import error: {e}")

    total = len(alerts)
    print(f"\nSENDING {total} ALERTS\n")

    sent = 0
    for idx, (name, msg) in enumerate(alerts, start=1):
        if _send(name, msg, idx, total):
            sent += 1
        time.sleep(3)  # Telegram rate limit safety

    print(f"\n{'=' * 60}")
    print(f"DONE: {sent}/{total} sent")
    print("=" * 60)
    return sent


if __name__ == "__main__":
    run_all()
