"""
GA4 Notification & Alert System - Eagle 3D KPI System
100% Free - Pure Python anomaly detection
"""

import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Alert:
    severity: str
    category: str
    title: str
    message: str
    metric: str
    current_value: float
    previous_value: float
    pct_change: float
    recommendation: str
    emoji: str = "📊"
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    )


def _pct(new_val, old_val):
    if old_val == 0:
        return 100.0 if new_val > 0 else 0.0
    return round((new_val - old_val) / old_val * 100, 1)


def _severity(pct):
    if pct <= -40:
        return "critical", "🚨"
    if pct <= -20:
        return "warning", "⚠️"
    if pct >= 60:
        return "positive", "🚀"
    if pct >= 30:
        return "positive", "📈"
    return "info", "ℹ️"


def detect_page_anomalies(current_df, previous_df):
    alerts = []
    if current_df.empty or previous_df.empty:
        return alerts
    curr = current_df.groupby("pagePath")["screenPageViews"].sum()
    prev = previous_df.groupby("pagePath")["screenPageViews"].sum()
    for page in curr.index:
        c = float(curr.get(page, 0))
        p = float(prev.get(page, 0))
        pct = _pct(c, p)
        if abs(pct) < 20 and p > 0:
            continue
        sev, emoji = _severity(pct)
        rec = (
            f"Investigate '{page}' — check links, SEO, content changes."
            if pct < 0
            else f"'{page}' is trending up! Add a signup CTA to capture this traffic."
        )
        alerts.append(Alert(
            severity=sev, category="page",
            title=f"Page {'Spike' if pct > 0 else 'Drop'}: {page}",
            message=f"Views: {int(p):,} → {int(c):,} ({pct:+.1f}%)",
            metric="screenPageViews",
            current_value=c, previous_value=p, pct_change=pct,
            recommendation=rec, emoji=emoji,
        ))
    return sorted(alerts, key=lambda a: abs(a.pct_change), reverse=True)


def detect_event_anomalies(current_df, previous_df):
    alerts = []
    if current_df.empty or previous_df.empty:
        return alerts
    curr = current_df.groupby("eventName")["eventCount"].sum()
    prev = previous_df.groupby("eventName")["eventCount"].sum()
    signup_signals = [
        "sign_up","signup","registration","form_submit",
        "begin_checkout","purchase","trial_start","demo_request",
    ]
    for event in curr.index:
        c = float(curr.get(event, 0))
        p = float(prev.get(event, 0))
        pct = _pct(c, p)
        is_signal = any(s in event.lower() for s in signup_signals)
        if abs(pct) < (15 if is_signal else 30):
            continue
        sev, emoji = _severity(pct)
        if is_signal and pct < 0:
            sev, emoji = "critical", "🚨"
        alerts.append(Alert(
            severity=sev, category="event",
            title=f"Event {'Surge' if pct > 0 else 'Drop'}: {event}",
            message=f"Count: {int(p):,} → {int(c):,} ({pct:+.1f}%)",
            metric="eventCount",
            current_value=c, previous_value=p, pct_change=pct,
            recommendation=(
                f"'{event}' dropping — audit the user journey for this action."
                if pct < 0
                else f"'{event}' surging — investigate what drove this increase."
            ),
            emoji=emoji,
        ))
    return sorted(alerts, key=lambda a: abs(a.pct_change), reverse=True)


def detect_source_anomalies(current_df, previous_df):
    alerts = []
    if current_df.empty or previous_df.empty:
        return alerts
    curr = current_df.groupby("sessionSource")["sessions"].sum()
    prev = previous_df.groupby("sessionSource")["sessions"].sum()
    for src in curr.index:
        c = float(curr.get(src, 0))
        p = float(prev.get(src, 0))
        if c < 5:
            continue
        pct = _pct(c, p)
        if abs(pct) < 25:
            continue
        sev, emoji = _severity(pct)
        alerts.append(Alert(
            severity=sev, category="source",
            title=f"Source {'Surge' if pct > 0 else 'Drop'}: {src}",
            message=f"Sessions: {int(p):,} → {int(c):,} ({pct:+.1f}%)",
            metric="sessions",
            current_value=c, previous_value=p, pct_change=pct,
            recommendation=(
                f"Traffic from '{src}' declining — check budget/rankings/links."
                if pct < 0
                else f"Traffic from '{src}' surging — ensure landing pages can handle volume."
            ),
            emoji=emoji,
        ))
    return sorted(alerts, key=lambda a: abs(a.pct_change), reverse=True)


def detect_conversion_anomalies(
    current_df, previous_df,
    ext_curr=None, ext_prev=None
):
    alerts = []
    if current_df.empty:
        return alerts

    def safe_sum(df, col):
        return float(df[col].sum()) if not df.empty and col in df.columns else 0.0

    curr_conv = safe_sum(current_df, "conversions")
    curr_sess = safe_sum(current_df, "sessions")
    curr_rate = (curr_conv / curr_sess * 100) if curr_sess > 0 else 0

    if not previous_df.empty:
        prev_conv = safe_sum(previous_df, "conversions")
        prev_sess = safe_sum(previous_df, "sessions")
        prev_rate = (prev_conv / prev_sess * 100) if prev_sess > 0 else 0
        pct = _pct(curr_rate, prev_rate)
        if abs(pct) >= 15:
            sev, emoji = _severity(pct)
            alerts.append(Alert(
                severity=sev, category="conversion",
                title=f"Conversion Rate {'Up' if pct > 0 else 'Down'}",
                message=f"Rate: {prev_rate:.2f}% → {curr_rate:.2f}% ({pct:+.1f}%)",
                metric="conversionRate",
                current_value=curr_rate, previous_value=prev_rate, pct_change=pct,
                recommendation=(
                    "Great! Find what changed and double down."
                    if pct > 0
                    else "Conversion rate dropping — audit signup flow and landing pages."
                ),
                emoji=emoji,
            ))

    if ext_curr is not None and ext_prev is not None:
        pct = _pct(ext_curr, ext_prev)
        if abs(pct) >= 20:
            sev, emoji = _severity(pct)
            alerts.append(Alert(
                severity=sev, category="signup",
                title=f"CRM Signups {'Up' if pct > 0 else 'Down'}",
                message=f"Signups: {ext_prev} → {ext_curr} ({pct:+.1f}%)",
                metric="signups",
                current_value=float(ext_curr),
                previous_value=float(ext_prev),
                pct_change=pct,
                recommendation=(
                    "Strong growth! Trace which source drove this."
                    if pct > 0
                    else "Signup decline — cross-check traffic source and funnel."
                ),
                emoji=emoji,
            ))
    return alerts


def build_notification_summary(all_alerts):
    critical  = [a for a in all_alerts if a.severity == "critical"]
    warnings  = [a for a in all_alerts if a.severity == "warning"]
    positives = [a for a in all_alerts if a.severity == "positive"]
    info      = [a for a in all_alerts if a.severity == "info"]
    return {
        "total":    len(all_alerts),
        "critical": critical,
        "warnings": warnings,
        "positives":positives,
        "info":     info,
        "has_urgency": len(critical) > 0,
        "summary_line": (
            f"🚨 {len(critical)} Critical | ⚠️ {len(warnings)} Warnings | "
            f"🚀 {len(positives)} Positive | Total: {len(all_alerts)}"
        ),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

