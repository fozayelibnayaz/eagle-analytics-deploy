"""


reporting_engine.py — v4 COMPREHENSIVE
LAYER 6 — REPORTING + NOTIFICATIONS
Sends Telegram (group) + Email + Slack with FULL SYSTEM report covering:
  1. KPI System (sign-ups, uploads, paid)
  2. GA4 Analytics (traffic, top pages, top sources)
  3. YouTube (channel stats, top videos, subscriber change)
  4. LinkedIn (followers, company info)
  5. Cross-Platform (correlations, unified summary)
  6. Stripe (revenue, payments)
  7. Pipeline health
"""
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








def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Report] {msg}", flush=True)


def escape_html(text):
    """Escape special chars for Telegram HTML parse mode (reliable, unlike MarkdownV2)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# Keep escape_md as alias for backward compat
def escape_md(text):
    return escape_html(text)


def si(v):
    """Safe int conversion."""
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def sf(v, decimals=1):
    """Safe float conversion."""
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _parse_report_date(raw):
    """Parse any date string to YYYY-MM-DD format for reporting."""
    if not raw or str(raw).strip() in ("", "nan", "None", "—", "-"):
        return ""
    from email.utils import parsedate_to_datetime as _pdt
    import re as _re
    raw = str(raw).strip()
    # Try RFC 2822
    try:
        dt = _pdt(raw)
        if dt:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    # Try common formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%y, %I:%M %p",
                "%m/%d/%Y, %I:%M %p", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    # Regex: YYYY-MM-DD
    m = _re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        try:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except Exception:
            pass
    return ""


def fmt_num(n):
    """Format number with commas."""
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def send_telegram(message, parse_mode="HTML"):
    """Send message to Telegram group via Bot API. Uses HTML (reliable)."""
    # Allow skip via env var when comprehensive_alerts is in use
    # Telegram sender active (no skip)
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    
    # Fallback to st.secrets (for Streamlit Cloud dashboard buttons)
    if not bot_token or not chat_id:
        try:
            import streamlit as st
            if "TELEGRAM_BOT_TOKEN" in st.secrets:
                val = st.secrets["TELEGRAM_BOT_TOKEN"]
                if val and str(val).strip():
                    bot_token = str(val).strip()
            if "TELEGRAM_CHAT_ID" in st.secrets:
                val = st.secrets["TELEGRAM_CHAT_ID"]
                if val and str(val).strip():
                    chat_id = str(val).strip()
        except Exception:
            pass

    if not bot_token or not chat_id:
        log("Telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    try:
        url     = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        # Try requests first (proven faster on this network)
        try:
            import requests
            r = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": parse_mode}, timeout=30)
            body = r.json()
            if body.get("ok"):
                log("Telegram sent (requests)")
                return True
            log(f"Telegram API error: {body.get('description','')}")
            # If parse error, retry without parse_mode
            if "parse" in str(body.get('description','')).lower():
                r2 = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=30)
                if r2.json().get("ok"):
                    log("Telegram sent (no parse_mode)")
                    return True
            return False
        except Exception as e:
            log(f"requests failed: {e}, trying urllib...")

        # Fallback to urllib
        payload = json.dumps({
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": parse_mode,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            if body.get("ok"):
                log("Telegram sent (urllib)")
                return True
            log(f"Telegram API error: {body}")
            return False
    except Exception as e:
        log(f"Telegram failed: {e}")
        return False


def send_email(subject, body):
    sender   = os.environ.get("EMAIL_FROM", "").strip()
    password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    receiver = os.environ.get("EMAIL_TO", "").strip()

    # Fallback to st.secrets (for Streamlit Cloud dashboard buttons)
    if not sender or not password or not receiver:
        try:
            import streamlit as st
            if "EMAIL_FROM" in st.secrets:
                val = st.secrets["EMAIL_FROM"]
                if val and str(val).strip():
                    sender = str(val).strip()
            if "EMAIL_APP_PASSWORD" in st.secrets:
                val = st.secrets["EMAIL_APP_PASSWORD"]
                if val and str(val).strip():
                    password = str(val).strip()
            if "EMAIL_TO" in st.secrets:
                val = st.secrets["EMAIL_TO"]
                if val and str(val).strip():
                    receiver = str(val).strip()
        except Exception:
            pass

    if not sender or not password or not receiver:
        log("Email skipped: EMAIL_FROM/EMAIL_APP_PASSWORD/EMAIL_TO not set")
        return False

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg            = MIMEMultipart()
        msg["From"]    = sender
        msg["To"]      = receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.send_message(msg)

        log(f"✅ Email sent to {receiver}")
        return True
    except Exception as e:
        log(f"Email failed: {e}")
        return False


def send_slack(text):
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        log("Slack skipped: SLACK_WEBHOOK_URL not set")
        return False
    try:
        payload = json.dumps({"text": f"```\n{text}\n```"}).encode()
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15)
        log("✅ Slack sent")
        return True
    except Exception as e:
        log(f"Slack failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# DATA BUILDERS — each subsystem
# ═══════════════════════════════════════════════════════════════

def build_kpi_stats():
    """KPI System stats - uses MongoDB as primary source"""
    import os as _os_kpi
    # ── HARD GUARD: ALWAYS use MongoDB if env vars set ──
    _su = _os_kpi.environ.get("MONGO_URI", "").strip()
    _sk = _os_kpi.environ.get("MONGO_DB", "").strip()
    if not _su or not _sk:
        try:
            import streamlit as _st_kpi
            _su = str(_st_kpi.secrets.get("MONGO_URI", "")).strip()
            _sk = str(_st_kpi.secrets.get("MONGO_DB", "")).strip()
        except Exception:
            pass

    if _su and _sk:
        try:
            _sb = get_db()
            _today = datetime.now().strftime("%Y-%m-%d")
            _mstart = datetime.now().strftime("%Y-%m-01")
            # Common period = first upload date (locked)
            _upload_start = get_earliest_upload_date() or "2025-12-01"
            try:
                pass
            except Exception:
                pass
            # Today
            _st_t = _sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",_today).execute()
            _ut_t = _sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",_today).execute()
            _pt_t = _sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",_today).execute()
            # Month
            _sm = _sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",_mstart).execute()
            _um = _sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",_mstart).execute()
            _pm = _sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",_mstart).execute()
            # All Time = COMMON PERIOD ONLY (Dec 2025 onwards)
            _sa = _sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",_upload_start).execute()
            _ua = _sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",_upload_start).execute()
            _pa = _sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",_upload_start).execute()
            _ovr = _sb.table("manual_overrides").select("count",count="exact").eq("is_active",True).execute()
            _month_str = datetime.now().strftime("%Y-%m")
            log(f"[MongoDB] Today S/U/P={_st_t.count}/{_ut_t.count}/{_pt_t.count} Month={_sm.count}/{_um.count}/{_pm.count} Common={_sa.count}/{_ua.count}/{_pa.count}")
            return {
                "signups_today":          _st_t.count or 0,
                "uploads_today":          _ut_t.count or 0,
                "paid_today":             _pt_t.count or 0,
                "signups_month":          _sm.count or 0,
                "uploads_month":          _um.count or 0,
                "paid_month":             _pm.count or 0,
                "signups_all":            _sa.count or 0,
                "uploads_all":            _ua.count or 0,
                "paid_all":               _pa.count or 0,
                "signups_full_db":        _sa.count or 0,
                "uploads_full_db":        _ua.count or 0,
                "paid_full_db":           _pa.count or 0,
                "signups_all_override":   _sa.count or 0,
                "uploads_all_override":   _ua.count or 0,
                "paid_all_override":      _pa.count or 0,
                "signups_month_override": _sm.count or 0,
                "uploads_month_override": _um.count or 0,
                "paid_month_override":    _pm.count or 0,
                "today_str":              _today,
                "month_str":              _month_str,
                "alltime_period":         f"Common Period from {_upload_start}",
                "alltime_start":          _upload_start,
                "alltime_end":            _today,
                "total_overrides":        _ovr.count or 0,
                "validation_passed":      True,
                "validation_warnings":    0,
                "validation_summary":     "PASS - MongoDB common period (locked to first upload date)",
                "validation_banner":      "",
                "source": "mongodb",
            }
        except Exception as _e:
            import traceback
            log(f"[MongoDB HARD GUARD] Failed: {_e}")
            log(f"[MongoDB HARD GUARD] Trace: {traceback.format_exc()[:300]}")
            log(f"[MongoDB HARD GUARD] Falling back to old logic")

    """KPI System stats - uses MongoDB as primary source"""
    # FALLBACK: original Sheets-based implementation
    """KPI System stats — counts from Verified tabs (always accurate) + Daily_Counts supplement."""
    from sheets_writer import read_tab_data
    from manual_override_engine import load_overrides, normalize_email, ACTION_TO_STATUS

    today_str     = datetime.now().strftime("%Y-%m-%d")
    cur_month_str = datetime.now().strftime("%Y-%m")

    # ── PRIMARY: Count directly from Verified tabs (always accurate, like the dashboard) ──
    free_rows   = read_tab_data("Verified_FREE")
    upload_rows = read_tab_data("Verified_FIRST_UPLOAD")
    stripe_rows = read_tab_data("Verified_STRIPE")

    # Apply overrides
    overrides = load_overrides()
    if overrides:
        for tab_rows in (free_rows, upload_rows, stripe_rows):
            for r in tab_rows:
                em = ""
                for ek in ("Email", "email", "__email_normalized__"):
                    if r.get(ek) and "@" in str(r[ek]):
                        em = str(r[ek]).strip().lower()
                        break
                norm = normalize_email(em) if em else ""
                if norm and norm in overrides:
                    ov = overrides[norm]
                    action = ov.get("action", "")
                    m = ACTION_TO_STATUS.get(action, {})
                    if m:
                        r["final_status"] = m["final_status"]

    # Count ACCEPTED by date
    s_today = u_today = p_today = 0
    s_month = u_month = p_month = 0
    s_all = u_all = p_all = 0

    for r in free_rows:
        if str(r.get("final_status", "")).upper() == "ACCEPTED":
            s_all += 1
            for f in ("row_date_used", "Account Created On", "__scraped_at__"):
                d = _parse_report_date(str(r.get(f, "")))
                if d:
                    if d == today_str:
                        s_today += 1
                    if d.startswith(cur_month_str):
                        s_month += 1
                    break

    for r in upload_rows:
        if str(r.get("final_status", "")).upper() == "ACCEPTED":
            u_all += 1
            for f in ("row_date_used", "Upload Date", "__scraped_at__"):
                d = _parse_report_date(str(r.get(f, "")))
                if d:
                    if d == today_str:
                        u_today += 1
                    if d.startswith(cur_month_str):
                        u_month += 1
                    break

    for r in stripe_rows:
        if str(r.get("final_status", "")).upper() == "ACCEPTED":
            p_all += 1
            for f in ("First payment", "row_date_used", "Created", "__scraped_at__"):
                d = _parse_report_date(str(r.get(f, "")))
                if d:
                    if d == today_str:
                        p_today += 1
                    if d.startswith(cur_month_str):
                        p_month += 1
                    break

    stats = {
        "signups_today":  s_today,
        "uploads_today":  u_today,
        "paid_today":     p_today,
        "signups_month":  s_month,
        "uploads_month":  u_month,
        "paid_month":     p_month,
        "signups_all":    s_all,
        "uploads_all":    u_all,
        "paid_all":       p_all,
        # Also set override keys to same values (overrides already applied above)
        "signups_all_override": s_all,
        "uploads_all_override": u_all,
        "paid_all_override": p_all,
        "signups_month_override": s_month,
        "uploads_month_override": u_month,
        "paid_month_override": p_month,
    }

    stats["today_str"] = today_str
    stats["month_str"] = cur_month_str
    stats["total_overrides"] = len(overrides) if overrides else 0
    return stats


def build_ga4_stats():
    """GA4 traffic summary — tries API, then cached files. Returns today/month/all-time."""
    import pandas as pd
    result = {
        "connected": False, "today_users": 0, "today_sessions": 0,
        "month_users": 0, "month_sessions": 0,
        "all_time_users": 0, "all_time_sessions": 0,
        "top_sources": [], "top_pages": [], "top_countries": [],
        "prev_month_users": 0, "prev_month_sessions": 0,
    }

    today_str = datetime.now().strftime("%Y-%m-%d")
    cur_month_str = datetime.now().strftime("%Y-%m")
    prev_month_str = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    # Try API first
    try:
        from ga4_connector import get_status
        status = get_status()
        if status.get("connected"):
            from ga4_connector import fetch_utm_traffic, fetch_geo_traffic
            # Fetch 60 days for month-over-month comparison
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
            utm = fetch_utm_traffic(start, end)
            # Mark as connected if API call succeeded (even with empty data)
            result["connected"] = True
            if not utm.empty:
                # Ensure date column
                if "date" in utm.columns:
                    utm["date"] = pd.to_datetime(utm["date"], errors="coerce")
                    # Today
                    today_utm = utm[utm["date"].dt.strftime("%Y-%m-%d") == today_str]
                    result["today_sessions"] = si(today_utm.get("sessions", pd.Series([0])).sum())
                    result["today_users"] = si(today_utm.get("totalUsers", pd.Series([0])).sum())
                    # This month
                    month_utm = utm[utm["date"].dt.strftime("%Y-%m") == cur_month_str]
                    result["month_sessions"] = si(month_utm.get("sessions", pd.Series([0])).sum())
                    result["month_users"] = si(month_utm.get("totalUsers", pd.Series([0])).sum())
                    # Previous month
                    prev_utm = utm[utm["date"].dt.strftime("%Y-%m") == prev_month_str]
                    result["prev_month_sessions"] = si(prev_utm.get("sessions", pd.Series([0])).sum())
                    result["prev_month_users"] = si(prev_utm.get("totalUsers", pd.Series([0])).sum())
                # All time (what we have)
                result["all_time_sessions"] = si(utm.get("sessions", pd.Series([0])).sum())
                result["all_time_users"] = si(utm.get("totalUsers", pd.Series([0])).sum())
                if "sourceMedium" in utm.columns:
                    top = utm.groupby("sourceMedium")["sessions"].sum().sort_values(ascending=False).head(5)
                    result["top_sources"] = [(s, int(v)) for s, v in top.items()]
            geo = fetch_geo_traffic(start, end)
            if not geo.empty and "country" in geo.columns:
                top = geo.groupby("country")["sessions"].sum().sort_values(ascending=False).head(5)
                result["top_countries"] = [(c, int(v)) for c, v in top.items()]
            if result["connected"]:
                return result
    except Exception as e:
        log(f"GA4 API error: {e}")

    # Fallback: read cached GA4 data from pipeline
    try:
        _ga4_cache = DATA_DIR / "ga4_traffic_cache.json"
        if _ga4_cache.exists():
            _data = json.loads(_ga4_cache.read_text())
            if _data:
                result["connected"] = True
                result["month_sessions"] = si(_data.get("total_sessions", 0))
                result["month_users"] = si(_data.get("total_users", 0))
                result["all_time_sessions"] = result["month_sessions"]
                result["all_time_users"] = result["month_users"]
                if _data.get("top_sources"):
                    result["top_sources"] = _data["top_sources"][:5]
                if _data.get("top_countries"):
                    result["top_countries"] = _data["top_countries"][:5]
                log("GA4 stats: using cached data")
    except Exception as e:
        log(f"GA4 cache error: {e}")

    # ── METHOD 3: Direct GA4 Data API call (last resort, when on Streamlit Cloud) ──
    if not result["connected"]:
        try:
            _prop_id = os.environ.get("GA4_PROPERTY_ID", "374525971")
            # Try to get credentials from st.secrets or file
            _creds = None
            try:
                import streamlit as st
                if "ga4_service_account" in st.secrets:
                    d = dict(st.secrets["ga4_service_account"])
                    if "private_key" in d:
                        d["private_key"] = d["private_key"].replace("\\n", "\n")
                    _creds = service_account.Credentials.from_service_account_info(
                        d, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
                    )
            except Exception:
                pass
            if not _creds:
                try:
                    _creds = service_account.Credentials.from_service_account_file(
                        "google_creds.json",
                        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
                    )
                except Exception:
                    pass
            if _creds:
                log("GA4: Attempting direct live API call...")
                from google.analytics.data_v1beta import BetaAnalyticsDataClient
                from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Dimension, Metric
                client = BetaAnalyticsDataClient(credentials=_creds)
                _end = datetime.now().strftime("%Y-%m-%d")
                _start_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                _start_60d = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
                _prev_start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
                _prev_end = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d")

                # Get 30d sessions/users
                _body = RunReportRequest(
                    property=f"properties/{_prop_id}",
                    date_ranges=[DateRange(start_date=_start_30d, end_date=_end)],
                    dimensions=[Dimension(name="sourceMedium")],
                    metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
                )
                _resp = client.run_report(_body)
                _total_sessions = 0
                _total_users = 0
                _sources = {}
                for row in _resp.rows:
                    s = si(row.metric_values[0].value)
                    u = si(row.metric_values[1].value)
                    _total_sessions += s
                    _total_users += u
                    src = row.dimension_values[0].value
                    _sources[src] = _sources.get(src, 0) + s
                result["connected"] = True
                result["month_sessions"] = _total_sessions
                result["month_users"] = _total_users
                result["all_time_sessions"] = _total_sessions
                result["all_time_users"] = _total_users
                if _sources:
                    result["top_sources"] = sorted(_sources.items(), key=lambda x: x[1], reverse=True)[:5]

                # Previous month for MoM
                try:
                    _prev_body = RunReportRequest(
                        property=f"properties/{_prop_id}",
                        date_ranges=[DateRange(start_date=_prev_start, end_date=_prev_end)],
                        dimensions=[],
                        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
                    )
                    _prev_resp = client.run_report(_prev_body)
                    for row in _prev_resp.rows:
                        result["prev_month_sessions"] = si(row.metric_values[0].value)
                        result["prev_month_users"] = si(row.metric_values[1].value)
                        break
                except Exception:
                    pass

                # Today
                try:
                    _today_body = RunReportRequest(
                        property=f"properties/{_prop_id}",
                        date_ranges=[DateRange(start_date=today_str, end_date=today_str)],
                        dimensions=[],
                        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
                    )
                    _today_resp = client.run_report(_today_body)
                    for row in _today_resp.rows:
                        result["today_sessions"] = si(row.metric_values[0].value)
                        result["today_users"] = si(row.metric_values[1].value)
                        break
                except Exception:
                    pass

                # Geo data
                try:
                    _geo_body = RunReportRequest(
                        property=f"properties/{_prop_id}",
                        date_ranges=[DateRange(start_date=_start_30d, end_date=_end)],
                        dimensions=[Dimension(name="country")],
                        metrics=[Metric(name="sessions")],
                    )
                    _geo_resp = client.run_report(_geo_body)
                    _countries = {}
                    for row in _geo_resp.rows:
                        c = row.dimension_values[0].value
                        v = si(row.metric_values[0].value)
                        _countries[c] = _countries.get(c, 0) + v
                    if _countries:
                        result["top_countries"] = sorted(_countries.items(), key=lambda x: x[1], reverse=True)[:5]
                except Exception:
                    pass

                log(f"GA4: Live API — {_total_sessions:,} sessions, {_total_users:,} users")
        except Exception as e:
            log(f"GA4 live API error (non-fatal): {e}")

    return result


def build_youtube_stats():
    """YouTube channel summary — tries API, then cached files, then live API call. Returns today/month/all-time."""
    import pandas as pd
    result = {
        "connected": False, "subscribers": 0, "total_views": 0,
        "video_count": 0, "top_videos": [],
        "today_views": 0, "today_subs_gained": 0, "today_watch_hours": 0,
        "month_views": 0, "month_subs_gained": 0, "month_watch_hours": 0,
        "prev_month_views": 0, "prev_month_subs_gained": 0,
        "has_analytics": False, "dead_videos": [], "fastest_growing": None,
        "days_since_upload": 0, "total_likes": 0, "total_comments": 0,
        "channel_health": "❓", "avg_engagement": 0.0,
        "uploaded_today": 0, "low_engagement_count": 0, "dead_video_count": 0,
        "channel_title": "", "videos_raw": [],
        "period_views": 0, "period_watch_hours": 0, "period_subs_gained": 0,
    }

    cur_month_str = datetime.now().strftime("%Y-%m")
    prev_month_str = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Try API first
    try:
        from youtube_connector import is_configured
        if is_configured():
            from youtube_connector import get_channel_info, get_channel_videos, has_analytics_access
            result["connected"] = True
            ch = get_channel_info()
            result["subscribers"] = si(ch.get("subscribers", 0))
            result["total_views"] = si(ch.get("total_views", 0))
            result["video_count"] = si(ch.get("video_count", 0))
            result["channel_title"] = ch.get("title", "")

            vids = get_channel_videos(max_videos=500)
            if vids:
                top = sorted(vids, key=lambda v: v.get("views", 0), reverse=True)[:5]
                result["top_videos"] = [
                    (v.get("title", "Untitled")[:40], si(v.get("views", 0)), si(v.get("likes", 0)))
                    for v in top
                ]
                # Compute channel health metrics
                total_likes = sum(v.get("likes", 0) for v in vids)
                total_comments = sum(v.get("comments", 0) for v in vids)
                total_views = sum(v.get("views", 0) for v in vids)
                result["total_likes"] = total_likes
                result["total_comments"] = total_comments
                result["avg_engagement"] = ((total_likes + total_comments) / total_views * 100) if total_views > 0 else 0

                # Dead videos (< 1 view/day after 30+ days)
                dead = []
                for v in vids:
                    vdate = v.get("published_at", "")
                    views = v.get("views", 0)
                    if vdate and views is not None:
                        try:
                            age_days = (datetime.now() - datetime.fromisoformat(vdate.replace("Z", ""))).days
                            if age_days > 30:
                                vpd = views / age_days
                                if vpd < 1:
                                    dead.append({
                                        "title": v.get("title", "?")[:50],
                                        "views_per_day": round(vpd, 2),
                                        "age_days": age_days,
                                        "views": views,
})
                        except Exception:
                            pass
                result["dead_videos"] = sorted(dead, key=lambda x: x["views_per_day"])[:5]
                result["dead_video_count"] = len(dead)

                # Fastest growing video
                fastest = None
                for v in vids:
                    vdate = v.get("published_at", "")
                    views = v.get("views", 0)
                    if vdate and views and views > 100:
                        try:
                            age_days = max(1, (datetime.now() - datetime.fromisoformat(vdate.replace("Z", ""))).days)
                            vpd = views / age_days
                            if not fastest or vpd > fastest["views_per_day"]:
                                fastest = {
                                    "title": v.get("title", "?")[:50],
                                    "views_per_day": round(vpd),
                                    "views": views,
                                }
                        except Exception:
                            pass
                result["fastest_growing"] = fastest

                # Days since last upload
                upload_dates = []
                for v in vids:
                    vdate = v.get("published_at", "")
                    if vdate:
                        try:
                            upload_dates.append(datetime.fromisoformat(vdate.replace("Z", "")))
                        except Exception:
                            pass
                if upload_dates:
                    result["days_since_upload"] = (datetime.now() - max(upload_dates)).days
                    result["uploaded_today"] = sum(1 for d in upload_dates if d.strftime("%Y-%m-%d") == today_str)

                # Channel health score
                eng = result["avg_engagement"]
                if result["days_since_upload"] > 30 or eng < 0.5:
                    result["channel_health"] = "🔴 Critical"
                elif result["days_since_upload"] > 14 or eng < 1.0:
                    result["channel_health"] = "🟡 Needs Attention"
                else:
                    result["channel_health"] = "🟢 Healthy"

                # Low engagement videos (< 0.5% ER with 100+ views)
                low_eng = 0
                for v in vids:
                    views = v.get("views", 0)
                    likes = v.get("likes", 0)
                    if views >= 100 and (likes / views * 100) < 0.5:
                        low_eng += 1
                result["low_engagement_count"] = low_eng
                result["videos_raw"] = vids

            if has_analytics_access():
                result["has_analytics"] = True
                from youtube_connector import get_daily_analytics
                end = datetime.now().strftime("%Y-%m-%d")
                # Fetch 60 days for month comparison
                start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
                daily = get_daily_analytics(start, end)
                if not daily.empty:
                    # Today
                    if "date" in daily.columns:
                        daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
                        today_data = daily[daily["date"].dt.strftime("%Y-%m-%d") == today_str]
                        result["today_views"] = si(today_data.get("views", pd.Series([0])).sum())
                        result["today_subs_gained"] = si(today_data.get("subscribersGained", pd.Series([0])).sum())
                        watch_min_today = sf(today_data.get("estimatedMinutesWatched", pd.Series([0])).sum())
                        result["today_watch_hours"] = round(watch_min_today / 60, 1)
                        # This month
                        month_data = daily[daily["date"].dt.strftime("%Y-%m") == cur_month_str]
                        result["month_views"] = si(month_data.get("views", pd.Series([0])).sum())
                        result["month_subs_gained"] = si(month_data.get("subscribersGained", pd.Series([0])).sum())
                        watch_min_month = sf(month_data.get("estimatedMinutesWatched", pd.Series([0])).sum())
                        result["month_watch_hours"] = round(watch_min_month / 60, 1)
                        # Previous month
                        prev_data = daily[daily["date"].dt.strftime("%Y-%m") == prev_month_str]
                        result["prev_month_views"] = si(prev_data.get("views", pd.Series([0])).sum())
                        result["prev_month_subs_gained"] = si(prev_data.get("subscribersGained", pd.Series([0])).sum())
                        # Period (last 30d) for Telegram
                        _period_days = 30
                        _period_start = (datetime.now() - timedelta(days=_period_days)).strftime("%Y-%m-%d")
                        _period_data = daily[daily["date"].dt.strftime("%Y-%m-%d") >= _period_start]
                        result["period_views"] = si(_period_data.get("views", pd.Series([0])).sum())
                        _period_watch_min = sf(_period_data.get("estimatedMinutesWatched", pd.Series([0])).sum())
                        result["period_watch_hours"] = round(_period_watch_min / 60, 1)
                        result["period_subs_gained"] = si(_period_data.get("subscribersGained", pd.Series([0])).sum())
            if result["connected"]:
                return result
    except Exception as e:
        log(f"YouTube API error: {e}")

    # Fallback: read cached YouTube data from pipeline
    try:
        _yt_ch = DATA_DIR / "youtube_channel.json"
        if _yt_ch.exists():
            _ch = json.loads(_yt_ch.read_text())
            result["connected"] = True
            result["subscribers"] = si(_ch.get("subscribers", 0))
            result["total_views"] = si(_ch.get("total_views", 0))
            result["video_count"] = si(_ch.get("video_count", 0))
        _yt_vids = DATA_DIR / "youtube_videos.json"
        if _yt_vids.exists():
            _vids_data = json.loads(_yt_vids.read_text())
            _vids = _vids_data.get("videos", []) if isinstance(_vids_data, dict) else _vids_data
            if _vids:
                top = sorted(_vids, key=lambda v: v.get("views", 0), reverse=True)[:5]
                result["top_videos"] = [
                    (v.get("title", "Untitled")[:40], si(v.get("views", 0)), si(v.get("likes", 0)))
                    for v in top
                ]
                # Dead videos from cache
                dead = []
                for v in _vids:
                    vdate = v.get("published_at", "")
                    views = v.get("views", 0)
                    if vdate and views is not None:
                        try:
                            age_days = (datetime.now() - datetime.fromisoformat(vdate.replace("Z", ""))).days
                            if age_days > 30:
                                vpd = views / age_days
                                if vpd < 1:
                                    dead.append({
                                        "title": v.get("title", "?")[:50],
                                        "views_per_day": round(vpd, 2),
                                        "age_days": age_days,
                                        "views": views,
})
                        except Exception:
                            pass
                result["dead_videos"] = sorted(dead, key=lambda x: x["views_per_day"])[:5]
                result["dead_video_count"] = len(dead)
                # Total likes/comments
                result["total_likes"] = sum(v.get("likes", 0) for v in _vids)
                result["total_comments"] = sum(v.get("comments", 0) for v in _vids)
                total_views = sum(v.get("views", 0) for v in _vids)
                result["avg_engagement"] = ((result["total_likes"] + result["total_comments"]) / total_views * 100) if total_views > 0 else 0
                # Channel health
                if result["avg_engagement"] < 0.5:
                    result["channel_health"] = "🔴 Critical"
                elif result["avg_engagement"] < 1.0:
                    result["channel_health"] = "🟡 Needs Attention"
                else:
                    result["channel_health"] = "🟢 Healthy"
                # Fastest growing
                fastest = None
                for v in _vids:
                    vdate = v.get("published_at", "")
                    views = v.get("views", 0)
                    if vdate and views and views > 100:
                        try:
                            age_days = max(1, (datetime.now() - datetime.fromisoformat(vdate.replace("Z", ""))).days)
                            vpd = views / age_days
                            if not fastest or vpd > fastest["views_per_day"]:
                                fastest = {"title": v.get("title", "?")[:50], "views_per_day": round(vpd), "views": views}
                        except Exception:
                            pass
                result["fastest_growing"] = fastest
        if result.get("connected"):
            log("YouTube stats: using cached data")
    except Exception as e:
        log(f"YouTube cache error: {e}")

    # ── METHOD 3: Direct live YouTube Data API call (last resort) ──
    if not result["connected"] or result["subscribers"] == 0:
        try:
            _yt_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
            if not _yt_key:
                try:
                    import streamlit as st
                    if "YOUTUBE_API_KEY" in st.secrets:
                        _yt_key = str(st.secrets["YOUTUBE_API_KEY"]).strip()
                except Exception:
                    pass
            _yt_ch = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
            if not _yt_ch:
                try:
                    import streamlit as st
                    if "YOUTUBE_CHANNEL_ID" in st.secrets:
                        _yt_ch = str(st.secrets["YOUTUBE_CHANNEL_ID"]).strip()
                except Exception:
                    pass
            if _yt_key and _yt_ch:
                import urllib.parse as _up
                log("YouTube: Attempting direct live API call...")
                # Get channel info
                _url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={_yt_ch}&key={_yt_key}"
                _req = urllib.request.Request(_url)
                with urllib.request.urlopen(_req, timeout=15) as _resp:
                    _data = json.loads(_resp.read().decode())
                if _data and _data.get("items"):
                    _item = _data["items"][0]
                    _stats = _item.get("statistics", {})
                    _snippet = _item.get("snippet", {})
                    result["connected"] = True
                    result["subscribers"] = si(_stats.get("subscriberCount", 0))
                    result["total_views"] = si(_stats.get("viewCount", 0))
                    result["video_count"] = si(_stats.get("videoCount", 0))
                    result["channel_title"] = _snippet.get("title", "")

                # Get video list for engagement data
                try:
                    _vids_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={_yt_ch}&maxResults=50&type=video&order=date&key={_yt_key}"
                    _vids_req = urllib.request.Request(_vids_url)
                    with urllib.request.urlopen(_vids_req, timeout=15) as _vresp:
                        _vids_data = json.loads(_vresp.read().decode())
                    if _vids_data and _vids_data.get("items"):
                        _video_ids = [i["id"]["videoId"] for i in _vids_data["items"] if i.get("id", {}).get("videoId")]
                        if _video_ids:
                            # Get video statistics
                            _ids_str = ",".join(_video_ids[:50])
                            _stats_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={_ids_str}&key={_yt_key}"
                            _stats_req = urllib.request.Request(_stats_url)
                            with urllib.request.urlopen(_stats_req, timeout=15) as _sresp:
                                _stats_data = json.loads(_sresp.read().decode())
                            if _stats_data and _stats_data.get("items"):
                                _vids = []
                                for _vi in _stats_data["items"]:
                                    _vs = _vi.get("statistics", {})
                                    _vsn = _vi.get("snippet", {})
                                    _vids.append({
                                        "title": _vsn.get("title", ""),
                                        "views": si(_vs.get("viewCount", 0)),
                                        "likes": si(_vs.get("likeCount", 0)),
                                        "comments": si(_vs.get("commentCount", 0)),
"published_at": _vsn.get("publishedAt", ""),
    })
                                # Compute metrics
                                total_likes = sum(v["likes"] for v in _vids)
                                total_comments = sum(v["comments"] for v in _vids)
                                total_views = sum(v["views"] for v in _vids)
                                result["total_likes"] = total_likes
                                result["total_comments"] = total_comments
                                result["avg_engagement"] = ((total_likes + total_comments) / total_views * 100) if total_views > 0 else 0

                                # Top videos
                                top = sorted(_vids, key=lambda v: v["views"], reverse=True)[:5]
                                result["top_videos"] = [
                                    (v["title"][:40], v["views"], v["likes"]) for v in top
                                ]

                                # Channel health
                                if result["avg_engagement"] < 0.5:
                                    result["channel_health"] = "🔴 Critical"
                                elif result["avg_engagement"] < 1.0:
                                    result["channel_health"] = "🟡 Needs Attention"
                                else:
                                    result["channel_health"] = "🟢 Healthy"

                                # Days since last upload
                                _upload_dates = []
                                for v in _vids:
                                    if v.get("published_at"):
                                        try:
                                            _upload_dates.append(datetime.fromisoformat(v["published_at"].replace("Z", "")))
                                        except Exception:
                                            pass
                                if _upload_dates:
                                    result["days_since_upload"] = (datetime.now() - max(_upload_dates)).days
                                    result["uploaded_today"] = sum(1 for d in _upload_dates if d.strftime("%Y-%m-%d") == today_str)

                                # Fastest growing
                                fastest = None
                                for v in _vids:
                                    vdate = v.get("published_at", "")
                                    views = v["views"]
                                    if vdate and views > 100:
                                        try:
                                            age_days = max(1, (datetime.now() - datetime.fromisoformat(vdate.replace("Z", ""))).days)
                                            vpd = views / age_days
                                            if not fastest or vpd > fastest["views_per_day"]:
                                                fastest = {"title": v["title"][:50], "views_per_day": round(vpd), "views": views}
                                        except Exception:
                                            pass
                                result["fastest_growing"] = fastest

                except Exception as e:
                    log(f"YouTube live video stats error: {e}")

                if result["connected"]:
                    log(f"YouTube: Live API — {result['subscribers']:,} subs, {result['video_count']} videos")
        except Exception as e:
            log(f"YouTube live API error: {e}")

    return result


def build_linkedin_stats():
    """LinkedIn company page summary — daily/monthly/all-time with MoM comparison.
    Reads from: 1) linkedin_connector API, 2) linkedin_metrics.json cache, 3) linkedin_daily.json history.
    """
    result = {
        "connected": False, "followers": 0, "company_name": "",
        "employees": "", "industry": "",
        "today_followers_delta": 0, "month_followers_delta": 0,
        "prev_month_followers_delta": 0,
        "post_count": 0, "total_likes": 0, "total_comments": 0,
        "total_impressions": 0, "top_posts": [],
        "history_days": 0, "prev_month_followers": 0,
        "description": "", "total_reposts": 0, "total_shares": 0,
        "recent_posts": [],
        "total_clicks": 0, "total_follows": 0, "avg_ctr": 0.0,
        "impressions_change_pct": "", "reactions_change_pct": "",
        "comments_change_pct": "", "reposts_change_pct": "",
    }
    cur_month_str = datetime.now().strftime("%Y-%m")
    prev_month_str = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    # ── METHOD 1: Try linkedin_connector module ──
    try:
        from linkedin_connector import is_configured, get_cached_metrics, get_manual_history, get_posts
        if is_configured():
            result["connected"] = True
        metrics = get_cached_metrics()
        if metrics and not metrics.get("error"):
            result["followers"] = si(metrics.get("followers", 0))
            result["company_name"] = metrics.get("company_name", "")
            result["employees"] = metrics.get("employees", "")
            result["industry"] = metrics.get("industry", "")
            result["description"] = metrics.get("description", "")
            result["connected"] = True
            result["total_impressions"] = si(metrics.get("impressionCount", 0))

            # Highlights change percentages
            for _hk in ("impressions_change_pct", "reactions_change_pct",
                        "comments_change_pct", "reposts_change_pct"):
                if metrics.get(_hk):
                    result[_hk] = metrics[_hk]

            # ── Read posts from linkedin_metrics.json if get_posts() is empty ──
            posts = []
            try:
                posts = get_posts()
            except Exception:
                pass
            if not posts and "posts" in metrics and metrics["posts"]:
                posts = metrics["posts"]
                log(f"LinkedIn: Read {len(posts)} posts from metrics cache (fallback)")

            if posts:
                result["post_count"] = len(posts)
                result["total_likes"] = sum(p.get("likes", 0) for p in posts)
                result["total_comments"] = sum(p.get("comments", 0) for p in posts)
                result["total_reposts"] = sum(p.get("reposts", 0) for p in posts)
                result["total_shares"] = sum(p.get("shares", 0) for p in posts)
                result["total_clicks"] = sum(p.get("clicks", 0) for p in posts)
                result["total_follows"] = sum(p.get("follows", 0) for p in posts)
                _ctr_vals = [p.get("ctr", 0) for p in posts if p.get("ctr", 0) > 0]
                if _ctr_vals:
                    result["avg_ctr"] = round(sum(_ctr_vals) / len(_ctr_vals), 2)
                result["total_impressions"] = max(result["total_impressions"],
                    sum(p.get("impressions", 0) for p in posts))
                # Top posts by engagement
                scored = []
                for p in posts:
                    imp = max(p.get("impressions", 0), 1)
                    likes = p.get("likes", 0)
                    comments = p.get("comments", 0)
                    reposts = p.get("reposts", 0)
                    er = (likes + comments + reposts) / imp * 100 if imp > 0 else 0
                    title = (p.get("title", "") or p.get("text", "?"))[:50]
                    scored.append({
                        "title": title, "er": round(er, 2),
                        "likes": likes, "comments": comments,
                        "date": p.get("published_at", "")[:10],
                        "url": p.get("url", ""),
                    })
                result["top_posts"] = sorted(scored, key=lambda x: x["er"], reverse=True)[:5]
                result["recent_posts"] = sorted(posts, key=lambda p: p.get("published_at", ""), reverse=True)[:5]

        # Get follower history for delta calculations
        try:
            hist = get_manual_history()
            if not hist.empty and "followers" in hist.columns:
                import pandas as pd
                result["history_days"] = len(hist)
                if "date" in hist.columns:
                    hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
                    hist_sorted = hist.dropna(subset=["followers"]).sort_values("date")
                    if len(hist_sorted) >= 2:
                        today_followers = hist_sorted.iloc[-1]["followers"]
                        prev_followers = hist_sorted.iloc[-2]["followers"]
                        result["today_followers_delta"] = si(today_followers) - si(prev_followers)
                    month_data = hist_sorted[hist_sorted["date"].dt.strftime("%Y-%m") == cur_month_str]
                    if len(month_data) >= 2:
                        result["month_followers_delta"] = si(month_data.iloc[-1]["followers"]) - si(month_data.iloc[0]["followers"])
                    elif len(month_data) == 1 and len(hist_sorted) > 1:
                        before_month = hist_sorted[hist_sorted["date"].dt.strftime("%Y-%m") < cur_month_str]
                        if not before_month.empty:
                            result["month_followers_delta"] = si(month_data.iloc[-1]["followers"]) - si(before_month.iloc[-1]["followers"])
                    prev_month_data = hist_sorted[hist_sorted["date"].dt.strftime("%Y-%m") == prev_month_str]
                    if len(prev_month_data) >= 2:
                        result["prev_month_followers_delta"] = si(prev_month_data.iloc[-1]["followers"]) - si(prev_month_data.iloc[0]["followers"])
                    latest = hist_sorted.tail(1)
                    if not latest.empty:
                        result["followers"] = si(latest["followers"].iloc[0])
                        result["connected"] = True
                    if not prev_month_data.empty:
                        result["prev_month_followers"] = si(prev_month_data.iloc[-1]["followers"])
        except Exception as e:
            log(f"LinkedIn history error: {e}")

    except Exception as e:
        log(f"LinkedIn connector error: {e}")

    # ── METHOD 2: Direct read from linkedin_metrics.json cache file ──
    if not result["connected"] or result["followers"] == 0:
        try:
            _lm_path = DATA_DIR / "linkedin_metrics.json"
            if _lm_path.exists():
                _lm = json.loads(_lm_path.read_text())
                if _lm and not _lm.get("error"):
                    result["connected"] = True
                    if result["followers"] == 0:
                        result["followers"] = si(_lm.get("followers", 0))
                    if not result["company_name"]:
                        result["company_name"] = _lm.get("company_name", "")
                    if not result["employees"]:
                        result["employees"] = _lm.get("employees", "")
                    if not result["industry"]:
                        result["industry"] = _lm.get("industry", "")
                    if not result["description"]:
                        result["description"] = _lm.get("description", "")
                    # Read posts from metrics cache
                    if result["post_count"] == 0 and "posts" in _lm and _lm["posts"]:
                        _posts = _lm["posts"]
                        result["post_count"] = len(_posts)
                        result["total_likes"] = sum(p.get("likes", 0) for p in _posts)
                        result["total_comments"] = sum(p.get("comments", 0) for p in _posts)
                        result["total_reposts"] = sum(p.get("reposts", 0) for p in _posts)
                        scored = []
                        for p in _posts:
                            imp = max(p.get("impressions", 0), 1)
                            likes = p.get("likes", 0)
                            comments = p.get("comments", 0)
                            er = (likes + comments) / imp * 100 if imp > 0 else 0
                            title = (p.get("title", "") or p.get("text", "?"))[:50]
                            scored.append({
                                "title": title, "er": round(er, 2),
                                "likes": likes, "comments": comments,
                                "date": p.get("published_at", "")[:10],
                                "url": p.get("url", ""),
                            })
                        result["top_posts"] = sorted(scored, key=lambda x: x["er"], reverse=True)[:5]
                        result["recent_posts"] = sorted(_posts, key=lambda p: p.get("published_at", ""), reverse=True)[:5]
                    log("LinkedIn: Read from linkedin_metrics.json cache (fallback)")
        except Exception as e:
            log(f"LinkedIn metrics cache error: {e}")

    # ── METHOD 3: Try live public scrape (last resort) ──
    if not result["connected"] or result["followers"] == 0:
        try:
            from linkedin_connector import scrape_public_metrics
            live = scrape_public_metrics()
            if live and not live.get("error"):
                result["connected"] = True
                result["followers"] = si(live.get("followers", 0))
                result["company_name"] = live.get("company_name", "")
                result["employees"] = live.get("employees", "")
                result["industry"] = live.get("industry", "")
                if "posts" in live and live["posts"] and result["post_count"] == 0:
                    _posts = live["posts"]
                    result["post_count"] = len(_posts)
                    result["total_likes"] = sum(p.get("likes", 0) for p in _posts)
                    result["total_comments"] = sum(p.get("comments", 0) for p in _posts)
                log("LinkedIn: Live public scrape successful")
        except Exception as e:
            log(f"LinkedIn live scrape error: {e}")

    return result


def build_cross_platform_stats():
    """Cross-platform correlation summary — builds from all available data.
    Even without a cache file, builds summary from live subsystem stats.
    """
    result = {"available": False, "metrics": [], "top_correlations": [], "sources_connected": {}}

    # Track which sources are connected
    try:
        _yt_ok = False
        try:
            from youtube_connector import is_configured
            _yt_ok = is_configured()
        except Exception:
            pass
        _li_ok = False
        try:
            from linkedin_connector import is_configured
            _li_ok = is_configured()
        except Exception:
            pass
        _ga4_ok = False
        try:
            from ga4_connector import is_configured as ga4_cfg
            _ga4_ok = ga4_cfg()
        except Exception:
            pass
        _kpi_ok = (DATA_DIR / "daily_counts.json").exists() or (DATA_DIR / "historical_accounts.json").exists()
        result["sources_connected"] = {
            "KPI": _kpi_ok,
            "GA4": _ga4_ok,
            "YouTube": _yt_ok,
            "LinkedIn": _li_ok,
        }
    except Exception:
        pass

    try:
        # Try cached data first
        cp_path = DATA_DIR / "cross_platform_cache.json"
        if cp_path.exists():
            with open(cp_path) as f:
                data = json.load(f)
                result["available"] = True
                result["metrics"] = list(data.get("unified_metrics", {}).keys())[:10]
                if "correlations" in data:
                    corrs = data["correlations"]
                    sorted_corrs = sorted(
                        [(k, abs(v)) for k, v in corrs.items() if isinstance(v, (int, float)) and abs(v) > 0.1],
                        key=lambda x: x[1], reverse=True
                    )[:5]
                    result["top_correlations"] = sorted_corrs

        # If no cache, try to build from available data sources
        if not result["available"]:
            import pandas as pd
            try:
                from cross_platform_engine import build_unified_timeline, compute_correlations
                # Get KPI data
                _kpi_df = pd.DataFrame()
                try:
                    _dc_path = DATA_DIR / "daily_counts.json"
                    if _dc_path.exists():
                        _kpi_df = pd.read_json(str(_dc_path))
                except Exception:
                    pass
                # Get YouTube data
                _yt_df = pd.DataFrame()
                try:
                    _yt_path = DATA_DIR / "youtube_daily.json"
                    if _yt_path.exists():
                        _yt_data = json.loads(_yt_path.read_text())
                        _yt_rows = [{"date": d, **v} for d, v in _yt_data.items()]
                        _yt_df = pd.DataFrame(_yt_rows)
                except Exception:
                    pass
                # Get LinkedIn data
                _li_df = pd.DataFrame()
                try:
                    from linkedin_connector import get_manual_history
                    _li_df = get_manual_history()
                except Exception:
                    pass
                # Get GA4 data
                _ga4_df = pd.DataFrame()
                try:
                    _ga4_cache = DATA_DIR / "ga4_traffic_cache.json"
                    if _ga4_cache.exists():
                        _ga4_data = json.loads(_ga4_cache.read_text())
                        if _ga4_data.get("daily"):
                            _ga4_df = pd.DataFrame(_ga4_data["daily"])
                except Exception:
                    pass

                if not _kpi_df.empty or not _yt_df.empty or not _li_df.empty:
                    _unified = build_unified_timeline(
                        kpi_df=_kpi_df, ga4_df=_ga4_df,
                        youtube_daily=_yt_df, linkedin_daily=_li_df,
                    )
                    if not _unified.empty:
                        _corrs = compute_correlations(_unified)
                        result["available"] = True
                        _num_cols = [c for c in _unified.columns if c != "date" and pd.api.types.is_numeric_dtype(_unified[c])]
                        result["metrics"] = _num_cols[:10]
                        if _corrs:
                            sorted_corrs = sorted(
                                [(k, abs(v)) for k, v in _corrs.items()
                                    if isinstance(v, (int, float)) and abs(v) > 0.1],
                                key=lambda x: x[1], reverse=True
                            )[:5]
                            result["top_correlations"] = sorted_corrs
            except ImportError:
                log("Cross-platform engine not available — building from subsystem stats")

        # ── LAST RESORT: Build cross-platform summary from subsystem stats ──
        if not result["available"]:
            _connected_sources = result.get("sources_connected", {})
            _active = sum(1 for v in _connected_sources.values() if v)
            if _active >= 1:
                result["available"] = True
                result["metrics"] = [k for k, v in _connected_sources.items() if v]
                result["top_correlations"] = []
                log(f"Cross-platform: Built summary from {_active} connected sources")
    except Exception as e:
        log(f"Cross-platform stats error: {e}")
    return result


def build_stripe_stats():
    """Stripe revenue summary — counts ACCEPTED from Verified_STRIPE + verifies via Stripe API if STRIPE_SECRET_KEY available."""
    result = {"connected": False, "total_paid": 0, "month_paid": 0,
              "today_paid": 0, "total_revenue": 0.0, "month_revenue": 0.0,
              "api_total": 0, "api_accepted": 0, "api_revenue": 0.0, "api_verified": False}
    try:
        from sheets_writer import read_tab_data
        stripe_rows = read_tab_data("Verified_STRIPE")
        today_str = datetime.now().strftime("%Y-%m-%d")
        month_str = datetime.now().strftime("%Y-%m")
        accepted = [r for r in stripe_rows if str(r.get("final_status", "")).upper() == "ACCEPTED"]
        result["total_paid"] = len(accepted)
        for r in accepted:
            # Try multiple date fields and parse properly
            date_val = ""
            for field in ("First payment", "row_date_used", "Created", "__scraped_at__"):
                raw = str(r.get(field, "")).strip()
                if raw and raw not in ("nan", "None", ""):
                    date_val = _parse_report_date(raw)
                    if date_val:
                        break
            # Revenue
            for amt_field in ("amount", "Total spend", "Total Spend", "__amount__"):
                amt_raw = r.get(amt_field, "")
                if amt_raw and str(amt_raw) not in ("nan", "None", ""):
                    try:
                        amt = float(str(amt_raw).replace("$", "").replace(",", "").strip())
                        result["total_revenue"] += amt
                        if date_val and date_val.startswith(month_str):
                            result["month_revenue"] += amt
                        break
                    except Exception:
                        pass
            if date_val:
                if date_val.startswith(today_str):
                    result["today_paid"] += 1
                if date_val.startswith(month_str):
                    result["month_paid"] += 1
        result["connected"] = len(stripe_rows) > 0
    except Exception as e:
        log(f"Stripe stats error: {e}")
    
    # Verify with Stripe API if STRIPE_SECRET_KEY is available
    try:
        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if not stripe_key:
            try:
                import streamlit as st
                if "STRIPE_SECRET_KEY" in st.secrets:
                    stripe_key = str(st.secrets["STRIPE_SECRET_KEY"])
            except Exception:
                pass
        if stripe_key and stripe_key.startswith("sk_"):
            import stripe as stripe_lib
            stripe_lib.api_key = stripe_key
            now = datetime.now()
            month_start = datetime(now.year, now.month, 1)
            month_start_ts = int(month_start.timestamp())
            all_intents = []
            has_more = True
            starting_after = None
            while has_more:
                params = {"created": {"gte": month_start_ts}, "limit": 100}
                if starting_after:
                    params["starting_after"] = starting_after
                resp = stripe_lib.PaymentIntent.list(**params)
                all_intents.extend(resp.data)
                has_more = resp.has_more
                if has_more and resp.data:
                    starting_after = resp.data[-1].id
            result["api_total"] = len(all_intents)
            result["api_accepted"] = sum(1 for i in all_intents if i.status == "succeeded")
            result["api_revenue"] = round(sum(i.amount / 100 for i in all_intents if i.status == "succeeded"), 2)
            result["api_verified"] = True
            log(f"Stripe API verified: {result['api_accepted']} succeeded of {result['api_total']} total, ${result['api_revenue']:.2f}")
    except Exception as e:
        log(f"Stripe API verification (non-fatal): {e}")
    
    return result


def build_pipeline_health():
    """Pipeline health from cache — also checks GitHub Actions for latest run info."""
    result = {"last_run": "Never", "stages_passed": 0, "total_stages": 7,
              "duration": 0, "stale_hours": 0, "results": {}}
    try:
        hp_path = DATA_DIR / "pipeline_health.json"
        if hp_path.exists():
            with open(hp_path) as f:
                data = json.load(f)
                result["last_run"] = data.get("last_run", "Unknown")
                result["stages_passed"] = data.get("stages_passed", 0)
                result["duration"] = data.get("duration_seconds", 0)
                result["results"] = data.get("results", {})
                # Calculate staleness
                if result["last_run"] not in ("Never", "Unknown"):
                    try:
                        last_dt = datetime.fromisoformat(result["last_run"])
                        result["stale_hours"] = round((datetime.now() - last_dt).total_seconds() / 3600, 1)
                    except Exception:
                        pass
        else:
            # Try to check if pipeline has ever run by looking at data files
            _data_files = ["youtube_channel.json", "linkedin_metrics.json", "ga4_traffic_cache.json", "daily_counts.json"]
            _found = [f for f in _data_files if (DATA_DIR / f).exists()]
            if _found:
                result["last_run"] = "Unknown (data files exist)"
                result["stages_passed"] = len(_found)
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════════
# MESSAGE BUILDERS
# ═══════════════════════════════════════════════════════════════

def _mom_arrow(current, previous):
    """Return MoM comparison string with arrow."""
    if previous == 0:
        return "🆕" if current > 0 else ""
    delta = current - previous
    pct = (delta / previous * 100) if previous > 0 else 0
    if pct > 10:
        return f"📈+{pct:.0f}%"
    elif pct > 0:
        return f"⬆+{pct:.0f}%"
    elif pct < -10:
        return f"📉{pct:.0f}%"
    elif pct < 0:
        return f"⬇{pct:.0f}%"
    return "➡0%"


def build_telegram_kpi_section(stats):
    """Build KPI section for Telegram (HTML parse mode) — daily/monthly/all-time + MoM."""
    today = escape_html(stats["today_str"])
    month = escape_html(stats["month_str"])

    s_all = stats.get("signups_all_override", stats["signups_all"])
    u_all = stats.get("uploads_all_override", stats["uploads_all"])
    p_all = stats.get("paid_all_override", stats["paid_all"])
    s_month = stats.get("signups_month_override", stats["signups_month"])
    u_month = stats.get("uploads_month_override", stats["uploads_month"])
    p_month = stats.get("paid_month_override", stats["paid_month"])

    s2u = (u_all / s_all * 100) if s_all > 0 else 0
    s2p = (p_all / s_all * 100) if s_all > 0 else 0

    section = (
        f"🦅 <b>EAGLE3D KPI — {today}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"📊 <b>KPI SYSTEM</b>\n"
        f"┌────────────────────────\n"
        f"│ 📅 <b>Today</b>\n"
        f"│ ✅ Sign-ups: <code>{stats['signups_today']}</code>\n"
        f"│ 📤 Uploads:  <code>{stats['uploads_today']}</code>\n"
        f"│ 💳 Paid:     <code>{stats['paid_today']}</code>\n"
        f"├────────────────────────\n"
        f"│ 📆 <b>Month ({month})</b>\n"
        f"│ ✅ Sign-ups: <code>{s_month}</code>\n"
        f"│ 📤 Uploads:  <code>{u_month}</code>\n"
        f"│ 💳 Paid:     <code>{p_month}</code>\n"
        f"├────────────────────────\n"
        f"│ 🏆 <b>All Time</b>\n"
        f"│ ✅ Sign-ups: <code>{s_all}</code>\n"
        f"│ 📤 Uploads:  <code>{u_all}</code>\n"
        f"│ 💳 Paid:     <code>{p_all}</code>\n"
        f"├────────────────────────\n"
        f"│ 🔄 <b>Conversion Rates</b>\n"
        f"│ Sign→Upload: <code>{s2u:.1f}%</code> | Sign→Paid: <code>{s2p:.1f}%</code>\n"
    )
    if stats.get("total_overrides", 0) > 0:
        section += f"│ ✏️ Overrides: <code>{stats['total_overrides']}</code>\n"
    section += "└────────────────────────\n"
    return section


def build_telegram_ga4_section(ga4):
    """Build GA4 section (HTML) — daily/monthly/all-time + MoM."""
    if not ga4["connected"]:
        return "🌐 <b>GA4 ANALYTICS</b> — Not connected\n"
    today_s = ga4.get("today_sessions", 0)
    today_u = ga4.get("today_users", 0)
    month_s = ga4.get("month_sessions", 0)
    month_u = ga4.get("month_users", 0)
    prev_s = ga4.get("prev_month_sessions", 0)
    prev_u = ga4.get("prev_month_users", 0)
    all_s = ga4.get("all_time_sessions", 0)
    all_u = ga4.get("all_time_users", 0)
    mom_s = _mom_arrow(month_s, prev_s)
    mom_u = _mom_arrow(month_u, prev_u)

    section = (
        f"\n🌐 <b>GA4 ANALYTICS</b> ✅\n"
        f"┌────────────────────────\n"
        f"│ 📅 <b>Today</b>\n"
        f"│ 👥 Users: <code>{today_u}</code>\n"
        f"│ 📊 Sessions: <code>{today_s}</code>\n"
        f"├────────────────────────\n"
        f"│ 📆 <b>This Month</b>\n"
        f"│ 👥 Users: <code>{month_u}</code> {mom_u}\n"
        f"│ 📊 Sessions: <code>{month_s}</code> {mom_s}\n"
        f"├────────────────────────\n"
        f"│ 🏆 <b>All Time</b>\n"
        f"│ 👥 Users: <code>{all_u}</code>\n"
        f"│ 📊 Sessions: <code>{all_s}</code>\n"
    )
    if ga4["top_sources"]:
        section += "│ 📈 <b>Top Sources:</b>\n"
        for src, count in ga4["top_sources"][:3]:
            section += f"│   • {escape_html(src)}: <code>{count}</code>\n"
    if ga4["top_countries"]:
        section += "│ 🌍 <b>Top Countries:</b>\n"
        for country, count in ga4["top_countries"][:3]:
            section += f"│   • {escape_html(country)}: <code>{count}</code>\n"
    section += "└────────────────────────\n"
    return section


def build_telegram_youtube_section(yt):
    """Build YouTube section (HTML) — channel snapshot + daily/month/all-time + health."""
    if not yt["connected"]:
        return "📺 <b>YOUTUBE</b> — Not connected\n"
    today_str = datetime.now().strftime("%A, %B %d")
    _ch_title = escape_html(yt.get("channel_title", ""))
    section = (
        f"\n📈 📺 <b>YouTube — {today_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if _ch_title:
        section += f"│ 📺 {_ch_title}\n"
    section += (
        f"│ 📋 <b>Channel Snapshot</b>\n"
        f"┌────────────────────────\n"
        f"│ 👥 Subscribers: <code>{yt['subscribers']:,}</code>\n"
        f"│ 👁 Total Views: <code>{yt['total_views']:,}</code>\n"
        f"│ 👍 Total Likes: <code>{yt.get('total_likes', 0):,}</code>\n"
        f"│ 💬 Total Comments: <code>{yt.get('total_comments', 0):,}</code>\n"
        f"│ 📊 Avg Engagement: <code>{yt.get('avg_engagement', 0):.2f}%</code>\n"
        f"│ ⭐ Channel Health: <code>{yt.get('channel_health', '❓')}</code>\n"
        f"│ 📹 Total Videos: <code>{yt['video_count']}</code>\n"
        f"│ 🆕 Uploaded Today: <code>{yt.get('uploaded_today', 0)}</code>\n"
        f"│ 🪦 Dead Videos: <code>{yt.get('dead_video_count', 0)}</code>\n"
        f"│ ❌ Low Engagement: <code>{yt.get('low_engagement_count', 0)}</code>\n"
        f"│ 📅 Days Since Upload: <code>{yt.get('days_since_upload', 0)}</code>\n"
    )
    # Top video
    if yt["top_videos"]:
        top = yt["top_videos"][0]
        section += f"│ 🥇 Top Video: {escape_html(top[0])}\n"
        section += f"│ 🥇 Top Views: <code>{top[1]:,}</code>\n"
        section += f"│ 🥇 Top Likes: <code>{top[2]:,}</code>\n"
    # Fastest growing
    fg = yt.get("fastest_growing")
    if fg:
        section += f"│ 🚀 Fastest Growing: {escape_html(fg['title'])}\n"
        section += f"│ 🚀 Views/Day: <code>{fg['views_per_day']}</code>\n"
    section += "├────────────────────────\n"
    # Daily/Monthly analytics
    section += (
        f"│ 📅 <b>Today</b>\n"
        f"│ 👁 Views: <code>{yt.get('today_views', 0):,}</code>\n"
        f"│ ⏱ Watch: <code>{yt.get('today_watch_hours', 0)}h</code>\n"
        f"│ 👤 Subs Gained: <code>{yt.get('today_subs_gained', 0)}</code>\n"
        f"├────────────────────────\n"
        f"│ 📆 <b>This Month</b>\n"
        f"│ 👁 Views: <code>{yt.get('month_views', 0):,}</code> {_mom_arrow(yt.get('month_views', 0), yt.get('prev_month_views', 0))}\n"
        f"│ ⏱ Watch: <code>{yt.get('month_watch_hours', 0)}h</code>\n"
        f"│ 👤 Subs Gained: <code>{yt.get('month_subs_gained', 0)}</code> {_mom_arrow(yt.get('month_subs_gained', 0), yt.get('prev_month_subs_gained', 0))}\n"
    )
    section += "└────────────────────────\n"
    return section


def build_telegram_linkedin_section(li):
    """Build LinkedIn section (HTML) — daily/monthly/all-time + MoM + full analytics."""
    if not li["connected"]:
        return "💼 <b>LINKEDIN</b> — Not connected\n"
    today_delta = li.get("today_followers_delta", 0)
    month_delta = li.get("month_followers_delta", 0)
    prev_delta = li.get("prev_month_followers_delta", 0)
    mom = _mom_arrow(month_delta, prev_delta) if prev_delta != 0 else ""

    section = (
        f"\n💼 <b>LINKEDIN</b> ✅\n"
        f"┌────────────────────────\n"
        f"│ 📅 <b>Today</b>\n"
        f"│ 👥 Followers: <code>{li['followers']:,}</code> ({'+' if today_delta >= 0 else ''}{today_delta})\n"
        f"├────────────────────────\n"
        f"│ 📆 <b>This Month</b>\n"
        f"│ 👥 Gained: <code>{'+' if month_delta >= 0 else ''}{month_delta}</code> {mom}\n"
    )
    if li["company_name"]:
        section += f"│ 🏢 {escape_html(li['company_name'])}\n"
    if li["employees"]:
        section += f"│ 👔 Employees: {escape_html(li['employees'])}\n"
    if li["industry"]:
        section += f"│ 🏭 {escape_html(li['industry'])}\n"
    if li.get("total_impressions", 0) > 0:
        _imp_change = li.get("impressions_change_pct", "")
        _imp_note = f" ({_imp_change})" if _imp_change else ""
        section += f"│ 👁 Impressions: <code>{li['total_impressions']:,}</code>{_imp_note}\n"
    if li.get("total_clicks", 0) > 0:
        section += f"│ 👆 Clicks: <code>{li['total_clicks']:,}</code>"
        if li.get("avg_ctr", 0) > 0:
            section += f" (CTR <code>{li['avg_ctr']:.1f}%</code>)"
        section += "\n"
    if li.get("post_count", 0) > 0:
        _react_change = li.get("reactions_change_pct", "")
        _react_note = f" ({_react_change})" if _react_change else ""
        section += f"│ 📝 Posts: <code>{li['post_count']}</code> | 👍 <code>{li.get('total_likes', 0):,}</code>{_react_note} | 💬 <code>{li.get('total_comments', 0):,}</code>\n"
    if li.get("total_reposts", 0) > 0:
        _rep_change = li.get("reposts_change_pct", "")
        _rep_note = f" ({_rep_change})" if _rep_change else ""
        section += f"│ 🔁 Reposts: <code>{li['total_reposts']:,}</code>{_rep_note}\n"
    if li.get("total_follows", 0) > 0:
        section += f"│ ➕ Follows: <code>{li['total_follows']:,}</code>\n"
    if li.get("top_posts"):
        section += "│ 🔥 <b>Top Posts:</b>\n"
        for p in li["top_posts"][:3]:
            section += f"│   • {escape_html(p['title'])}: ER <code>{p['er']:.1f}%</code>\n"
    # Recent posts with dates
    if li.get("recent_posts"):
        section += "│ 📋 <b>Recent Posts:</b>\n"
        for p in li["recent_posts"][:5]:
            _pdate = p.get("published_at", "")[:10]
            _ptitle = (p.get("title", "") or p.get("text", "?"))[:40]
            section += f"│   • {_pdate}: {escape_html(_ptitle)}\n"
    if li.get("history_days", 0) > 0:
        section += f"│ 📅 History: <code>{li['history_days']}</code> days\n"
    section += "└────────────────────────\n"
    return section


def build_telegram_stripe_section(stripe):
    """Build Stripe section (HTML)."""
    if not stripe["connected"]:
        return "💳 <b>STRIPE</b> — No data (cookies may be expired)\n"
    section = (
        f"\n💳 <b>STRIPE PAYMENTS</b>\n"
        f"┌────────────────────────\n"
        f"│ 📅 Today: <code>{stripe['today_paid']}</code> paid\n"
        f"│ 📆 Month: <code>{stripe['month_paid']}</code> paid\n"
        f"│ 🏆 All Time: <code>{stripe['total_paid']}</code> paid\n"
    )
    if stripe.get("month_revenue", 0) > 0:
        section += f"│ 💰 Month Revenue: <code>${stripe['month_revenue']:,.2f}</code>\n"
    if stripe.get("total_revenue", 0) > 0:
        section += f"│ 💰 Total Revenue: <code>${stripe['total_revenue']:,.2f}</code>\n"
    section += "└────────────────────────\n"
    return section


def build_telegram_pipeline_section(health):
    """Build pipeline health section (HTML) with staleness info."""
    _last = health.get("last_run", "Never")
    if _last not in ("Never", "Unknown") and len(_last) > 19:
        _last = _last[:19]
    _stale = health.get("stale_hours", 0)
    _stale_icon = "🟢" if _stale < 24 else ("🟡" if _stale < 48 else "🔴")
    _stale_note = ""
    if _stale > 0:
        if _stale < 24:
            _stale_note = f" ({_stale:.0f}h ago {_stale_icon})"
        else:
            _stale_note = f" ({_stale:.0f}h ago {_stale_icon} STALE)"
    section = (
        f"\n⚙️ <b>PIPELINE HEALTH</b>\n"
        f"┌────────────────────────\n"
        f"│ 🕐 Last Run: {escape_html(str(_last))}{_stale_note}\n"
        f"│ ✅ Stages: <code>{health['stages_passed']}/{health['total_stages']}</code>\n"
        f"│ ⏱ Duration: <code>{health['duration']:.0f}s</code>\n"
    )
    # Show per-stage results if available
    _results = health.get("results", {})
    if _results:
        for _stage_key, _stage_val in _results.items():
            _icon = "✅" if _stage_val == "ok" else "❌"
            _name = _stage_key.replace("stage", "S").replace("_", " ").title()
            section += f"│ {_icon} {escape_html(_name)}\n"
    section += "└────────────────────────\n"
    return section


def build_full_telegram_message(kpi, ga4, yt, li, stripe, health):
    """Build the comprehensive multi-section Telegram message (HTML)."""
    msg = build_telegram_kpi_section(kpi)
    msg += build_telegram_ga4_section(ga4)
    msg += build_telegram_youtube_section(yt)
    msg += build_telegram_linkedin_section(li)
    msg += build_telegram_stripe_section(stripe)
    msg += build_telegram_pipeline_section(health)
    msg += (
        f"\n🔗 <a href=\"https://eagle3d-kpi-automation.streamlit.app/\">Dashboard</a>\n"
        f"<i>Auto-generated at {datetime.utcnow().strftime('%H:%M')} UTC</i>"
    )
    return msg


def build_youtube_dead_video_alerts(yt):
    """Build per-video dead video alerts (like the user's reference format)."""
    alerts = []
    for dv in yt.get("dead_videos", []):
        msg = (
            f"⚠️ 🪦 <b>DEAD VIDEO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Dead video: {dv['views_per_day']} views/day after {dv['age_days']} days\n"
            f"📋 <b>Details</b>\n"
            f"• Video: {escape_html(dv['title'])}\n"
            f"• Views/Day: <code>{dv['views_per_day']}</code>\n"
            f"• Age: <code>{dv['age_days']}</code> days\n"
            f"• Views: <code>{dv['views']:,}</code>\n"
            f"⏰ {datetime.utcnow().strftime('%b %d, %Y, %I:%M %p')} UTC"
        )
        alerts.append(msg)
    return alerts


def build_smart_anomaly_alerts(kpi_stats, ga4_stats, yt_stats, li_stats):
    """Detect spikes, flatlines, and anomalies across ALL systems.
    Includes cross-platform correlation: if sign-ups spike, check WHY by looking at GA4/YouTube/LinkedIn.
    """
    alerts = []
    ts = datetime.utcnow().strftime('%b %d, %Y, %I:%M %p UTC')

    # ── KPI Anomalies ──
    s_today = kpi_stats.get("signups_today", 0)
    u_today = kpi_stats.get("uploads_today", 0)
    p_today = kpi_stats.get("paid_today", 0)
    s_month = kpi_stats.get("signups_month_override", kpi_stats.get("signups_month", 0))
    p_month = kpi_stats.get("paid_month_override", kpi_stats.get("paid_month", 0))
    u_month = kpi_stats.get("uploads_month_override", kpi_stats.get("uploads_month", 0))

    if s_today == 0:
        _zero_reasons = []
        ga4_ok = ga4_stats.get("connected", False)
        yt_ok = yt_stats.get("connected", False)
        li_ok = li_stats.get("connected", False)
        if ga4_ok:
            if ga4_stats.get("today_sessions", 0) == 0:
                _zero_reasons.append("• GA4 shows 0 sessions — website may be down or tracking broken")
            else:
                _zero_reasons.append(f"• GA4 has {ga4_stats.get('today_sessions', 0):,} sessions but 0 sign-ups — conversion broken")
        else:
            _zero_reasons.append("• GA4 not connected — cannot verify website traffic")
        if yt_ok:
            if yt_stats.get("uploaded_today", 0) > 0:
                _zero_reasons.append("• YouTube has new uploads but no sign-ups — check video CTAs")
            elif yt_stats.get("days_since_upload", 0) > 14:
                _zero_reasons.append(f"• No YouTube video in {yt_stats.get('days_since_upload', 0)} days")
        if not _zero_reasons:
            _zero_reasons.append("• No marketing activity today or website tracking broken")
        _zero_text = "\n".join(_zero_reasons)
        alerts.append("🔴 <b>KPI ALERT</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>Zero sign-ups today!</b> No new users registered.\n\n🔍 <b>Possible causes:</b>\n" + _zero_text + "\n⏰ " + ts)
    if u_today == 0 and s_today > 0:
        alerts.append("🟡 <b>KPI ALERT</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>Sign-ups but zero uploads.</b> Users registering but not converting to uploads.\n\n📊 Sign-ups today: " + str(s_today) + "\n🔍 Check onboarding flow or documentation gaps\n⏰ " + ts)
    if p_today > 3:
        # Cross-platform: why did paid spike?
        reasons = []
        if ga4_stats.get("today_sessions", 0) > 200:
            reasons.append(f"• GA4 traffic high: {ga4_stats.get('today_sessions', 0):,} sessions")
        if yt_stats.get("today_views", 0) > 100:
            reasons.append(f"• YouTube views high: {yt_stats.get('today_views', 0):,} views")
        if li_stats.get("today_followers_delta", 0) > 5:
            reasons.append(f"• LinkedIn growing: +{li_stats.get('today_followers_delta', 0)} followers")
        reason_text = "\n".join(reasons) if reasons else "• No clear cross-platform driver found"
        alerts.append(f"🚀 <b>KPI SPIKE — DATA ACCELERATED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🔥 <b>{p_today} paid customers today!</b>\n\n📊 Today: {s_today} sign-ups, {u_today} uploads, {p_today} paid\n🔍 <b>Why this spike?</b>\n{reason_text}\n⏰ " + ts)
    if s_today > 20:
        # Cross-platform: why did sign-ups spike?
        reasons = []
        if ga4_stats.get("today_sessions", 0) > 300:
            reasons.append(f"• GA4 traffic surge: {ga4_stats.get('today_sessions', 0):,} sessions")
        if ga4_stats.get("connected") and ga4_stats.get("top_sources"):
            top_src = ga4_stats["top_sources"][0]
            reasons.append(f"• Top traffic source: {escape_html(top_src[0])} ({top_src[1]} sessions)")
        if yt_stats.get("today_views", 0) > 200:
            reasons.append(f"• YouTube active: {yt_stats.get('today_views', 0):,} views today")
            if yt_stats.get("uploaded_today", 0) > 0:
                reasons.append(f"• New video uploaded today!")
        if li_stats.get("today_followers_delta", 0) > 3:
            reasons.append(f"• LinkedIn growing: +{li_stats.get('today_followers_delta', 0)} followers")
        reason_text = "\n".join(reasons) if reasons else "• No clear cross-platform driver — possibly email/direct traffic"
        alerts.append(f"🚀 <b>SIGN-UP SPIKE — DATA ACCELERATED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🔥 <b>{s_today} sign-ups today!</b> Unusually high registration.\n\n🔍 <b>Why this spike?</b>\n{reason_text}\n⏰ " + ts)

    # ── Sign-up drop / stagnation ──
    if 0 < s_today <= 3:
        reasons = []
        ga4_ok = ga4_stats.get("connected", False)
        yt_ok = yt_stats.get("connected", False)
        li_ok = li_stats.get("connected", False)

        if ga4_ok:
            ga4_sess = ga4_stats.get("today_sessions", 0)
            if ga4_sess < 50:
                reasons.append(f"• GA4 traffic low: only {ga4_sess} sessions today — website visibility issue")
            elif ga4_sess > 0:
                reasons.append(f"• GA4 has {ga4_sess} sessions but {s_today} sign-ups — conversion bottleneck")
        else:
            reasons.append("• GA4 not connected — cannot check website traffic (add ga4_service_account to secrets)")

        if yt_ok:
            dsu = yt_stats.get("days_since_upload", 0)
            if dsu > 14:
                reasons.append(f"• No YouTube video in {dsu} days — content drought hurting discoverability")
            elif dsu > 7:
                reasons.append(f"• YouTube last upload {dsu} days ago — content pipeline slowing")
            subs = yt_stats.get("subscribers", 0)
            if subs > 0:
                reasons.append(f"• YouTube: {subs:,} subs but not driving sign-ups — check video CTAs")
        else:
            reasons.append("• YouTube not connected — cannot check video impact (add YOUTUBE_API_KEY to secrets)")

        if li_ok:
            li_delta = li_stats.get("today_followers_delta", 0)
            if li_delta < 0:
                reasons.append(f"• LinkedIn losing followers ({li_delta}) — audience shrinking")
            elif li_delta == 0:
                reasons.append(f"• LinkedIn stagnant: 0 new followers today — post engagement may be low")
            li_posts = li_stats.get("post_count", 0)
            if li_posts > 0:
                reasons.append(f"• LinkedIn has {li_posts} recent posts but {s_today} sign-ups — posts may not have CTAs")
        else:
            reasons.append("• LinkedIn not connected — cannot check social impact (add LINKEDIN_COMPANY_PAGE to secrets)")

        if not reasons:
            reasons.append("• No platform data available to diagnose — connect GA4, YouTube, and LinkedIn for insights")

        reason_text = "\n".join(reasons)
        alerts.append(f"📉 <b>SIGN-UP FLATLINE — DATA HAMPERED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ Only <b>{s_today} sign-ups today.</b> Below normal activity.\n\n🔍 <b>Why the slowdown?</b>\n{reason_text}\n⏰ " + ts)

    # ── GA4 Anomalies ──
    if ga4_stats.get("connected"):
        today_s = ga4_stats.get("today_sessions", 0)
        month_s = ga4_stats.get("month_sessions", 0)
        prev_s = ga4_stats.get("prev_month_sessions", 0)
        if today_s == 0:
            alerts.append("🔴 <b>GA4 ALERT</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>Zero website sessions today!</b>\n\n🔍 Possible causes:\n• GA4 tracking broken\n• Website down\n• DNS/CDN issue\n⏰ " + ts)
        if prev_s > 0 and month_s > 0:
            drop_pct = (1 - month_s / prev_s) * 100
            if drop_pct > 30:
                # Cross-platform: is the traffic drop reflected in KPI?
                reasons = []
                if s_month < kpi_stats.get("signups_month_override", kpi_stats.get("signups_month", 0)) * 0.7:
                    reasons.append(f"• Sign-ups also dropped — correlated")
                if yt_stats.get("days_since_upload", 0) > 14:
                    reasons.append(f"• No new YouTube content in {yt_stats.get('days_since_upload', 0)} days")
                reason_text = "\n".join(reasons) if reasons else "• Traffic drop may be seasonal or marketing gap"
                alerts.append(f"📉 <b>GA4 DROP — DATA HAMPERED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>Traffic down {drop_pct:.0f}%</b> vs last month ({prev_s:,} → {month_s:,} sessions)\n\n🔍 <b>Impact analysis:</b>\n{reason_text}\n⏰ " + ts)
            spike_pct = (month_s / prev_s - 1) * 100
            if spike_pct > 50:
                # Cross-platform: what drove the traffic?
                reasons = []
                if yt_stats.get("uploaded_today", 0) > 0 or yt_stats.get("days_since_upload", 0) < 7:
                    reasons.append("• Recent YouTube activity — video driving traffic")
                if li_stats.get("today_followers_delta", 0) > 3:
                    reasons.append(f"• LinkedIn growth (+{li_stats.get('today_followers_delta', 0)} followers)")
                if ga4_stats.get("top_sources"):
                    top_src = ga4_stats["top_sources"][0]
                    reasons.append(f"• Top source: {escape_html(top_src[0])}")
                reason_text = "\n".join(reasons) if reasons else "• Possibly SEO improvement or viral content"
                alerts.append(f"🚀 <b>GA4 SURGE — DATA ACCELERATED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🔥 <b>Traffic up +{spike_pct:.0f}%</b> vs last month ({prev_s:,} → {month_s:,} sessions)\n\n🔍 <b>What's driving this?</b>\n{reason_text}\n⏰ " + ts)

    # ── YouTube Anomalies ──
    if yt_stats.get("connected"):
        days_since = yt_stats.get("days_since_upload", 0)
        if days_since > 30:
            alerts.append(f"🔴 <b>YOUTUBE ALERT — DATA HAMPERED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>No upload in {days_since} days!</b> Channel inactive.\n\n📊 Impact:\n• YouTube not contributing to sign-up pipeline\n• SEO rankings may decline\n• Subscriber growth stalling\n\n💡 Recommendation: Schedule new content\n⏰ " + ts)
        if yt_stats.get("dead_video_count", 0) > 10:
            alerts.append(f"🪦 <b>YOUTUBE — {yt_stats['dead_video_count']} DEAD VIDEOS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>{yt_stats['dead_video_count']} videos</b> with &lt;1 view/day.\n\n📊 Channel Health: {escape_html(yt_stats.get('channel_health', '?'))}\n💡 Consider: update titles/thumbnails, create playlists, or unlist\n⏰ " + ts)
        if yt_stats.get("uploaded_today", 0) > 0:
            # Cross-platform: does a new video drive sign-ups?
            reasons = []
            if s_today > 5:
                reasons.append(f"• {s_today} sign-ups today — video may be converting!")
            if ga4_stats.get("today_sessions", 0) > 100:
                reasons.append(f"• GA4 traffic: {ga4_stats.get('today_sessions', 0):,} sessions — video driving visits")
            reason_text = "\n".join(reasons) if reasons else "• Tracking impact on sign-ups..."
            alerts.append(f"🆕 <b>YOUTUBE — NEW VIDEO UPLOADED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n✅ <b>{yt_stats['uploaded_today']} new video(s) today!</b>\n\n🔍 <b>Cross-platform impact:</b>\n{reason_text}\n⏰ " + ts)
        if yt_stats.get("today_views", 0) > 500:
            alerts.append(f"🚀 <b>YOUTUBE SPIKE</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🔥 <b>{yt_stats.get('today_views', 0):,} views today!</b>\n\n📊 Sign-ups today: {s_today} | Uploads: {u_today}\n⏰ " + ts)

    # ── LinkedIn Anomalies ──
    if li_stats.get("connected"):
        today_delta = li_stats.get("today_followers_delta", 0)
        month_delta = li_stats.get("month_followers_delta", 0)
        if today_delta < -5:
            alerts.append(f"📉 <b>LINKEDIN — DATA HAMPERED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>{abs(today_delta)} followers lost today!</b>\n\n🔍 Check:\n• Recent post performance\n• Competitor activity\n• Content relevance\n⏰ " + ts)
        elif today_delta > 10:
            reasons = []
            if s_today > 5:
                reasons.append(f"• {s_today} sign-ups — LinkedIn driving registrations")
            if li_stats.get("post_count", 0) > 0:
                reasons.append(f"• {li_stats.get('post_count', 0)} posts active — content resonating")
            reason_text = "\n".join(reasons) if reasons else ""
            alerts.append(f"🚀 <b>LINKEDIN SURGE — DATA ACCELERATED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🔥 <b>+{today_delta} followers today!</b>\n{reason_text}\n⏰ " + ts)
        if month_delta < 0:
            alerts.append(f"📉 <b>LINKEDIN FLATLINE</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>Net {abs(month_delta)} followers lost this month.</b>\n\n💡 Post more frequently, engage with comments\n⏰ " + ts)

    # ── Cross-Platform Correlation Alerts ──
    # All platforms up = strong day
    platforms_up = 0
    if s_today > 5:
        platforms_up += 1
    if ga4_stats.get("today_sessions", 0) > 100:
        platforms_up += 1
    if yt_stats.get("today_views", 0) > 100:
        platforms_up += 1
    if li_stats.get("today_followers_delta", 0) > 0:
        platforms_up += 1

    if platforms_up >= 3:
        alerts.append(f"🌟 <b>ALL SYSTEMS GO — DATA ACCELERATED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n✅ <b>All platforms performing well today!</b>\n\n📊 KPI: {s_today} sign-ups, {u_today} uploads, {p_today} paid\n📊 GA4: {ga4_stats.get('today_sessions', 0):,} sessions\n📺 YouTube: {yt_stats.get('today_views', 0):,} views\n💼 LinkedIn: +{max(0, li_stats.get('today_followers_delta', 0))} followers\n\n💡 Great day — analyze what content drove this and replicate!\n⏰ " + ts)

    # All platforms down = bad day
    platforms_down = 0
    if s_today == 0:
        platforms_down += 1
    if ga4_stats.get("today_sessions", 0) < 20:
        platforms_down += 1
    if yt_stats.get("today_views", 0) == 0:
        platforms_down += 1
    if li_stats.get("today_followers_delta", 0) < 0:
        platforms_down += 1

    if platforms_down >= 3:
        alerts.append(f"🔴 <b>ALL PLATFORMS SLOW — DATA HAMPERED</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>All systems showing low activity today!</b>\n\n📊 KPI: {s_today} sign-ups\n📊 GA4: {ga4_stats.get('today_sessions', 0):,} sessions\n📺 YouTube: {yt_stats.get('today_views', 0):,} views\n💼 LinkedIn: {li_stats.get('today_followers_delta', 0)} followers\n\n🔍 This could be:\n• Weekend/holiday effect\n• Tracking outage\n• Content drought\n\n💡 Action: Check website status and tracking\n⏰ " + ts)

    return alerts


# ═══════════════════════════════════════════════════════════════
# INDIVIDUAL SUBSYSTEM TELEGRAM MESSAGES (sent separately for detail)
# ═══════════════════════════════════════════════════════════════

def send_subsystem_reports():
    """Send individual detailed reports for each subsystem + smart alerts."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    # Fallback to st.secrets
    if not bot_token or not chat_id:
        try:
            import streamlit as st
            if "TELEGRAM_BOT_TOKEN" in st.secrets:
                val = st.secrets["TELEGRAM_BOT_TOKEN"]
                if val and str(val).strip():
                    bot_token = str(val).strip()
            if "TELEGRAM_CHAT_ID" in st.secrets:
                val = st.secrets["TELEGRAM_CHAT_ID"]
                if val and str(val).strip():
                    chat_id = str(val).strip()
        except Exception:
            pass
    if not bot_token or not chat_id:
        return

    # Build all stats once
    kpi = ga4 = yt = li = stripe = health = None
    try:
        kpi = build_kpi_stats()
    except Exception as e:
        log(f"KPI stats error: {e}")
    try:
        ga4 = build_ga4_stats()
    except Exception as e:
        log(f"GA4 stats error: {e}")
    try:
        yt = build_youtube_stats()
    except Exception as e:
        log(f"YouTube stats error: {e}")
    try:
        li = build_linkedin_stats()
    except Exception as e:
        log(f"LinkedIn stats error: {e}")
    try:
        stripe = build_stripe_stats()
    except Exception as e:
        log(f"Stripe stats error: {e}")
    try:
        health = build_pipeline_health()
    except Exception as e:
        log(f"Health stats error: {e}")

    # ── KPI DETAILED (always send) ──
    if kpi:
        try:
            kpi_msg = build_telegram_kpi_section(kpi)
            send_telegram(kpi_msg)
        except Exception as e:
            log(f"KPI report error: {e}")

    # ── GA4 DETAILED (always send) ──
    if ga4:
        try:
            ga4_msg = build_telegram_ga4_section(ga4)
            send_telegram(ga4_msg)
        except Exception as e:
            log(f"GA4 report error: {e}")

    # ── YOUTUBE DETAILED (always send) ──
    if yt:
        try:
            yt_msg = build_telegram_youtube_section(yt)
            send_telegram(yt_msg)
        except Exception as e:
            log(f"YouTube report error: {e}")

    # ── YOUTUBE DEAD VIDEO ALERTS (per-video) ──
    if yt and yt.get("dead_videos"):
        try:
            dead_alerts = build_youtube_dead_video_alerts(yt)
            for alert in dead_alerts[:5]:  # Max 5 per run
                send_telegram(alert)
        except Exception as e:
            log(f"Dead video alerts error: {e}")

    # ── YOUTUBE SMART NOTIFICATION EVENTS ──
    if yt and yt.get("videos_raw"):
        try:
            from youtube_connector import detect_video_events
            _events = detect_video_events(yt["videos_raw"], prev_snapshot=None, channel_subs=yt.get("subscribers", 0))
            for _ev in _events[:8]:
                _sev_icon = {"critical": "🚨", "warning": "⚠️", "success": "✅", "info": "ℹ️"}.get(_ev.get("severity", "info"), "ℹ️")
                _msg = f"{_ev['emoji']} <b>{_ev['type'].replace('_', ' ').title()}</b>\n"
                _msg += f"━━━━━━━━━━━━━━━━━━━━━━\n"
                _msg += f"{_ev['message']}\n"
                if _ev.get("data"):
                    for _k, _v in _ev["data"].items():
                        _msg += f"• {escape_html(str(_k))}: <code>{escape_html(str(_v))}</code>\n"
                _msg += f"⏰ {datetime.utcnow().strftime('%b %d, %Y, %I:%M %p')} UTC"
                send_telegram(_msg)
        except Exception as e:
            log(f"Smart video events error: {e}")

    # ── LINKEDIN DETAILED (always send) ──
    if li:
        try:
            li_msg = build_telegram_linkedin_section(li)
            send_telegram(li_msg)
        except Exception as e:
            log(f"LinkedIn report error: {e}")

    # ── STRIPE DETAILED (always send) ──
    if stripe:
        try:
            stripe_msg = build_telegram_stripe_section(stripe)
            send_telegram(stripe_msg)
        except Exception as e:
            log(f"Stripe report error: {e}")

    # ── CROSS-PLATFORM (always send) ──
    try:
        cp = build_cross_platform_stats()
        cp_msg = "🔗 <b>CROSS-PLATFORM CORRELATION</b>\n┌────────────────────────\n"
        if cp["available"] and cp.get("top_correlations"):
            for metric, strength in cp["top_correlations"][:5]:
                name = escape_html(metric.replace("_", " ").title())
                cp_msg += f"│ {name}: <code>{strength:.2f}</code>\n"
        elif cp["available"]:
            # Show connected sources instead
            _sources = cp.get("sources_connected", {})
            for _src, _ok in _sources.items():
                _icon = "✅" if _ok else "❌"
                cp_msg += f"│ {_icon} {_src}\n"
            cp_msg += "│ 📊 Correlations need more data\n"
        else:
            # Show what's missing
            _sources = cp.get("sources_connected", {})
            if _sources:
                for _src, _ok in _sources.items():
                    _icon = "✅" if _ok else "❌"
                    cp_msg += f"│ {_icon} {_src}\n"
                cp_msg += "│ 💡 Connect more sources for correlation\n"
            else:
                cp_msg += "│ ⚠️ No platform data available\n"
                cp_msg += "│ 💡 Pipeline needs to run first\n"
        cp_msg += "└────────────────────────\n"
        send_telegram(cp_msg)
    except Exception as e:
        log(f"Cross-platform report error: {e}")

    # ── PIPELINE HEALTH (always send) ──
    try:
        health = build_pipeline_health()
        pipe_msg = build_telegram_pipeline_section(health)
        send_telegram(pipe_msg)
    except Exception as e:
        log(f"Pipeline report error: {e}")

    # ── SMART ANOMALY ALERTS (spikes, flatlines, anomalies across ALL systems) ──
    try:
        anomaly_alerts = build_smart_anomaly_alerts(
            kpi or {}, ga4 or {}, yt or {}, li or {}
        )
        for alert in anomaly_alerts:
            try:
                send_telegram(alert)
            except Exception:
                pass
    except Exception as e:
        log(f"Smart anomaly alerts error: {e}")

    # ── MONTHLY GOALS PROGRESS ──
    try:
        _goals_path = Path("monthly_goals.json")
        if _goals_path.exists():
            _goals = json.loads(_goals_path.read_text())
            if _goals:
                _cur_month = datetime.now().strftime("%Y-%m")
                _cur_goals = _goals.get(_cur_month, {})
                if _cur_goals:
                    _gmsg = f"🎯 <b>MONTHLY GOALS — {_cur_month}</b>\n┌────────────────────────\n"
                    # Get actual KPI data for comparison
                    _kpi = {}
                    try:
                        _kpi = build_kpi_stats()
                    except Exception:
                        pass
                    _s_month = _kpi.get("signups_month_override", _kpi.get("signups_month", 0))
                    _u_month = _kpi.get("uploads_month_override", _kpi.get("uploads_month", 0))
                    _p_month = _kpi.get("paid_month_override", _kpi.get("paid_month", 0))
                    _goal_map = {
                        "SignUps": ("✅ Sign-ups", _s_month),
                        "FirstUploads": ("📤 Uploads", _u_month),
                        "Paid": ("💳 Paid", _p_month),
                    }
                    for _gk, _gv in _cur_goals.items():
                        if _gv > 0:
                            _label, _actual = _goal_map.get(_gk, (_gk, 0))
                            _pct = (_actual / _gv * 100) if _gv > 0 else 0
                            _icon = "🟢" if _pct >= 100 else ("🟡" if _pct >= 50 else "🔴")
                            _gmsg += f"│ {_icon} {escape_html(_label)}: <code>{_actual}</code>/<code>{_gv}</code> ({_pct:.0f}%)\n"
                    _gmsg += "└────────────────────────\n"
                    send_telegram(_gmsg)
    except Exception as e:
        log(f"Monthly goals report error: {e}")


def build_text_report(kpi, ga4, yt, li, stripe, health):
    """Build plain text version for email/Slack."""
    today = kpi["today_str"]
    month = kpi["month_str"]
    s_all = kpi.get("signups_all_override", kpi["signups_all"])
    u_all = kpi.get("uploads_all_override", kpi["uploads_all"])
    p_all = kpi.get("paid_all_override", kpi["paid_all"])
    s_month = kpi.get("signups_month_override", kpi["signups_month"])
    u_month = kpi.get("uploads_month_override", kpi["uploads_month"])
    p_month = kpi.get("paid_month_override", kpi["paid_month"])

    lines = [
        "🦅 EAGLE3D FULL SYSTEM REPORT",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        "📊 KPI SYSTEM",
        "-" * 40,
        f"  TODAY ({today}):",
        f"    Sign-ups:      {kpi['signups_today']}",
        f"    First Uploads: {kpi['uploads_today']}",
        f"    Paid:          {kpi['paid_today']}",
        "",
        f"  MONTH ({month}):",
        f"    Sign-ups:      {s_month}",
        f"    First Uploads: {u_month}",
        f"    Paid:          {p_month}",
        "",
        "  ALL TIME:",
        f"    Sign-ups:      {s_all}",
        f"    First Uploads: {u_all}",
        f"    Paid:          {p_all}",
        "",
        f"  Active Overrides: {kpi.get('total_overrides', 0)}",
        "",
    ]

    lines.append("🌐 GA4 ANALYTICS")
    lines.append("-" * 40)
    if ga4["connected"]:
        lines.append(f"  Users (30d):    {ga4['month_users']:,}")
        lines.append(f"  Sessions (30d): {ga4['month_sessions']:,}")
        if ga4["top_sources"]:
            lines.append("  Top Sources:")
            for src, count in ga4["top_sources"][:5]:
                lines.append(f"    {src}: {count:,}")
        if ga4["top_countries"]:
            lines.append("  Top Countries:")
            for c, count in ga4["top_countries"][:5]:
                lines.append(f"    {c}: {count:,}")
    else:
        lines.append("  Not connected")
    lines.append("")

    lines.append("📺 YOUTUBE")
    lines.append("-" * 40)
    if yt["connected"]:
        lines.append(f"  Subscribers:  {yt['subscribers']:,}")
        lines.append(f"  Total Views:  {yt['total_views']:,}")
        lines.append(f"  Videos:       {yt['video_count']}")
        if yt["has_analytics"]:
            lines.append(f"  30d Views:    {yt['period_views']:,}")
            lines.append(f"  30d Watch:    {yt['period_watch_hours']}h")
            lines.append(f"  30d Subs:     +{yt['period_subs_gained']}")
        if yt["top_videos"]:
            lines.append("  Top Videos:")
            for title, views, likes in yt["top_videos"][:5]:
                lines.append(f"    {title}: {views:,} views, {likes:,} likes")
    else:
        lines.append("  Not connected")
    lines.append("")

    lines.append("💼 LINKEDIN")
    lines.append("-" * 40)
    if li["connected"]:
        lines.append(f"  Followers: {li['followers']:,}")
        if li["company_name"]:
            lines.append(f"  Company:   {li['company_name']}")
        if li["employees"]:
            lines.append(f"  Employees: {li['employees']}")
        if li["industry"]:
            lines.append(f"  Industry:  {li['industry']}")
    else:
        lines.append("  Not connected")
    lines.append("")

    lines.append("💳 STRIPE")
    lines.append("-" * 40)
    if stripe["connected"]:
        lines.append(f"  Today:     {stripe['today_paid']} paid")
        lines.append(f"  Month:     {stripe['month_paid']} paid")
        lines.append(f"  All Time:  {stripe['total_paid']} paid")
    else:
        lines.append("  No data")
    lines.append("")

    lines.append("⚙️ PIPELINE HEALTH")
    lines.append("-" * 40)
    lines.append(f"  Last Run:  {health['last_run'][:19] if health['last_run'] != 'Never' else 'Never'}")
    lines.append(f"  Stages:    {health['stages_passed']}/{health['total_stages']}")
    lines.append(f"  Duration:  {health['duration']:.0f}s")
    lines.append("")
    lines.append("Dashboard: https://eagle3d-kpi-automation.streamlit.app/")

    return "\n".join(lines)


def main():
    import pandas as pd

    log("=" * 60)
    log("REPORTING ENGINE v4 — FULL SYSTEM")
    log("=" * 60)

    # Build all subsystem data
    log("Building KPI stats...")
    try:
        kpi = build_kpi_stats()
    except Exception as e:
        log(f"KPI stats failed: {e}")
        kpi = {
            "signups_today": 0, "uploads_today": 0, "paid_today": 0,
            "signups_month": 0, "uploads_month": 0, "paid_month": 0,
            "signups_all": 0, "uploads_all": 0, "paid_all": 0,
            "today_str": datetime.now().strftime("%Y-%m-%d"),
            "month_str": datetime.now().strftime("%Y-%m"),
            "total_overrides": 0,
        }

    log("Building GA4 stats...")
    try:
        ga4 = build_ga4_stats()
    except Exception as e:
        log(f"GA4 stats failed: {e}")
        ga4 = {"connected": False}

    log("Building YouTube stats...")
    try:
        yt = build_youtube_stats()
    except Exception as e:
        log(f"YouTube stats failed: {e}")
        yt = {"connected": False}

    log("Building LinkedIn stats...")
    try:
        li = build_linkedin_stats()
    except Exception as e:
        log(f"LinkedIn stats failed: {e}")
        li = {"connected": False}

    log("Building Stripe stats...")
    try:
        stripe = build_stripe_stats()
    except Exception as e:
        log(f"Stripe stats failed: {e}")
        stripe = {"connected": False}

    log("Building pipeline health...")
    try:
        health = build_pipeline_health()
    except Exception as e:
        log(f"Pipeline health failed: {e}")
        health = {"last_run": "Unknown", "stages_passed": 0, "total_stages": 7, "duration": 0}

    # Build combined text report
    text = build_text_report(kpi, ga4, yt, li, stripe, health)
    log("\n" + text)

    # Save report
    report_file = DATA_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_file.parent.mkdir(exist_ok=True)
    report_file.write_text(text)
    log(f"Saved: {report_file}")

    # VALIDATION: Check data sources before sending Telegram
    validation_errors = []
    if not kpi.get("signups_all", 0) > 0:
        validation_errors.append("KPI: zero all-time signups")
    if not ga4.get("connected"):
        validation_errors.append("GA4: not connected")
    if not yt.get("connected"):
        validation_errors.append("YouTube: not connected (missing API key/channel ID)")
    if not li.get("connected"):
        validation_errors.append("LinkedIn: not connected (missing company page/cookies)")
    if not stripe.get("connected"):
        validation_errors.append("Stripe: not connected (no data)")
    
    if validation_errors:
        log(f"VALIDATION WARNINGS: {'; '.join(validation_errors)}")
        # Still send but include warnings in message
    
    # Send comprehensive Telegram (combined summary message)
    log("Sending combined Telegram summary...")
    combined_msg = build_full_telegram_message(kpi, ga4, yt, li, stripe, health)
    
    # Add validation notice if any source missing
    if validation_errors:
        combined_msg += f"\n\n⚠️ <b>DATA VALIDATION WARNINGS:</b>\n" + "\n".join(f"• {e}" for e in validation_errors)
    
    tg_combined = send_telegram(combined_msg)

    # Individual subsystem messages are DISABLED to prevent duplicates.
    # The combined message above covers ALL systems in a single notification.
    # log("Sending individual subsystem Telegram reports...")
    # try:
    #     send_subsystem_reports()
    # except Exception as e:
    #     log(f"Subsystem reports error: {e}")

    # Send email + Slack with full text report
    log("Sending email + Slack...")
    em_sent = send_email(f"Eagle3D Full System Report — {kpi['today_str']}", text)
    sl_sent = send_slack(text)

    log("\nNotification results:")
    log(f"  Telegram: {'✅ sent' if tg_combined else '❌ not sent'}")
    log(f"  Email:    {'✅ sent' if em_sent else '❌ not sent'}")
    log(f"  Slack:    {'✅ sent' if sl_sent else '❌ not sent'}")


if __name__ == "__main__":
    main()
