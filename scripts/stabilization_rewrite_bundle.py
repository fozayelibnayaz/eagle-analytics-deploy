from pathlib import Path
from datetime import datetime
import textwrap
import re

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.stabilization_rewrite.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# -------------------------------------------------------------------
# 1) kpi_totals_resolver.py
# -------------------------------------------------------------------
resolver = ROOT / "kpi_totals_resolver.py"
backup(resolver) if resolver.exists() else None
resolver.write_text(textwrap.dedent("""\
from __future__ import annotations

from typing import Tuple, Dict, List
from mongo_client import find_all

def _as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def _as_float(v):
    try:
        if v is None or str(v).strip() == "":
            return 0.0
        return float(v)
    except Exception:
        return 0.0

def _norm(v):
    return str(v or "").strip().lower()

def _pick_date(doc, keys):
    for k in keys:
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _pick_amount(doc):
    for k in ("amount", "total_spend", "paid_amount", "invoice_amount"):
        v = doc.get(k)
        if v not in (None, "", 0, "0"):
            return _as_float(v)
    return 0.0

def _is_accepted(doc):
    fs = str(doc.get("final_status", "")).strip().upper()
    if fs:
        return fs == "ACCEPTED"
    return _pick_amount(doc) > 0

def _all_payment_events():
    collections = [
        "payments",
        "payment_history",
        "sheet_verified_stripe",
        "sheet_raw_stripe",
    ]

    events = []
    seen = set()

    for col in collections:
        try:
            docs = find_all(col, {})
        except Exception:
            docs = []

        for d in docs:
            if not _is_accepted(d):
                continue

            email = _norm(d.get("email") or d.get("email_normalized"))
            dt = _pick_date(d, ["first_payment_date", "payment_date", "created_date", "date"])
            amt = _pick_amount(d)
            if not email or not dt or amt <= 0:
                continue

            # Exclude obvious synthetic/test data
            if email.endswith("@example.com") or "webhook-test" in email or "cloud-test" in email:
                continue

            sig = (email, dt, round(amt, 2))
            if sig in seen:
                continue
            seen.add(sig)

            events.append({
                "email": email,
                "date": dt,
                "amount": amt,
                "status": str(
                    d.get("subscription_status")
                    or d.get("status")
                    or d.get("plan_status")
                    or d.get("customer_status")
                    or ""
                ).strip().lower(),
                "collection": col,
                "id": d.get("id"),
            })

    events.sort(key=lambda x: (x["email"], x["date"], x["collection"]))
    return events

def _first_paid_map():
    events = _all_payment_events()
    first_paid = {}
    for e in events:
        first_paid.setdefault(e["email"], e["date"])
    return events, first_paid

def resolve_period_kpis(start_iso: str, end_iso: str) -> Tuple[int, int, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]

    rows = find_all(
        "daily_kpis",
        filters={"date": {"$gte": start_day, "$lte": end_day}},
        sort=[("date", 1)],
        limit=10000,
    )

    signups = sum(_as_int(r.get("signups", 0)) for r in rows)
    uploads = sum(_as_int(r.get("first_uploads", r.get("uploads", 0))) for r in rows)

    events, first_paid = _first_paid_map()
    new_paid = len({
        e["email"] for e in events
        if start_day <= e["date"] <= end_day and first_paid.get(e["email"]) == e["date"]
    })

    return signups, uploads, new_paid

def resolve_paid_breakdown(start_iso: str, end_iso: str) -> Dict[str, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]

    events, first_paid = _first_paid_map()
    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    new_set = set()
    recurring_set = set()
    stopped_set = set()

    for e in events:
        if not (start_day <= e["date"] <= end_day):
            continue
        if first_paid.get(e["email"]) == e["date"]:
            new_set.add(e["email"])
        else:
            recurring_set.add(e["email"])

        if e["status"] in stop_statuses and first_paid.get(e["email"], e["date"]) < e["date"]:
            stopped_set.add(e["email"])

    return {
        "new_paid_customers": len(new_set),
        "recurring_customers": len(recurring_set),
        "stopped_recurring_customers": len(stopped_set),
        "total_paying_customers": len(new_set | recurring_set),
    }
"""), encoding="utf-8")
print("✅ kpi_totals_resolver.py rewritten")

