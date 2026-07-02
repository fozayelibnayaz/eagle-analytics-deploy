#!/usr/bin/env python3
"""
ALL ALERTS - sends every alert in the system to ONE main group.
Combines:
- 8 comprehensive sections (KPI/GA4/YouTube/LinkedIn/Stripe/CS/CrossPlatform/AI)
- 4 scheduled reports (Daily Standup/Marketer Weekly/CS Lead Weekly/Founder Monthly)
= 12 total alerts to ONE Telegram group
"""
import os
import time
from datetime import datetime, date


def _send(msg, idx, total):
    """Send to Telegram with retry."""
    if not msg or not msg.strip():
        print(f"  [{idx}/{total}] EMPTY - skipped")
        return False
    try:
        from reporting_engine import send_telegram
        ok = send_telegram(msg)
        status = "SENT" if ok else "FAILED"
        print(f"  [{idx}/{total}] {status} ({len(msg)} chars)")
        return ok
    except Exception as e:
        print(f"  [{idx}/{total}] ERROR: {e}")
        return False


def run_all():
    print("=" * 60)
    print(f"SENDING ALL ALERTS TO MAIN GROUP — {datetime.utcnow().isoformat()}")
    print("=" * 60)

    alerts = []

    # ── 8 COMPREHENSIVE SECTIONS ──
    try:
        from comprehensive_alerts import (
            alert_kpi_detailed, alert_ga4, alert_youtube, alert_linkedin,
            alert_stripe, alert_customer_success, alert_cross_platform, alert_ai_insights
        )
        print("\nBuilding 8 comprehensive sections...")
        alerts.append(("KPI Detailed",      alert_kpi_detailed()))
        alerts.append(("GA4 Detailed",      alert_ga4()))
        alerts.append(("YouTube Detailed",  alert_youtube()))
        alerts.append(("LinkedIn Detailed", alert_linkedin()))
        alerts.append(("Stripe + Revenue",  alert_stripe()))
        alerts.append(("Customer Success",  alert_customer_success()))
        alerts.append(("Cross-Platform",    alert_cross_platform()))
        alerts.append(("AI Insights",       alert_ai_insights()))
    except Exception as e:
        print(f"Comprehensive alerts error: {e}")

    # ── 4 SCHEDULED REPORTS (optional - skip if module missing) ──
    try:
        from role_alerts import daily_standup, marketer_weekly, cs_lead_weekly, founder_monthly
        print("\nBuilding 4 scheduled reports...")
        try:
            alerts.append(("Daily Standup",     daily_standup()))
        except Exception as e:
            print(f"  Daily Standup error: {e}")
        try:
            alerts.append(("Marketer Weekly",   marketer_weekly()))
        except Exception as e:
            print(f"  Marketer Weekly error: {e}")
        try:
            alerts.append(("CS Lead Weekly",    cs_lead_weekly()))
        except Exception as e:
            print(f"  CS Lead Weekly error: {e}")
        try:
            alerts.append(("Founder Monthly",   founder_monthly()))
        except Exception as e:
            print(f"  Founder Monthly error: {e}")
    except ImportError as e:
        print(f"role_alerts not available - skipping scheduled reports: {e}")
    except Exception as e:
        print(f"Scheduled reports error: {e}")

    total = len(alerts)
    print(f"\n{'=' * 60}")
    print(f"SENDING {total} ALERTS")
    print(f"{'=' * 60}\n")

    sent = 0
    for idx, (name, msg) in enumerate(alerts, start=1):
        print(f"[{idx}/{total}] {name}...")
        if _send(msg, idx, total):
            sent += 1
        time.sleep(3)  # rate limit safety

    print(f"\n{'=' * 60}")
    print(f"COMPLETE: {sent}/{total} sent")
    print(f"{'=' * 60}")
    return sent


if __name__ == "__main__":
    run_all()
