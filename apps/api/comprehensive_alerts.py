#!/usr/bin/env python3
"""
Comprehensive Multi-System Alert Engine
Sends Telegram alerts for all systems:
KPI metrics, GA4, YouTube, LinkedIn, Stripe, Customer Success, AI insights.
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go



import os
import json
import urllib.request
from datetime import datetime, date, timedelta
from collections import Counter

from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
from mongo_data_loader import (
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status, load_all_ml_training_tabs
)









def _send_telegram(message, parse_mode="HTML", max_retries=3):
    """Use proven send_telegram from reporting_engine - urllib works."""
    import time
    try:
        from reporting_engine import send_telegram as _proven_send
    except Exception:
        return False

    CHUNK_SIZE = 3500
    chunks = []
    if len(message) <= CHUNK_SIZE:
        chunks = [message]
    else:
        remaining = message
        while remaining:
            if len(remaining) <= CHUNK_SIZE:
                chunks.append(remaining)
                break
            split = remaining.rfind("\n", 0, CHUNK_SIZE)
            if split < 1000:
                split = CHUNK_SIZE
            chunks.append(remaining[:split])
            remaining = remaining[split:].lstrip()

    success = 0
    for chunk in chunks:
        if not chunk.strip():
            continue
        for attempt in range(max_retries):
            try:
                if _proven_send(chunk, parse_mode=parse_mode):
                    success += 1
                    break
            except Exception as e:
                print(f"Send err {attempt+1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(3 + attempt * 2)
    return success > 0



def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _get_sb():
    return get_db()


# ═══════════════════════════════════════════════
# ALERT 1: KPI WITH MoM + ANOMALY DETECTION
# ═══════════════════════════════════════════════
def alert_kpi_detailed():
    sb = _get_sb()
    if sb is None:
        return ""

    today = date.today().strftime("%Y-%m-%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_start = date.today().strftime("%Y-%m-01")
    last_month = (date.today().replace(day=1) - timedelta(days=1))
    last_month_start = last_month.replace(day=1).strftime("%Y-%m-%d")
    last_month_end = last_month.strftime("%Y-%m-%d")

    def cnt(table, col, gte, lte=None):
        q = sb.table(table).select("count", count="exact").eq("final_status","ACCEPTED").gte(col, gte)
        if lte:
            q = q.lte(col, lte)
        return q.execute().count or 0

    # Today
    s_today = cnt("signups", "signup_date", today)
    u_today = cnt("uploads", "upload_date", today)
    p_today = cnt("payments", "first_payment_date", today)

    # Yesterday for comparison
    s_yest = cnt("signups", "signup_date", yesterday, yesterday)
    u_yest = cnt("uploads", "upload_date", yesterday, yesterday)
    p_yest = cnt("payments", "first_payment_date", yesterday, yesterday)

    # Week
    s_week = cnt("signups", "signup_date", week_ago)
    u_week = cnt("uploads", "upload_date", week_ago)
    p_week = cnt("payments", "first_payment_date", week_ago)

    # Month
    s_month = cnt("signups", "signup_date", month_start)
    u_month = cnt("uploads", "upload_date", month_start)
    p_month = cnt("payments", "first_payment_date", month_start)

    # Last Month
    s_lmonth = cnt("signups", "signup_date", last_month_start, last_month_end)
    u_lmonth = cnt("uploads", "upload_date", last_month_start, last_month_end)
    p_lmonth = cnt("payments", "first_payment_date", last_month_start, last_month_end)

    def delta(curr, prev):
        if prev == 0:
            return "🆕" if curr > 0 else ""
        pct = (curr - prev) / prev * 100
        if pct > 50:  return f"🚀+{pct:.0f}%"
        if pct > 10:  return f"📈+{pct:.0f}%"
        if pct > 0:   return f"⬆+{pct:.0f}%"
        if pct < -50: return f"💀{pct:.0f}%"
        if pct < -10: return f"📉{pct:.0f}%"
        if pct < 0:   return f"⬇{pct:.0f}%"
        return "➡0%"

    # Anomalies
    anomalies = []
    if s_today == 0:
        anomalies.append("🚨 ZERO signups today!")
    if s_today > s_yest * 2 and s_yest > 0:
        anomalies.append(f"🔥 Signup SPIKE: {s_today} today vs {s_yest} yesterday")
    if p_today >= 3:
        anomalies.append(f"💎 {p_today} new paid customers today!")
    if u_today == 0 and s_today > 0:
        anomalies.append(f"⚠️ {s_today} signups but ZERO uploads - onboarding broken?")

    msg = (
        f"📊 <b>KPI DETAILED ALERT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"📅 <b>Today vs Yesterday</b>\n"
        f"├ Signups: <code>{s_today}</code> (yest {s_yest}) {delta(s_today, s_yest)}\n"
        f"├ Uploads: <code>{u_today}</code> (yest {u_yest}) {delta(u_today, u_yest)}\n"
        f"└ Paid:    <code>{p_today}</code> (yest {p_yest}) {delta(p_today, p_yest)}\n"
        f"\n"
        f"📅 <b>Last 7 Days</b>\n"
        f"├ Signups: <code>{s_week}</code>\n"
        f"├ Uploads: <code>{u_week}</code>\n"
        f"└ Paid:    <code>{p_week}</code>\n"
        f"\n"
        f"📆 <b>This Month vs Last Month</b>\n"
        f"├ Signups: <code>{s_month}</code> (last {s_lmonth}) {delta(s_month, s_lmonth)}\n"
        f"├ Uploads: <code>{u_month}</code> (last {u_lmonth}) {delta(u_month, u_lmonth)}\n"
        f"└ Paid:    <code>{p_month}</code> (last {p_lmonth}) {delta(p_month, p_lmonth)}\n"
    )

    if anomalies:
        msg += "\n⚠️ <b>ANOMALIES DETECTED</b>\n"
        for a in anomalies:
            msg += f"• {a}\n"

    return msg


# ═══════════════════════════════════════════════
# ALERT 2: CUSTOMER SUCCESS HEALTH
# ═══════════════════════════════════════════════
def alert_customer_success():
    sb = _get_sb()
    if sb is None:
        return ""
    try:
        from customer_success_analytics import (
            churn_by_month, subscription_lifecycle, sheet1_analysis,
            customer_value_tiers, recent_activity_analysis, phone_call_analytics
        )
        churn = churn_by_month()
        sub = subscription_lifecycle()
        sheet1 = sheet1_analysis()
        tiers = customer_value_tiers()
        recent = recent_activity_analysis()
        phones = phone_call_analytics()
    except Exception as e:
        return f"\n🎯 <b>CUSTOMER SUCCESS</b> Error: {_esc(str(e))[:200]}\n"

    msg = (
        f"\n🎯 <b>CUSTOMER SUCCESS ALERT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💔 Total Churned: <code>{churn['total_churned']}</code>\n"
        f"💸 Annual Loss: <code>${churn['annual_revenue_lost']:,.2f}</code>\n"
        f"\n"
        f"📅 <b>Subscriptions</b>\n"
        f"├ 🆕 New This Month: <code>{sub['count_new']}</code>\n"
        f"├ ⏰ Ending in 30d: <code>{sub['count_ending']}</code> ⚠️\n"
        f"├ ❌ Recently Expired: <code>{sub['count_expired']}</code>\n"
        f"└ 💎 Long-term (12+): <code>{sub['count_long_term']}</code>\n"
        f"\n"
        f"💎 <b>Customer Tiers</b>\n"
        f"├ VIP (18+): <code>{tiers['vip_count']}</code>\n"
        f"├ High (12+): <code>{tiers['high_count']}</code>\n"
        f"├ Mid (6+): <code>{tiers['mid_count']}</code>\n"
        f"└ Low (1-5): <code>{tiers['low_count']}</code>\n"
        f"\n"
        f"📈 <b>Activity Trend</b>\n"
        f"├ 🚀 Growing: <code>{recent['count_growing']}</code>\n"
        f"├ ➡️ Steady: <code>{recent['count_steady']}</code>\n"
        f"└ 📉 Declining: <code>{recent['count_declining']}</code> ⚠️\n"
        f"\n"
        f"☎️ <b>Phone Campaign</b>\n"
        f"├ Total Calls: <code>{phones['total_calls_made']}</code>\n"
        f"├ Customers Reached: <code>{phones['customers_called']}</code>\n"
        f"└ Answer Rate: <code>{phones['answer_rate']}%</code>\n"
        f"\n"
        f"🚨 <b>Critical:</b>\n"
        f"• {len(sheet1.get('dormant_paying', []))} paying customers DORMANT 30+ days\n"
        f"• {sub['count_ending']} subscriptions ending in 30 days\n"
        f"• {recent['count_declining']} customers declining usage\n"
    )
    return msg


# ═══════════════════════════════════════════════
# ALERT 3: LINKEDIN DETAILED
# ═══════════════════════════════════════════════
def alert_linkedin():
    """LinkedIn alert - shows actual metrics from latest snapshot + post totals."""
    sb = _get_sb()
    if sb is None:
        return ""
    try:
        # Get latest highlight snapshot
        latest_data = sb.table("linkedin_highlights_daily").select("*").order("snapshot_date", desc=True).limit(1).execute().data
        latest = latest_data[0] if latest_data else {}

        # Get ALL posts with their metrics
        posts = sb.table("linkedin_posts").select("title,published_at,impressions,reactions,comments,clicks,ctr,engagement_rate").order("published_at", desc=True).execute().data or []

        # Calculate totals from posts
        total_imp = sum(p.get("impressions", 0) or 0 for p in posts)
        total_react = sum(p.get("reactions", 0) or 0 for p in posts)
        total_comm = sum(p.get("comments", 0) or 0 for p in posts)
        total_clicks = sum(p.get("clicks", 0) or 0 for p in posts)

        # This month posts
        from datetime import date as _d
        this_month = _d.today().strftime("%Y-%m")
        last_month = (_d.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        month_posts = [p for p in posts if str(p.get("published_at","") or "")[:7] == this_month]
        last_month_posts = [p for p in posts if str(p.get("published_at","") or "")[:7] == last_month]

        msg = "\n" + chr(128188) + " <b>LINKEDIN ALERT</b>\n"
        msg += "----------------------------------------\n"
        msg += "Snapshot: <code>" + str(latest.get("snapshot_date","N/A")) + "</code>\n\n"

        msg += "<b>Content Performance (all " + str(len(posts)) + " posts)</b>\n"
        msg += "- Total Impressions: <code>" + "{:,}".format(total_imp) + "</code>\n"
        msg += "- Total Reactions: <code>" + str(total_react) + "</code>\n"
        msg += "- Total Comments: <code>" + str(total_comm) + "</code>\n"
        msg += "- Total Clicks: <code>" + str(total_clicks) + "</code>\n\n"

        msg += "<b>This Month (" + this_month + ")</b>\n"
        msg += "- Posts Published: <code>" + str(len(month_posts)) + "</code>\n"
        month_imp = sum(p.get("impressions",0) or 0 for p in month_posts)
        msg += "- Month Impressions: <code>" + "{:,}".format(month_imp) + "</code>\n\n"

        msg += "<b>Last Month (" + last_month + ")</b>\n"
        msg += "- Posts Published: <code>" + str(len(last_month_posts)) + "</code>\n"
        last_imp = sum(p.get("impressions",0) or 0 for p in last_month_posts)
        msg += "- Month Impressions: <code>" + "{:,}".format(last_imp) + "</code>\n\n"

        msg += "<b>Audience</b>\n"
        msg += "- Followers: <code>" + "{:,}".format(latest.get("total_followers",0)) + "</code>\n"
        msg += "- Page Views: <code>" + "{:,}".format(latest.get("page_views",0)) + "</code>\n"
        msg += "- Unique Visitors: <code>" + "{:,}".format(latest.get("unique_visitors",0)) + "</code>\n"
        msg += "- Newsletter: <code>" + "{:,}".format(latest.get("newsletter_subscribers",0)) + "</code>\n\n"

        if posts:
            msg += "<b>Top 3 Posts (by impressions)</b>\n"
            top = sorted(posts, key=lambda x: x.get("impressions",0) or 0, reverse=True)[:3]
            for p in top:
                title = str(p.get("title",""))[:50]
                imp = p.get("impressions",0) or 0
                msg += "- " + _esc(title) + "... (" + "{:,}".format(imp) + " imp)\n"

        return msg
    except Exception as e:
        return "\n" + chr(128188) + " <b>LINKEDIN</b> Error: " + _esc(str(e))[:200] + "\n"



def alert_stripe():
    sb = _get_sb()
    if sb is None:
        return ""
    try:
        today = date.today().strftime("%Y-%m-%d")
        month_start = date.today().strftime("%Y-%m-01")
        last_month = date.today().replace(day=1) - timedelta(days=1)
        last_month_start = last_month.replace(day=1).strftime("%Y-%m-%d")

        all_paid = sb.table("payments").select("count", count="exact").eq("final_status","ACCEPTED").execute().count or 0
        today_paid = sb.table("payments").select("count", count="exact").eq("final_status","ACCEPTED").gte("first_payment_date", today).execute().count or 0
        month_paid = sb.table("payments").select("count", count="exact").eq("final_status","ACCEPTED").gte("first_payment_date", month_start).execute().count or 0
        last_month_paid = sb.table("payments").select("count", count="exact").eq("final_status","ACCEPTED").gte("first_payment_date", last_month_start).lte("first_payment_date", last_month.strftime("%Y-%m-%d")).execute().count or 0

        # Revenue
        pays = sb.table("payments").select("total_spend,first_payment_date").eq("final_status","ACCEPTED").execute().data or []
        total_rev = sum(float(p.get("total_spend") or 0) for p in pays)
        month_rev = sum(float(p.get("total_spend") or 0) for p in pays if str(p.get("first_payment_date","")).startswith(date.today().strftime("%Y-%m")))

        msg = (
            f"\n💳 <b>STRIPE ALERT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Today: <code>{today_paid}</code> new paid\n"
            f"📆 This Month: <code>{month_paid}</code> (last mo: {last_month_paid})\n"
            f"🏆 All Time: <code>{all_paid}</code> customers\n"
            f"💰 Month Revenue: <code>${month_rev:,.2f}</code>\n"
            f"💎 Total Revenue: <code>${total_rev:,.2f}</code>\n"
            f"📊 Avg Subscription: <code>${total_rev/all_paid if all_paid else 0:,.2f}</code>\n"
        )
        return msg
    except Exception as e:
        return f"\n💳 <b>STRIPE</b> Error: {_esc(str(e))[:200]}\n"


# ═══════════════════════════════════════════════
# ALERT 5: AI INSIGHTS - cross-platform anomalies
# ═══════════════════════════════════════════════
def alert_ai_insights():
    try:
        from ai_assistant_engine import get_full_context
        from ai_assistant_engine import _call_groq
        ctx = get_full_context("all")

        prompt = f"""You are a business analyst. Look at this REAL data and identify the TOP 3 most important things to know about right now.