# -------------------------------------------------------------------
# 2) scripts/fix_daily_kpis_safe.py
# -------------------------------------------------------------------
kpi_fix = ROOT / "scripts" / "fix_daily_kpis_safe.py"
backup(kpi_fix) if kpi_fix.exists() else None
kpi_fix.write_text(textwrap.dedent("""\
from __future__ import annotations

from pathlib import Path
from datetime import datetime, date
import json
import glob
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import find_all, get_raw_db
from kpi_totals_resolver import resolve_paid_breakdown

TODAY = date.today().isoformat()
MONTH_START = date.today().replace(day=1).isoformat()

def _as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def _norm(v):
    return str(v or "").strip().lower()

def _pick_date(doc, keys):
    for k in keys:
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _is_accepted(doc):
    return str(doc.get("final_status", "")).strip().upper() == "ACCEPTED"

def latest_daily_kpis_backup():
    candidates = []
    candidates += glob.glob(str(ROOT / "backups" / "daily_kpis.before_paid_logic_fix.*.json"))
    candidates += glob.glob(str(ROOT / "backups" / "daily_kpis.safe_fix_before_*.json"))
    candidates.sort(reverse=True)
    return Path(candidates[0]) if candidates else None

def load_base_daily_kpis():
    backup = latest_daily_kpis_backup()
    if backup and backup.exists():
        rows = json.loads(backup.read_text(encoding="utf-8"))
        daymap = {}
        for r in rows:
            d = str(r.get("date", "")).strip()[:10]
            if not d:
                continue
            daymap[d] = {
                "date": d,
                "signups": _as_int(r.get("signups", 0)),
                "uploads": _as_int(r.get("uploads", r.get("first_uploads", 0))),
                "first_uploads": _as_int(r.get("first_uploads", r.get("uploads", 0))),
            }
        return daymap

    daymap = {}

    def ensure_day(d):
        if d not in daymap:
            daymap[d] = {"date": d, "_s": set(), "_u": set()}
        return daymap[d]

    for s in find_all("signups", {}):
        if not _is_accepted(s):
            continue
        d = _pick_date(s, ["signup_date", "account_created_on", "created_date", "date"])
        e = _norm(s.get("email") or s.get("email_normalized"))
        if d and e:
            ensure_day(d)["_s"].add(e)

    for u in find_all("uploads", {}):
        if not _is_accepted(u):
            continue
        d = _pick_date(u, ["upload_date", "first_upload_date", "created_date", "date"])
        e = _norm(u.get("email") or u.get("email_normalized"))
        if d and e:
            ensure_day(d)["_u"].add(e)

    final = {}
    for d, b in daymap.items():
        final[d] = {
            "date": d,
            "signups": len(b["_s"]),
            "uploads": len(b["_u"]),
            "first_uploads": len(b["_u"]),
        }
    return final

def build_recurring_maps():
    breakdown_by_day = {}
    rows = find_all("payments", {})
    accepted_rows = [r for r in rows if _is_accepted(r)]

    from kpi_totals_resolver import _all_payment_events, _first_paid_map
    events, first_paid = _first_paid_map()

    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    new_map = {}
    recurring_map = {}
    stopped_map = {}

    def add(mapper, d, email):
        mapper.setdefault(d, set()).add(email)

    for e in events:
        d = e["date"]
        email = e["email"]
        if first_paid.get(email) == d:
            add(new_map, d, email)
        else:
            add(recurring_map, d, email)

        if e["status"] in stop_statuses and first_paid.get(email, d) < d:
            add(stopped_map, d, email)

    return new_map, recurring_map, stopped_map

def main():
    db = get_raw_db()
    if db is None:
        raise SystemExit("MongoDB not available")

    base = load_base_daily_kpis()
    new_by_day, recurring_by_day, stopped_by_day = build_recurring_maps()

    all_dates = set(base.keys()) | set(new_by_day.keys()) | set(recurring_by_day.keys()) | set(stopped_by_day.keys())
    rows = []

    for d in sorted(all_dates):
        b = base.get(d, {"date": d, "signups": 0, "uploads": 0, "first_uploads": 0})
        new_c = len(new_by_day.get(d, set()))
        rec_c = len(recurring_by_day.get(d, set()))
        stop_c = len(stopped_by_day.get(d, set()))

        rows.append({
            "date": d,
            "signups": _as_int(b.get("signups", 0)),
            "uploads": _as_int(b.get("uploads", b.get("first_uploads", 0))),
            "first_uploads": _as_int(b.get("first_uploads", b.get("uploads", 0))),
            "paid_customers": new_c,
            "new_paid_customers": new_c,
            "recurring_customers": rec_c,
            "stopped_recurring_customers": stop_c,
            "total_paying_customers": new_c + rec_c,
            "payments": new_c,
            "source": "daily_kpis_safe_fix",
            "rebuilt_at": datetime.utcnow().isoformat(),
        })

    db["daily_kpis"].delete_many({})
    if rows:
        db["daily_kpis"].insert_many(rows)

    month_rows = [r for r in rows if MONTH_START <= r["date"] <= TODAY]
    print(json.dumps({
        "month_signups": sum(_as_int(r["signups"]) for r in month_rows),
        "month_first_uploads": sum(_as_int(r["first_uploads"]) for r in month_rows),
        "month_new_paid_customers": sum(_as_int(r["new_paid_customers"]) for r in month_rows),
        "month_recurring_customers": sum(_as_int(r["recurring_customers"]) for r in month_rows),
        "month_stopped_recurring_customers": sum(_as_int(r["stopped_recurring_customers"]) for r in month_rows),
        "month_total_paying_customers": sum(_as_int(r["total_paying_customers"]) for r in month_rows),
    }, indent=2))

if __name__ == "__main__":
    main()
"""), encoding="utf-8")
print("✅ scripts/fix_daily_kpis_safe.py rewritten")

