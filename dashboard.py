"""
DASHBOARD v10 - Eagle3D KPI
Fixed:
- Date range filter applies to ALL metrics (cards + charts + tables)
- Disposable/Duplicate counters use correct column names
- Browse Data has date filter
- All Time vs This Month works correctly
- Daily breakdown respects selected date range
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
import requests
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="Eagle3D KPI Dashboard",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ─── CREDENTIALS ─────────────────────────────────────────────────
def get_creds_path():
    if os.path.exists("google_creds.json"):
        return "google_creds.json"
    try:
        if "GOOGLE_CREDS" in st.secrets:
            raw = st.secrets["GOOGLE_CREDS"]
            creds = json.loads(raw) if isinstance(raw, str) else dict(raw)
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json.dump(creds, tmp)
            tmp.close()
            return tmp.name
    except Exception as e:
        st.error(f"Failed to read GOOGLE_CREDS: {e}")
        st.stop()
    try:
        raw = st.secrets["GOOGLE_CREDS_JSON"]
        creds = json.loads(raw) if isinstance(raw, str) else dict(raw)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(creds, tmp)
        tmp.close()
        return tmp.name
    except Exception:
        pass
    st.error("Google credentials not found.")
    st.stop()


def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


def secret_exists(key):
    try:
        return key in st.secrets
    except Exception:
        return False


CREDS_PATH = get_creds_path()
MASTER_SHEET_URL = get_secret("MASTER_SHEET_URL")
GITHUB_TOKEN     = get_secret("GITHUB_TOKEN")
GITHUB_REPO      = get_secret("GITHUB_REPO", "fozayelibnayaz/eagle3d-kpi-automation")
WORKFLOW_FILE    = get_secret("WORKFLOW_FILE", "daily.yml")


# ─── DATA LOADING ────────────────────────────────────────────────
@st.cache_data(ttl=120)
def load_sheet(tab):
    try:
        creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(MASTER_SHEET_URL)
        ws = sh.worksheet(tab)
        data = ws.get_all_values()
        if len(data) < 2:
            return pd.DataFrame()
        headers = data[0]
        # Deduplicate column names
        seen = {}
        clean = []
        for h in headers:
            h = h.strip() if h else "unknown"
            if h in seen:
                seen[h] += 1
                clean.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                clean.append(h)
        return pd.DataFrame(data[1:], columns=clean)
    except Exception:
        return pd.DataFrame()


# ─── DATE PARSING ────────────────────────────────────────────────
import re
from email.utils import parsedate_to_datetime

DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    "%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p",
    "%m/%d/%y %I:%M %p", "%m/%d/%Y %I:%M %p",
    "%m/%d/%y", "%m/%d/%Y",
    "%a %b %d %Y", "%a %b %d %Y %H:%M:%S",
    "%b %d, %Y", "%d %b %Y",
    "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S GMT",
]


def parse_to_date(raw):
    """Parse any date string to datetime.date. Returns None on failure."""
    if not raw or str(raw).strip() in ("", "—", "-", "nan", "None"):
        return None
    raw = str(raw).strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            return dt.date()
    except Exception:
        pass

    # Try known formats
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    # ISO-like fallback
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except Exception:
            pass
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if m:
        try:
            mo, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yr < 100:
                yr += 2000
            return datetime(yr, mo, day).date()
        except Exception:
            pass
    return None
def card(label, value, color, sub=None):
    sub_html = f"<div style=\"font-size:13px;opacity:0.85;margin-top:4px;\">{sub}</div>" if sub else ""
    html = f"<div style=\"background:{color};color:white;padding:25px;border-radius:12px;text-align:center;\">"
    html += f"<div style=\"font-size:14px;opacity:0.9;\">{label}</div>"
    html += f"<div style=\"font-size:48px;font-weight:bold;margin:8px 0;\">{value}</div>"
    html += sub_html + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def n_accepted(df):
    if df.empty or "final_status" not in df.columns:
        return 0
    return int((df["final_status"].str.upper() == "ACCEPTED").sum())


def n_accepted_in_range(df, date_field, date_range):
    """Count ACCEPTED rows where date_field falls within date_range."""
    if df.empty or "final_status" not in df.columns:
        return 0
    accepted = df[df["final_status"].astype(str).str.upper() == "ACCEPTED"]
    if accepted.empty or date_range is None:
        return len(accepted) if date_range is None else 0
    if date_field not in accepted.columns:
        return 0
    
    start_date, end_date = date_range
    
    def in_range(val):
        if not val or str(val).strip() in ("", "—", "-", "nan"):
            return False
        s = str(val).strip()
        from datetime import datetime as _dt
        try:
            d = _dt.strptime(s[:10], "%Y-%m-%d").date()
            return start_date <= d <= end_date
        except Exception:
            pass
        for fmt in ["%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p",
                    "%m/%d/%y", "%m/%d/%Y", "%a %b %d %Y",
                    "%a %b %d %Y %H:%M:%S"]:
            try:
                d = _dt.strptime(s, fmt).date()
                return start_date <= d <= end_date
            except Exception:
                continue
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
            if dt:
                return start_date <= dt.date() <= end_date
        except Exception:
            pass
        return False
    
    return int(accepted[date_field].apply(in_range).sum())


def filter_df_by_date(df, date_field, date_range):
    """Filter rows where date_field is in date_range."""
    if df.empty or date_range is None:
        return df
    if date_field not in df.columns:
        return df
    
    start_date, end_date = date_range
    
    def in_range(val):
        if not val or str(val).strip() in ("", "—", "-", "nan"):
            return False
        s = str(val).strip()
        from datetime import datetime as _dt
        try:
            d = _dt.strptime(s[:10], "%Y-%m-%d").date()
            return start_date <= d <= end_date
        except Exception:
            pass
        for fmt in ["%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p",
                    "%m/%d/%y", "%m/%d/%Y", "%a %b %d %Y",
                    "%a %b %d %Y %H:%M:%S"]:
            try:
                d = _dt.strptime(s, fmt).date()
                return start_date <= d <= end_date
            except Exception:
                continue
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
            if dt:
                return start_date <= dt.date() <= end_date
        except Exception:
            pass
        return False
    
    return df[df[date_field].apply(in_range)].copy()


def get_range_label(preset, date_range):
    """Get human-readable label for the selected range."""
    if preset == "All Time" or date_range is None:
        return "All Time"
    if preset == "This Month":
        from datetime import datetime as _dt
        return _dt.now().strftime("%B %Y")
    if preset == "Last Month":
        from datetime import datetime as _dt, timedelta
        last_month = _dt.now().replace(day=1) - timedelta(days=1)
        return last_month.strftime("%B %Y")
    return preset



def n_accepted_current_month(df, date_field):
    """Count rows where final_status=ACCEPTED AND date is in current month."""
    if df.empty:
        return 0
    if "final_status" not in df.columns:
        return 0
    
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    
    # Filter to ACCEPTED
    accepted = df[df["final_status"].astype(str).str.upper() == "ACCEPTED"]
    if accepted.empty:
        return 0
    
    # Filter to current month using the date field
    if date_field not in accepted.columns:
        return 0
    
    # Parse dates and check if they're in current month
    def in_current_month(val):
        if not val or str(val).strip() in ("", "—", "-", "nan"):
            return False
        parsed = parse_to_date(val)
        if parsed is None:
            return False
        return parsed.strftime("%Y-%m") == current_month


# ─── DATE RANGE ──────────────────────────────────────────────────
def get_date_range(preset):
    today = datetime.now().date()
    if preset == "Today":
        return (today, today)
    if preset == "This Week":
        return (today - timedelta(days=today.weekday()), today)
    if preset == "Last Week":
        end = today - timedelta(days=today.weekday() + 1)
        return (end - timedelta(days=6), end)
    if preset == "Last 7 Days":
        return (today - timedelta(days=6), today)
    if preset == "Last 15 Days":
        return (today - timedelta(days=14), today)
    if preset == "Last 28 Days":
        return (today - timedelta(days=27), today)
    if preset == "This Month":
        return (today.replace(day=1), today)
    if preset == "Last Month":
        first = today.replace(day=1)
        last_prev = first - timedelta(days=1)
        return (last_prev.replace(day=1), last_prev)
    if preset == "Last 3 Months":
        return (today - timedelta(days=90), today)
    if preset == "Last 6 Months":
        return (today - timedelta(days=180), today)
    if preset == "This Year":
        return (today.replace(month=1, day=1), today)
    if preset == "Last Year":
        ly = today.year - 1
        return (datetime(ly, 1, 1).date(), datetime(ly, 12, 31).date())
    return None  # All Time


# ─── GITHUB ──────────────────────────────────────────────────────
def github_headers():
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def trigger_workflow():
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN missing"
    url = (f"https://api.github.com/repos/{GITHUB_REPO}/actions/"
           f"workflows/{WORKFLOW_FILE}/dispatches")
    try:
        r = requests.post(url, headers=github_headers(), json={"ref": "main"}, timeout=15)
        if r.status_code == 204:
            return True, "Pipeline triggered. Refresh in 5–10 minutes."
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def get_workflow_runs(limit=5):
    if not GITHUB_TOKEN:
        return []
    url = (f"https://api.github.com/repos/{GITHUB_REPO}/actions/"
           f"workflows/{WORKFLOW_FILE}/runs?per_page={limit}")
    try:
        r = requests.get(url, headers=github_headers(), timeout=15)
        if r.status_code == 200:
            return r.json().get("workflow_runs", [])
    except Exception:
        pass
    return []


def format_age(iso_str):
    if not iso_str:
        return "?"
    try:
        ts = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - ts
        s = age.total_seconds()
        if s < 60:    return f"{int(s)}s ago"
        if s < 3600:  return f"{int(s//60)}m ago"
        if s < 86400: return f"{int(s//3600)}h ago"
        return f"{int(s//86400)}d ago"
    except Exception:
        return iso_str


# ─── HELPERS ─────────────────────────────────────────────────────
def card(label, value, color, sub=None):
    sub_html = (f'<div style="font-size:13px;opacity:0.85;margin-top:4px;">{sub}</div>'
                if sub else "")
    st.markdown(
        f'<div style="background:{color};color:white;padding:25px;border-radius:12px;'
        f'text-align:center;">'
        f'<div style="font-size:14px;opacity:0.9;">{label}</div>'
        f'<div style="font-size:48px;font-weight:bold;margin:8px 0;">{value}</div>'
        f'{sub_html}</div>',
        unsafe_allow_html=True,
    )


def safe_int_col(df, col):
    if col not in df.columns:
        return pd.Series([0] * len(df))
    return pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)


def n_accepted(df):
    """Count ACCEPTED rows in a verified dataframe."""
    if df.empty or "final_status" not in df.columns:
        return 0
    return int((df["final_status"].astype(str).str.upper() == "ACCEPTED").sum())


def count_by_reason(df, keyword):
    """
    Count rows where category OR email_verdict OR verdict_reason contains keyword.
    Case-insensitive. Used for Disposable, Duplicate, etc.
    """
    if df.empty:
        return 0
    total = 0
    for col in ("category", "email_verdict", "verdict_reason", "__rejection_reason__"):
        if col in df.columns:
            total = int(df[col].astype(str).str.contains(keyword, case=False, na=False).sum())
            if total > 0:
                return total
    return 0


def filter_df_by_date_range(df, date_field, date_range):
    """
    Filter dataframe by date range using the specified date_field.
    Returns filtered dataframe.
    """
    if df.empty or date_range is None:
        return df
    if date_field not in df.columns:
        return df

    start_date, end_date = date_range
    dates = df[date_field].apply(parse_to_date)
    mask = dates.apply(
        lambda d: d is not None and start_date <= d <= end_date
    )
    return df[mask]


def count_accepted_in_range(df, date_field, date_range):
    """Count ACCEPTED rows within date range."""
    if df.empty:
        return 0
    # First filter to ACCEPTED
    if "final_status" in df.columns:
        acc = df[df["final_status"].astype(str).str.upper() == "ACCEPTED"]
    else:
        acc = df
    if acc.empty:
        return 0
    # Then filter by date range
    filtered = filter_df_by_date_range(acc, date_field, date_range)
    return len(filtered)


# ════════════════════════════════════════════════════════════════
#  SIDEBAR
# ════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("🦅 Eagle3D KPIs")
    st.divider()

    st.subheader("⚙️ Pipeline Control")
    runs = get_workflow_runs()
    if runs:
        latest = runs[0]
        status     = latest.get("status", "?")
        conclusion = latest.get("conclusion", "?")
        ago        = format_age(latest.get("created_at"))
        if status in ("in_progress", "queued"):
            st.info(f"🔄 Running ({ago})")
        elif conclusion == "success":
            st.success(f"✅ Last: SUCCESS ({ago})")
        elif conclusion == "failure":
            st.error(f"❌ Last: FAILED ({ago})")
        else:
            st.warning(f"⚠️ Last: {conclusion} ({ago})")
    else:
        st.warning("No runs found")

    if st.button("🚀 Run Pipeline Now", type="primary"):
        with st.spinner("Triggering..."):
            ok, msg = trigger_workflow()
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    if st.button("🔄 Refresh Dashboard"):
        st.cache_data.clear()
        st.rerun()

    with st.expander("Stripe Cookie Refresh"):
        st.markdown("""