DATA:
{json.dumps(ctx, indent=2, default=str)[:4000]}

Return exactly 3 short alerts:
1. [Most positive thing]
2. [Most concerning thing]
3. [Most actionable opportunity]

Each alert should be 1-2 sentences max, with specific numbers from the data."""

        ans, err = _call_groq([{"role":"user","content":prompt}], max_tokens=600, temperature=0.2)
        if ans:
            return f"\n🤖 <b>AI INSIGHTS (Top 3)</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{_esc(ans)[:1500]}\n"
    except Exception as e:
        return f"\n🤖 <b>AI INSIGHTS</b> Error: {_esc(str(e))[:200]}\n"
    return ""




# ═══════════════════════════════════════════════
# ALERT 6: YOUTUBE DETAILED
# ═══════════════════════════════════════════════
def alert_youtube():
    """YouTube alert - uses channel data + video list (works without Analytics OAuth)."""
    try:
        yt_data = None
        # Try cached data first
        try:
            from youtube_command_center import get_cached_or_fetch
            yt_data = get_cached_or_fetch(period_days=30)
        except Exception:
            pass
        if not yt_data:
            try:
                import json
                from pathlib import Path as _P
                cache = _P("data_output/youtube_command_center.json")
                if cache.exists():
                    yt_data = json.loads(cache.read_text())
            except Exception:
                pass

        if not yt_data or not yt_data.get("channel"):
            return "\n" + chr(128250) + " <b>YOUTUBE</b> No data\n"

        ch = yt_data.get("channel", {})
        ana = yt_data.get("analytics", {})
        vids = yt_data.get("videos", [])
        rev = yt_data.get("revenue", {})

        total_likes = sum(v.get("likes",0) for v in vids)
        total_comments = sum(v.get("comments",0) for v in vids)
        engagement = ((total_likes+total_comments) / max(ch.get("total_views",1),1)) * 100
        dead_count = sum(1 for v in vids if v.get("views_per_day",0) < 1)

        # Recent videos (last 30 days)
        from datetime import date as _d, timedelta as _td
        cutoff_30 = (_d.today() - _td(days=30)).isoformat()
        recent = [v for v in vids if str(v.get("published_at",""))[:10] >= cutoff_30]

        msg = "\n" + chr(128250) + " <b>YOUTUBE ALERT</b>\n"
        msg += "----------------------------------------\n"
        msg += "Channel: <code>" + _esc(ch.get("title",""))[:40] + "</code>\n\n"

        msg += "<b>Channel Stats</b>\n"
        msg += "- Subscribers: <code>" + "{:,}".format(ch.get("subscribers",0)) + "</code>\n"
        msg += "- Total Views: <code>" + "{:,}".format(ch.get("total_views",0)) + "</code>\n"
        msg += "- Videos: <code>" + str(ch.get("video_count",0)) + "</code>\n"
        msg += "- Engagement: <code>" + str(round(engagement,2)) + "%</code>\n"
        msg += "- Dead Videos: <code>" + str(dead_count) + "</code>\n\n"

        if ana:
            msg += "<b>Last 30 Days (Analytics)</b>\n"
            msg += "- Views: <code>" + "{:,}".format(ana.get("views",0)) + "</code>\n"
            msg += "- Watch Hours: <code>" + str(round(ana.get("watch_hours",0),1)) + "h</code>\n"
            msg += "- Subs Gained: <code>" + str(ana.get("subscribers_gained",0)) + "</code>\n"
            msg += "- Likes: <code>" + str(ana.get("likes",0)) + "</code>\n"
            msg += "- Comments: <code>" + str(ana.get("comments",0)) + "</code>\n\n"
        else:
            msg += "<b>Last 30 Days</b>\n"
            msg += "- Recent uploads: <code>" + str(len(recent)) + "</code> videos\n\n"

        if rev and rev.get("estimated",0) > 0:
            msg += "<b>Revenue</b>\n"
            msg += "- Estimated: <code>$" + "{:,.2f}".format(rev.get("estimated",0)) + "</code>\n\n"

        # Top 3 videos
        if vids:
            top3 = sorted(vids, key=lambda v: v.get("views",0), reverse=True)[:3]
            msg += "<b>Top 3 Videos</b>\n"
            for v in top3:
                msg += "- " + _esc(str(v.get("title",""))[:50]) + " (" + "{:,}".format(v.get("views",0)) + "v)\n"

        return msg
    except Exception as e:
        return "\n" + chr(128250) + " <b>YOUTUBE</b> Error: " + _esc(str(e))[:200] + "\n"



def alert_ga4():
    """Show daily deltas - what NEW today, this week, this month."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Dimension, Metric
        import json as _json
        SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
        creds = None
        try:
            import streamlit as st
            sa = dict(st.secrets["ga4_service_account"])
            if "private_key" in sa:
                sa["private_key"] = sa["private_key"].replace("\\n","\n")
            creds = service_account.Credentials.from_service_account_info(sa, scopes=SCOPES)
        except Exception:
            pass
        if not creds and os.path.exists("google_creds.json"):
            try:
                creds = service_account.Credentials.from_service_account_file("google_creds.json", scopes=SCOPES)
            except Exception:
                pass
        if not creds:
            gc = os.environ.get("GOOGLE_CREDS_JSON","")
            if gc:
                try:
                    sa = _json.loads(gc)
                    if "private_key" in sa:
                        sa["private_key"] = sa["private_key"].replace("\\n","\n")
                    creds = service_account.Credentials.from_service_account_info(sa, scopes=SCOPES)
                except Exception:
                    pass
        if not creds:
            return "\n" + chr(127760) + " <b>GA4</b> No credentials\n"

        pid = os.environ.get("GA4_PROPERTY_ID","374525971")
        try:
            import streamlit as st
            pid = str(st.secrets.get("GA4_PROPERTY_ID", pid)).strip()
        except Exception:
            pass

        client = BetaAnalyticsDataClient(credentials=creds)
        today_dt = date.today()
        today = today_dt.strftime("%Y-%m-%d")
        yest = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        week_ago = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        prev_week_ago = (today_dt - timedelta(days=14)).strftime("%Y-%m-%d")
        month_ago = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        prev_month_ago = (today_dt - timedelta(days=60)).strftime("%Y-%m-%d")

        def q(start, end):
            try:
                r = client.run_report(RunReportRequest(
                    property=f"properties/{pid}",
                    date_ranges=[DateRange(start_date=start, end_date=end)],
                    metrics=[Metric(name="sessions"), Metric(name="totalUsers"), Metric(name="screenPageViews")],
                ))
                if r.rows:
                    row = r.rows[0]
                    return (int(row.metric_values[0].value), int(row.metric_values[1].value), int(row.metric_values[2].value))
            except Exception:
                pass
            return (0, 0, 0)

        # Period values
        t_s, t_u, t_p = q(today, today)
        y_s, y_u, y_p = q(yest, yest)
        w_s, w_u, w_p = q(week_ago, today)
        pw_s, pw_u, pw_p = q(prev_week_ago, week_ago)
        m_s, m_u, m_p = q(month_ago, today)
        pm_s, pm_u, pm_p = q(prev_month_ago, month_ago)

        # If today is 0 (GA4 delay), use yesterday as today
        if t_s == 0:
            t_s, t_u, t_p = y_s, y_u, y_p
            today_label = "Yesterday (GA4 delay)"
        else:
            today_label = "Today"

        # Deltas
        def fmt_d(v, p):
            if p == 0:
                return ("+" + str(v)) if v > 0 else str(v)
            d = v - p
            pct = (d/p*100) if p else 0
            sign = "+" if d >= 0 else ""
            return sign + str(d) + " (" + sign + str(round(pct)) + "%)"

        # Top countries last 30d
        try:
            rc = client.run_report(RunReportRequest(
                property=f"properties/{pid}",
                date_ranges=[DateRange(start_date=month_ago, end_date=today)],
                dimensions=[Dimension(name="country")],
                metrics=[Metric(name="sessions")],
                limit=5,
            ))
            countries = [(rw.dimension_values[0].value, int(rw.metric_values[0].value)) for rw in rc.rows]
        except Exception:
            countries = []

        msg = "\n" + chr(127760) + " <b>GA4 ALERT</b>\n"
        msg += "----------------------------------------\n"
        msg += "<b>" + today_label + " (vs yesterday)</b>\n"
        msg += "- Users:      <code>" + str(t_u) + "</code> " + fmt_d(t_u, y_u) + "\n"
        msg += "- Sessions:   <code>" + str(t_s) + "</code> " + fmt_d(t_s, y_s) + "\n"
        msg += "- Page Views: <code>" + str(t_p) + "</code> " + fmt_d(t_p, y_p) + "\n\n"

        msg += "<b>Last 7 Days (vs previous 7d)</b>\n"
        msg += "- Users:      <code>" + str(w_u) + "</code> " + fmt_d(w_u, pw_u) + "\n"
        msg += "- Sessions:   <code>" + str(w_s) + "</code> " + fmt_d(w_s, pw_s) + "\n"
        msg += "- Page Views: <code>" + str(w_p) + "</code> " + fmt_d(w_p, pw_p) + "\n\n"

        msg += "<b>Last 30 Days (vs previous 30d)</b>\n"
        msg += "- Users:      <code>" + str(m_u) + "</code> " + fmt_d(m_u, pm_u) + "\n"
        msg += "- Sessions:   <code>" + str(m_s) + "</code> " + fmt_d(m_s, pm_s) + "\n"
        msg += "- Page Views: <code>" + str(m_p) + "</code> " + fmt_d(m_p, pm_p) + "\n\n"

        msg += "<b>Top 5 Countries (30d)</b>\n"
        for country, sess in countries:
            msg += "- " + _esc(country) + ": <code>" + "{:,}".format(sess) + "</code>\n"
        return msg
    except Exception as e:
        return "\n" + chr(127760) + " <b>GA4</b> Error: " + _esc(str(e))[:200] + "\n"



