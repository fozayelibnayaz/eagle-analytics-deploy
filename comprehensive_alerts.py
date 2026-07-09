"""
comprehensive_alerts.py — Eagle 3D Streaming Analytics Hub
============================================================
Builds 8 sections of the daily "comprehensive" Telegram alert.
Each function returns a Markdown-formatted string, ready to send.
All data comes from MongoDB.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from mongo_client import find_all, find_one
from mongo_data_loader import (
    get_kpi_counts,
    load_daily_kpis,
    load_linkedin_highlights,
    load_linkedin_posts,
    load_payments,
    load_youtube_channel,
    load_youtube_videos,
    load_customer_success_master,
)


BRAND = "Eagle 3D Streaming"


def _fmt_pct(a: float, b: float) -> str:
    if not b:
        return "—"
    return f"{(a / b) * 100:.1f}%"


def _today_str() -> str:
    return date.today().isoformat()


def _yesterday_str() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _header(title: str, emoji: str = "📊") -> str:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return f"{emoji} *{BRAND} — {title}*\n_{ts}_\n"


# ─────────────────────────────────────────────────────────────────
# 1. KPI (detailed)
# ─────────────────────────────────────────────────────────────────
def alert_kpi_detailed() -> str:
    c = get_kpi_counts()
    s_t, u_t, p_t = c["signups_today"], c["uploads_today"], c["payments_today"]
    s_m, u_m, p_m = c["signups_month"], c["uploads_month"], c["payments_month"]
    s_a, p_a     = c["signups_total"], c["payments_total"]

    body = (
        f"*Today*\n"
        f"  👥 Signups:  {s_t}\n"
        f"  📤 Uploads:  {u_t}\n"
        f"  💳 Payments: {p_t}\n\n"
        f"*This Month*\n"
        f"  👥 Signups:  {s_m}\n"
        f"  📤 Uploads:  {u_m}\n"
        f"  💳 Payments: {p_m}\n\n"
        f"*Conversion Rates (all-time)*\n"
        f"  Signup → Payment: {_fmt_pct(p_a, s_a)}\n\n"
        f"*Lifetime Totals*\n"
        f"  Signups:  {s_a:,}\n"
        f"  Payments: {p_a:,}\n"
    )
    return _header("KPI Detailed", "📈") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# 2. GA4
# ─────────────────────────────────────────────────────────────────
def alert_ga4() -> str:
    # Try cached JSON (from pipeline) since GA4 API is separate
    from pathlib import Path
    import json
    cache = Path("data_output/ga4_traffic_cache.json")
    if not cache.exists():
        return _header("GA4 Traffic", "🌐") + "\n_No GA4 data cached yet._"

    try:
        data = json.loads(cache.read_text())
    except Exception:
        return _header("GA4 Traffic", "🌐") + "\n_GA4 cache unreadable._"

    body = (
        f"*Sessions (30d):* {data.get('total_sessions', 0):,}\n"
        f"*Users (30d):*    {data.get('total_users', 0):,}\n\n"
    )
    tops = data.get("top_sources", [])[:5]
    if tops:
        body += "*Top Sources*\n"
        for s, n in tops:
            body += f"  • {s}: {n:,}\n"
    countries = data.get("top_countries", [])[:5]
    if countries:
        body += "\n*Top Countries*\n"
        for c, n in countries:
            body += f"  • {c}: {n:,}\n"
    return _header("GA4 Traffic", "🌐") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# 3. YouTube
# ─────────────────────────────────────────────────────────────────
def alert_youtube() -> str:
    ch = load_youtube_channel() or {}
    vids = load_youtube_videos(limit=200)

    total_views = sum(int(v.get("views", 0) or 0) for v in vids)
    total_likes = sum(int(v.get("likes", 0) or 0) for v in vids)
    top = sorted(vids, key=lambda v: int(v.get("views", 0) or 0), reverse=True)[:3]

    body = (
        f"*Channel:* {ch.get('title', 'N/A')}\n"
        f"*Subscribers:* {int(ch.get('subscribers', 0)):,}\n"
        f"*Videos:* {len(vids):,}\n"
        f"*Total Views:* {total_views:,}\n"
        f"*Total Likes:* {total_likes:,}\n\n"
    )
    if top:
        body += "*Top 3 Videos*\n"
        for v in top:
            title = str(v.get("title", ""))[:60]
            body += f"  • {title}: {int(v.get('views',0)):,} views\n"
    return _header("YouTube", "📺") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# 4. LinkedIn
# ─────────────────────────────────────────────────────────────────
def alert_linkedin() -> str:
    hl = load_linkedin_highlights(limit=1)
    latest = hl[0] if hl else {}
    posts = load_linkedin_posts(limit=100)

    total_imp  = sum(int(p.get("impressions", 0) or 0) for p in posts)
    total_rxn  = sum(int(p.get("reactions", 0) or 0) for p in posts)
    total_com  = sum(int(p.get("comments", 0) or 0)  for p in posts)

    body = (
        f"*Total Followers:* {int(latest.get('total_followers', 0)):,}\n"
        f"*Page Views (30d):* {int(latest.get('page_views', 0)):,}\n"
        f"*Unique Visitors:* {int(latest.get('unique_visitors', 0)):,}\n\n"
        f"*Posts:* {len(posts)}\n"
        f"*Total Impressions:* {total_imp:,}\n"
        f"*Total Reactions:*   {total_rxn:,}\n"
        f"*Total Comments:*    {total_com:,}\n"
    )
    return _header("LinkedIn", "💼") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# 5. Stripe + Revenue
# ─────────────────────────────────────────────────────────────────
def alert_stripe() -> str:
    df = load_payments("ACCEPTED")
    if df.empty:
        return _header("Stripe + Revenue", "💰") + "\n_No payment data._"

    for col in ("total_spend", "amount", "total"):
        if col in df.columns:
            df["spend"] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            break
    else:
        df["spend"] = 0

    total_revenue = float(df["spend"].sum())
    avg_spend     = float(df["spend"].mean()) if len(df) else 0
    n_customers   = len(df)

    body = (
        f"*Paying Customers:* {n_customers:,}\n"
        f"*Total Revenue:*    ${total_revenue:,.2f}\n"
        f"*Avg Customer Spend:* ${avg_spend:,.2f}\n"
    )
    return _header("Stripe + Revenue", "💰") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# 6. Customer Success
# ─────────────────────────────────────────────────────────────────
def alert_customer_success() -> str:
    cs = load_customer_success_master(limit=200000)
    total = len(cs)
    body = (
        f"*Customer Success Master Rows:* {total:,}\n"
    )
    return _header("Customer Success", "🎯") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# 7. Cross-Platform
# ─────────────────────────────────────────────────────────────────
def alert_cross_platform() -> str:
    ch = load_youtube_channel() or {}
    hl = load_linkedin_highlights(limit=1)
    latest_li = hl[0] if hl else {}
    c = get_kpi_counts()

    body = (
        f"*Cross-Platform Snapshot*\n"
        f"  📺 YouTube subs:      {int(ch.get('subscribers', 0)):,}\n"
        f"  💼 LinkedIn followers: {int(latest_li.get('total_followers', 0)):,}\n"
        f"  👥 Total signups:      {c['signups_total']:,}\n"
        f"  💳 Paying customers:   {c['payments_total']:,}\n"
    )
    return _header("Cross-Platform", "🔗") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# 8. AI Insights (rule-based fallback for now)
# ─────────────────────────────────────────────────────────────────
def alert_ai_insights() -> str:
    c = get_kpi_counts()
    insights: List[str] = []

    if c["signups_today"] == 0:
        insights.append("• No signups today — check acquisition channels")
    if c["signups_month"] > 0 and c["payments_month"] == 0:
        insights.append("• Signups this month but 0 payments — funnel may be broken")

    df = load_daily_kpis()
    if not df.empty and "signups" in df.columns and len(df) >= 14:
        s = pd.to_numeric(df["signups"], errors="coerce").fillna(0)
        last7 = float(s.tail(7).mean())
        prev7 = float(s.tail(14).head(7).mean())
        if prev7 > 0:
            delta = (last7 - prev7) / prev7 * 100
            if abs(delta) >= 20:
                arrow = "📈" if delta > 0 else "📉"
                insights.append(f"• {arrow} Signup trend: {delta:+.1f}% vs previous 7 days")

    if not insights:
        insights.append("• All metrics within normal ranges ✅")

    body = "\n".join(insights)
    return _header("AI Insights", "🤖") + "\n" + body


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for fn in (alert_kpi_detailed, alert_ga4, alert_youtube, alert_linkedin,
               alert_stripe, alert_customer_success, alert_cross_platform,
               alert_ai_insights):
        print("\n" + "=" * 60)
        print(f"### {fn.__name__}")
        print("=" * 60)
        print(fn())
