#!/usr/bin/env python3
"""

Universal Trend Analysis Engine
Compares current month vs previous month for any metric.
Works for: KPI signups/uploads/paid, GA4 sessions/users, YouTube views/subs,
LinkedIn impressions/reactions/followers.
"""
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


def _month_range(year_month: str):
    """Returns (first_day, last_day) for a YYYY-MM string."""
    y, m = year_month.split("-")
    y, m = int(y), int(m)
    first = date(y, m, 1)
    if m == 12:
        last = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(y, m + 1, 1) - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _previous_month(year_month: str):
    y, m = map(int, year_month.split("-"))
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def compare_periods(table, date_col, metric_col, current_month, agg="sum", filters=None):
    """Compare current month vs previous month for any MongoDB column."""
    sb = _get_db()
    if sb is None:
        return None

    prev_month = _previous_month(current_month)
    cur_start, cur_end = _month_range(current_month)
    prev_start, prev_end = _month_range(prev_month)

    def _fetch(start, end):
        try:
            q = sb.table(table).select(f"{date_col},{metric_col}").gte(date_col, start).lte(date_col, end)
            if filters:
                for k, v in filters.items():
                    q = q.eq(k, v)
            return q.execute().data or []
        except Exception:
            return []

    cur_rows = _fetch(cur_start, cur_end)
    prev_rows = _fetch(prev_start, prev_end)

    def _agg(rows):
        if not rows:
            return 0
        vals = [float(r.get(metric_col, 0) or 0) for r in rows]
        if agg == "sum":
            return sum(vals)
        if agg == "avg":
            return sum(vals) / len(vals) if vals else 0
        if agg == "max":
            return max(vals)
        if agg == "count":
            return len(rows)
        return sum(vals)

    cur_val = _agg(cur_rows)
    prev_val = _agg(prev_rows)
    delta = cur_val - prev_val
    delta_pct = (delta / prev_val * 100) if prev_val > 0 else None

    return {
        "current_month":  current_month,
        "previous_month": prev_month,
        "current_value":  cur_val,
        "previous_value": prev_val,
        "delta":          delta,
        "delta_pct":      delta_pct,
        "current_count":  len(cur_rows),
        "previous_count": len(prev_rows),
        "current_period": f"{cur_start} to {cur_end}",
        "previous_period": f"{prev_start} to {prev_end}",
    }


def compute_efficiency_ratio(numerator_compare, denominator_compare):
    """e.g., posts last month=3, impressions last month=39322 -> 13107 impressions per post.
    Then compare current month efficiency. Tells you if quality went up despite less quantity."""
    if not numerator_compare or not denominator_compare:
        return None

    cur_n = numerator_compare["current_value"]
    cur_d = denominator_compare["current_value"]
    prev_n = numerator_compare["previous_value"]
    prev_d = denominator_compare["previous_value"]

    cur_eff = (cur_n / cur_d) if cur_d > 0 else 0
    prev_eff = (prev_n / prev_d) if prev_d > 0 else 0
    delta_eff = cur_eff - prev_eff
    delta_pct = (delta_eff / prev_eff * 100) if prev_eff > 0 else None

    return {
        "current_efficiency":  cur_eff,
        "previous_efficiency": prev_eff,
        "delta":               delta_eff,
        "delta_pct":           delta_pct,
        "interpretation":      _interpret(delta_pct, prev_eff, cur_eff),
    }


def _interpret(delta_pct, prev, cur):
    if delta_pct is None:
        return "No previous data"
    if delta_pct > 50:
        return f"Massive improvement (+{delta_pct:.0f}%) - quality much higher"
    if delta_pct > 20:
        return f"Strong improvement (+{delta_pct:.0f}%) - quality up"
    if delta_pct > 5:
        return f"Slight improvement (+{delta_pct:.0f}%)"
    if delta_pct > -5:
        return f"Roughly stable ({delta_pct:+.0f}%)"
    if delta_pct > -20:
        return f"Slight decline ({delta_pct:+.0f}%)"
    return f"Significant drop ({delta_pct:+.0f}%) - quality down"


