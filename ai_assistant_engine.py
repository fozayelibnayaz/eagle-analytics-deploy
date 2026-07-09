#!/usr/bin/env python3
"""

AI Assistant Engine - Multi-platform, multi-model, with memory
Reads REAL data from MongoDB for accurate grounded answers.
Supports Groq (primary) + Gemini (fallback).
Conversation history stored in MongoDB for memory persistence.
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


import os
import re
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, date

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





def _get_sb():
    return get_db()


def _get_groq_key():
    v = os.environ.get("GROQ_API_KEY", "")
    if not v:
        try:
            import streamlit as st
            v = str(st.secrets.get("GROQ_API_KEY", "")).strip()
        except Exception:
            pass
    return v


def _get_gemini_key():
    v = os.environ.get("GEMINI_API_KEY", "")
    if not v:
        try:
            import streamlit as st
            v = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
        except Exception:
            pass
    return v


# ═════════════════════════════════════════════════
# CONTEXT BUILDERS - per platform
# ═════════════════════════════════════════════════

def context_kpi():
    sb = _get_sb()
    if sb is None:
        return {}
    ctx = {}
    try:
        today = date.today().strftime("%Y-%m-%d")
        month_start = date.today().strftime("%Y-%m-01")
        upload_start = "2025-12-01"
        ur = sb.table("uploads").select("upload_date").eq("final_status","ACCEPTED").order("upload_date").limit(1).execute()
        if ur.data and ur.data[0].get("upload_date"):
            upload_start = str(ur.data[0]["upload_date"])[:10]

        ctx["today"] = today
        ctx["common_period_start"] = upload_start
        ctx["today_signups"]  = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",today).execute().count or 0
        ctx["today_uploads"]  = sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",today).execute().count or 0
        ctx["today_paid"]     = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",today).execute().count or 0
        ctx["month_signups"]  = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",month_start).execute().count or 0
        ctx["month_uploads"]  = sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",month_start).execute().count or 0
        ctx["month_paid"]     = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",month_start).execute().count or 0
        ctx["alltime_signups"] = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",upload_start).execute().count or 0
        ctx["alltime_uploads"] = sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",upload_start).execute().count or 0
        ctx["alltime_paid"]    = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",upload_start).execute().count or 0
        # Revenue
        pays = sb.table("payments").select("total_spend,first_payment_date").eq("final_status","ACCEPTED").execute().data or []
        ctx["total_revenue"] = round(sum(float(p.get("total_spend") or 0) for p in pays), 2)
        ctx["paying_customers"] = len([p for p in pays if (p.get("total_spend") or 0) > 0])
        if ctx["paying_customers"]:
            ctx["avg_subscription"] = round(ctx["total_revenue"] / ctx["paying_customers"], 2)
        # Conversion
        if ctx["alltime_signups"]:
            ctx["s2u_rate"] = round(ctx["alltime_uploads"] / ctx["alltime_signups"] * 100, 2)
            ctx["s2p_rate"] = round(ctx["alltime_paid"]    / ctx["alltime_signups"] * 100, 2)
        # Top lead sources
        signups_data = sb.table("signups").select("lead_source").eq("final_status","ACCEPTED").execute().data or []
        from collections import Counter
        sources = Counter(s.get("lead_source","") for s in signups_data if s.get("lead_source"))
        ctx["top_lead_sources"] = sources.most_common(10)
    except Exception as e:
        ctx["error"] = str(e)
    return ctx


def context_linkedin():
    sb = _get_sb()
    if sb is None:
        return {}
    ctx = {}
    try:
        hl = sb.table("linkedin_highlights_daily").select("*").order("snapshot_date",desc=True).limit(1).execute().data
        if hl:
            ctx["latest"] = hl[0]
        posts = sb.table("linkedin_posts").select("*").order("impressions",desc=True).limit(20).execute().data or []
        ctx["top_posts"] = [
            {"title": p.get("title","")[:200], "impressions": p.get("impressions",0),
             "reactions": p.get("reactions",0), "comments": p.get("comments",0),
             "clicks": p.get("clicks",0), "ctr": p.get("ctr",0),
             "engagement_rate": p.get("engagement_rate",0)}
            for p in posts
        ]
        ctx["total_posts_tracked"] = sb.table("linkedin_posts").select("count",count="exact").execute().count or 0
        fd = sb.table("linkedin_followers_daily").select("snapshot_date,total,delta_total").order("snapshot_date").execute().data or []
        ctx["follower_history"] = fd[-30:]
        comps = sb.table("linkedin_competitors_daily").select("*").order("snapshot_date",desc=True).limit(10).execute().data or []
        ctx["competitors"] = comps
    except Exception as e:
        ctx["error"] = str(e)
    return ctx


def context_youtube():
    ctx = {}
    try:
        from youtube_command_center import get_cached_or_fetch
        d = get_cached_or_fetch(period_days=90)
        ctx["channel"]   = d.get("channel", {})
        ctx["analytics"] = d.get("analytics", {})
        ctx["revenue"]   = d.get("revenue", {})
        vids = d.get("videos", [])
        ctx["total_videos"] = len(vids)
        ctx["top_5_videos"] = sorted(vids, key=lambda v: v.get("views",0), reverse=True)[:5]
        ctx["bottom_5_videos"] = sorted([v for v in vids if v.get("views",0)>0], key=lambda v: v.get("views",0))[:5]
        # Engagement breakdown
        ctx["avg_engagement"] = round(sum(v.get("engagement",0) for v in vids) / len(vids), 2) if vids else 0
        ctx["total_views_all"] = sum(v.get("views",0) for v in vids)
        ctx["videos_with_no_views"] = len([v for v in vids if v.get("views",0)==0])
    except Exception as e:
        ctx["error"] = str(e)
    return ctx


def context_ga4():
    ctx = {}
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Dimension, Metric
        creds = None
        try:
            import streamlit as st
            sa = dict(st.secrets["ga4_service_account"])
            if "private_key" in sa:
                sa["private_key"] = sa["private_key"].replace("\\n", "\n")
            creds = service_account.Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        except Exception:
            pass
        if not creds:
            return {"error": "GA4 credentials missing"}

        pid = os.environ.get("GA4_PROPERTY_ID","374525971")
        try:
            import streamlit as st
            pid = str(st.secrets.get("GA4_PROPERTY_ID", pid))
        except Exception:
            pass
        client = BetaAnalyticsDataClient(credentials=creds)
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        r = client.run_report(RunReportRequest(
            property=f"properties/{pid}",
            date_ranges=[DateRange(start_date=start, end_date=end)],
            metrics=[Metric(name="sessions"), Metric(name="totalUsers"), Metric(name="screenPageViews")],
        ))
        if r.rows:
            row = r.rows[0]
            ctx["last_30d_sessions"]  = int(row.metric_values[0].value)
            ctx["last_30d_users"]     = int(row.metric_values[1].value)
            ctx["last_30d_pageviews"] = int(row.metric_values[2].value)

        # Top countries
        rc = client.run_report(RunReportRequest(
            property=f"properties/{pid}",
            date_ranges=[DateRange(start_date=start, end_date=end)],
            dimensions=[Dimension(name="country")],
            metrics=[Metric(name="sessions")],
            limit=10,
        ))
        ctx["top_countries"] = [(rw.dimension_values[0].value, int(rw.metric_values[0].value)) for rw in rc.rows]
    except Exception as e:
        ctx["error"] = str(e)
    return ctx


def context_customer_success():
    sb = _get_sb()
    if sb is None:
        return {}
    ctx = {}
    try:
        ctx["total_in_cs_sheet"] = sb.table("customer_success_master").select("count",count="exact").execute().count or 0
        ctx["enriched"] = sb.table("customer_success_enriched").select("count",count="exact").execute().count or 0
        ctx["active_subs"] = sb.table("customer_success_enriched").select("count",count="exact").eq("subscription_status","active").execute().count or 0
        ctx["canceled"] = sb.table("customer_success_enriched").select("count",count="exact").eq("subscription_status","canceled").execute().count or 0
        ctx["delinquent"] = sb.table("customer_success_enriched").select("count",count="exact").eq("stripe_delinquent",True).execute().count or 0
        # Funnel
        funnel = sb.table("customer_success_enriched").select("signup_date,first_upload_date,first_payment_date,days_signup_to_paid").execute().data or []
        with_signup = sum(1 for f in funnel if f.get("signup_date"))
        with_upload = sum(1 for f in funnel if f.get("first_upload_date"))
        with_paid = sum(1 for f in funnel if f.get("first_payment_date"))
        ctx["funnel"] = {"signed_up": with_signup, "uploaded": with_upload, "paid": with_paid}
        days = [f["days_signup_to_paid"] for f in funnel if f.get("days_signup_to_paid")]
        if days:
            ctx["avg_days_to_paid"] = round(sum(days)/len(days), 1)
    except Exception as e:
        ctx["error"] = str(e)
    return ctx


def get_full_context(platform="all"):
    if platform == "kpi":
        return {"kpi": context_kpi()}
    if platform == "linkedin":
        return {"linkedin": context_linkedin()}
    if platform == "youtube":
        return {"youtube": context_youtube()}
    if platform == "ga4":
        return {"ga4": context_ga4()}
    if platform == "customer_success":
        return {"customer_success": context_customer_success()}
    return {
        "kpi":               context_kpi(),
        "linkedin":          context_linkedin(),
        "youtube":           context_youtube(),
        "ga4":               context_ga4(),
        "customer_success":  context_customer_success(),
    }


# ═════════════════════════════════════════════════
# AI CALL with memory
# ═════════════════════════════════════════════════

def _call_groq(messages, max_tokens=2000, temperature=0.2):
    key = _get_groq_key()
    if not key:
        return None, "GROQ_API_KEY not set"
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps({
                "model":    "llama-3.3-70b-versatile",
                "messages": messages,
                "max_tokens":  max_tokens,
                "temperature": temperature,
            }).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
                "User-Agent":    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept":        "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            r = json.loads(resp.read())
            return r["choices"][0]["message"]["content"], None
    except urllib.error.HTTPError as e:
        return None, f"Groq {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return None, f"Groq error: {e}"


def _call_gemini(messages, max_tokens=2000, temperature=0.2):
    key = _get_gemini_key()
    if not key:
        return None, "GEMINI_API_KEY not set"
    try:
        # Convert OpenAI-style to Gemini contents
        contents = []
        for m in messages:
            role = "user" if m["role"] in ("user","system") else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        req = urllib.request.Request(
            url,
            data=json.dumps({
                "contents": contents,
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
            }).encode(),
            headers={"Content-Type":"application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            r = json.loads(resp.read())
            return r["candidates"][0]["content"]["parts"][0]["text"], None
    except Exception as e:
        return None, f"Gemini error: {e}"


def ask_ai(question: str, platform: str = "all", history: list = None, user_email: str = "anonymous"):
    """
    Ask AI a question with platform context + conversation history.
    Returns dict: {answer, source, error, context_used, history}
    """
    history = history or []
    context = get_full_context(platform)

    system_prompt = f"""You are the Eagle3D KPI Hub AI Assistant, an expert business intelligence analyst.