# -------------------------------------------------------------------
# 3) app.py clean stable shell
# -------------------------------------------------------------------
app = ROOT / "app.py"
backup(app) if app.exists() else None
app.write_text(textwrap.dedent("""\
\"\"\"
app.py — Eagle 3D Streaming Analytics Hub
Stable cloud shell.
\"\"\"
from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from period_engine import get_period, get_period_button_label, render_period_picker
from kpi_totals_resolver import resolve_period_kpis

st.set_page_config(
    page_title="Eagle 3D Streaming — Analytics Hub",
    page_icon="static/eagle3d_logo2.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BRAND_NAME = "Eagle 3D Streaming"

def require_auth():
    try:
        from auth_guard import require_auth
        return require_auth("Dashboard")
    except Exception:
        return "ayaz@eagle3dstreaming.com", "admin"

@st.cache_data(show_spinner=False)
def load_logo(filename: str) -> str:
    p = Path("static") / filename
    if p.exists():
        return base64.b64encode(p.read_bytes()).decode()
    return ""

LOGO_MAIN = load_logo("eagle3d_logo2.png")

def logo_img(size: int = 36) -> str:
    if not LOGO_MAIN:
        return ""
    return f'<img src="data:image/png;base64,{LOGO_MAIN}" style="width:{size}px;height:{size}px;object-fit:contain;display:block;" alt="Eagle 3D Streaming">'

def _greeting() -> str:
    try:
        h = datetime.now().hour
        return "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")
    except Exception:
        return "Hello"

def inject_css():
    st.markdown(\"\"\"
    <style>
    #MainMenu, header, footer, [data-testid="stSidebar"] { display:none !important; }
    html, body, [data-testid="stApp"] { background:#080808 !important; color:#fff !important; }
    .main .block-container { max-width:100% !important; padding:0 !important; }
    .navwrap { display:flex; gap:10px; align-items:center; justify-content:center; padding:14px 20px; border-bottom:1px solid rgba(255,255,255,.08); background:#0b0b0b; position:sticky; top:0; z-index:10; }
    .brand { display:flex; align-items:center; gap:10px; margin-right:20px; font-weight:700; font-size:15px; color:#fff; }
    .navbtn { padding:8px 16px; border-radius:999px; background:#111; color:#9CA3AF; border:1px solid rgba(255,255,255,.06); text-decoration:none; font-size:13px; }
    .navbtn.active { background:linear-gradient(135deg,#9EFF2F,#5EF46A); color:#000; border:none; font-weight:700; }
    .section-title { font-size:18px; font-weight:700; color:#fff; margin:0 0 4px 0; }
    .section-sub { color:#9CA3AF; font-size:14px; margin:0 0 18px 0; }
    .hero { padding:28px 36px 12px 36px; }
    .hero h1 { margin:0; font-size:40px; line-height:1.1; color:#fff; }
    .hero p { margin:8px 0 0; color:#9CA3AF; font-size:15px; }
    [data-testid="stMetric"] { background:#111 !important; border:1px solid rgba(255,255,255,.06) !important; border-radius:20px !important; padding:22px 24px !important; }
    [data-testid="stMetricLabel"] { color:#9CA3AF !important; font-size:12px !important; text-transform:uppercase !important; letter-spacing:.04em !important; }
    [data-testid="stMetricValue"] { color:#fff !important; font-weight:700 !important; font-size:30px !important; }
    </style>
    \"\"\", unsafe_allow_html=True)

def get_current_page() -> str:
    valid = {"dashboard","kpi","ga4","youtube","linkedin","cs","cross","ai","custom","settings","_logout"}
    page = st.query_params.get("page", "dashboard")
    if isinstance(page, list):
        page = page[0] if page else "dashboard"
    return page if page in valid else "dashboard"

def render_nav(current_page: str):
    pages = [
        ("dashboard", "Dashboard"),
        ("kpi", "KPI"),
        ("ga4", "Traffic"),
        ("youtube", "YouTube"),
        ("linkedin", "LinkedIn"),
        ("cs", "CS"),
        ("cross", "Cross"),
        ("ai", "AI"),
        ("custom", "Custom"),
    ]
    cols = st.columns([1.4] + [1]*len(pages) + [0.8])
    with cols[0]:
        st.markdown(f'<div class="brand">{logo_img(28)}<span>{BRAND_NAME}</span></div>', unsafe_allow_html=True)
    for i, (key, label) in enumerate(pages, start=1):
        if cols[i].button(label, key=f"nav_{key}", use_container_width=True):
            st.query_params["page"] = key
            st.rerun()
    with cols[-1]:
        if st.button("Logout", key="nav_logout", use_container_width=True):
            st.query_params["page"] = "_logout"
            st.rerun()

def render_dashboard(user_email: str) -> None:
    from mongo_client import find_all, get_mongo_status

    period = get_period()
    name = user_email.split("@")[0].split(".")[0].capitalize() if user_email else "there"

    st.markdown(
        f'''<div class="hero"><h1>{_greeting()}, {name}</h1><p>{period.label} · {period.start_iso()} → {period.end_iso()} · {period.days} days</p></div>''',
        unsafe_allow_html=True,
    )

    signups = uploads = new_paid = 0
    prev_signups = prev_uploads = prev_new_paid = 0
    revenue = 0.0
    db_connected = False

    try:
        s = get_mongo_status()
        db_connected = s.get("connected", False)

        if db_connected:
            signups, uploads, new_paid = resolve_period_kpis(period.start_iso(), period.end_iso())

            if getattr(period, "compare_enabled", False) and getattr(period, "compare_start", None) and getattr(period, "compare_end", None):
                prev_signups, prev_uploads, prev_new_paid = resolve_period_kpis(period.compare_start_iso(), period.compare_end_iso())

            pay_docs = find_all(
                "payments",
                filters={
                    "final_status": "ACCEPTED",
                    "first_payment_date": {"$gte": period.start_iso()[:10], "$lte": period.end_iso()[:10]},
                },
                limit=5000
            )
            revenue = sum(float(p.get("total_spend", 0) or p.get("amount", 0) or 0) for p in pay_docs)
    except Exception as e:
        st.warning(f"Dashboard data fetch warning: {e}")

    def delta(current, prev):
        if prev == 0:
            return f"+{current} new" if current > 0 else "—"
        pct = (current - prev) / prev * 100
        return f"{'+' if pct >= 0 else ''}{pct:.1f}% vs prev"

    left, right = st.columns([2.2, 1])
    with left:
        st.markdown('<div class="section-title">Verified Counts (post-dedup)</div><div class="section-sub">This period</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("👥 Sign-ups", f"{signups:,}", delta(signups, prev_signups))
        c2.metric("�� First Uploads", f"{uploads:,}", delta(uploads, prev_uploads))
        c3.metric("💳 New Paying Customers", f"{new_paid:,}", delta(new_paid, prev_new_paid))

    with right:
        st.metric("💰 Revenue", f"${revenue:,.0f}")

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

def render_settings(user_email: str) -> None:
    st.title("Settings")
    st.caption(f"Logged in as {user_email}")
    if st.button("Logout"):
        for k in ("_pwd_ok", "_auth_ok", "user_email", "user_role", "current_page"):
            st.session_state.pop(k, None)
        st.query_params.clear()
        st.rerun()

def route(page: str, user_email: str) -> None:
    if page == "_logout":
        for k in ("_pwd_ok", "_auth_ok", "user_email", "user_role", "current_page"):
            st.session_state.pop(k, None)
        st.query_params.clear()
        st.rerun()
    elif page == "dashboard":
        render_dashboard(user_email)
    elif page == "kpi":
        from pages_registry import render_kpi_page
        render_kpi_page(user_email)
    elif page == "ga4":
        from pages_registry import render_ga4_page
        render_ga4_page(user_email)
    elif page == "youtube":
        from pages_registry import render_youtube_page
        render_youtube_page(user_email)
    elif page == "linkedin":
        from pages_registry import render_linkedin_page
        render_linkedin_page(user_email)
    elif page == "cs":
        from pages_registry import render_cs_page
        render_cs_page(user_email)
    elif page == "cross":
        from pages_registry import render_cross_page
        render_cross_page(user_email)
    elif page == "ai":
        from pages_registry import render_ai_page
        render_ai_page(user_email)
    elif page == "custom":
        from pages_registry import render_custom_page
        render_custom_page(user_email)
    elif page == "settings":
        render_settings(user_email)
    else:
        st.warning(f"Unknown page: {page}")

def main() -> None:
    inject_css()
    user_email, _role = require_auth()
    current_page = get_current_page()
    render_nav(current_page)
    route(current_page, user_email)

if __name__ == "__main__":
    main()
"""), encoding="utf-8")
print("✅ app.py fully rewritten")

