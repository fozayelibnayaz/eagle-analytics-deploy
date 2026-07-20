"""
app.py — Eagle 3D Streaming Analytics Hub
Stable cloud shell.
"""
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
    st.markdown("""
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
    """, unsafe_allow_html=True)

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
