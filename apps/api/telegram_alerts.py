"""
telegram_alerts.py — Smart Telegram Alert System for Eagle3D KPI
================================================================
Sends rich, formatted Telegram messages using HTML parse mode.
Uses HTML for reliability (MarkdownV2 is notoriously fragile).
"""

import os
import json
import re
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


def _esc(t):
    """Escape for Telegram HTML parse mode."""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _get_verified_kpi_stats():
    """Get classifier-verified KPI stats from the single source of truth (reporting_engine.build_kpi_stats)."""
    try:
        from reporting_engine import build_kpi_stats
        return build_kpi_stats()
    except Exception as e:
        print(f"[Telegram] Failed to get verified KPI stats: {e}")
        return None


def _send(message: str, parse_mode="HTML") -> dict:
    """Send to Telegram. Checks st.secrets first, then env vars."""
    bot_token = ""
    chat_id = ""
    try:
        import streamlit as st
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "").strip()
    except Exception:
        pass
    if not bot_token:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not chat_id:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"}

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            if body.get("ok"):
                return {"ok": True, "error": None}
            return {"ok": False, "error": str(body)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# DAILY KPI REPORT
# ══════════════════════════════════════════════════════════════

def daily_kpi_report(kpi_df, prev_kpi_df=None, utm_df=None, leads_df=None) -> str:
    import pandas as pd
    now = datetime.now()

    signups = int(pd.to_numeric(kpi_df.get("signups", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0
    uploads = int(pd.to_numeric(kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0
    paid = int(pd.to_numeric(kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0

    prev_s = prev_u = prev_p = 0
    if prev_kpi_df is not None and not prev_kpi_df.empty:
        prev_s = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
        prev_u = int(pd.to_numeric(prev_kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum())
        prev_p = int(pd.to_numeric(prev_kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum())

    def chg(cur, prev):
        if prev == 0: return "N/A"
        c = (cur - prev) / prev * 100
        return f"{'📈' if c > 0 else '📉'} {c:+.1f}%"

    s2u = (uploads / signups * 100) if signups > 0 else 0
    u2p = (paid / uploads * 100) if uploads > 0 else 0

    total_sess = 0
    top_src = "N/A"
    if utm_df is not None and not utm_df.empty and "sessions" in utm_df.columns:
        total_sess = int(pd.to_numeric(utm_df["sessions"], errors="coerce").sum())
        src_col = "source_normalized" if "source_normalized" in utm_df.columns else "sessionSource"
        if src_col in utm_df.columns:
            top_sources = utm_df.groupby(src_col)["sessions"].sum().sort_values(ascending=False)
            if len(top_sources) > 0:
                top_src = f"{top_sources.index[0]} ({int(top_sources.iloc[0])})"

    today_date = now.strftime("%Y-%m-%d")
    today_s = today_u = today_p = 0
    if kpi_df is not None and not kpi_df.empty and "date" in kpi_df.columns:
        today_row = kpi_df[kpi_df["date"].astype(str) == today_date]
        if today_row.empty:
            today_row = kpi_df.head(1)
        if not today_row.empty:
            today_s = int(pd.to_numeric(today_row["signups"], errors="coerce").fillna(0).sum())
            today_u = int(pd.to_numeric(today_row["first_uploads"], errors="coerce").fillna(0).sum())
            today_p = int(pd.to_numeric(today_row["paid_customers"], errors="coerce").fillna(0).sum())

    if signups > 0 and s2u > 20:
        health = "🟢 EXCELLENT"
    elif signups > 0 and s2u > 10:
        health = "🟡 GOOD"
    elif signups > 0:
        health = "🟠 NEEDS ATTENTION"
    else:
        health = "🔴 NO DATA"

    msg = (
        f"🦅 <b>EAGLE3D DAILY KPI REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 {_esc(now.strftime('%A, %B %d, %Y'))}\n\n"
        f"📊 <b>TODAY'S NUMBERS</b>\n"
        f"├ Sign-ups: <code>{today_s}</code>\n"
        f"├ Uploads: <code>{today_u}</code>\n"
        f"└ Paid: <code>{today_p}</code>\n\n"
        f"📈 <b>PERIOD TOTAL</b>\n"
        f"├ 👥 Sign-ups: <code>{signups:,}</code> {chg(signups, prev_s)}\n"
        f"├ 📤 Uploads: <code>{uploads:,}</code> {chg(uploads, prev_u)}\n"
        f"└ 💳 Paid: <code>{paid:,}</code> {chg(paid, prev_p)}\n\n"
        f"🔄 <b>FUNNEL</b>\n"
        f"├ S→U Rate: <code>{s2u:.1f}%</code>\n"
        f"└ U→P Rate: <code>{u2p:.1f}%</code>\n\n"
        f"🌐 <b>TRAFFIC</b>: <code>{total_sess:,}</code> sessions\n"
        f"🏆 <b>Top Source</b>: {_esc(top_src)}\n\n"
        f"🏥 Health: {health}\n\n"
        f"⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"
    )
    return msg


# ══════════════════════════════════════════════════════════════
# WEEKLY / BIWEEKLY / MONTHLY REPORT
# ══════════════════════════════════════════════════════════════

def period_report(kpi_df, prev_kpi_df=None, utm_df=None, leads_df=None, pages_df=None, period_type="weekly") -> str:
    import pandas as pd
    now = datetime.now()

    signups = int(pd.to_numeric(kpi_df.get("signups", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0
    uploads = int(pd.to_numeric(kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0
    paid = int(pd.to_numeric(kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0

    prev_s = prev_u = prev_p = 0
    if prev_kpi_df is not None and not prev_kpi_df.empty:
        prev_s = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
        prev_u = int(pd.to_numeric(prev_kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum())
        prev_p = int(pd.to_numeric(prev_kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum())

    def chg(cur, prev):
        if prev == 0: return "N/A"
        c = (cur - prev) / prev * 100
        return f"{'🟢' if c > 0 else '🔴'} {c:+.1f}%"

    best_day = "N/A"
    best_day_s = 0
    if kpi_df is not None and not kpi_df.empty and "date" in kpi_df.columns and "signups" in kpi_df.columns:
        daily = kpi_df.groupby("date")["signups"].sum()
        if len(daily) > 0:
            best_day = str(daily.idxmax())
            best_day_s = int(daily.max())

    sources_text = "N/A"
    if utm_df is not None and not utm_df.empty and "sessions" in utm_df.columns:
        src_col = "source_normalized" if "source_normalized" in utm_df.columns else "sessionSource"
        if src_col in utm_df.columns:
            by_src = utm_df.groupby(src_col)["sessions"].sum().sort_values(ascending=False).head(5)
            total = by_src.sum()
            lines = []
            for src, sess in by_src.items():
                pct = sess / total * 100 if total > 0 else 0
                lines.append(f"  ├ {_esc(str(src))}: <code>{int(sess)}</code> ({pct:.0f}%)")
            sources_text = "\n".join(lines)

    leads_text = ""
    if leads_df is not None and not leads_df.empty:
        if "Lead Source" in leads_df.columns and "Signups" in leads_df.columns:
            top_leads = leads_df.sort_values("Signups", ascending=False).head(5)
            leads_text = "\n🎯 <b>TOP LEAD SOURCES</b>\n"
            for _, row in top_leads.iterrows():
                leads_text += f"  ├ {_esc(str(row['Lead Source']))}: <code>{int(row['Signups'])}</code>\n"

    period_labels = {"weekly": "WEEKLY", "biweekly": "BIWEEKLY", "monthly": "MONTHLY", "quarterly": "QUARTERLY"}
    label = period_labels.get(period_type, "PERIOD")

    msg = (
        f"📊 <b>EAGLE3D {label} REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 {_esc(now.strftime('%B %d, %Y'))}\n\n"
        f"📈 <b>KEY METRICS</b>\n"
        f"├ 👥 Sign-ups: <code>{signups:,}</code> {chg(signups, prev_s)}\n"
        f"├ 📤 Uploads: <code>{uploads:,}</code> {chg(uploads, prev_u)}\n"
        f"└ 💳 Paid: <code>{paid:,}</code> {chg(paid, prev_p)}\n\n"
        f"🏆 <b>BEST DAY</b>: {_esc(best_day)} (<code>{best_day_s}</code> signups)\n\n"
        f"🌐 <b>TOP TRAFFIC SOURCES</b>\n{sources_text}\n"
        f"{leads_text}\n"
        f"⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"
    )
    return msg


# ══════════════════════════════════════════════════════════════
# ANOMALY ALERTS — 20 TYPES
# ══════════════════════════════════════════════════════════════

def anomaly_alerts(kpi_df, prev_kpi_df=None) -> list:
    import pandas as pd
    alerts = []
    if kpi_df is None or kpi_df.empty:
        return [{"type": "info", "msg": "⚠️ No KPI data available for anomaly detection"}]
    now = datetime.now()

    signups = int(pd.to_numeric(kpi_df.get("signups", 0), errors="coerce").fillna(0).sum()) if not kpi_df.empty else 0
    uploads = int(pd.to_numeric(kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum()) if not kpi_df.empty else 0
    paid = int(pd.to_numeric(kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum()) if not kpi_df.empty else 0

    # 1. SIGNIFICANT DROPS/SPIKES
    if prev_kpi_df is not None and not prev_kpi_df.empty:
        for metric, label, icon in [("signups", "Sign-ups", "👥"), ("first_uploads", "Uploads", "📤"), ("paid_customers", "Paid", "💳")]:
            if metric in kpi_df.columns and metric in prev_kpi_df.columns:
                cur = int(pd.to_numeric(kpi_df[metric], errors="coerce").fillna(0).sum())
                prev = int(pd.to_numeric(prev_kpi_df[metric], errors="coerce").fillna(0).sum())
                if prev > 0:
                    change = (cur - prev) / prev * 100
                    if change <= -30:
                        alerts.append({"type": "critical", "msg": f"🚨 <b>{label} DROP ALERT</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\n{icon} {label} dropped by <code>{abs(change):.1f}%</code>\n\n📋 Details\n• Previous: <code>{prev}</code>\n• Current: <code>{cur}</code>\n• Change: <code>{change:+.1f}%</code>\n\n💡 <b>Action</b>: Investigate marketing changes, check sign-up flow, review ad campaigns\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})
                    elif change >= 30:
                        alerts.append({"type": "positive", "msg": f"📈 <b>{label} SPIKE</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\n{icon} {label} surged by <code>{change:.1f}%</code>\n\n📋 Details\n• Previous: <code>{prev}</code>\n• Current: <code>{cur}</code>\n• Change: <code>{change:+.1f}%</code>\n\n💡 <b>Action</b>: Identify what's working and double down!\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 2. ZERO-DAY ALERT
    if "signups" in kpi_df.columns and "date" in kpi_df.columns:
        daily = kpi_df.groupby("date")["signups"].sum()
        zero_days = daily[daily == 0]
        if len(zero_days) > 0 and len(daily) > 3:
            last_zero = str(zero_days.index[-1])
            alerts.append({"type": "warning", "msg": f"⚠️ <b>ZERO SIGNUP DAYS</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\n<code>{len(zero_days)}</code> days with zero signups found\n\n📋 Details\n• Zero days: <code>{len(zero_days)}</code>\n• Last zero: {_esc(last_zero)}\n\n💡 Check if pipeline ran correctly on these days\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 3. FUNNEL HEALTH
    s2u = (uploads / signups * 100) if signups > 0 else 0
    u2p = (paid / uploads * 100) if uploads > 0 else 0

    if signups > 10:
        # 4. LOW UPLOAD RATE
        if s2u < 15:
            alerts.append({"type": "warning", "msg": f"⚠️ <b>LOW UPLOAD RATE</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSign-up → Upload rate is only <code>{s2u:.1f}%</code>\n\n📋 Details\n• Sign-ups: <code>{signups}</code>\n• Uploads: <code>{uploads}</code>\n• Rate: <code>{s2u:.1f}%</code>\n\n💡 Improve onboarding, add tutorials, simplify upload flow\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})
        # 5. LOW CONVERSION TO PAID
        if u2p < 5:
            alerts.append({"type": "warning", "msg": f"⚠️ <b>LOW CONVERSION TO PAID</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nUpload → Paid rate is only <code>{u2p:.1f}%</code>\n\n📋 Details\n• Uploads: <code>{uploads}</code>\n• Paid: <code>{paid}</code>\n• Rate: <code>{u2p:.1f}%</code>\n\n💡 Review pricing, add upgrade prompts, improve value prop\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})
        # 6. EXCELLENT FUNNEL
        if s2u > 30 and u2p > 15:
            alerts.append({"type": "positive", "msg": f"✅ <b>EXCELLENT FUNNEL HEALTH</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nConversion rates are strong!\n\n📋 Details\n• S→U Rate: <code>{s2u:.1f}%</code>\n• U→P Rate: <code>{u2p:.1f}%</code>\n\n💡 Maintain current strategy, scale what works\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 7. DAILY ANOMALY (Z-SCORE)
    if "signups" in kpi_df.columns and len(kpi_df) >= 5:
        vals = pd.to_numeric(kpi_df["signups"], errors="coerce").dropna()
        if len(vals) >= 5:
            mean = vals.mean()
            std = vals.std()
            if std > 0:
                last_val = float(vals.iloc[0])
                z = (last_val - mean) / std
                if abs(z) >= 2.0:
                    direction = "SPIKE" if z > 0 else "DROP"
                    icon = "📈" if z > 0 else "🚨"
                    alerts.append({"type": "critical" if abs(z) >= 3 else "warning", "msg": f"{icon} <b>DAILY {direction} ANOMALY</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSign-ups deviate <code>{abs(z):.1f}</code> standard deviations from mean\n\n📋 Details\n• Last value: <code>{int(last_val)}</code>\n• Daily average: <code>{mean:.1f}</code>\n• Z-score: <code>{z:.1f}</code>\n\n💡 {'Capitalize on this spike — what drove it?' if z > 0 else 'Investigate the drop — is it a data issue or real?'}\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 8. STREAK DETECTION
    if "signups" in kpi_df.columns and "date" in kpi_df.columns and len(kpi_df) >= 5:
        sorted_kpi = kpi_df.sort_values("date", ascending=False)
        vals = pd.to_numeric(sorted_kpi["signups"], errors="coerce").fillna(0).tolist()
        # Declining streak
        decline = 0
        for i in range(len(vals)-1):
            if vals[i] < vals[i+1]:
                decline += 1
            else:
                break
        if decline >= 4:
            alerts.append({"type": "warning", "msg": f"📉 <b>DECLINING STREAK</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSign-ups have declined for <code>{decline}</code> consecutive days\n\n💡 Review recent changes, check traffic sources, examine ad campaigns\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})
        # Growing streak
        growth = 0
        for i in range(len(vals)-1):
            if vals[i] > vals[i+1]:
                growth += 1
            else:
                break
        if growth >= 4:
            alerts.append({"type": "positive", "msg": f"📈 <b>GROWTH STREAK</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSign-ups have grown for <code>{growth}</code> consecutive days!\n\n💡 Identify what's driving this growth and sustain it\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 9. MILESTONE ALERTS
    if signups > 0:
        milestones = [(10, "10"), (25, "25"), (50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1,000")]
        prev_total = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum()) if prev_kpi_df is not None and not prev_kpi_df.empty else 0
        for threshold, label in milestones:
            if prev_total < threshold <= signups:
                alerts.append({"type": "positive", "msg": f"🏆 <b>MILESTONE REACHED: {label} SIGN-UPS!</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\n🎉 Congratulations! You've hit <code>{label}</code> sign-ups this period!\n\n📋 Details\n• Sign-ups: <code>{signups}</code>\n• Previous period: <code>{prev_total}</code>\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})
                break

    # 10. UPLOAD-TO-PAID GAP
    if uploads > 5 and paid == 0:
        alerts.append({"type": "warning", "msg": f"⚠️ <b>UPLOADS BUT ZERO PAID</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\n<code>{uploads}</code> uploads but <code>0</code> paid customers\n\n💡 Users are uploading but not converting. Review pricing page, add upgrade prompts after upload\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 11. HIGH SIGNUP BUT LOW UPLOAD (activation problem)
    if signups > 20 and s2u < 10:
        alerts.append({"type": "critical", "msg": f"🔴 <b>ACTIVATION CRISIS</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\n<code>{signups}</code> sign-ups but only <code>{uploads}</code> uploaded (<code>{s2u:.1f}%</code>)\n\n💡 CRITICAL: Users sign up but don't use the product. Improve onboarding flow, add guided tutorial, send activation emails\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 12. PAID GROWTH OUTPACING SIGNUPS (good monetization)
    if signups > 0 and paid > 0 and prev_kpi_df is not None and not prev_kpi_df.empty:
        prev_s = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
        prev_p = int(pd.to_numeric(prev_kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum())
        if prev_s > 0 and prev_p > 0:
            s_change = (signups - prev_s) / prev_s * 100
            p_change = (paid - prev_p) / prev_p * 100
            if p_change > s_change and p_change > 20:
                alerts.append({"type": "positive", "msg": f"💰 <b>MONETIZATION ACCELERATING</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nPaid growth (<code>{p_change:+.1f}%</code>) outpacing sign-up growth (<code>{s_change:+.1f}%</code>)\n\n💡 Your monetization strategy is working. Keep optimizing conversion paths\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 13. WEEKEND DIP PATTERN
    if "date" in kpi_df.columns and "signups" in kpi_df.columns and len(kpi_df) >= 7:
        kpi_copy = kpi_df.copy()
        kpi_copy["dow"] = pd.to_datetime(kpi_copy["date"]).dt.dayofweek
        weekend = kpi_copy[kpi_copy["dow"].isin([5, 6])]["signups"].mean()
        weekday = kpi_copy[~kpi_copy["dow"].isin([5, 6])]["signups"].mean()
        if weekday > 0 and weekend / weekday < 0.5:
            alerts.append({"type": "info", "msg": f"📅 <b>WEEKEND DIP DETECTED</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nWeekend sign-ups (<code>{weekend:.1f}/day</code>) are <code>{(1-weekend/weekday)*100:.0f}%</code> lower than weekday (<code>{weekday:.1f}/day</code>)\n\n💡 Consider weekend-specific campaigns or content scheduling\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 14. VOLATILITY WARNING
    if "signups" in kpi_df.columns and len(kpi_df) >= 7:
        vals = pd.to_numeric(kpi_df["signups"], errors="coerce").dropna()
        if len(vals) >= 7:
            cv = vals.std() / vals.mean() if vals.mean() > 0 else 0
            if cv > 0.8:
                alerts.append({"type": "warning", "msg": f"📊 <b>HIGH VOLATILITY</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSign-up numbers are highly volatile (CV: <code>{cv:.2f}</code>)\n\n📋 Details\n• Mean: <code>{vals.mean():.1f}</code>\n• Std Dev: <code>{vals.std():.1f}</code>\n\n💡 High volatility means unpredictable revenue. Focus on stable acquisition channels\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 15. DATA STALENESS CHECK
    if "date" in kpi_df.columns:
        latest = kpi_df["date"].max()
        try:
            latest_dt = pd.to_datetime(latest)
            days_old = (datetime.now() - latest_dt).days
            if days_old > 2:
                alerts.append({"type": "critical", "msg": f"🔴 <b>STALE DATA WARNING</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nLast data is <code>{days_old}</code> days old ({_esc(str(latest))})\n\n💡 Pipeline may not be running. Check GitHub Actions, verify schedule\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 🔄 Pipeline"})
        except Exception:
            pass

    # 16. CONVERSION RATE TREND
    if prev_kpi_df is not None and not prev_kpi_df.empty and signups > 0:
        prev_s = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
        prev_u = int(pd.to_numeric(prev_kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum())
        prev_s2u = (prev_u / prev_s * 100) if prev_s > 0 else 0
        if prev_s2u > 0 and s2u < prev_s2u * 0.7:
            alerts.append({"type": "warning", "msg": f"📉 <b>CONVERSION RATE DECLINING</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nS→U rate dropped from <code>{prev_s2u:.1f}%</code> to <code>{s2u:.1f}%</code>\n\n💡 Conversion rate is dropping. Check if traffic quality changed or onboarding broke\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 17. CONSECUTIVE ZERO UPLOAD DAYS
    if "first_uploads" in kpi_df.columns and "date" in kpi_df.columns and len(kpi_df) >= 3:
        sorted_kpi = kpi_df.sort_values("date", ascending=False)
        up_vals = pd.to_numeric(sorted_kpi["first_uploads"], errors="coerce").fillna(0).tolist()
        zero_upload_streak = 0
        for v in up_vals:
            if v == 0:
                zero_upload_streak += 1
            else:
                break
        if zero_upload_streak >= 3:
            alerts.append({"type": "warning", "msg": f"📤 <b>UPLOAD DROUGHT</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nNo uploads for <code>{zero_upload_streak}</code> consecutive days\n\n💡 Check if upload functionality is working, send re-engagement emails to recent sign-ups\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 18. RAPID GROWTH ALERT
    if prev_kpi_df is not None and not prev_kpi_df.empty:
        prev_s = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
        if prev_s > 5 and signups > prev_s * 2:
            growth_pct = (signups - prev_s) / prev_s * 100
            alerts.append({"type": "positive", "msg": f"🚀 <b>RAPID GROWTH DETECTED</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSign-ups grew <code>{growth_pct:.0f}%</code> vs previous period!\n\n📋 Details\n• Previous: <code>{prev_s}</code>\n• Current: <code>{signups}</code>\n\n💡 This is exceptional growth. Document what changed and scale it\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 19. BALANCED METRICS CHECK
    if signups > 0 and uploads > 0 and paid > 0:
        s2u_ok = 15 < s2u < 50
        u2p_ok = 5 < u2p < 50
        if s2u_ok and u2p_ok:
            alerts.append({"type": "positive", "msg": f"✅ <b>BALANCED FUNNEL</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nAll conversion rates are in healthy range\n\n📋 Details\n• Sign-ups: <code>{signups}</code>\n• Uploads: <code>{uploads}</code> (S→U: <code>{s2u:.1f}%</code>)\n• Paid: <code>{paid}</code> (U→P: <code>{u2p:.1f}%</code>)\n\n💡 Funnel is healthy. Focus on scaling volume at the top\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    # 20. ALL QUIET (no issues found)
    if not alerts:
        alerts.append({"type": "positive", "msg": f"✅ <b>ALL SYSTEMS NORMAL</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\nNo anomalies detected\nSign-ups: <code>{signups}</code> | Uploads: <code>{uploads}</code> | Paid: <code>{paid}</code>\n\n⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"})

    return alerts


# ══════════════════════════════════════════════════════════════
# MARKETING TEAM PERFORMANCE
# ══════════════════════════════════════════════════════════════

def marketing_performance(kpi_df, prev_kpi_df=None, utm_df=None, leads_df=None) -> str:
    import pandas as pd
    now = datetime.now()

    signups = int(pd.to_numeric(kpi_df.get("signups", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0
    uploads = int(pd.to_numeric(kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0
    paid = int(pd.to_numeric(kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum()) if kpi_df is not None and not kpi_df.empty else 0

    if signups >= 20: grade = "🥇 A+"
    elif signups >= 10: grade = "🥈 A"
    elif signups >= 5: grade = "🥉 B"
    elif signups >= 1: grade = "📋 C"
    else: grade = "🔴 F"

    s2u = (uploads / signups * 100) if signups > 0 else 0
    u2p = (paid / uploads * 100) if uploads > 0 else 0

    sources_text = ""
    if utm_df is not None and not utm_df.empty and "sessions" in utm_df.columns:
        src_col = "source_normalized" if "source_normalized" in utm_df.columns else "sessionSource"
        if src_col in utm_df.columns:
            by_src = utm_df.groupby(src_col)["sessions"].sum().sort_values(ascending=False).head(5)
            total = by_src.sum()
            for src, sess in by_src.items():
                pct = sess / total * 100 if total > 0 else 0
                sources_text += f"  ├ {_esc(str(src))}: <code>{int(sess)}</code> ({pct:.0f}%)\n"

    prev_s = 0
    if prev_kpi_df is not None and not prev_kpi_df.empty:
        prev_s = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
    trend = "📈 UP" if signups > prev_s else "📉 DOWN" if signups < prev_s else "➡️ FLAT"

    msg = (
        f"📊 <b>MARKETING TEAM SCORECARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 {_esc(now.strftime('%A, %B %d'))}\n\n"
        f"🏆 <b>GRADE</b>: {grade}\n\n"
        f"📊 <b>METRICS</b>\n"
        f"├ 👥 Sign-ups: <code>{signups}</code>\n"
        f"├ 📤 Uploads: <code>{uploads}</code>\n"
        f"├ 💳 Paid: <code>{paid}</code>\n"
        f"├ 🔄 S→U: <code>{s2u:.1f}%</code>\n"
        f"└ 💰 U→P: <code>{u2p:.1f}%</code>\n\n"
        f"📈 <b>Trend</b>: {trend}\n\n"
        f"🌐 <b>Traffic Sources</b>\n{sources_text}\n"
        f"⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Marketing Team"
    )
    return msg


# ══════════════════════════════════════════════════════════════
# PIPELINE HEALTH ALERT
# ══════════════════════════════════════════════════════════════

def pipeline_health_alert(success=True, stages=None, error_msg="") -> str:
    now = datetime.now()
    if success:
        stage_text = ""
        if stages:
            for s in stages:
                stage_text += f"  ├ ✅ {_esc(str(s))}\n"
        return (
            f"✅ <b>PIPELINE COMPLETED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 All stages passed\n"
            f"{stage_text}\n"
            f"⏰ {_esc(now.strftime('%I:%M %p'))} | 🔄 Pipeline"
        )
    return (
        f"🚨 <b>PIPELINE FAILED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Error: {_esc(error_msg[:200])}\n\n"
        f"💡 Check GitHub Actions for details\n\n"
        f"⏰ {_esc(now.strftime('%I:%M %p'))} | 🔄 Pipeline"
    )


# ══════════════════════════════════════════════════════════════
# TOP PERFORMER ALERT
# ══════════════════════════════════════════════════════════════

def top_performer_alert(kpi_df, utm_df=None) -> str:
    import pandas as pd
    now = datetime.now()
    best_date = "N/A"
    best_signups = 0
    if kpi_df is not None and not kpi_df.empty and "date" in kpi_df.columns and "signups" in kpi_df.columns:
        daily = kpi_df.groupby("date")["signups"].sum()
        if len(daily) > 0:
            best_date = str(daily.idxmax())
            best_signups = int(daily.max())
    return (
        f"✅ 🥇 <b>TOP PERFORMER</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Best performing day by sign-ups\n\n"
        f"📋 Details\n"
        f"• Date: {_esc(best_date)}\n"
        f"• Sign-ups: <code>{best_signups}</code>\n\n"
        f"💡 What was different on this day? Check campaigns and content.\n\n"
        f"⏰ {_esc(now.strftime('%I:%M %p'))} | 👥 Team"
    )


# ══════════════════════════════════════════════════════════════
# SEND HELPER — used by app.py buttons
# ══════════════════════════════════════════════════════════════

def send(msg: str) -> dict:
    """Convenience wrapper."""
    return _send(msg)