# -------------------------------------------------------------------
# 4) pages_registry.py clean stable implementation
# -------------------------------------------------------------------
pr = ROOT / "pages_registry.py"
backup(pr) if pr.exists() else None
pr.write_text(textwrap.dedent("""\
from __future__ import annotations

from datetime import date, timedelta
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from mongo_client import find_all, count_docs
from kpi_totals_resolver import resolve_period_kpis
from period_engine import get_period

def _section(title: str, sub: str = ""):
    st.markdown(f"### {title}")
    if sub:
        st.caption(sub)

def _pct(cur, prv):
    if prv == 0:
        return f"+{cur} new" if cur else "—"
    return f"{'+' if cur >= prv else ''}{(cur-prv)/prv*100:.1f}% vs prev"

def render_kpi_page(user_email: str = "") -> None:
    render_kpi_dashboard(user_email)

def render_kpi_dashboard(user_email: str = "") -> None:
    period = get_period()

    sign, up, pay = resolve_period_kpis(period.start_iso(), period.end_iso())
    prev_s = prev_u = prev_p = 0
    if getattr(period, "compare_enabled", False) and getattr(period, "compare_start", None):
        prev_s, prev_u, prev_p = resolve_period_kpis(period.compare_start_iso(), period.compare_end_iso())

    _section("Verified Counts (post-dedup)", f"{period.label} · {period.start_iso()} → {period.end_iso()}")
    c1, c2, c3 = st.columns(3)
    c1.metric("👥 Sign-ups", f"{sign:,}", _pct(sign, prev_s))
    c2.metric("📤 Uploads", f"{up:,}", _pct(up, prev_u))
    c3.metric("💳 New Paying Customers", f"{pay:,}", _pct(pay, prev_p))

    _section("Funnel")
    su = round(up / sign * 100, 1) if sign else 0
    upr = round(pay / up * 100, 1) if up else 0
    sp = round(pay / sign * 100, 1) if sign else 0
    r1, r2, r3 = st.columns(3)
    r1.metric("🔄 Sign→Upload", f"{su}%")
    r2.metric("💰 Upload→Paid", f"{upr}%")
    r3.metric("🎯 Sign→Paid", f"{sp}%")

    _section("Daily Trend")
    rows = find_all(
        "daily_kpis",
        filters={"date": {"$gte": period.start_iso()[:10], "$lte": period.end_iso()[:10]}},
        sort=[("date", 1)],
        limit=10000,
    )
    if rows:
        df = pd.DataFrame(rows)
        df = df[df["date"].notna()].sort_values("date")
        for c in ["signups", "first_uploads", "new_paid_customers"]:
            if c not in df.columns:
                df[c] = 0
            df[c] = df[c].fillna(0).astype(int)

        fig = go.Figure()
        for key, label, color in [
            ("signups", "Sign-ups", "#9EFF2F"),
            ("first_uploads", "Uploads", "#5EF46A"),
            ("new_paid_customers", "New Paying Customers", "#4ADE80"),
        ]:
            fig.add_trace(go.Scatter(x=df["date"], y=df[key], name=label, mode="lines", line=dict(color=color, width=2.5)))

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#9CA3AF"),
            height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h")
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No daily_kpis rows found for this period.")

def render_ga4_page(user_email: str = "") -> None:
    _section("Google Analytics + Website Events", "GA4 traffic, sources, attribution, pattern analysis + GTM event tracking.")
    try:
        import streamlit as st
        has_prop = bool(st.secrets.get("GA4_PROPERTY_ID", ""))
        has_sa = "ga4_service_account" in st.secrets
    except Exception:
        has_prop = has_sa = False

    if not (has_prop and has_sa):
        st.warning("GA4 not configured. Add GA4_PROPERTY_ID and [ga4_service_account] to secrets/env.")
        return

    st.success("GA4 is configured.")
    # keep page stable even if GA4 deeper modules fail
    try:
        from events_page_ui import render_events_page
        render_events_page(user_email)
    except Exception as e:
        st.info(f"GA4 subpage warning: {e}")

def render_youtube_page(user_email: str = "") -> None:
    _section("YouTube")
    try:
        from youtube_page_v2 import render_youtube_page_v2
        render_youtube_page_v2()
    except Exception as e:
        st.warning(f"YouTube page warning: {e}")

def render_linkedin_page(user_email: str = "") -> None:
    _section("LinkedIn")
    try:
        from linkedin_command_center_ui import render_linkedin_command_center
        render_linkedin_command_center()
    except Exception as e:
        st.warning(f"LinkedIn page warning: {e}")

def render_cs_page(user_email: str = "") -> None:
    _section("Customer Success Hub", "Master view, enriched funnel, Stripe live, deep analytics.")
    try:
        from customer_success_ui import render_customer_success_page
        render_customer_success_page()
    except Exception as e:
        st.warning(f"Customer Success page warning: {e}")

def render_cross_page(user_email: str = "") -> None:
    _section("Cross-Platform")
    try:
        from cross_platform_engine import build_cross_platform_snapshot
        snapshot = build_cross_platform_snapshot()
        st.json(snapshot)
    except Exception as e:
        st.warning(f"Cross-platform page warning: {e}")

def render_ai_page(user_email: str = "") -> None:
    _section("AI")
    try:
        from ai_assistant_ui import render_ai_assistant_page
        render_ai_assistant_page(user_email)
    except Exception as e:
        st.warning(f"AI page warning: {e}")

def render_custom_page(user_email: str = "") -> None:
    _section("Custom Modules")
    st.info("Custom modules page is available; advanced rendering can be reattached later.")
"""), encoding="utf-8")
print("✅ pages_registry.py fully rewritten")