def get_full_trend_kpi(current_month=None):
    """Get full trend analysis for KPI tables."""
    if not current_month:
        current_month = datetime.now().strftime("%Y-%m")

    return {
        "month":   current_month,
        "signups": compare_periods("signups",  "signup_date",        "id", current_month, agg="count", filters={"final_status": "ACCEPTED"}),
        "uploads": compare_periods("uploads",  "upload_date",        "id", current_month, agg="count", filters={"final_status": "ACCEPTED"}),
        "paid":    compare_periods("payments", "first_payment_date", "id", current_month, agg="count", filters={"final_status": "ACCEPTED"}),
        "revenue": compare_periods("payments", "first_payment_date", "total_spend", current_month, agg="sum", filters={"final_status": "ACCEPTED"}),
    }


def get_full_trend_linkedin(current_month=None):
    """LinkedIn MoM comparison from snapshot tables."""
    if not current_month:
        current_month = datetime.now().strftime("%Y-%m")

    sb = _get_db()
    if sb is None:
        return None

    prev_month = _previous_month(current_month)
    cur_start, cur_end = _month_range(current_month)
    prev_start, prev_end = _month_range(prev_month)

    def _highlights_in(start, end):
        try:
            r = sb.table("linkedin_highlights_daily").select("*").gte("snapshot_date", start).lte("snapshot_date", end).order("snapshot_date", desc=True).limit(1).execute()
            return r.data[0] if r.data else {}
        except Exception:
            return {}

    cur = _highlights_in(cur_start, cur_end)
    prev = _highlights_in(prev_start, prev_end)

    metrics = ["impressions", "reactions", "comments", "reposts", "clicks", "page_views", "unique_visitors", "total_followers"]
    result = {"month": current_month, "metrics": {}}

    for m in metrics:
        c_val = cur.get(m, 0) or 0
        p_val = prev.get(m, 0) or 0
        delta = c_val - p_val
        delta_pct = (delta / p_val * 100) if p_val > 0 else None
        result["metrics"][m] = {
            "current":   c_val,
            "previous":  p_val,
            "delta":     delta,
            "delta_pct": delta_pct,
        }

    # Posts published per month
    try:
        cur_posts = sb.table("linkedin_posts_daily").select("post_urn").gte("snapshot_date", cur_start).lte("snapshot_date", cur_end).execute().data or []
        prev_posts = sb.table("linkedin_posts_daily").select("post_urn").gte("snapshot_date", prev_start).lte("snapshot_date", prev_end).execute().data or []
        cur_count = len(set(p["post_urn"] for p in cur_posts))
        prev_count = len(set(p["post_urn"] for p in prev_posts))
        result["metrics"]["posts_active"] = {
            "current": cur_count, "previous": prev_count,
            "delta": cur_count - prev_count,
            "delta_pct": ((cur_count - prev_count) / prev_count * 100) if prev_count else None,
        }
    except Exception:
        pass

    # Efficiency: impressions per post
    posts_cmp = result["metrics"].get("posts_active")
    imps_cmp = result["metrics"].get("impressions")
    if posts_cmp and imps_cmp:
        result["efficiency"] = {
            "impressions_per_post": {
                "current":     (imps_cmp["current"] / posts_cmp["current"]) if posts_cmp["current"] else 0,
                "previous":    (imps_cmp["previous"] / posts_cmp["previous"]) if posts_cmp["previous"] else 0,
            },
        }
        cur_eff = result["efficiency"]["impressions_per_post"]["current"]
        prev_eff = result["efficiency"]["impressions_per_post"]["previous"]
        result["efficiency"]["impressions_per_post"]["delta_pct"] = ((cur_eff - prev_eff) / prev_eff * 100) if prev_eff else None
        result["efficiency"]["impressions_per_post"]["interpretation"] = _interpret(
            result["efficiency"]["impressions_per_post"]["delta_pct"], prev_eff, cur_eff
        )

    return result