def alert_cross_platform():
    """Cross-platform correlation - daily deltas across all systems."""
    sb = _get_sb()
    if sb is None:
        return ""
    try:
        today_dt = date.today()
        today = today_dt.strftime("%Y-%m-%d")
        yest = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        week_ago = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")

        # KPI today vs yesterday
        s_t = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",today).execute().count or 0
        s_y = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",yest).lte("signup_date",yest).execute().count or 0
        s_w = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",week_ago).execute().count or 0

        p_t = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",today).execute().count or 0
        p_y = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",yest).lte("first_payment_date",yest).execute().count or 0
        p_w = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",week_ago).execute().count or 0

        u_t = sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",today).execute().count or 0
        u_y = sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",yest).lte("upload_date",yest).execute().count or 0

        # LinkedIn deltas
        li_today = sb.table("linkedin_highlights_daily").select("*").eq("snapshot_date", today).limit(1).execute().data or []
        li_yest = sb.table("linkedin_highlights_daily").select("*").eq("snapshot_date", yest).limit(1).execute().data or []
        li_imp_today = li_today[0].get("impressions",0) if li_today else 0
        li_imp_yest = li_yest[0].get("impressions",0) if li_yest else 0
        li_imp_delta = li_imp_today - li_imp_yest if li_yest else 0
        li_followers = (li_today[0] if li_today else (li_yest[0] if li_yest else {})).get("total_followers",0)

        # Patterns detection
        patterns = []
        if s_t == 0 and li_imp_today > 100:
            patterns.append("- LinkedIn has impressions today but ZERO signups - landing page issue?")
        if s_t > 5 and p_t == 0:
            patterns.append("- " + str(s_t) + " signups today but 0 paid - check upgrade flow")
        if li_followers > 2500 and s_t < 3:
            patterns.append("- " + "{:,}".format(li_followers) + " LinkedIn followers but only " + str(s_t) + " signups today - audience mismatch")
        if p_t > p_y * 2 and p_y > 0:
            patterns.append("- Paid customers SPIKED today (" + str(p_t) + " vs " + str(p_y) + " yesterday)")
        if not patterns:
            patterns.append("- No critical cross-platform issues detected today")

        def fmt_d(v, p):
            if p == 0:
                return ("+" + str(v)) if v > 0 else str(v)
            d = v - p
            sign = "+" if d >= 0 else ""
            return sign + str(d)

        msg = "\n" + chr(128279) + " <b>CROSS-PLATFORM CORRELATION</b>\n"
        msg += "----------------------------------------\n\n"

        msg += "<b>Today vs Yesterday</b>\n"
        msg += "- Signups:   <code>" + str(s_t) + "</code> " + fmt_d(s_t, s_y) + "\n"
        msg += "- Uploads:   <code>" + str(u_t) + "</code> " + fmt_d(u_t, u_y) + "\n"
        msg += "- Paid:      <code>" + str(p_t) + "</code> " + fmt_d(p_t, p_y) + "\n"
        msg += "- LI Impressions: " + fmt_d(li_imp_delta, 0) + "\n\n"

        msg += "<b>Last 7 Days Total</b>\n"
        msg += "- Signups: <code>" + str(s_w) + "</code>\n"
        msg += "- Paid:    <code>" + str(p_w) + "</code>\n\n"

        msg += "<b>Pattern Detection</b>\n"
        for p in patterns:
            msg += p + "\n"
        msg += "\n<b>System Health</b>\n"
        msg += "- KPI: " + ("[OK]" if s_t > 0 else "[!]") + " " + str(s_t) + " signups today\n"
        msg += "- LinkedIn: " + ("[OK]" if li_imp_today > 100 else "[!]") + " " + "{:,}".format(li_imp_today) + " impressions\n"
        msg += "- Stripe: " + ("[OK]" if p_t > 0 else "[!]") + " " + str(p_t) + " paid today\n"
        return msg
    except Exception as e:
        return "\n" + chr(128279) + " <b>CROSS-PLATFORM</b> Error: " + _esc(str(e))[:200] + "\n"



