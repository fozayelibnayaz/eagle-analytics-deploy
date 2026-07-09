#!/usr/bin/env python3
"""
TELEGRAM VALIDATOR — Priority 6
Telegram reports must ONLY send validated data.
If validation fails, sends warning instead of wrong numbers.
"""
import json
from pathlib import Path
from datetime import datetime
from validation_engine import validate_all_metrics, validate_kpi_metrics
from common_period_engine import compute_alltime_metrics, get_common_period

DATA_DIR = Path("data_output")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [TelegramValidator] {msg}", flush=True)


def build_validated_kpi_report(kpi: dict, ga4: dict, stripe: dict) -> dict:
    """
    Returns validated report dict.
    result["send"] = True/False
    result["message"] = what to send
    result["validation"] = ValidationResult
    """
    # Run validation
    validation = validate_all_metrics(kpi, ga4, stripe)

    # Get common period metrics (correct All-Time)
    alltime = compute_alltime_metrics(use_common_period=True)
    common_start, common_end = get_common_period()

    today_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")

    # If hard failures — send warning only
    if not validation.is_valid:
        warn_msg = (
            f"⚠️ <b>DATA VALIDATION FAILED — {today_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"❌ KPI report NOT sent — data failed validation checks.\n"
            f"\n"
            f"<b>Failures detected:</b>\n"
        )
        for f in validation.failures:
            warn_msg += f"• {f['rule']}: {f['message']}\n"
        warn_msg += (
            f"\n"
            f"<b>Action required:</b>\n"
            f"• Check data pipeline\n"
            f"• Review source data\n"
            f"• Fix before next report\n"
            f"\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        )
        return {
            "send": True,
            "message": warn_msg,
            "is_warning": True,
            "validation": validation,
            "alltime": alltime,
        }

    # Build validated report
    s_today = kpi.get("signups_today", 0)
    u_today = kpi.get("uploads_today", 0)
    p_today = kpi.get("paid_today", 0)
    s_month = kpi.get("signups_month", 0)
    u_month = kpi.get("uploads_month", 0)
    p_month = kpi.get("paid_month", 0)

    # Use COMMON PERIOD for All-Time (not full DB)
    s_all = alltime.get("signups", kpi.get("signups_all", 0))
    u_all = alltime.get("uploads", kpi.get("uploads_all", 0))
    p_all = alltime.get("paid",    kpi.get("paid_all", 0))
    s2u   = alltime.get("signup_to_upload", 0)
    s2p   = alltime.get("signup_to_paid", 0)

    period_label = alltime.get("period_label", "Common Period")

    # Warning banner if any warnings
    warn_banner = ""
    if validation.has_warnings:
        warn_banner = "\n⚠️ <b>Data Coverage Warning:</b>\n"
        for w in validation.warnings[:3]:
            warn_banner += f"• {w['message'][:80]}\n"

    # Full DB totals (for transparency)
    full_s = alltime.get("full_db_signups", 0)
    full_u = alltime.get("full_db_uploads", 0)
    full_p = alltime.get("full_db_paid", 0)

    msg = (
        f"🦅 <b>EAGLE3D KPI REPORT — {today_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"📊 <b>KPI SYSTEM</b> ✅ Validated\n"
        f"┌────────────────────────\n"
        f"│ 📅 <b>Today ({today_str})</b>\n"
        f"│ ✅ Sign-ups: <code>{s_today}</code>\n"
        f"│ 📤 Uploads:  <code>{u_today}</code>\n"
        f"│ 💳 Paid:     <code>{p_today}</code>\n"
        f"├────────────────────────\n"
        f"│ 📆 <b>Month ({month_str})</b>\n"
        f"│ ✅ Sign-ups: <code>{s_month}</code>\n"
        f"│ 📤 Uploads:  <code>{u_month}</code>\n"
        f"│ 💳 Paid:     <code>{p_month}</code>\n"
        f"├────────────────────────\n"
        f"│ 🏆 <b>Common Period</b>\n"
        f"│ <i>({period_label})</i>\n"
        f"│ ✅ Sign-ups: <code>{s_all}</code>\n"
        f"│ 📤 Uploads:  <code>{u_all}</code>\n"
        f"│ 💳 Paid:     <code>{p_all}</code>\n"
        f"├────────────────────────\n"
        f"│ 🔄 <b>Conversion Rates</b> (Common Period)\n"
        f"│ Sign→Upload: <code>{s2u:.1f}%</code>\n"
        f"│ Sign→Paid:   <code>{s2p:.1f}%</code>\n"
        f"├────────────────────────\n"
        f"│ 📋 <b>Full DB Totals</b> (all history)\n"
        f"│ ✅ Sign-ups: <code>{full_s}</code>\n"
        f"│ 📤 Uploads:  <code>{full_u}</code>\n"
        f"│ 💳 Paid:     <code>{full_p}</code>\n"
        f"│ <i>Note: Full DB conversion rates invalid</i>\n"
        f"│ <i>due to upload tracking gap (pre-Dec 2025)</i>\n"
        f"└────────────────────────\n"
        f"{warn_banner}"
        f"\n✅ <b>Validation:</b> {len(validation.passed)} checks passed\n"
        f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )

    return {
        "send": True,
        "message": msg,
        "is_warning": False,
        "validation": validation,
        "alltime": alltime,
    }


def send_validated_telegram(kpi: dict, ga4: dict, stripe: dict) -> bool:
    """Send Telegram report only after validation."""
    import os, json, urllib.request

    report = build_validated_kpi_report(kpi, ga4, stripe)
    validation = report["validation"]

    log(f"Validation: {validation.get_summary()}")

    if not report["send"]:
        log("Report suppressed by validation")
        return False

    # Get Telegram credentials
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        try:
            import streamlit as st
            bot_token = str(st.secrets.get("TELEGRAM_BOT_TOKEN", "")).strip()
            chat_id   = str(st.secrets.get("TELEGRAM_CHAT_ID", "")).strip()
        except Exception:
            pass

    if not bot_token or not chat_id:
        log("Telegram credentials not found")
        return False

    msg = report["message"]
    payload = json.dumps({
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            if body.get("ok"):
                status = "WARNING" if report["is_warning"] else "VALIDATED"
                log(f"✅ Telegram sent [{status}]")
                return True
            log(f"Telegram API error: {body}")
            return False
    except Exception as e:
        log(f"Telegram send failed: {e}")
        return False
