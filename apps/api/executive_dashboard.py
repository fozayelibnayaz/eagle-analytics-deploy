#!/usr/bin/env python3
"""

Executive Dashboard - Core Business Metrics
Shows ONLY what matters: Revenue, Signups, Uploads, Marketing, Growth
Data accuracy first. No vanity metrics.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


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


def _fetch_all(sb, table, cols, filters=None):
    rows = []
    offset = 0
    while True:
        try:
            q = sb.table(table).select(cols)
            if filters:
                for k, v in filters.items():
                    q = q.eq(k, v)
            r = q.range(offset, offset + 999).execute()
            batch = r.data or []
            rows.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000
        except Exception:
            break
    return rows


def _period_range(period_name):
    """Returns (start_date, end_date, prev_start, prev_end, label)."""
    today = date.today()
    if period_name == "this_month":
        start = today.replace(day=1)
        end = today
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return start, end, prev_start, prev_end, f"{start.strftime('%B %Y')}"
    elif period_name == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return start, end, prev_start, prev_end, f"{start.strftime('%B %Y')}"
    elif period_name == "this_quarter":
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        end = today
        prev_start = date(today.year if q > 0 else today.year - 1, (q - 1) * 3 + 1 if q > 0 else 10, 1)
        prev_end = start - timedelta(days=1)
        return start, end, prev_start, prev_end, f"Q{q+1} {today.year}"
    elif period_name == "this_year":
        start = date(today.year, 1, 1)
        end = today
        prev_start = date(today.year - 1, 1, 1)
        prev_end = date(today.year - 1, 12, 31)
        return start, end, prev_start, prev_end, str(today.year)
    elif period_name == "last_year":
        start = date(today.year - 1, 1, 1)
        end = date(today.year - 1, 12, 31)
        prev_start = date(today.year - 2, 1, 1)
        prev_end = date(today.year - 2, 12, 31)
        return start, end, prev_start, prev_end, str(today.year - 1)
    else:
        start = today.replace(day=1)
        end = today
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return start, end, prev_start, prev_end, "Current"



def _compute_content_volume(sb, start, end, prev_start):
    """Content published: LinkedIn posts + YouTube videos + GA4 new pages (blogs)."""
    from collections import defaultdict
    import os
    result = {"linkedin": {}, "youtube": {}, "blog_pages": {}, "total_this_month": 0, "total_last_month": 0}

    this_m = start.strftime("%Y-%m")
    last_m = prev_start.strftime("%Y-%m")

    # ── LinkedIn posts ──
    try:
        li_posts = sb.table("linkedin_posts").select("urn,title,published_at,impressions,reactions,comments,clicks,ctr,engagement_rate").execute().data or []
        li_by_month = defaultdict(list)
        undated_posts = []
        for p in li_posts:
            pub = p.get("published_at")
            if pub and str(pub).strip() not in ("None","null",""):
                month_key = str(pub)[:7]
                li_by_month[month_key].append(p)
            else:
                undated_posts.append(p)
        result["linkedin"] = {
            "total_posts": len(li_posts),
            "this_month":  len(li_by_month.get(this_m, [])),
            "last_month":  len(li_by_month.get(last_m, [])),
            "undated":     len(undated_posts),
            "by_month":    {m: len(v) for m, v in sorted(li_by_month.items())},
            "top_posts":   sorted(li_posts, key=lambda x: x.get("impressions", 0) or 0, reverse=True)[:10],
            "all_posts":   li_posts,
        }
    except Exception:
        pass

    # ── YouTube videos ──
    try:
        import json
        yt_vids = []
        try:
            from youtube_command_center import get_cached_or_fetch
            yt_vids = get_cached_or_fetch(period_days=365).get("videos", [])
        except Exception:
            pass
        if not yt_vids:
            yt_path = Path("data_output/youtube_command_center.json")
            if yt_path.exists():
                yt_vids = json.loads(yt_path.read_text()).get("videos", [])
        yt_by_month = defaultdict(list)
        for v in yt_vids:
            pub = str(v.get("published_at") or "")[:7]
            if pub:
                yt_by_month[pub].append(v)
        result["youtube"] = {
            "total_videos": len(yt_vids),
            "this_month":   len(yt_by_month.get(this_m, [])),
            "last_month":   len(yt_by_month.get(last_m, [])),
            "by_month":     {m: len(v) for m, v in sorted(yt_by_month.items())},
            "top_videos":   sorted(yt_vids, key=lambda x: x.get("views", 0), reverse=True)[:5],
        }
    except Exception:
        pass

    # ── Blog/Website Pages from GA4 (new pages with their performance) ──
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Dimension, Metric, OrderBy
        _creds = None
        try:
            import streamlit as _st
            _sa_dict = dict(_st.secrets["ga4_service_account"])
            if "private_key" in _sa_dict:
                _sa_dict["private_key"] = _sa_dict["private_key"].replace("\\n", "\n")
            _creds = _sa.Credentials.from_service_account_info(_sa_dict, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        except Exception:
            pass
        if not _creds and os.path.exists("google_creds.json"):
            _creds = _sa.Credentials.from_service_account_file("google_creds.json", scopes=["https://www.googleapis.com/auth/analytics.readonly"])

        if _creds:
            _pid = os.environ.get("GA4_PROPERTY_ID", "374525971")
            try:
                import streamlit as _st2
                _pid = str(_st2.secrets.get("GA4_PROPERTY_ID", _pid))
            except Exception:
                pass
            _client = BetaAnalyticsDataClient(credentials=_creds)

            # Get ALL pages with their performance THIS MONTH
            try:
                r = _client.run_report(RunReportRequest(
                    property=f"properties/{_pid}",
                    date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
                    dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
                    metrics=[Metric(name="screenPageViews"), Metric(name="totalUsers"), Metric(name="sessions")],
                    order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
                    limit=10000,
                ))
                this_month_pages = []
                for row in r.rows:
                    path = row.dimension_values[0].value
                    title = row.dimension_values[1].value
                    views = int(row.metric_values[0].value)
                    users = int(row.metric_values[1].value)
                    sessions = int(row.metric_values[2].value)
                    this_month_pages.append({
                        "path": path,
                        "title": title[:100],
                        "views": views,
                        "users": users,
                        "sessions": sessions,
                    })
            except Exception:
                this_month_pages = []

            # Get ALL pages ever seen (full GA4 history)
            # Use maximum date range GA4 allows
            try:
                r2 = _client.run_report(RunReportRequest(
                    property=f"properties/{_pid}",
                    date_ranges=[DateRange(start_date="2020-01-01", end_date=(start - timedelta(days=1)).isoformat())],
                    dimensions=[Dimension(name="pagePath")],
                    metrics=[Metric(name="screenPageViews")],
                    limit=10000,
                ))
                all_historical_paths = set()
                for row in r2.rows:
                    all_historical_paths.add(row.dimension_values[0].value)
            except Exception:
                all_historical_paths = set()

            # Also save/load from MongoDB for persistent tracking
            try:
                existing = sb.table("analytics_cache").select("data").eq("source", "ga4_known_pages").execute().data
                if existing and existing[0].get("data"):
                    saved_paths = set(existing[0]["data"].get("paths", []))
                    all_historical_paths = all_historical_paths | saved_paths
            except Exception:
                pass

            # Save current known pages to MongoDB for next time
            try:
                all_known = all_historical_paths | set(p["path"] for p in this_month_pages)
                sb.table("analytics_cache").upsert({
                    "source": "ga4_known_pages",
                    "metric_date": end.isoformat(),
                    "period_type": "all_time",
                    "data": {"paths": list(all_known), "count": len(all_known), "updated": datetime.utcnow().isoformat()},
                    "fetched_at": datetime.utcnow().isoformat(),
                    "is_valid": True,
                }, on_conflict="source,metric_date").execute()
            except Exception:
                pass

            # TRULY NEW = this month pages NOT in any historical record
            new_pages = [p for p in this_month_pages if p["path"] not in all_historical_paths]

            # Filter out non-content pages
            ignore_patterns = ["/signup", "/login", "/analytics", "/utilities", "/developer",
                             "/team", "/reset", "/verify", "/callback", "/api/", "/admin",
                             "/control-panel", "/404", "/account", "/?", "/start-streaming",
                             "/pricing", "/demo", "/about", "/contact", "/privacy", "/terms",
                             "/career", "/job-description", "/data-visualization"]
            new_pages = [p for p in new_pages if not any(ig in p["path"].lower() for ig in ignore_patterns)]

            # Also filter pages with generic titles (Control Panel, Eagle 3D Streaming)
            new_pages = [p for p in new_pages if
                        "Control Panel" not in p.get("title","") and
                        p.get("title","") != "Eagle 3D Streaming | Unreal Engine 5 Pixel Streaming Platform"]

            # Blog pages = paths containing /blog/ or common blog patterns
            blog_pages = [p for p in this_month_pages if any(k in p["path"].lower() for k in ["/blog", "/article", "/post", "/news", "/learn", "/resource", "/guide", "/tutorial", "/case-study"])]

            result["blog_pages"] = {
                "total_pages_this_month": len(this_month_pages),
                "new_pages_this_month":   len(new_pages),
                "blog_pages_this_month":  len(blog_pages),
                "top_pages":              this_month_pages[:20],
                "new_pages":              new_pages[:20],
                "blog_pages":             blog_pages[:20],
            }
    except Exception:
        pass

    result["total_this_month"] = (
        result.get("linkedin", {}).get("this_month", 0) +
        result.get("youtube", {}).get("this_month", 0) +
        result.get("blog_pages", {}).get("new_pages_this_month", 0)
    )
    result["total_last_month"] = (
        result.get("linkedin", {}).get("last_month", 0) +
        result.get("youtube", {}).get("last_month", 0)
    )
    return result


def _compute_channel_growth(sb):
    """Channel growth: LinkedIn followers, YouTube subs, website traffic."""
    result = {}

    try:
        # LinkedIn followers daily history
        li_fol = sb.table("linkedin_followers_daily").select("snapshot_date,total,delta_total").order("snapshot_date").execute().data or []
        if li_fol:
            current = li_fol[-1].get("total", 0)
            ago_30 = li_fol[-31].get("total", current) if len(li_fol) > 30 else li_fol[0].get("total", current)
            ago_90 = li_fol[-91].get("total", current) if len(li_fol) > 90 else li_fol[0].get("total", current)
            result["linkedin_followers"] = {
                "current":    current,
                "30d_ago":    ago_30,
                "90d_ago":    ago_90,
                "growth_30d": current - ago_30,
                "growth_90d": current - ago_90,
                "history":    [{"date": r.get("snapshot_date"), "total": r.get("total", 0)} for r in li_fol],
            }
    except Exception:
        pass

    try:
        # YouTube subs - try API first, then cache
        yt_ch = {}
        try:
            from youtube_command_center import get_cached_or_fetch
            yt_data = get_cached_or_fetch(period_days=30)
            yt_ch = yt_data.get("channel", {})
        except Exception:
            pass
        if not yt_ch:
            try:
                import json
                yt_path = Path("data_output/youtube_command_center.json")
                if yt_path.exists():
                    yt_ch = json.loads(yt_path.read_text()).get("channel", {})
            except Exception:
                pass
        if yt_ch:
            result["youtube_subs"] = {
                "current":     yt_ch.get("subscribers", 0),
                "total_views": yt_ch.get("total_views", 0),
                "video_count": yt_ch.get("video_count", 0),
            }
    except Exception:
        pass

    try:
        # Website traffic from GA4 (monthly for last 12 months)
        import os
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric
        _creds = None
        try:
            import streamlit as _st
            _sa_dict = dict(_st.secrets["ga4_service_account"])
            if "private_key" in _sa_dict:
                _sa_dict["private_key"] = _sa_dict["private_key"].replace("\n", "\n")
            _creds = _sa.Credentials.from_service_account_info(_sa_dict, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        except Exception:
            pass
        if not _creds and os.path.exists("google_creds.json"):
            _creds = _sa.Credentials.from_service_account_file("google_creds.json", scopes=["https://www.googleapis.com/auth/analytics.readonly"])

        if _creds:
            _pid = os.environ.get("GA4_PROPERTY_ID", "374525971")
            try:
                import streamlit as _st2
                _pid = str(_st2.secrets.get("GA4_PROPERTY_ID", _pid))
            except Exception:
                pass
            _client = BetaAnalyticsDataClient(credentials=_creds)
            today = date.today()
            ga4_monthly = []
            for i in range(12):
                m_date = date(today.year, today.month, 1) - timedelta(days=30 * i)
                ms = date(m_date.year, m_date.month, 1).isoformat()
                me = (date(m_date.year, m_date.month + 1, 1) - timedelta(days=1)).isoformat() if m_date.month < 12 else date(m_date.year, 12, 31).isoformat()
                try:
                    r = _client.run_report(RunReportRequest(
                        property=f"properties/{_pid}",
                        date_ranges=[DateRange(start_date=ms, end_date=me)],
                        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
                    ))
                    if r.rows:
                        ga4_monthly.append({
                            "month":    m_date.strftime("%Y-%m"),
                            "sessions": int(r.rows[0].metric_values[0].value),
                            "users":    int(r.rows[0].metric_values[1].value),
                        })
                except Exception:
                    pass
            ga4_monthly.reverse()
            result["website_traffic"] = ga4_monthly
    except Exception:
        pass

    return result



def _calc_revenue(date_gte=None, date_lte=None):
    """Calculate total revenue from payments collection."""
    try:
        db = get_db()
        if db is None:
            return 0.0
        filters = {"final_status": "ACCEPTED"}
        if date_gte or date_lte:
            filters["first_payment_date"] = {}
            if date_gte:
                filters["first_payment_date"]["$gte"] = str(date_gte)
            if date_lte:
                filters["first_payment_date"]["$lte"] = str(date_lte)
        docs = list(db["payments"].find(filters, {"total_spend": 1, "_id": 0}))
        total = 0.0
        for doc in docs:
            val = doc.get("total_spend", 0) or 0
            try:
                cleaned = str(val).replace("$", "").replace(",", "").strip()
                total += float(cleaned) if cleaned else 0.0
            except Exception:
                pass
        return round(total, 2)
    except Exception:
        return 0.0


def get_core_metrics(period="this_month"):
    """
    Get complete core business metrics from MongoDB.

    Contract guarantee:
    This function returns every key required by executive_dashboard_ui.py.
    It intentionally supports both old display labels and new period codes:
    - "this_month" / "This Month"
    - "last_month" / "Last Month"
    - "this_quarter" / "This Quarter"
    - "this_year" / "This Year"
    - "last_year" / "Last Year"
    - "today" / "Today"
    - "all_time" / "All Time"
    """
    from datetime import datetime, date, timedelta
    from collections import Counter, defaultdict
    import calendar
    import math

    from mongo_client import get_db

    db = get_db()
    if db is None:
        return {"error": "MongoDB not connected"}

    def _period_code(p):
        s = str(p or "this_month").strip().lower().replace(" ", "_")
        mapping = {
            "this_month": "this_month",
            "last_month": "last_month",
            "this_quarter": "this_quarter",
            "this_year": "this_year",
            "last_year": "last_year",
            "today": "today",
            "all_time": "all_time",
            "all": "all_time",
        }
        return mapping.get(s, "this_month")

    def _month_add(d, months):
        y = d.year + (d.month - 1 + months) // 12
        m = (d.month - 1 + months) % 12 + 1
        day = min(d.day, calendar.monthrange(y, m)[1])
        return date(y, m, day)

    def _month_start(d):
        return date(d.year, d.month, 1)

    def _month_end(d):
        return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])

    def _quarter_start(d):
        q_month = ((d.month - 1) // 3) * 3 + 1
        return date(d.year, q_month, 1)

    def _quarter_end(d):
        qs = _quarter_start(d)
        next_q = _month_add(qs, 3)
        return next_q - timedelta(days=1)

    def _range_for_period(code):
        today = date.today()

        if code == "today":
            start = end = today
            prev_start = prev_end = today - timedelta(days=1)
            label = "Today"
            prev_label = "Yesterday"

        elif code == "last_month":
            last = _month_add(_month_start(today), -1)
            start = _month_start(last)
            end = _month_end(last)
            prev_month = _month_add(start, -1)
            prev_start = _month_start(prev_month)
            prev_end = _month_end(prev_month)
            label = start.strftime("%B %Y")
            prev_label = prev_start.strftime("%B %Y")

        elif code == "this_quarter":
            start = _quarter_start(today)
            end = today
            prev_q_start = _month_add(start, -3)
            prev_start = prev_q_start
            prev_end = start - timedelta(days=1)
            label = f"Q{((start.month - 1)//3) + 1} {start.year}"
            prev_label = f"Q{((prev_start.month - 1)//3) + 1} {prev_start.year}"

        elif code == "this_year":
            start = date(today.year, 1, 1)
            end = today
            prev_start = date(today.year - 1, 1, 1)
            prev_end = date(today.year - 1, 12, 31)
            label = str(today.year)
            prev_label = str(today.year - 1)

        elif code == "last_year":
            start = date(today.year - 1, 1, 1)
            end = date(today.year - 1, 12, 31)
            prev_start = date(today.year - 2, 1, 1)
            prev_end = date(today.year - 2, 12, 31)
            label = str(today.year - 1)
            prev_label = str(today.year - 2)

        elif code == "all_time":
            start = date(2020, 1, 1)
            end = today
            prev_start = date(2020, 1, 1)
            prev_end = date(2020, 1, 1)
            label = "All Time"
            prev_label = "Previous Period"

        else:
            start = _month_start(today)
            end = today
            prev_month = _month_add(start, -1)
            prev_start = _month_start(prev_month)
            prev_end = _month_end(prev_month)
            label = start.strftime("%B %Y")
            prev_label = prev_start.strftime("%B %Y")

        return start, end, prev_start, prev_end, label, prev_label

    def _same_period_last_year(start, end):
        try:
            return date(start.year - 1, start.month, start.day), date(end.year - 1, end.month, end.day)
        except ValueError:
            # Handles Feb 29
            return date(start.year - 1, start.month, min(start.day, 28)), date(end.year - 1, end.month, min(end.day, 28))

    def _parse_date(v):
        if v is None:
            return None

        if isinstance(v, datetime):
            return v.date()

        if isinstance(v, date):
            return v

        s = str(v).strip()
        if not s or s.lower() in ("none", "nan", "null", "nat"):
            return None

        s = s[:10]

        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass

        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
        except Exception:
            return None

    def _date_from_doc(doc, fields):
        for f in fields:
            if f in doc:
                d = _parse_date(doc.get(f))
                if d:
                    return d
        # Fallback: any date-like field
        for k, v in doc.items():
            lk = str(k).lower()
            if "date" in lk or "created" in lk or "payment" in lk:
                d = _parse_date(v)
                if d:
                    return d
        return None

    def _money(v):
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            if math.isnan(v) if isinstance(v, float) else False:
                return 0.0
            return float(v)
        s = str(v).replace("$", "").replace(",", "").strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except Exception:
            return 0.0

    def _status(doc):
        return str(
            doc.get("final_status")
            or doc.get("status")
            or doc.get("category")
            or ""
        ).strip().upper()

    def _is_accepted(doc):
        return _status(doc) in ("ACCEPTED", "ALREADY_COUNTED", "YES", "TRUE")

    def _is_internal(doc):
        email = str(
            doc.get("email")
            or doc.get("email_normalized")
            or doc.get("Email")
            or doc.get("User Email")
            or ""
        ).strip().lower()
        return email.endswith("@eagle3dstreaming.com")

    def _safe_docs(collection):
        try:
            return list(db[collection].find({}, {"_id": 0}))
        except Exception:
            return []

    signups_docs = _safe_docs("signups")
    uploads_docs = _safe_docs("uploads")
    payments_docs = _safe_docs("payments")

    signup_date_fields = [
        "signup_date", "Signup Date", "Account Created On", "account_created_on",
        "created", "created_at", "date", "row_date_used", "__scraped_date__"
    ]
    upload_date_fields = [
        "upload_date", "Upload Date", "first_upload_date", "First Upload Date",
        "created", "created_at", "date", "row_date_used", "__scraped_date__"
    ]
    payment_date_fields = [
        "first_payment_date", "First Payment", "payment_date", "Payment Date",
        "created", "created_at", "date", "row_date_used", "__scraped_date__"
    ]

    code = _period_code(period)
    start, end, prev_start, prev_end, label, prev_label = _range_for_period(code)
    yoy_start, yoy_end = _same_period_last_year(start, end)

    def _filter(docs, fields, s, e, accepted_only=True):
        out = []
        for doc in docs:
            if accepted_only and not _is_accepted(doc):
                continue
            d = _date_from_doc(doc, fields)
            if not d:
                continue
            if s <= d <= e:
                out.append(doc)
        return out

    cur_signups_docs = _filter(signups_docs, signup_date_fields, start, end)
    cur_uploads_docs = _filter(uploads_docs, upload_date_fields, start, end)
    cur_paid_docs = _filter(payments_docs, payment_date_fields, start, end)

    prev_signups_docs = _filter(signups_docs, signup_date_fields, prev_start, prev_end)
    prev_uploads_docs = _filter(uploads_docs, upload_date_fields, prev_start, prev_end)
    prev_paid_docs = _filter(payments_docs, payment_date_fields, prev_start, prev_end)

    yoy_signups_docs = _filter(signups_docs, signup_date_fields, yoy_start, yoy_end)
    yoy_paid_docs = _filter(payments_docs, payment_date_fields, yoy_start, yoy_end)

    signups = len(cur_signups_docs)
    uploads = len(cur_uploads_docs)
    paid = len(cur_paid_docs)

    prev_signups = len(prev_signups_docs)
    prev_uploads = len(prev_uploads_docs)
    prev_paid = len(prev_paid_docs)

    revenue = round(sum(_money(d.get("total_spend") or d.get("amount") or d.get("revenue")) for d in cur_paid_docs), 2)
    prev_revenue = round(sum(_money(d.get("total_spend") or d.get("amount") or d.get("revenue")) for d in prev_paid_docs), 2)
    yoy_revenue = round(sum(_money(d.get("total_spend") or d.get("amount") or d.get("revenue")) for d in yoy_paid_docs), 2)

    def pct(cur, prev):
        if prev in (0, None):
            if cur:
                return 100.0
            return 0.0
        return round((cur - prev) / prev * 100, 1)

    accepted_signups_all = [d for d in signups_docs if _is_accepted(d)]
    accepted_uploads_all = [d for d in uploads_docs if _is_accepted(d)]
    accepted_paid_all = [d for d in payments_docs if _is_accepted(d)]

    total_revenue = round(sum(_money(d.get("total_spend") or d.get("amount") or d.get("revenue")) for d in accepted_paid_all), 2)
    total_paid = len(accepted_paid_all)
    avg_subscription = round(total_revenue / total_paid, 2) if total_paid else 0.0

    total_raw = len(signups_docs)
    total_accepted = len(accepted_signups_all)
    total_rejected = max(0, total_raw - total_accepted)
    spam_rate = round(total_rejected / total_raw * 100, 1) if total_raw else 0.0
    internal_count = sum(1 for d in signups_docs if _is_internal(d))

    s2u_rate = round(uploads / signups * 100, 1) if signups else 0.0
    s2p_rate = round(paid / signups * 100, 1) if signups else 0.0
    u2p_rate = round(paid / uploads * 100, 1) if uploads else 0.0

    # Monthly trend for last 12 months
    monthly_trend = []
    today = date.today()
    base = _month_start(today)

    for i in range(11, -1, -1):
        ms = _month_add(base, -i)
        me = min(_month_end(ms), today) if ms.year == today.year and ms.month == today.month else _month_end(ms)

        m_signups_docs = _filter(signups_docs, signup_date_fields, ms, me)
        m_uploads_docs = _filter(uploads_docs, upload_date_fields, ms, me)
        m_paid_docs = _filter(payments_docs, payment_date_fields, ms, me)
        m_revenue = round(sum(_money(d.get("total_spend") or d.get("amount") or d.get("revenue")) for d in m_paid_docs), 2)

        monthly_trend.append({
            "month": ms.strftime("%Y-%m"),
            "signups": len(m_signups_docs),
            "uploads": len(m_uploads_docs),
            "paid": len(m_paid_docs),
            "revenue": m_revenue,
        })

    def _lead_source(doc):
        return str(
            doc.get("lead_source")
            or doc.get("Lead Source")
            or doc.get("source")
            or doc.get("utm_source")
            or "Unknown"
        ).strip() or "Unknown"

    lead_sources_period = dict(Counter(_lead_source(d) for d in cur_signups_docs).most_common(20))
    lead_sources_all = dict(Counter(_lead_source(d) for d in accepted_signups_all).most_common(20))

    def _reject_reason(doc):
        return str(
            doc.get("rejection_reason")
            or doc.get("__rejection_reason__")
            or doc.get("verdict_reason")
            or doc.get("final_status")
            or "Unknown"
        ).strip() or "Unknown"

    rejected_docs = [d for d in signups_docs if not _is_accepted(d)]
    rejection_reasons = dict(Counter(_reject_reason(d) for d in rejected_docs).most_common(20))

    result = {
        "period": code,
        "period_label": label,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "prev_period": prev_label,
        "prev_period_start": prev_start.isoformat(),
        "prev_period_end": prev_end.isoformat(),

        "signups": signups,
        "uploads": uploads,
        "paid": paid,
        "revenue": revenue,

        "prev_signups": prev_signups,
        "prev_uploads": prev_uploads,
        "prev_paid": prev_paid,
        "prev_revenue": prev_revenue,

        "signup_pct": pct(signups, prev_signups),
        "upload_pct": pct(uploads, prev_uploads),
        "paid_pct": pct(paid, prev_paid),
        "revenue_pct": pct(revenue, prev_revenue),

        # Backward-compatible aliases
        "signups_pct": pct(signups, prev_signups),
        "uploads_pct": pct(uploads, prev_uploads),

        "yoy_signups": len(yoy_signups_docs),
        "yoy_revenue": yoy_revenue,
        "yoy_signup_pct": pct(signups, len(yoy_signups_docs)),
        "yoy_revenue_pct": pct(revenue, yoy_revenue),

        "s2u_rate": s2u_rate,
        "s2p_rate": s2p_rate,
        "u2p_rate": u2p_rate,
        "s_to_u_rate": s2u_rate,
        "s_to_p_rate": s2p_rate,
        "u_to_p_rate": u2p_rate,

        "total_revenue": total_revenue,
        "total_paid": total_paid,
        "avg_subscription": avg_subscription,

        "total_raw": total_raw,
        "total_accepted": total_accepted,
        "total_rejected": total_rejected,
        "spam_rate": spam_rate,
        "internal_count": internal_count,

        "monthly_trend": monthly_trend,
        "lead_sources_period": dict(lead_sources_period) if not isinstance(lead_sources_period, dict) else lead_sources_period,
        "lead_sources_all": dict(lead_sources_all) if not isinstance(lead_sources_all, dict) else lead_sources_all,
        "rejection_reasons": rejection_reasons,

        "content_volume": {},
        "channel_growth": {},

        "source": "mongodb",
        "generated_at": datetime.utcnow().isoformat(),
    }

    return result



def get_signup_definition():
    """Clear definition of what counts as a signup."""
    return {
        "definition": "A signup is a UNIQUE, VERIFIED, NON-INTERNAL email that registered on the Eagle3D platform.",
        "accepted_criteria": [
            "Email has valid format",
            "Email has valid MX record (mail server exists)",
            "Email is NOT from a disposable domain",
            "Email is NOT from eagle3dstreaming.com (internal)",
            "Email is NOT a duplicate of an existing signup",
            "Email passed SMTP verification (when available)",
        ],
        "rejected_reasons": [
            "NOT_DETERMINED: SMTP check inconclusive (conservative reject)",
            "DISPOSABLE: Email from known disposable domain",
            "INTERNAL: eagle3dstreaming.com domain",
            "DUPLICATE_IN_BATCH: Same email appeared twice in one scrape",
            "NO_MX: Domain has no mail server",
            "DUPLICATE_DIFFERENT_DATE: Already signed up on different date",
            "INVALID_FORMAT: Not a valid email address",
            "SUSPICIOUS: Pattern matches known spam",
        ],
        "note": "This definition scrubs spam and duplicates. Only ACCEPTED signups are counted in KPIs.",
    }


if __name__ == "__main__":
    import json
    m = get_core_metrics("this_month")
    print(json.dumps({k: v for k, v in m.items() if k != "monthly_trend"}, indent=2, default=str))


def _normalize_core_metrics_contract(metrics):
    """
    Runtime contract normalizer for executive_dashboard_ui.py.

    The dashboard UI must never crash because a backend metric key is missing
    or because a collection shape changed from dict to list.
    """
    from datetime import datetime

    if not isinstance(metrics, dict):
        metrics = {"error": f"Invalid metrics payload: {type(metrics).__name__}"}

    defaults = {
        "period": "this_month",
        "period_start": "",
        "period_end": "",
        "prev_period": "Previous Period",

        "revenue": 0.0,
        "revenue_pct": 0.0,
        "prev_revenue": 0.0,

        "signups": 0,
        "signup_pct": 0.0,
        "prev_signups": 0,

        "uploads": 0,
        "upload_pct": 0.0,
        "prev_uploads": 0,

        "paid": 0,
        "paid_pct": 0.0,
        "prev_paid": 0,

        "yoy_revenue": 0.0,
        "yoy_revenue_pct": 0.0,
        "yoy_signups": 0,
        "yoy_signup_pct": 0.0,

        "s2u_rate": 0.0,
        "s2p_rate": 0.0,

        "total_revenue": 0.0,
        "total_paid": 0,
        "avg_subscription": 0.0,

        "total_raw": 0,
        "total_accepted": 0,
        "total_rejected": 0,
        "spam_rate": 0.0,
        "internal_count": 0,

        "monthly_trend": [],
        "lead_sources_period": {},
        "lead_sources_all": {},
        "rejection_reasons": {},
        "content_volume": {},
        "channel_growth": {},

        "source": "mongodb",
        "generated_at": datetime.utcnow().isoformat(),
    }

    for k, v in defaults.items():
        metrics.setdefault(k, v)

    # Alias older backend names to UI names
    if "signups_pct" in metrics and "signup_pct" not in metrics:
        metrics["signup_pct"] = metrics["signups_pct"]

    if "uploads_pct" in metrics and "upload_pct" not in metrics:
        metrics["upload_pct"] = metrics["uploads_pct"]

    if "s_to_u_rate" in metrics and "s2u_rate" not in metrics:
        metrics["s2u_rate"] = metrics["s_to_u_rate"]

    if "s_to_p_rate" in metrics and "s2p_rate" not in metrics:
        metrics["s2p_rate"] = metrics["s_to_p_rate"]

    def _to_number(v, default=0):
        try:
            if v is None:
                return default
            return int(v)
        except Exception:
            return default

    def _to_float(v, default=0.0):
        try:
            if v is None:
                return default
            return float(v)
        except Exception:
            return default

    int_keys = [
        "signups", "prev_signups", "uploads", "prev_uploads",
        "paid", "prev_paid", "total_paid", "total_raw",
        "total_accepted", "total_rejected", "internal_count",
        "yoy_signups",
    ]

    float_keys = [
        "revenue", "prev_revenue", "total_revenue", "avg_subscription",
        "revenue_pct", "signup_pct", "upload_pct", "paid_pct",
        "yoy_revenue", "yoy_revenue_pct", "yoy_signup_pct",
        "s2u_rate", "s2p_rate", "spam_rate",
    ]

    for k in int_keys:
        metrics[k] = _to_number(metrics.get(k), 0)

    for k in float_keys:
        metrics[k] = _to_float(metrics.get(k), 0.0)

    def _normalize_source_map(value):
        if value is None:
            return {}

        if isinstance(value, dict):
            return value

        if isinstance(value, list):
            out = {}
            for item in value:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    out[str(item[0])] = item[1]
                elif isinstance(item, dict):
                    key = item.get("source") or item.get("Source") or item.get("lead_source") or item.get("name")
                    val = item.get("signups") or item.get("Signups") or item.get("count") or item.get("value") or 0
                    if key:
                        out[str(key)] = val
            return out

        return {}

    metrics["lead_sources_period"] = _normalize_source_map(metrics.get("lead_sources_period"))
    metrics["lead_sources_all"] = _normalize_source_map(metrics.get("lead_sources_all"))
    metrics["rejection_reasons"] = _normalize_source_map(metrics.get("rejection_reasons"))

    if not isinstance(metrics.get("monthly_trend"), list):
        metrics["monthly_trend"] = []

    if not isinstance(metrics.get("content_volume"), dict):
        metrics["content_volume"] = {}

    if not isinstance(metrics.get("channel_growth"), dict):
        metrics["channel_growth"] = {}

    return metrics


# Wrap get_core_metrics once so every caller receives safe metrics.
try:
    _original_get_core_metrics = get_core_metrics

    def get_core_metrics(period="this_month"):
        return _normalize_core_metrics_contract(_original_get_core_metrics(period))
except Exception:
    pass




# === ROBUST_EXECUTIVE_CONTENT_CHANNEL_PATCH_START ===
def _robust_parse_date_for_exec(v):
    from datetime import datetime, date
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v

    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "null", "nat"):
        return None

    raw = s
    s = s[:10]

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _robust_num_for_exec(v, default=0):
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.replace(",", "").replace("$", "").strip()
            if not v:
                return default
        return float(v)
    except Exception:
        return default


def _load_json_cache_for_exec(path):
    try:
        from pathlib import Path
        import json
        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _ensure_marketing_caches_in_mongo_for_exec(db):
    """
    One-time best effort migration of existing JSON caches into MongoDB.
    MongoDB remains the source for dashboard reads.
    """
    from datetime import datetime

    if db is None:
        return

    now = datetime.utcnow().isoformat()

    # YouTube videos
    try:
        if db["youtube_videos"].count_documents({}) == 0:
            data = _load_json_cache_for_exec("data_output/youtube_videos.json") or _load_json_cache_for_exec("data_output/youtube_cache.json")
            videos = []
            if isinstance(data, list):
                videos = data
            elif isinstance(data, dict):
                videos = data.get("videos") or data.get("items") or []
            if videos:
                docs = []
                for i, v in enumerate(videos):
                    if isinstance(v, dict):
                        d = dict(v)
                        d.setdefault("_cache_source", "data_output")
                        d.setdefault("_migrated_at", now)
                        d.setdefault("_row_index", i)
                        docs.append(d)
                if docs:
                    db["youtube_videos"].insert_many(docs, ordered=False)
    except Exception:
        pass

    # YouTube channel
    try:
        if db["youtube_channel"].count_documents({}) == 0:
            data = _load_json_cache_for_exec("data_output/youtube_channel.json") or _load_json_cache_for_exec("data_output/youtube_cache.json")
            channel = data.get("channel", data) if isinstance(data, dict) else {}
            if isinstance(channel, dict) and channel:
                channel["_cache_source"] = "data_output"
                channel["_migrated_at"] = now
                db["youtube_channel"].insert_one(channel)
    except Exception:
        pass

    # LinkedIn posts
    try:
        if db["linkedin_posts"].count_documents({}) == 0:
            data = _load_json_cache_for_exec("data_output/linkedin_posts.json") or _load_json_cache_for_exec("data_output/linkedin_all_posts.json")
            posts = []
            if isinstance(data, list):
                posts = data
            elif isinstance(data, dict):
                posts = data.get("posts") or data.get("data") or []
            if posts:
                docs = []
                for i, p in enumerate(posts):
                    if isinstance(p, dict):
                        d = dict(p)
                        d.setdefault("_cache_source", "data_output")
                        d.setdefault("_migrated_at", now)
                        d.setdefault("_row_index", i)
                        docs.append(d)
                if docs:
                    db["linkedin_posts"].insert_many(docs, ordered=False)
    except Exception:
        pass

    # LinkedIn followers
    try:
        if db["linkedin_followers_daily"].count_documents({}) == 0:
            data = _load_json_cache_for_exec("data_output/linkedin_followers.json") or _load_json_cache_for_exec("data_output/linkedin_daily.json")
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get("followers", {}).get("by_date") or data.get("by_date") or data.get("daily") or []
            docs = []
            for i, r in enumerate(rows):
                if isinstance(r, dict):
                    d = dict(r)
                    if "date" in d and "snapshot_date" not in d:
                        d["snapshot_date"] = d["date"]
                    d.setdefault("_cache_source", "data_output")
                    d.setdefault("_migrated_at", now)
                    d.setdefault("_row_index", i)
                    docs.append(d)
            if docs:
                db["linkedin_followers_daily"].insert_many(docs, ordered=False)
    except Exception:
        pass


def _robust_content_volume_mongodb_only(db, start, end, prev_start):
    from collections import defaultdict

    result = {
        "linkedin": {
            "total_posts": 0,
            "this_month": 0,
            "last_month": 0,
            "undated": 0,
            "by_month": {},
            "top_posts": [],
            "all_posts": [],
        },
        "youtube": {
            "total_videos": 0,
            "this_month": 0,
            "last_month": 0,
            "by_month": {},
            "top_videos": [],
        },
        "blog_pages": {
            "new_pages_this_month": 0,
            "total_pages_this_month": 0,
            "new_pages": [],
            "top_pages": [],
            "blog_pages": [],
            "blog_pages_this_month": 0,
        },
        "total_this_month": 0,
        "total_last_month": 0,
    }

    if db is None:
        return result

    _ensure_marketing_caches_in_mongo_for_exec(db)

    this_m = start.strftime("%Y-%m")
    last_m = prev_start.strftime("%Y-%m")

    # LinkedIn posts
    try:
        posts = list(db["linkedin_posts"].find({}, {"_id": 0}))
        by_month = defaultdict(list)
        undated = []

        for p in posts:
            d = None
            for f in ("published_at", "publishedAt", "date", "created_at", "snapshot_date"):
                d = _robust_parse_date_for_exec(p.get(f))
                if d:
                    break

            if d:
                by_month[d.strftime("%Y-%m")].append(p)
            else:
                undated.append(p)

        result["linkedin"] = {
            "total_posts": len(posts),
            "this_month": len(by_month.get(this_m, [])),
            "last_month": len(by_month.get(last_m, [])),
            "undated": len(undated),
            "by_month": {m: len(v) for m, v in sorted(by_month.items())},
            "top_posts": sorted(
                posts,
                key=lambda x: _robust_num_for_exec(x.get("impressions") or x.get("views") or x.get("clicks")),
                reverse=True,
            )[:10],
            "all_posts": posts,
        }
    except Exception:
        pass

    # YouTube videos
    try:
        videos = list(db["youtube_videos"].find({}, {"_id": 0}))
        by_month = defaultdict(list)

        for v in videos:
            d = None
            for f in ("published_at", "publishedAt", "published", "date", "created_at"):
                d = _robust_parse_date_for_exec(v.get(f))
                if d:
                    break

            if d:
                by_month[d.strftime("%Y-%m")].append(v)

        result["youtube"] = {
            "total_videos": len(videos),
            "this_month": len(by_month.get(this_m, [])),
            "last_month": len(by_month.get(last_m, [])),
            "by_month": {m: len(v) for m, v in sorted(by_month.items())},
            "top_videos": sorted(
                videos,
                key=lambda x: _robust_num_for_exec(x.get("views") or x.get("view_count")),
                reverse=True,
            )[:10],
        }
    except Exception:
        pass

    # Website/GA4 pages from Mongo if available
    try:
        pages = list(db["ga4_pages"].find({}, {"_id": 0}))
        this_pages = []
        new_pages = []

        for p in pages:
            d = None
            for f in ("date", "first_seen", "created_at", "snapshot_date"):
                d = _robust_parse_date_for_exec(p.get(f))
                if d:
                    break

            views = int(_robust_num_for_exec(p.get("views") or p.get("screenPageViews") or p.get("pageviews"), 0))
            row = {
                "title": str(p.get("title") or p.get("pageTitle") or "")[:120],
                "path": str(p.get("path") or p.get("pagePath") or p.get("url") or ""),
                "views": views,
                "users": int(_robust_num_for_exec(p.get("users") or p.get("totalUsers"), 0)),
                "sessions": int(_robust_num_for_exec(p.get("sessions"), 0)),
            }

            if d and start <= d <= end:
                this_pages.append(row)
                new_pages.append(row)

        result["blog_pages"] = {
            "new_pages_this_month": len(new_pages),
            "total_pages_this_month": len(this_pages),
            "new_pages": sorted(new_pages, key=lambda x: x.get("views", 0), reverse=True)[:200],
            "top_pages": sorted(this_pages, key=lambda x: x.get("views", 0), reverse=True)[:200],
            "blog_pages": [p for p in this_pages if "blog" in p.get("path", "").lower() or "article" in p.get("path", "").lower()],
            "blog_pages_this_month": len([p for p in this_pages if "blog" in p.get("path", "").lower() or "article" in p.get("path", "").lower()]),
        }
    except Exception:
        pass

    result["total_this_month"] = (
        result["linkedin"]["this_month"]
        + result["youtube"]["this_month"]
        + result["blog_pages"]["new_pages_this_month"]
    )

    result["total_last_month"] = (
        result["linkedin"]["last_month"]
        + result["youtube"]["last_month"]
    )

    return result


def _robust_channel_growth_mongodb_only(db):
    result = {
        "linkedin_followers": {},
        "youtube_subs": {},
        "website_traffic": [],
    }

    if db is None:
        return result

    _ensure_marketing_caches_in_mongo_for_exec(db)

    # LinkedIn followers
    try:
        rows = list(db["linkedin_followers_daily"].find({}, {"_id": 0}))
        clean = []

        for r in rows:
            d = _robust_parse_date_for_exec(r.get("snapshot_date") or r.get("date"))
            total = _robust_num_for_exec(r.get("total") or r.get("followers") or r.get("total_followers"), 0)
            if d and total:
                clean.append({"date": d.isoformat(), "total": int(total)})

        clean = sorted(clean, key=lambda x: x["date"])

        if clean:
            current = clean[-1]["total"]
            ago_30 = clean[-31]["total"] if len(clean) > 30 else clean[0]["total"]
            ago_90 = clean[-91]["total"] if len(clean) > 90 else clean[0]["total"]

            result["linkedin_followers"] = {
                "current": current,
                "30d_ago": ago_30,
                "90d_ago": ago_90,
                "growth_30d": current - ago_30,
                "growth_90d": current - ago_90,
                "history": clean,
            }
    except Exception:
        pass

    # YouTube channel
    try:
        ch = db["youtube_channel"].find_one({}, {"_id": 0}) or {}
        if ch:
            result["youtube_subs"] = {
                "current": int(_robust_num_for_exec(ch.get("subscribers") or ch.get("subscriber_count"), 0)),
                "total_views": int(_robust_num_for_exec(ch.get("total_views") or ch.get("views"), 0)),
                "video_count": int(_robust_num_for_exec(ch.get("video_count") or ch.get("videos"), 0)),
            }
    except Exception:
        pass

    # Website traffic from Mongo if available
    try:
        rows = list(db["ga4_monthly_traffic"].find({}, {"_id": 0}))
        traffic = []
        for r in rows:
            month = str(r.get("month") or r.get("date") or "")[:7]
            if month:
                traffic.append({
                    "month": month,
                    "sessions": int(_robust_num_for_exec(r.get("sessions"), 0)),
                    "users": int(_robust_num_for_exec(r.get("users") or r.get("totalUsers"), 0)),
                })
        result["website_traffic"] = sorted(traffic, key=lambda x: x["month"])
    except Exception:
        pass

    return result


try:
    _exec_metrics_before_content_patch = get_core_metrics

    def get_core_metrics(period="this_month"):
        metrics = _exec_metrics_before_content_patch(period)

        if not isinstance(metrics, dict):
            metrics = {"error": f"Invalid metrics payload: {type(metrics).__name__}"}

        try:
            db = get_db()
            s = _robust_parse_date_for_exec(metrics.get("period_start"))
            e = _robust_parse_date_for_exec(metrics.get("period_end"))
            ps = _robust_parse_date_for_exec(metrics.get("prev_period_start"))

            if s and e:
                if not metrics.get("content_volume"):
                    metrics["content_volume"] = _robust_content_volume_mongodb_only(db, s, e, ps or s)

                if not metrics.get("channel_growth"):
                    metrics["channel_growth"] = _robust_channel_growth_mongodb_only(db)

        except Exception as _content_patch_error:
            metrics.setdefault("content_volume_error", str(_content_patch_error))

        return metrics
except Exception:
    pass
# === ROBUST_EXECUTIVE_CONTENT_CHANNEL_PATCH_END ===