You have access to REAL data from the Eagle3D Streaming business across these systems:
- KPI: signups, uploads, paid customers, conversion rates, revenue
- LinkedIn: posts, impressions, reactions, followers, competitors
- YouTube: channel stats, video performance, analytics
- GA4: website sessions, users, page views, countries
- Customer Success: customer health, churn, lifetime, funnel

CURRENT DATA CONTEXT (use this for ALL answers):
{json.dumps(context, indent=2, default=str)[:8000]}

RULES:
1. Use ONLY the data provided above. Never make up numbers.
2. If asked about something not in the data, say "I don't have that data yet"
3. Quote specific numbers from context when answering
4. Be concise but thorough
5. Format with headers, bullets, and bold for readability
6. Always include actionable insights
7. Remember previous conversation context

Today's date: {date.today().isoformat()}
User: {user_email}
Platform focus: {platform}"""

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})

    # Try Groq first
    answer, err = _call_groq(messages, max_tokens=2500)
    if answer:
        _save_conversation(user_email, platform, question, answer, "groq")
        return {"answer": answer, "source": "Groq llama-3.3-70b", "error": None, "context_used": bool(context)}

    # Fallback Gemini
    answer, err2 = _call_gemini(messages, max_tokens=2500)
    if answer:
        _save_conversation(user_email, platform, question, answer, "gemini")
        return {"answer": answer, "source": "Gemini 1.5", "error": None, "context_used": bool(context)}

    return {"answer": None, "source": None, "error": f"Both failed: Groq={err} | Gemini={err2}"}


def _save_conversation(user_email, platform, question, answer, model):
    sb = _get_sb()
    if sb is None:
        return
    try:
        sb.table("ai_conversations").insert({
            "user_email":  user_email,
            "platform":    platform,
            "question":    question,
            "answer":      answer,
            "model_used":  model,
            "created_at":  datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass


def get_history(user_email, platform=None, limit=50):
    sb = _get_sb()
    if sb is None:
        return []
    try:
        q = sb.table("ai_conversations").select("*").eq("user_email", user_email)
        if platform:
            q = q.eq("platform", platform)
        q = q.order("created_at", desc=True).limit(limit)
        return q.execute().data or []
    except Exception:
        return []


# ═════════════════════════════════════════════════
# AI POWER TOOLS (specialized prompts)
# ═════════════════════════════════════════════════

TOOLS = {
    "youtube": [
        {"id":"content_strategy",     "name":"Content Strategy",       "desc":"90-day strategy from YOUR data", "icon":"🎯"},
        {"id":"title_optimizer",      "name":"Title Optimizer",        "desc":"Rewrite for max CTR",            "icon":"✨", "input":"current title"},
        {"id":"viral_detector",       "name":"Viral Pattern Detector", "desc":"Replicate viral success",        "icon":"⚡"},
        {"id":"30day_plan",           "name":"30-Day Plan",            "desc":"Actionable daily plan",          "icon":"💡"},
        {"id":"tag_optimizer",        "name":"Tag Optimizer",          "desc":"Generate optimal SEO tags",      "icon":"🏷️", "input":"video topic"},
        {"id":"hook_gen",             "name":"Hook Generator",         "desc":"First 15s hooks",                "icon":"🎤", "input":"video topic"},
        {"id":"chapters",             "name":"Auto Chapters",          "desc":"Timestamp chapters",             "icon":"📋", "input":"video URL or transcript"},
        {"id":"smart_reply",          "name":"Smart Reply",            "desc":"Reply to comments",              "icon":"↩️", "input":"comment text"},
        {"id":"keyword_finder",       "name":"Keyword Finder",         "desc":"Low-comp keywords",              "icon":"🔑", "input":"topic"},
        {"id":"collab_finder",        "name":"Collab Finder",          "desc":"Channels to collab with",        "icon":"🤝"},
        {"id":"competitive_gap",      "name":"Competitive Gap",        "desc":"Find content opportunities",     "icon":"📊", "input":"competitor channel"},
        {"id":"upload_schedule",      "name":"Upload Schedule",        "desc":"Data-driven schedule",           "icon":"📅"},
        {"id":"comment_insights",     "name":"Comment Insights",       "desc":"Ideas from comments",            "icon":"💬"},
        {"id":"video_clone",          "name":"Video Clone Blueprint",  "desc":"Replicate top videos",           "icon":"📝", "input":"video title"},
        {"id":"swot",                 "name":"SWOT Analysis",          "desc":"Strengths Weaknesses Ops",       "icon":"🧭"},
        {"id":"script_writer",        "name":"Full Script Writer",     "desc":"Complete video scripts",         "icon":"🎬", "input":"video topic"},
        {"id":"sponsor_pitch",        "name":"Sponsor Pitch",          "desc":"Brand outreach emails",          "icon":"📧", "input":"brand name"},
        {"id":"cta_gen",              "name":"CTA Generator",          "desc":"Convert viewers to subs",        "icon":"🖱️", "input":"video topic"},
        {"id":"channel_audit",        "name":"Full Channel Audit",     "desc":"Complete A-F review",            "icon":"✅"},
        {"id":"niche_analyzer",       "name":"Niche Analyzer",         "desc":"Niche saturation",               "icon":"🧩", "input":"niche"},
        {"id":"thumbnail_audit",      "name":"Thumbnail Audit",        "desc":"What thumbnails work",           "icon":"🖼️"},
        {"id":"audience_persona",     "name":"Audience Persona",       "desc":"Who your viewers are",           "icon":"👥"},
        {"id":"weekly_report",        "name":"Weekly Report",          "desc":"Executive-ready report",         "icon":"📋"},
        {"id":"description_writer",   "name":"Description Writer",     "desc":"SEO-optimized descriptions",     "icon":"📖", "input":"video topic"},
        {"id":"ab_test",              "name":"A/B Test Planner",       "desc":"Plan title/thumbnail tests",     "icon":"🔀", "input":"video URL"},
        {"id":"shorts_ideas",         "name":"Shorts Ideas",           "desc":"Viral shorts from videos",       "icon":"✂️"},
        {"id":"community_posts",      "name":"Community Posts",        "desc":"High-engagement posts",          "icon":"📢"},
        {"id":"trend_radar",          "name":"Trend Radar",            "desc":"Trending topics now",            "icon":"📡", "input":"niche"},
        {"id":"revenue_forecast",     "name":"Revenue Forecast",       "desc":"Predict earnings",               "icon":"💰"},
        {"id":"algo_decoder",         "name":"Algorithm Decoder",      "desc":"What YT favors now",             "icon":"🤖"},
    ],

    "kpi": [
        {"id":"signup_strategy",      "name":"Signup Growth Strategy", "desc":"Plan to 2x signups",             "icon":"📈"},
        {"id":"funnel_audit",         "name":"Funnel Audit",           "desc":"Where users drop off",           "icon":"🔬"},
        {"id":"conversion_optimizer", "name":"Conversion Optimizer",   "desc":"Increase Sign->Paid rate",       "icon":"🎯"},
        {"id":"revenue_forecast",     "name":"Revenue Forecast",       "desc":"Predict next quarter",           "icon":"💰"},
        {"id":"lead_source_audit",    "name":"Lead Source Audit",      "desc":"Best vs worst channels",         "icon":"📊"},
        {"id":"region_strategy",      "name":"Region Expansion",       "desc":"Where to invest geographically", "icon":"🌍"},
        {"id":"month_forecast",       "name":"Month Forecast",         "desc":"End-of-month predictions",       "icon":"📅"},
        {"id":"churn_prevention",     "name":"Churn Prevention Plan",  "desc":"Reduce subscription losses",     "icon":"🛡️"},
        {"id":"signup_velocity",      "name":"Signup Velocity",        "desc":"Growth rate analysis",           "icon":"⚡"},
        {"id":"upload_funnel",        "name":"Upload Funnel",          "desc":"Why uploads lag signups",        "icon":"📤"},
        {"id":"paid_predictor",       "name":"Paid Predictor",         "desc":"Predict who will pay",           "icon":"💳"},
        {"id":"daily_action",         "name":"Daily Action Plan",      "desc":"What to do today",               "icon":"☀️"},
        {"id":"weekly_action",        "name":"Weekly Action Plan",     "desc":"7-day execution plan",           "icon":"📆"},
        {"id":"monthly_strategy",     "name":"Monthly Strategy",       "desc":"30-day strategic plan",          "icon":"🗓️"},
        {"id":"q_strategy",           "name":"Quarterly Strategy",     "desc":"90-day OKRs",                    "icon":"🎯"},
        {"id":"competitor_bench",     "name":"Competitor Benchmark",   "desc":"How you compare", "icon":"⚖️",   "input":"competitor name"},
        {"id":"price_strategy",       "name":"Price Strategy",         "desc":"Optimize pricing tiers",         "icon":"💲"},
        {"id":"retention_strategy",   "name":"Retention Strategy",     "desc":"Keep paying customers",          "icon":"🔒"},
        {"id":"reactivation",         "name":"Reactivation Campaign",  "desc":"Win back churned users",         "icon":"♻️"},
        {"id":"signup_alert",         "name":"Signup Alert Setup",     "desc":"Configure smart alerts",         "icon":"🔔"},
        {"id":"kpi_report_exec",      "name":"Executive Report",       "desc":"Board-ready KPI report",         "icon":"📋"},
        {"id":"weekly_kpi_summary",   "name":"Weekly KPI Summary",     "desc":"Slack-ready Friday digest",      "icon":"��"},
        {"id":"data_anomaly",         "name":"Data Anomaly Scan",      "desc":"Detect unusual patterns",        "icon":"🚨"},
        {"id":"cohort_analysis",      "name":"Cohort Analysis",        "desc":"Compare signup cohorts",         "icon":"👥"},
        {"id":"ltv_calculator",       "name":"LTV Calculator",         "desc":"Customer lifetime value",        "icon":"💎"},
        {"id":"cac_estimator",        "name":"CAC Estimator",          "desc":"Cost to acquire customer",       "icon":"🎯"},
        {"id":"ltv_cac_ratio",        "name":"LTV:CAC Ratio",          "desc":"Unit economics check",           "icon":"📐"},
        {"id":"growth_loops",         "name":"Growth Loops Audit",     "desc":"Find scalable growth",           "icon":"🔄"},
        {"id":"red_flags",            "name":"Red Flags Scanner",      "desc":"What needs immediate fix",       "icon":"🚩"},
        {"id":"kpi_ai_qa",            "name":"Custom KPI Q&A",         "desc":"Ask anything specific",          "icon":"💬", "input":"your question"},
    ],

    "linkedin": [
        {"id":"post_strategy",        "name":"Post Strategy",          "desc":"What to post next",              "icon":"📝"},
        {"id":"top_post_replicate",   "name":"Top Post Replicator",    "desc":"Replicate viral posts",          "icon":"⚡"},
        {"id":"follower_growth",      "name":"Follower Growth Plan",   "desc":"Hit next milestone",             "icon":"📈"},
        {"id":"competitor_steal",     "name":"Competitor Tactics",     "desc":"What competitors do well",       "icon":"🕵️"},
        {"id":"engagement_audit",     "name":"Engagement Audit",       "desc":"Why posts under-perform",        "icon":"🔍"},
        {"id":"content_calendar",     "name":"30-Day Calendar",        "desc":"Daily post plan",                "icon":"📅"},
        {"id":"hashtag_strategy",     "name":"Hashtag Strategy",       "desc":"Best tags for reach",            "icon":"#️⃣", "input":"topic"},
        {"id":"thought_leadership",   "name":"Thought Leadership",     "desc":"Position founder as expert",     "icon":"🎓"},
        {"id":"hook_writer_li",       "name":"LinkedIn Hook Writer",   "desc":"First-line scrollers",           "icon":"🪝", "input":"topic"},
        {"id":"post_writer",          "name":"Post Writer",            "desc":"Full LinkedIn post",             "icon":"✍️", "input":"topic"},
        {"id":"carousel_ideas",       "name":"Carousel Ideas",         "desc":"10-slide carousel topics",       "icon":"🎠"},
        {"id":"comment_engagement",   "name":"Comment Engagement",     "desc":"Reply strategy",                 "icon":"💬"},
        {"id":"connection_outreach",  "name":"Connection Outreach",    "desc":"DM template",                    "icon":"🤝", "input":"target persona"},
        {"id":"lead_magnet",          "name":"Lead Magnet Ideas",      "desc":"Free content to grow",           "icon":"🧲"},
        {"id":"company_page_audit",   "name":"Company Page Audit",     "desc":"Improve profile",                "icon":"🏢"},
        {"id":"newsletter_strategy",  "name":"Newsletter Strategy",    "desc":"Grow subscribers",               "icon":"📰"},
        {"id":"article_ideas",        "name":"Article Ideas",          "desc":"Long-form article topics",       "icon":"📰"},
        {"id":"video_post_ideas",     "name":"Video Post Ideas",       "desc":"Native video topics",            "icon":"🎬"},
        {"id":"poll_ideas",           "name":"Poll Ideas",             "desc":"Engagement polls",               "icon":"📊"},
        {"id":"event_promo",          "name":"Event Promotion",        "desc":"Promote event/webinar",          "icon":"📢", "input":"event name"},
        {"id":"employee_advocacy",    "name":"Employee Advocacy",      "desc":"Get team to share",              "icon":"👥"},
        {"id":"competitor_analysis",  "name":"Competitor Analysis",    "desc":"Deep dive competitor",           "icon":"🎯", "input":"competitor URL"},
        {"id":"viral_topics",         "name":"Viral Topics Now",       "desc":"Trending in your niche",         "icon":"🔥"},
        {"id":"post_time_optimizer",  "name":"Post Time Optimizer",    "desc":"Best hours to post",             "icon":"⏰"},
        {"id":"li_ad_ideas",          "name":"LinkedIn Ad Ideas",      "desc":"Paid ad copy",                   "icon":"💸"},
        {"id":"sales_navigator_tips", "name":"Sales Nav Tips",         "desc":"Use Sales Navigator",            "icon":"🎯"},
        {"id":"linkedin_seo",         "name":"LinkedIn SEO",           "desc":"Profile SEO optimization",       "icon":"🔍"},
        {"id":"linkedin_audit",       "name":"Full LinkedIn Audit",    "desc":"A-F company page review",        "icon":"✅"},
        {"id":"weekly_li_report",     "name":"Weekly LI Report",       "desc":"Executive summary",              "icon":"📋"},
        {"id":"li_ai_qa",             "name":"Custom LinkedIn Q&A",    "desc":"Ask anything",                   "icon":"💬", "input":"your question"},
    ],

    "customer_success": [
        {"id":"churn_predict",        "name":"Churn Prediction",       "desc":"Who's about to leave",           "icon":"🔮"},
        {"id":"upsell_targets",       "name":"Upsell Targets",         "desc":"Best customers for upgrade",     "icon":"📈"},
        {"id":"at_risk_action",       "name":"At-Risk Action Plan",    "desc":"Save customers at risk",         "icon":"��"},
        {"id":"onboarding_audit",     "name":"Onboarding Audit",       "desc":"Why signups don't convert",      "icon":"🚀"},
        {"id":"customer_segments",    "name":"Customer Segments",      "desc":"Group by behavior",              "icon":"🧩"},
        {"id":"win_back_canceled",    "name":"Win-Back Campaign",      "desc":"Re-engage canceled users",       "icon":"♻️"},
        {"id":"dormant_alert",        "name":"Dormant User Alert",     "desc":"Paying but not using",           "icon":"😴"},
        {"id":"power_users",          "name":"Power User Profile",     "desc":"Identify and learn",             "icon":"💪"},
        {"id":"plan_recommend",       "name":"Plan Recommender",       "desc":"Right plan per customer",        "icon":"🎯"},
        {"id":"renewal_pitch",        "name":"Renewal Pitch",          "desc":"Custom renewal email",           "icon":"📧", "input":"customer email"},
        {"id":"customer_health_score","name":"Health Score Builder",   "desc":"Build CHI formula",              "icon":"❤️"},
        {"id":"nps_strategy",         "name":"NPS Strategy",           "desc":"Improve NPS score",              "icon":"😊"},
        {"id":"feedback_analyzer",    "name":"Feedback Analyzer",      "desc":"Synthesize all feedback",        "icon":"💭"},
        {"id":"feature_requests",     "name":"Feature Requests",       "desc":"Prioritize from data",           "icon":"🎁"},
        {"id":"customer_journey",     "name":"Customer Journey",       "desc":"Map full experience",            "icon":"🗺️"},
        {"id":"success_metrics",      "name":"Success Metrics",        "desc":"Define key CS KPIs",             "icon":"📊"},
        {"id":"qbr_template",         "name":"QBR Template",           "desc":"Quarterly Business Review",      "icon":"📋", "input":"customer name"},
        {"id":"expansion_revenue",    "name":"Expansion Revenue",      "desc":"Where to find more $",           "icon":"💰"},
        {"id":"saved_revenue",        "name":"Saved Revenue Report",   "desc":"Show CS impact",                 "icon":"💎"},
        {"id":"churn_root_cause",     "name":"Churn Root Cause",       "desc":"Why people really leave",        "icon":"🔍"},
        {"id":"cs_playbook",          "name":"CS Playbook Builder",    "desc":"SOP for common scenarios",       "icon":"📖"},
        {"id":"escalation_protocol",  "name":"Escalation Protocol",    "desc":"When to escalate",               "icon":"🚨"},
        {"id":"check_in_cadence",     "name":"Check-in Cadence",       "desc":"How often to touch base",        "icon":"📞"},
        {"id":"video_call_agenda",    "name":"Video Call Agenda",      "desc":"Customer call prep",             "icon":"🎥", "input":"customer email"},
        {"id":"survey_design",        "name":"Survey Design",          "desc":"Build NPS/CSAT survey",          "icon":"��"},
        {"id":"loyalty_program",      "name":"Loyalty Program",        "desc":"Reward best customers",          "icon":"🏆"},
        {"id":"referral_program",     "name":"Referral Program",       "desc":"Customer-driven growth",         "icon":"🎁"},
        {"id":"cs_dashboard_kpis",    "name":"CS Dashboard KPIs",      "desc":"Top metrics to track",           "icon":"📈"},
        {"id":"weekly_cs_report",     "name":"Weekly CS Report",       "desc":"Executive summary",              "icon":"📋"},
        {"id":"cs_ai_qa",             "name":"Custom CS Q&A",          "desc":"Ask anything",                   "icon":"💬", "input":"your question"},
    ],

    "ga4": [
        {"id":"traffic_strategy",     "name":"Traffic Strategy",       "desc":"Grow website visitors",          "icon":"📈"},
        {"id":"seo_opportunities",    "name":"SEO Opportunities",      "desc":"Pages to optimize",              "icon":"🔍"},
        {"id":"country_expansion",    "name":"Country Expansion",      "desc":"Where to invest marketing",      "icon":"🌍"},
        {"id":"weekly_traffic",       "name":"Weekly Traffic Report",  "desc":"Executive summary",              "icon":"📋"},
        {"id":"content_gaps",         "name":"Content Gaps",           "desc":"What pages to create",           "icon":"📝"},
        {"id":"bounce_audit",         "name":"Bounce Rate Audit",      "desc":"Why visitors leave",             "icon":"⚡"},
        {"id":"conversion_paths",     "name":"Conversion Paths",       "desc":"Best converting routes",         "icon":"🛤️"},
        {"id":"channel_attribution",  "name":"Channel Attribution",    "desc":"Which channels work",            "icon":"🎯"},
        {"id":"campaign_audit",       "name":"Campaign Audit",         "desc":"UTM campaign analysis",          "icon":"📊"},
        {"id":"page_performance",     "name":"Page Performance",       "desc":"Top + worst pages",              "icon":"📄"},
        {"id":"mobile_vs_desktop",    "name":"Mobile vs Desktop",      "desc":"Device strategy",                "icon":"📱"},
        {"id":"new_vs_returning",     "name":"New vs Returning",       "desc":"Visitor retention",              "icon":"🔄"},
        {"id":"goal_setup",           "name":"Goal Setup",             "desc":"GA4 events to track",            "icon":"🎯"},
        {"id":"event_strategy",       "name":"Event Strategy",         "desc":"Custom events to add",           "icon":"⚡"},
        {"id":"funnel_builder",       "name":"Funnel Builder",         "desc":"Build conversion funnel",        "icon":"🔻"},
        {"id":"audience_builder",     "name":"Audience Builder",       "desc":"GA4 audiences to create",        "icon":"👥"},
        {"id":"google_ads_link",      "name":"Google Ads Strategy",    "desc":"Sync GA4 with Ads",              "icon":"💸"},
        {"id":"site_speed_audit",     "name":"Site Speed Audit",       "desc":"Improve Core Web Vitals",        "icon":"⚡"},
        {"id":"landing_optimizer",    "name":"Landing Page Optimizer", "desc":"Top landing improvements",       "icon":"🚀", "input":"page URL"},
        {"id":"keyword_research",     "name":"Keyword Research",       "desc":"Topics to target",               "icon":"🔑", "input":"topic"},
        {"id":"competitor_seo",       "name":"Competitor SEO",         "desc":"Steal their keywords",           "icon":"🕵️", "input":"competitor URL"},
        {"id":"blog_strategy",        "name":"Blog Strategy",          "desc":"Content roadmap",                "icon":"📝"},
        {"id":"backlink_strategy",    "name":"Backlink Strategy",      "desc":"Get authoritative links",        "icon":"🔗"},
        {"id":"local_seo",            "name":"Local SEO",              "desc":"Geographic optimization",        "icon":"📍"},
        {"id":"international_seo",    "name":"International SEO",      "desc":"Multi-country strategy",         "icon":"🌐"},
        {"id":"voice_search",         "name":"Voice Search SEO",       "desc":"Optimize for voice",             "icon":"🎤"},
        {"id":"core_vitals",          "name":"Core Web Vitals",        "desc":"LCP/FID/CLS audit",              "icon":"⚙️"},
        {"id":"social_traffic",       "name":"Social Traffic",         "desc":"Best performing social",         "icon":"📱"},
        {"id":"referral_audit",       "name":"Referral Audit",         "desc":"Who's linking to you",           "icon":"🔗"},
        {"id":"ga4_ai_qa",            "name":"Custom GA4 Q&A",         "desc":"Ask anything",                   "icon":"💬", "input":"your question"},
    ],

    "all": [
        {"id":"executive_brief",      "name":"Executive Brief",        "desc":"One-page biz summary",           "icon":"📋"},
        {"id":"cross_funnel",         "name":"Cross-Platform Funnel",  "desc":"GA4 -> Signup -> Paid",          "icon":"🔻"},
        {"id":"weekly_digest",        "name":"Weekly Digest",          "desc":"All KPIs in one report",         "icon":"📨"},
        {"id":"daily_standup",        "name":"Daily Standup",          "desc":"What matters today",             "icon":"☀️"},
        {"id":"top3_priorities",      "name":"Top 3 Priorities",       "desc":"What to focus on",               "icon":"🎯"},
        {"id":"red_flags_all",        "name":"Red Flags Scanner",      "desc":"Cross-system issues",            "icon":"🚩"},
        {"id":"opportunity_scan",     "name":"Opportunity Scanner",    "desc":"Hidden growth ops",              "icon":"💡"},
        {"id":"month_review",         "name":"Monthly Review",         "desc":"This vs last month",             "icon":"📅"},
        {"id":"quarter_strategy",     "name":"Quarter Strategy",       "desc":"90-day plan",                    "icon":"🗓️"},
        {"id":"annual_plan",          "name":"Annual Planning",        "desc":"Year ahead roadmap",             "icon":"📈"},
        {"id":"investor_update",      "name":"Investor Update",        "desc":"Investor email draft",           "icon":"💼"},
        {"id":"board_deck",           "name":"Board Deck Outline",     "desc":"Slides to present",              "icon":"📊"},
        {"id":"team_kpis",            "name":"Team KPIs",              "desc":"Goals per team",                 "icon":"👥"},
        {"id":"hiring_plan",          "name":"Hiring Plan",            "desc":"Who to hire next",               "icon":"🧑‍💼"},
        {"id":"budget_recommend",     "name":"Budget Recommendations", "desc":"Where to spend",                 "icon":"💰"},
        {"id":"channel_roi",          "name":"Channel ROI Compare",    "desc":"Best ROI per channel",           "icon":"💹"},
        {"id":"customer_360",         "name":"Customer 360 View",      "desc":"Full picture of customer",       "icon":"🔄", "input":"customer email"},
        {"id":"product_market_fit",   "name":"Product-Market Fit",     "desc":"PMF score from data",            "icon":"🎯"},
        {"id":"growth_levers",        "name":"Growth Levers",          "desc":"Top 5 growth experiments",       "icon":"⚡"},
        {"id":"competitive_pos",      "name":"Competitive Position",   "desc":"Where you stand",                "icon":"🏁"},
        {"id":"swot_overall",         "name":"Overall SWOT",           "desc":"Business SWOT",                  "icon":"🧭"},
        {"id":"north_star_metric",    "name":"North Star Metric",      "desc":"What metric matters most",       "icon":"⭐"},
        {"id":"okrs_quarterly",       "name":"Quarterly OKRs",         "desc":"Suggest OKRs from data",         "icon":"🎯"},
        {"id":"crisis_playbook",      "name":"Crisis Playbook",        "desc":"What if X happens",              "icon":"🚨", "input":"scenario"},
        {"id":"experiments_list",     "name":"Experiments List",       "desc":"A/B tests to run",               "icon":"🧪"},
        {"id":"automation_audit",     "name":"Automation Audit",       "desc":"What to automate next",          "icon":"🤖"},
        {"id":"tech_stack_review",    "name":"Tech Stack Review",      "desc":"Tools you need / don't",         "icon":"🛠️"},
        {"id":"data_quality_audit",   "name":"Data Quality Audit",     "desc":"Where data is wrong",            "icon":"🔬"},
        {"id":"meeting_prep",         "name":"Meeting Prep",           "desc":"Brief for any meeting",          "icon":"💼", "input":"meeting type"},
        {"id":"all_ai_qa",            "name":"Custom Q&A",             "desc":"Ask anything across all",        "icon":"💬", "input":"your question"},
    ],
}



def run_tool(platform: str, tool_id: str, user_input: str = "", user_email: str = "anonymous"):
    """Run a specific AI power tool."""
    tools_for_platform = TOOLS.get(platform, [])
    tool = next((t for t in tools_for_platform if t["id"] == tool_id), None)
    if not tool:
        return {"error": f"Unknown tool: {tool_id}"}

    prompt = f"""Run the '{tool['name']}' AI tool: {tool['desc']}.

{'User input: ' + user_input if user_input else ''}

Use the data context to provide a complete, actionable, data-driven response.
Format with clear sections, bullet points, and specific numbers from the data."""

    return ask_ai(prompt, platform=platform, user_email=user_email)


if __name__ == "__main__":
    r = ask_ai("How is the business doing overall?", platform="all", user_email="test")
    print(r.get("answer", r.get("error")))
