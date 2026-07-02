#!/usr/bin/env python3
"""Traffic Attribution - maps signups/uploads/paid to traffic sources."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter, defaultdict


import os
import re
import json
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


def normalize_lead_source(raw):
    if not raw or not str(raw).strip(): return "(Not Specified)"
    s = str(raw).strip().lower()
    if s in NORMALIZE_MAP: return NORMALIZE_MAP[s]
    for key, val in NORMALIZE_MAP.items():
        if key in s: return val
    return str(raw).strip().title()

def get_lead_source_attribution(period_start=None, period_end=None):
    sb = _get_sb()
    if sb is None: return {"error":"MongoDB not configured"}
    rows = []
    offset = 0
    while True:
        q = sb.table("signups").select("lead_source,signup_date").eq("final_status","ACCEPTED")
        if period_start: q = q.gte("signup_date", period_start)
        if period_end: q = q.lte("signup_date", period_end)
        r = q.range(offset, offset+999).execute()
        rows.extend(r.data or [])
        if len(r.data or []) < 1000: break
        offset += 1000
    by_source = Counter()
    for r in rows:
        by_source[normalize_lead_source(r.get("lead_source",""))] += 1
    total = sum(by_source.values())
    result = [{"source":s,"signups":c,"percentage":round(c/total*100,1) if total else 0}
              for s,c in by_source.most_common()]
    return {"total_signups":total,
            "specified":total-by_source.get("(Not Specified)",0),
            "unspecified":by_source.get("(Not Specified)",0),
            "sources":result}

def get_ga4_proportional_attribution(period_start=None, period_end=None):
    sb = _get_sb()
    if sb is None: return {"error":"MongoDB not configured"}
    if not period_start: period_start = (date.today()-timedelta(days=30)).isoformat()
    if not period_end: period_end = date.today().isoformat()
    ga4_sources = {}
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Dimension, Metric
        creds = None
        try:
            import streamlit as st
            sa = dict(st.secrets["ga4_service_account"])
            if "private_key" in sa: sa["private_key"] = sa["private_key"].replace("\\n","\n")
            creds = service_account.Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        except: pass
        if not creds and os.path.exists("google_creds.json"):
            creds = service_account.Credentials.from_service_account_file("google_creds.json", scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        if creds:
            pid = os.environ.get("GA4_PROPERTY_ID","374525971")
            try:
                import streamlit as st
                pid = str(st.secrets.get("GA4_PROPERTY_ID", pid))
            except: pass
            client = BetaAnalyticsDataClient(credentials=creds)
            r = client.run_report(RunReportRequest(
                property=f"properties/{pid}",
                date_ranges=[DateRange(start_date=period_start, end_date=period_end)],
                dimensions=[Dimension(name="sessionSource"),Dimension(name="sessionMedium")],
                metrics=[Metric(name="sessions"),Metric(name="totalUsers")],
                limit=50))
            for row in r.rows:
                src = row.dimension_values[0].value
                med = row.dimension_values[1].value
                sessions = int(row.metric_values[0].value)
                users = int(row.metric_values[1].value)
                if "google" in src.lower() and "organic" in med.lower(): n = "Google (Organic)"
                elif "google" in src.lower() and "cpc" in med.lower(): n = "Google (Ads)"
                elif "linkedin" in src.lower(): n = "LinkedIn"
                elif "youtube" in src.lower(): n = "YouTube"
                elif "facebook" in src.lower(): n = "Facebook"
                elif "chatgpt" in src.lower() or "gemini" in src.lower() or "claude" in src.lower(): n = "AI Assistant"
                elif "discord" in src.lower(): n = "Discord"
                elif src == "(direct)": n = "Direct"
                elif med == "referral": n = "Referral (" + src + ")"
                elif med == "email": n = "Email"
                else: n = src + " (" + med + ")"
                if n not in ga4_sources: ga4_sources[n] = {"sessions":0,"users":0}
                ga4_sources[n]["sessions"] += sessions
                ga4_sources[n]["users"] += users
    except Exception as e:
        return {"error":str(e)}
    if not ga4_sources: return {"error":"No GA4 data"}
    total_s = sum(v["sessions"] for v in ga4_sources.values())
    signups = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",period_start).lte("signup_date",period_end).execute().count or 0
    uploads = sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",period_start).lte("upload_date",period_end).execute().count or 0
    paid = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",period_start).lte("first_payment_date",period_end).execute().count or 0
    result = []
    for src, data in sorted(ga4_sources.items(), key=lambda x:-x[1]["sessions"]):
        share = data["sessions"]/total_s if total_s else 0
        result.append({"source":src,"sessions":data["sessions"],"users":data["users"],
                       "session_share":round(share*100,1),
                       "est_signups":round(signups*share,1),
                       "est_uploads":round(uploads*share,1),
                       "est_paid":round(paid*share,1)})
    return {"total_sessions":total_s,"total_signups":signups,"total_uploads":uploads,
            "total_paid":paid,"sources":result,
            "note":"Proportional estimate based on GA4 traffic share."}