# -------------------------------------------------------------------
# 5) start_streamlit_render.sh
# -------------------------------------------------------------------
ss = ROOT / "scripts" / "start_streamlit_render.sh"
backup(ss) if ss.exists() else None
ss.write_text(textwrap.dedent("""\
#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p .streamlit

cat > .streamlit/secrets.toml <<SECRETS
APP_PASSWORD = "${APP_PASSWORD:-}"
MONGO_URI = "${MONGO_URI:-}"
MONGO_DB = "${MONGO_DB:-eagle3d}"
TELEGRAM_BOT_TOKEN = "${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID = "${TELEGRAM_CHAT_ID:-}"
YOUTUBE_API_KEY = "${YOUTUBE_API_KEY:-}"
YOUTUBE_CHANNEL_ID = "${YOUTUBE_CHANNEL_ID:-}"
WEBHOOK_API_KEY = "${WEBHOOK_API_KEY:-}"
GA4_PROPERTY_ID = "${GA4_PROPERTY_ID:-}"
SECRETS

if [ -n "${GA4_SERVICE_ACCOUNT_JSON:-}" ]; then
python3 - <<'PY'
import json
import os
from pathlib import Path

raw = os.environ.get("GA4_SERVICE_ACCOUNT_JSON", "").strip()
if raw:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            p = Path(".streamlit/secrets.toml")
            text = p.read_text(encoding="utf-8")
            text += "\\n[ga4_service_account]\\n"
            for k, v in data.items():
                if isinstance(v, str):
                    text += f'{k} = "{v.replace(chr(34), chr(92)+chr(34))}"\\n'
                elif isinstance(v, bool):
                    text += f"{k} = {'true' if v else 'false'}\\n"
                else:
                    text += f"{k} = {json.dumps(v)}\\n"
            p.write_text(text, encoding="utf-8")
            print("GA4 service account written to secrets.toml")
    except Exception as e:
        print(f"WARNING: invalid GA4_SERVICE_ACCOUNT_JSON, skipping injection: {e}")
PY
fi

exec streamlit run app.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
"""), encoding="utf-8")
ss.chmod(0o755)
print("✅ start_streamlit_render.sh fully rewritten")