def send_all_alerts():
    print("Building comprehensive alerts...")
    today = date.today().strftime("%Y-%m-%d")

    header = f"🦅 <b>EAGLE3D COMPREHENSIVE ALERT — {today}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"

    parts = []
    print("  Building KPI...")
    parts.append(alert_kpi_detailed())
    print("  Building GA4...")
    parts.append(alert_ga4())
    print("  Building YouTube...")
    parts.append(alert_youtube())
    print("  Building LinkedIn...")
    parts.append(alert_linkedin())
    print("  Building Stripe...")
    parts.append(alert_stripe())
    print("  Building Customer Success...")
    parts.append(alert_customer_success())
    print("  Building Cross-Platform...")
    parts.append(alert_cross_platform())
    print("  Building AI insights...")
    parts.append(alert_ai_insights())

    footer = (
        f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <a href=\"https://eagle3d-kpi-automation.streamlit.app/\">Open Dashboard</a>\n"
        f"<i>Sent at {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</i>"
    )

    # Send each part separately with delay to avoid Telegram rate limit
    import time as _time
    sent = 0
    for idx, p in enumerate(parts):
        if p and p.strip():
            print(f"  Sending section {idx+1}/{len(parts)} ({len(p)} chars)...")
            if _send_telegram(p):
                sent += 1
                print(f"    SENT")
            else:
                print(f"    FAILED")
            _time.sleep(4)  # Conservative delay - Telegram bot 1msg/sec per chat

    if footer:
        _time.sleep(2)
        _send_telegram(footer)

    print(f"Sent {sent}/{len(parts)} alert sections")
    return sent


if __name__ == "__main__":
    send_all_alerts()