**When Stripe data stops updating:**
1. Open Chrome → https://dashboard.stripe.com/customers
2. Click Cookie-Editor extension → Export as JSON
3. Paste into [GitHub Secrets](https://github.com/fozayelibnayaz/eagle3d-kpi-automation/settings/secrets/actions)
4. Update `STRIPE_COOKIES_JSON`
        """)

    st.divider()
    st.subheader("🗓 Date Filter")
    PRESETS = [
        "Today", "This Week", "Last Week", "Last 7 Days", "Last 15 Days",
        "Last 28 Days", "This Month", "Last Month", "Last 3 Months",
        "Last 6 Months", "This Year", "Last Year", "All Time", "Custom",
    ]
    preset = st.selectbox("View Range", PRESETS, index=6)  # default: This Month

    if preset == "Custom":
        custom_start = st.date_input("Start", value=datetime.now().date() - timedelta(days=30))
        custom_end   = st.date_input("End",   value=datetime.now().date())
        date_range   = (custom_start, custom_end)
    else:
        date_range = get_date_range(preset)

    st.divider()
    st.subheader("📍 Navigation")
    page = st.radio(
        "Page",
        ["📊 Dashboard", "🔍 Browse Data", "🛠 Diagnostics"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Pipeline auto-runs daily at 10 AM Bangladesh.")


# ════════════════════════════════════════════════════════════════
#  HEADER
# ════════════════════════════════════════════════════════════════
st.title("🦅 Eagle3D Streaming — KPI Dashboard")

if date_range:
    st.caption(f"Showing: **{date_range[0]}** to **{date_range[1]}** ({preset})")
else:
    st.caption("Showing: **All Time**")


# ════════════════════════════════════════════════════════════════
#  DIAGNOSTICS
# ════════════════════════════════════════════════════════════════
if page == "🛠 Diagnostics":
    st.header("System Diagnostics")
    expected = ["MASTER_SHEET_URL", "GOOGLE_CREDS", "GITHUB_TOKEN", "GITHUB_REPO", "WORKFLOW_FILE"]
    rows = []
    for k in expected:
        present = secret_exists(k)
        if present:
            val = get_secret(k)
            if k == "GITHUB_TOKEN" and val:
                shown = val[:12] + "..." + val[-4:]
            elif k == "GOOGLE_CREDS":
                shown = "✓ TOML section"
            elif isinstance(val, str) and len(val) > 60:
                shown = val[:50] + "..."
            else:
                shown = str(val)[:80]
            status = "✅"
        else:
            shown = "❌ MISSING"
            status = "❌"
        rows.append({"Secret": k, "Status": status, "Value": shown})
    st.table(pd.DataFrame(rows))

    if st.button("🧪 Test Sheet Read"):
        for tab_name in ["Daily_Counts", "Verified_FREE", "Verified_FIRST_UPLOAD", "Verified_STRIPE"]:
            df = load_sheet(tab_name)
            if df.empty:
                st.warning(f"❌ {tab_name}: empty or not found")
            else:
                st.success(f"✅ {tab_name}: {len(df)} rows, cols: {list(df.columns[:6])}")


# ════════════════════════════════════════════════════════════════
#  BROWSE DATA
# ════════════════════════════════════════════════════════════════
elif page == "🔍 Browse Data":
    st.header("Browse Customer Data")

    free   = load_sheet("Verified_FREE")
    upload = load_sheet("Verified_FIRST_UPLOAD")
    stripe = load_sheet("Verified_STRIPE")

    # Date fields per source
    DATE_FIELD = {
        "Sign-ups":         "Account Created On",
        "First Uploads":    "Upload Date",
        "Paid Subscribers": "Created",
    }

    browse_tabs = st.tabs(["📥 Sign-ups", "📦 First Uploads", "💳 Paid Subscribers"])

    for tab, (label, df) in zip(browse_tabs, [
        ("Sign-ups", free),
        ("First Uploads", upload),
        ("Paid Subscribers", stripe),
    ]):
        with tab:
            if df.empty:
                st.warning(f"No {label} data yet.")
                continue

            # ── Filters row ──
            f1, f2, f3, f4 = st.columns([2, 2, 2, 3])

            with f1:
                status_opts = ["All", "ACCEPTED only", "REJECTED only"]
                status_filter = st.selectbox("Status:", status_opts, key=f"sf_{label}")

            with f2:
                verdict_opts = ["All"]
                for col in ("email_verdict", "category"):
                    if col in df.columns:
                        verdict_opts += sorted(df[col].dropna().unique().tolist())
                        break
                verdict_filter = st.selectbox("Verdict:", verdict_opts, key=f"vf_{label}")

            with f3:
                # Date range filter within Browse Data
                date_opts = ["All Dates"] + PRESETS[:-1]  # exclude Custom
                browse_date_preset = st.selectbox("Date:", date_opts, key=f"df_{label}")
                if browse_date_preset == "All Dates":
                    browse_range = None
                else:
                    browse_range = get_date_range(browse_date_preset) or date_range

            with f4:
                search = st.text_input("Search:", key=f"sq_{label}", placeholder="email, name...")

            # ── Apply filters ──
            filt = df.copy()

            if status_filter == "ACCEPTED only" and "final_status" in filt.columns:
                filt = filt[filt["final_status"].astype(str).str.upper() == "ACCEPTED"]
            elif status_filter == "REJECTED only" and "final_status" in filt.columns:
                filt = filt[filt["final_status"].astype(str).str.upper() == "REJECTED"]

            for col in ("email_verdict", "category"):
                if verdict_filter != "All" and col in filt.columns:
                    filt = filt[filt[col].astype(str) == verdict_filter]
                    break

            date_col = DATE_FIELD.get(label)
            if browse_range and date_col and date_col in filt.columns:
                filt = filter_df_by_date_range(filt, date_col, browse_range)

            if search:
                mask = pd.Series([False] * len(filt), index=filt.index)
                for col in filt.columns:
                    mask = mask | filt[col].astype(str).str.contains(
                        search, case=False, na=False
                    )
                filt = filt[mask]

            # ── Summary metrics ──
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Showing", len(filt))
            m2.metric("Accepted", n_accepted(filt))
            m3.metric("Disposable", count_by_reason(filt, "DISPOSABLE"))
            m4.metric("Duplicate", count_by_reason(filt, "DUPLICATE"))

            st.dataframe(filt, height=500, hide_index=True)

            csv_bytes = filt.to_csv(index=False).encode("utf-8")
            st.download_button(
                f"⬇️ Download {label}",
                data=csv_bytes,
                file_name=f"{label.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                key=f"dl_{label}",
            )


# ════════════════════════════════════════════════════════════════
#  MAIN DASHBOARD
# ════════════════════════════════════════════════════════════════
else:
    # Load all sources
    free   = load_sheet("Verified_FREE")
    upload = load_sheet("Verified_FIRST_UPLOAD")
    stripe = load_sheet("Verified_STRIPE")
    daily  = load_sheet("Daily_Counts")

    if daily.empty:
        st.error("Daily_Counts not yet populated. Run the pipeline first.")
        st.stop()

    # ── Validate required columns ──
    required_cols = ["SignUps_Accepted", "FirstUploads_Accepted", "PaidSubscribers_Accepted"]
    missing = [c for c in required_cols if c not in daily.columns]
    if missing:
        st.error(f"Daily_Counts missing columns: {missing}. Re-run pipeline.")
        st.stop()

    st.caption(f"Data source columns: {', '.join(required_cols)}")

    # ── Build _dt column ──
    if "Date" in daily.columns:
        daily["_dt"] = pd.to_datetime(daily["Date"], errors="coerce").dt.date
    else:
        st.error("Daily_Counts has no 'Date' column.")
        st.stop()

    daily = daily.dropna(subset=["_dt"])

    # ── Apply date range to daily ──
    if date_range:
        daily_filtered = daily[
            (daily["_dt"] >= date_range[0]) & (daily["_dt"] <= date_range[1])
        ].copy()
    else:
        daily_filtered = daily.copy()

    # ── Integer columns ──
    daily_filtered["_signups"] = safe_int_col(daily_filtered, "SignUps_Accepted")
    daily_filtered["_uploads"] = safe_int_col(daily_filtered, "FirstUploads_Accepted")
    daily_filtered["_paid"]    = safe_int_col(daily_filtered, "PaidSubscribers_Accepted")

    # ── Period totals (from daily_filtered → SUM) ──
    sum_signups = int(daily_filtered["_signups"].sum())
    sum_uploads = int(daily_filtered["_uploads"].sum())
    sum_paid    = int(daily_filtered["_paid"].sum())

    # ── Period label for cards ──
    if date_range:
        period_label = preset
    else:
        period_label = "All Time"

    # ══════════════════════════════════════════════
    #  KPI CARDS — respects selected date range
    # ══════════════════════════════════════════════
    st.markdown(f"### 📊 Totals for: {period_label}")
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Sign-ups", sum_signups, "#3b82f6",
             f"{period_label.lower()} · verified · deduped")
    with c2:
        card("First Uploads", sum_uploads, "#22c55e",
             f"{period_label.lower()} · verified · deduped")
    with c3:
        card("Paid Subscribers", sum_paid, "#f97316",
             f"{period_label.lower()} · active")

    st.divider()

    # ══════════════════════════════════════════════
    #  LIVE SNAPSHOT — always today
    # ══════════════════════════════════════════════
    today = datetime.now().date()
    today_row = daily[daily["_dt"] == today]
    today_s = int(safe_int_col(today_row, "SignUps_Accepted").sum())
    today_u = int(safe_int_col(today_row, "FirstUploads_Accepted").sum())
    today_p = int(safe_int_col(today_row, "PaidSubscribers_Accepted").sum())

    st.markdown("### 🔴 Live Snapshot (today)")
    l1, l2, l3 = st.columns(3)
    with l1:
        card("Sign-ups",      today_s, "#1e40af", "today")
    with l2:
        card("First Uploads", today_u, "#15803d", "today")
    with l3:
        card("Paid",          today_p, "#c2410c", "today")

    st.divider()

    # ══════════════════════════════════════════════
    #  TREND CHART
    # ══════════════════════════════════════════════
    st.markdown("### 📈 Daily Trend")
    if not daily_filtered.empty:
        chart_df = daily_filtered[["_dt", "_signups", "_uploads", "_paid"]].copy()
        chart_df.columns = ["Date", "Sign-ups", "First Uploads", "Paid"]
        chart_df["Date"] = pd.to_datetime(chart_df["Date"])
        chart_df = chart_df.sort_values("Date")
        fig = px.line(
            chart_df.set_index("Date"),
            title=f"Daily Trend — {period_label}",
            markers=True,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Funnel
        funnel_df = pd.DataFrame({
            "Stage": ["Sign-ups", "First Upload", "Paid"],
            "Count": [sum_signups, sum_uploads, sum_paid],
        })
        fig2 = px.funnel(funnel_df, x="Count", y="Stage",
                         title=f"Funnel — {period_label}")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No data in selected date range.")

    # ══════════════════════════════════════════════
    #  DAILY BREAKDOWN TABLE
    # ══════════════════════════════════════════════
    st.markdown("### 📋 Daily Breakdown")
    if not daily_filtered.empty:
        show_df = daily_filtered[["_dt", "_signups", "_uploads", "_paid"]].copy()
        show_df.columns = ["Date", "Sign-ups", "First Uploads", "Paid Subscribers"]
        show_df = show_df.sort_values("Date", ascending=False)
        st.dataframe(show_df, hide_index=True, height=400)
    else:
        st.info("No rows in selected date range.")

    st.divider()

    # ══════════════════════════════════════════════
    #  GROUPED ANALYSIS
    # ══════════════════════════════════════════════
    st.markdown("### 🗓️ Grouped Analysis")
    group_by = st.radio("Group by:", ["Day", "Week", "Month", "Year"], horizontal=True)

    if not daily_filtered.empty:
        gdf = daily_filtered[["_dt", "_signups", "_uploads", "_paid"]].copy()
        gdf["_dt"] = pd.to_datetime(gdf["_dt"])
        if group_by == "Day":
            gdf["bucket"] = gdf["_dt"].dt.strftime("%Y-%m-%d")
        elif group_by == "Week":
            gdf["bucket"] = gdf["_dt"].dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
        elif group_by == "Month":
            gdf["bucket"] = gdf["_dt"].dt.strftime("%Y-%m")
        else:
            gdf["bucket"] = gdf["_dt"].dt.strftime("%Y")

        grouped = gdf.groupby("bucket").agg(
            {"_signups": "sum", "_uploads": "sum", "_paid": "sum"}
        ).reset_index()
        grouped.columns = ["Period", "Sign-ups", "First Uploads", "Paid"]

        fig3 = px.bar(
            grouped, x="Period",
            y=["Sign-ups", "First Uploads", "Paid"],
            title=f"Grouped by {group_by} — {period_label}",
            barmode="group",
        )
        st.plotly_chart(fig3, use_container_width=True)
        st.dataframe(grouped, hide_index=True)
    else:
        st.info("No data to group.")