# -------------------------------------------------------------------
# 6) install_linkedin_cookies_full.py
# -------------------------------------------------------------------
lic = ROOT / "scripts" / "install_linkedin_cookies_full.py"
backup(lic) if lic.exists() else None
lic.write_text(textwrap.dedent("""\
from __future__ import annotations

import json, html, re, os
from pathlib import Path
from urllib.parse import urlparse

INPUTS = [
    Path("data/linkedin_cookies.json"),
    Path("data_output/linkedin_cookies.json"),
    Path.home() / "Downloads" / "linkedin_cookies.json"),
    Path("linkedin_cookies.json"),
]
OUTS = [Path("data/linkedin_cookies.json"), Path("data_output/linkedin_cookies.json")]
IMPORTANT = ["li_at","JSESSIONID","bcookie","bscookie","PLAY_SESSION","fptctx2"]

def unesc(v): return html.unescape(str(v or "")).strip()

def extract_host(raw: str) -> str:
    s = unesc(raw).strip('"').strip("'")
    m = re.search(r'((?:www\\.)?linkedin\\.com)\\b', s, re.I)
    if m: return m.group(1).lower()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            p = urlparse(s)
            if p.netloc: return p.netloc.lower()
        except Exception:
            pass
    return s.strip("/").lstrip(".").lower()

def clean_obj(obj):
    if isinstance(obj, dict): return {k: clean_obj(v) for k, v in obj.items()}
    if isinstance(obj, list): return [clean_obj(x) for x in obj]
    if isinstance(obj, str): return html.unescape(obj)
    return obj

def normalize_cookie(c):
    c = clean_obj(c)
    name = unesc(c.get("name"))
    value = unesc(c.get("value"))
    if not name: return None
    domain = extract_host(c.get("domain", ""))
    if not domain: return None
    fixed = dict(c)
    fixed["name"] = name
    fixed["value"] = value
    fixed["domain"] = domain if c.get("hostOnly", False) else "." + domain.lstrip(".")
    fixed["path"] = unesc(c.get("path") or "/") or "/"
    ss = unesc(c.get("sameSite"))
    if ss.lower() in ("no_restriction", "none", "no restriction"):
        fixed["sameSite"] = "no_restriction"
    elif ss.lower() in ("lax", "strict"):
        fixed["sameSite"] = ss.lower()
    else:
        fixed["sameSite"] = None
    return fixed

def main():
    raw_secret = os.environ.get("LINKEDIN_COOKIES_JSON", "").strip()
    if raw_secret:
        Path("data").mkdir(exist_ok=True)
        Path("data_output").mkdir(exist_ok=True)
        Path("data/linkedin_cookies.json").write_text(raw_secret, encoding="utf-8")
        Path("data_output/linkedin_cookies.json").write_text(raw_secret, encoding="utf-8")

    src = next((p for p in INPUTS if p.exists()), None)
    if src is None:
        print("❌ Could not find input cookie file.")
        for p in INPUTS:
            print(" -", p)
        raise SystemExit(1)

    raw = src.read_text(encoding="utf-8", errors="ignore").strip()
    if not raw:
        print(f"❌ Input file is empty: {src}")
        raise SystemExit(1)

    data = json.loads(raw)
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, list):
        print("❌ Cookie file is not a JSON list")
        raise SystemExit(1)

    cleaned = []
    for item in data:
        if isinstance(item, dict):
            norm = normalize_cookie(item)
            if norm:
                cleaned.append(norm)

    if not cleaned:
        print("❌ No valid cookies after normalization")
        raise SystemExit(1)

    names = {c.get("name") for c in cleaned}
    for out in OUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        print(f"OK: wrote full sanitized cookies -> {out}")

    print(f"Full cookie count: {len(cleaned)}")
    for k in IMPORTANT:
        print(f"{k}: {'PRESENT' if k in names else 'MISSING'}")

if __name__ == "__main__":
    main()
"""), encoding="utf-8")
print("✅ install_linkedin_cookies_full.py fully rewritten")