def get_full_trend_ga4(current_month=None):
    """GA4 MoM via direct API."""
    if not current_month:
        current_month = datetime.now().strftime("%Y-%m")

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric
    except ImportError:
        return {"error": "GA4 library not installed"}

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
        try:
            creds = service_account.Credentials.from_service_account_file("google_creds.json", scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        except Exception:
            return {"error": "GA4 credentials missing"}

    pid = os.environ.get("GA4_PROPERTY_ID", "374525971")
    try:
        pid = str(st.secrets.get("GA4_PROPERTY_ID", pid)).strip()
    except Exception:
        pass

    client = BetaAnalyticsDataClient(credentials=creds)
    prev_month = _previous_month(current_month)
    cur_start, cur_end = _month_range(current_month)
    prev_start, prev_end = _month_range(prev_month)

    def _query(s, e):
        try:
            r = client.run_report(RunReportRequest(
                property=f"properties/{pid}",
                date_ranges=[DateRange(start_date=s, end_date=e)],
                metrics=[Metric(name="sessions"), Metric(name="totalUsers"), Metric(name="screenPageViews")],
            ))
            if r.rows:
                row = r.rows[0]
                return {
                    "sessions":  int(row.metric_values[0].value),
                    "users":     int(row.metric_values[1].value),
                    "pageviews": int(row.metric_values[2].value),
                }
        except Exception:
            pass
        return {"sessions": 0, "users": 0, "pageviews": 0}

    cur = _query(cur_start, cur_end)
    prev = _query(prev_start, prev_end)

    result = {"month": current_month, "metrics": {}}
    for m in ["sessions", "users", "pageviews"]:
        c, p = cur[m], prev[m]
        d = c - p
        dp = (d / p * 100) if p > 0 else None
        result["metrics"][m] = {"current": c, "previous": p, "delta": d, "delta_pct": dp}
    return result


def get_full_trend_youtube(current_month=None):
    """YouTube MoM via cached analytics."""
    if not current_month:
        current_month = datetime.now().strftime("%Y-%m")

    try:
        from youtube_command_center import get_cached_or_fetch
    except ImportError:
        return {"error": "youtube_command_center not available"}

    # Get analytics for current and previous months
    prev_month = _previous_month(current_month)

    today = date.today()
    if current_month == today.strftime("%Y-%m"):
        cur_days = today.day
    else:
        cur_days = 30
    cur_data = get_cached_or_fetch(period_days=cur_days)

    # Previous month requires custom range - approximate from cached data
    prev_data = get_cached_or_fetch(period_days=60)

    cur_ana = cur_data.get("analytics", {})
    prev_ana = prev_data.get("analytics", {})

    metrics = ["views", "watch_hours", "subscribers_gained", "likes", "comments", "shares"]
    result = {"month": current_month, "metrics": {}}
    for m in metrics:
        c = cur_ana.get(m, 0)
        p_raw = prev_ana.get(m, 0)
        # Approximate previous month as (60day total - current 30day)
        p = max(0, p_raw - c)
        d = c - p
        dp = (d / p * 100) if p > 0 else None
        result["metrics"][m] = {"current": c, "previous": p, "delta": d, "delta_pct": dp}

    # Videos uploaded count
    cur_vids = cur_data.get("videos", [])
    cur_start, cur_end = _month_range(current_month)
    prev_start, prev_end = _month_range(prev_month)

    def _in_range(v, s, e):
        pub = v.get("published_at", "")[:10]
        return s <= pub <= e if pub else False

    cur_count = sum(1 for v in cur_vids if _in_range(v, cur_start, cur_end))
    prev_count = sum(1 for v in cur_vids if _in_range(v, prev_start, prev_end))

    result["metrics"]["videos_published"] = {
        "current": cur_count, "previous": prev_count,
        "delta": cur_count - prev_count,
        "delta_pct": ((cur_count - prev_count) / prev_count * 100) if prev_count else None,
    }
    return result


if __name__ == "__main__":
    import json
    print("=== KPI TREND ===")
    print(json.dumps(get_full_trend_kpi(), indent=2, default=str))
    print("\n=== LINKEDIN TREND ===")
    print(json.dumps(get_full_trend_linkedin(), indent=2, default=str))