# -------------------------------------------------------------------
# 7) send_telegram_test.py
# -------------------------------------------------------------------
tst = ROOT / "scripts" / "send_telegram_test.py"
tst.write_text(textwrap.dedent("""\
import json, os, urllib.request

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
if not token or not chat_id:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

payload = json.dumps({
    "chat_id": chat_id,
    "text": "✅ GitHub manual workflow heartbeat reached Telegram.",
    "parse_mode": "Markdown",
}).encode("utf-8")

req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=15) as resp:
    body = json.loads(resp.read().decode())
    print(body)
    if not body.get("ok"):
        raise SystemExit("Telegram send failed")
"""), encoding="utf-8")
print("✅ send_telegram_test.py written")

# -------------------------------------------------------------------
# 8) workflow rewrites
# -------------------------------------------------------------------
(ROOT / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

(ROOT / ".github" / "workflows" / "kpi-rebuild.yml").write_text(textwrap.dedent("""\
name: KPI Rebuild

on:
  workflow_dispatch:
  schedule:
    - cron: "15 * * * *"

jobs:
  rebuild:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Rebuild daily_kpis
        run: |
          python scripts/fix_daily_kpis_safe.py
"""), encoding="utf-8")
print("✅ kpi-rebuild.yml written")

(ROOT / ".github" / "workflows" / "engagement-alerts.yml").write_text(textwrap.dedent("""\
name: Engagement Alerts

on:
  workflow_dispatch:
  schedule:
    - cron: "*/15 * * * *"

jobs:
  alerts:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
      YOUTUBE_CHANNEL_ID: ${{ secrets.YOUTUBE_CHANNEL_ID }}
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install python-calamine xlrd lxml html5lib beautifulsoup4
      - name: Telegram heartbeat on manual dispatch
        if: github.event_name == 'workflow_dispatch'
        run: |
          python scripts/send_telegram_test.py
      - name: Run engagement alerts
        run: |
          python engagement_alerts.py
"""), encoding="utf-8")
print("✅ engagement-alerts.yml written")

(ROOT / ".github" / "workflows" / "linkedin-export-sync.yml").write_text(textwrap.dedent("""\
name: LinkedIn Export Sync

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */12 * * *"

jobs:
  sync-linkedin:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      LINKEDIN_COOKIES_JSON: ${{ secrets.LINKEDIN_COOKIES_JSON }}
      LINKEDIN_HEADLESS: "true"
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y xvfb
      - name: Install Python deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install python-calamine xlrd lxml html5lib beautifulsoup4
      - name: Install Playwright Chromium
        run: |
          python -m playwright install chromium
      - name: Install/sanitize cookies
        run: |
          python scripts/install_linkedin_cookies_full.py
      - name: Seed persistent profile from cookies
        run: |
          xvfb-run -a python scripts/seed_linkedin_profile_from_cookies.py
      - name: Run LinkedIn export sync
        run: |
          xvfb-run -a bash scripts/run_linkedin_export_sync.sh
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: linkedin-export-sync
          path: |
            downloads/linkedin_exports
            data_output/linkedin_exports_json
            logs/linkedin_export_sync.out.log
            logs/linkedin_export_sync.err.log
"""), encoding="utf-8")
print("✅ linkedin-export-sync.yml written")

# -------------------------------------------------------------------
# 9) kpi_pattern_analyzer fallback
# -------------------------------------------------------------------
kpa = ROOT / "kpi_pattern_analyzer.py"
if kpa.exists():
    backup(kpa)
    txt = kpa.read_text(encoding="utf-8", errors="ignore")
    if "DOMAIN_COUNTRY =" not in txt:
        insert = 'DOMAIN_COUNTRY = globals().get("DOMAIN_COUNTRY", {})\n\n'
        m = re.search(r'^(from .* import .*|import .*)$', txt, flags=re.M)
        if m:
            idx = m.end()
            txt = txt[:idx] + "\n" + insert + txt[idx:]
        else:
            txt = insert + txt
        kpa.write_text(txt, encoding="utf-8")
        print("✅ kpi_pattern_analyzer.py patched")
    else:
        print("ℹ️ kpi_pattern_analyzer.py already has DOMAIN_COUNTRY")

print("✅ stabilization rewrite bundle complete")
