"""
Eagle Analytics Hub — Unified KPI & Analytics Dashboard v7
=================================================================
All-in-one: KPI, GA4, YouTube, LinkedIn, Cross-Platform Correlation
Dark/light mode, AI-powered analytics, Telegram alerts.
Pages: Dashboard, Google Analytics, YouTube, LinkedIn,
       Cross-Platform, Ask AI, Predictions, Reports,
       Alerts, EDA Lab, Browse Data, Settings.
"""

import streamlit as st
from auth_guard import require_auth, render_user_menu
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import os
import tempfile
import re
import base64
import sys
from pathlib import Path
from email.utils import parsedate_to_datetime

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

# ── MongoDB connection status ──────────────────────────────────
try:
    _SUPABASE_ACTIVE = get_connection_status().get("connected", False)
except Exception:
    _SUPABASE_ACTIVE = False
_sb_load_tab = None  # legacy compatibility


# ── DATE PRESETS ──────────────────────────────────────────────

def parse_to_date(val):
    """Parse various date string formats to date object."""
    if not val or str(val).strip() in ("", "nan", "None", "—"):
        return None
    import re as _re
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(s[:19], fmt).date()
        except Exception:
            pass
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(s[:10]).date()
    except Exception:
        pass
    return None

DATE_PRESETS = [
    "Today",
    "Yesterday",
    "Last 7 Days",
    "Last 14 Days",
    "Last 30 Days",
    "Last 60 Days",
    "Last 90 Days",
    "This Month",
    "All Time",
    "Custom Range",
]

# ═══════════════════════════════════════════════════════════════
# LOGO & FAVICON — Eagle3D Official Logo
# ═══════════════════════════════════════════════════════════════
LOGO_B64 = None
LOGO_PATH = None
try:
    _root = os.path.dirname(os.path.abspath(__file__))
    for _lf in [
        "static/eagle3d_logo2.png",
        "static/eagle3d_logo.png",
        "static/logo.png",
        "eagle3d_logo.png",
        "logo.png",
    ]:
        _lp = os.path.join(_root, _lf)
        if os.path.exists(_lp):
            with open(_lp, "rb") as _f:
                LOGO_B64 = base64.b64encode(_f.read()).decode()
            LOGO_PATH = _lp
            break
except Exception:
    pass

# Eagle logo icon for page config
if LOGO_B64:
    _icon = f"data:image/png;base64,{LOGO_B64}"
else:
    _icon = "https://eagle3dstreaming.com/favicon.ico"


st.set_page_config(
    page_title="Eagle Analytics Hub",
    page_icon=_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── ACCESS CONTROL GATE ──
def _get_client_ip():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        from streamlit.runtime import get_instance
        ctx = get_script_run_ctx()
        if ctx:
            session_info = get_instance()._session_mgr.get_session_info(ctx.session_id)
            if session_info and session_info.client:
                req = getattr(session_info.client, "request", None)
                if req:
                    ip = req.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    if not ip:
                        ip = req.headers.get("X-Real-IP", "")
                    if not ip:
                        ip = getattr(req, "remote_ip", "")
                    return ip or "unknown"
    except Exception:
        pass

    try:
        import urllib.request, json as _j
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=3) as r:
            return _j.loads(r.read()).get("ip", "unknown")
    except Exception:
        return "unknown"


def _enforce_access_control():
    try:
        from access_control import is_allowed, log_access
    except ImportError:
        return
    if st.session_state.get("_access_checked"):
        return

    user_email = st.session_state.get("user_email", "") or st.session_state.get("auth_email", "")

    if not user_email:
        # ── CLEAN LOGIN SCREEN: hide sidebar + center content ──
        st.markdown("""
        <style>
            [data-testid="stSidebar"] {display: none !important;}
            [data-testid="stSidebarNav"] {display: none !important;}
            [data-testid="collapsedControl"] {display: none !important;}
            section[data-testid="stSidebar"] {display: none !important;}
            .main .block-container {
                max-width: 480px !important;
                padding-top: 5rem !important;
                margin: 0 auto !important;
            }
            header {visibility: hidden;}
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
        </style>
        """, unsafe_allow_html=True)

        st.markdown("# 🔒 Eagle3D KPI Hub")
        st.markdown("### Login Required")
        st.caption("Only authorized emails can access this dashboard.")
        st.markdown("---")

        with st.form("access_login", clear_on_submit=False):
            entered = st.text_input("Email address", placeholder="you@eagle3dstreaming.com")
            submit = st.form_submit_button("🔓 Verify Access", use_container_width=True)
            if submit:
                client_ip = _get_client_ip()
                if not entered or "@" not in entered:
                    st.error("Valid email required")
                    log_access(entered or "empty", "login_attempt", False, client_ip)
                    st.stop()
                allowed, role, reason = is_allowed(entered)
                log_access(entered, "login", allowed, client_ip)
                if allowed:
                    st.session_state["user_email"] = entered.strip().lower()
                    st.session_state["user_role"] = role
                    st.session_state["user_ip"] = client_ip
                    st.session_state["_access_checked"] = True
                    st.success(f"Welcome! Role: {role} | IP: {client_ip}")
                    st.rerun()
                else:
                    st.error(f"Access denied: {reason}")
                    st.caption(f"Attempt logged from IP: {client_ip}")
                    st.stop()

        st.markdown("---")
        st.caption("Need access? Contact your administrator.")
        st.stop()
    else:
        allowed, role, reason = is_allowed(user_email)
        if not allowed:
            st.error(f"Access revoked: {reason}")
            if st.button("Sign out"):
                for k in ("user_email", "user_role", "_access_checked", "user_ip"):
                    st.session_state.pop(k, None)
                st.rerun()
            st.stop()
        st.session_state["user_role"] = role
        st.session_state["_access_checked"] = True

_enforce_access_control()

# ═══════════════════════════════════════════════════════════════
# THEME ENGINE
# ═══════════════════════════════════════════════════════════════
# Theme: Dark mode only (no light mode switcher)
IS_DARK = True


def _theme_colors():
    if IS_DARK:
        return {
            "bg": "#060D1A", "surface": "#0D1829", "card": "#111D32",
            "card_alt": "#152240", "border": "#1B3054",
            "accent": "#00D4FF", "accent2": "#6C5CE7",
            "text": "#E8EDF5", "text_sec": "#94A3C1", "muted": "#5B6B85",
            "green": "#00E676", "yellow": "#FFD600", "red": "#FF5252",
            "plot_bg": "rgba(0,0,0,0)", "paper_bg": "rgba(0,0,0,0)",
            "font_c": "#94A3C1",
            "input_bg": "#0D1829", "input_text": "#E8EDF5",
            "sidebar_bg": "#0A1222", "df_header_bg": "#152240",
            "df_cell_bg": "#111D32",
        }
    else:
        return {
            "bg": "#F0F4F8", "surface": "#FFFFFF", "card": "#FFFFFF",
            "card_alt": "#EDF2F7", "border": "#CBD5E1",
            "accent": "#0077B6", "accent2": "#5B4FCF",
            "text": "#0F172A", "text_sec": "#334155", "muted": "#64748B",
            "green": "#16A34A", "yellow": "#CA8A04", "red": "#DC2626",
            "plot_bg": "#FFFFFF", "paper_bg": "#FFFFFF",
            "font_c": "#334155",
            "input_bg": "#FFFFFF", "input_text": "#0F172A",
            "sidebar_bg": "#F8FAFC", "df_header_bg": "#F1F5F9",
            "df_cell_bg": "#FFFFFF",
        }


T = _theme_colors()


def _css():
    """Inject comprehensive CSS for dark mode."""

    st.markdown(f"""
    <style>
    /* ═══ ROOT VARIABLES ═══ */
    :root {{
        --bg:{T['bg']}; --surface:{T['surface']}; --card:{T['card']};
        --card-alt:{T['card_alt']}; --border:{T['border']};
        --accent:{T['accent']}; --accent2:{T['accent2']};
        --text:{T['text']}; --text-sec:{T['text_sec']}; --muted:{T['muted']};
        --green:{T['green']}; --yellow:{T['yellow']}; --red:{T['red']};
    }}

    /* ═══ GLOBAL ═══ */
    .stApp {{ background: var(--bg) !important; }}
    .stMarkdown, .stText {{ color: var(--text); }}
    html {{ scroll-behavior: smooth; }}

    /* ═══ FADE-IN ANIMATION ═══ */
    @keyframes fadeInUp {{
        from {{ opacity: 0; transform: translateY(18px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes glowPulse {{
        0%, 100% {{ box-shadow: 0 0 8px {T['accent']}10; }}
        50% {{ box-shadow: 0 0 20px {T['accent']}25; }}
    }}
    @keyframes shimmer {{
        0% {{ background-position: -200% 0; }}
        100% {{ background-position: 200% 0; }}
    }}
    .kpi, .sec-head, .stDataFrame, .alert-card, .comp-box {{
        animation: fadeInUp 0.45s ease-out both;
    }}
    .kpi:nth-child(1) {{ animation-delay: 0.02s; }}
    .kpi:nth-child(2) {{ animation-delay: 0.06s; }}
    .kpi:nth-child(3) {{ animation-delay: 0.10s; }}
    .kpi:nth-child(4) {{ animation-delay: 0.14s; }}
    .kpi:nth-child(5) {{ animation-delay: 0.18s; }}
    .kpi:nth-child(6) {{ animation-delay: 0.22s; }}

    /* ═══ SIDEBAR ═══ */
    [data-testid="stSidebar"] {{
        background: {T['sidebar_bg']} !important;
        border-right: 1px solid var(--border) !important;
    }}
    [data-testid="stSidebarNav"] {{ display: none !important; }}
    [data-testid="stSidebar"] .stButton button {{
        color: var(--text-sec); font-size: 0.82rem; font-weight: 500;
        padding: 8px 14px; border-radius: 10px;
        border: 1px solid transparent; margin: 1px 0;
        transition: all 0.2s ease; background: transparent;
    }}
    [data-testid="stSidebar"] .stButton button:hover {{
        background: var(--card-alt) !important;
        border-color: var(--border) !important;
        transform: translateX(3px);
        color: var(--text) !important;
    }}
    [data-testid="stSidebar"] .stButton button:active {{
        background: linear-gradient(135deg, {T['accent']}22, {T['accent2']}18) !important;
        border-color: var(--accent) !important;
        color: var(--accent) !important;
    }}
    [data-testid="stSidebar"] .streamlit-expanderHeader {{
        font-size: 0.75rem; font-weight: 700; letter-spacing: 0.5px;
        color: var(--muted); text-transform: uppercase;
    }}

    /* ═══ KPI GRID ═══ */
    .kpi-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
        gap: 12px; margin: 12px 0 20px;
    }}
    .kpi {{
        background: linear-gradient(145deg, var(--card), var(--card-alt));
        border: 1px solid var(--border); border-radius: 14px;
        padding: 18px 14px; text-align: center;
        transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
        position: relative; overflow: hidden;
    }}
    .kpi::before {{
        content: ''; position: absolute; top: 0; left: -100%;
        width: 100%; height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.03), transparent);
        transition: left 0.6s;
    }}
    .kpi:hover::before {{ left: 100%; }}
    .kpi:hover {{
        transform: translateY(-3px) scale(1.02);
        box-shadow: 0 8px 32px {T['accent']}20;
        border-color: var(--accent);
    }}
    .kpi-val {{
        font-size: 1.8rem; font-weight: 800;
        color: var(--text); line-height: 1.15;
    }}
    .kpi-lbl {{
        font-size: 0.68rem; color: var(--muted);
        text-transform: uppercase; letter-spacing: 1px;
        margin-top: 5px; font-weight: 600;
    }}
    .kpi-delta {{ font-size: 0.78rem; font-weight: 700; margin-top: 4px; }}
    .d-up {{ color: var(--green); }} .d-dn {{ color: var(--red); }}
    .d-fl {{ color: var(--muted); }}

    /* ═══ SECTION HEADERS ═══ */
    .sec-head {{
        font-size: 1.15rem; font-weight: 700; color: var(--accent);
        border-bottom: 2px solid var(--border);
        padding-bottom: 8px; margin: 22px 0 14px;
    }}

    /* ═══ BADGES ═══ */
    .badge {{
        padding: 3px 10px; border-radius: 20px;
        font-size: 0.7rem; font-weight: 600;
        display: inline-block;
    }}
    .badge-ok {{ background: {T['green']}20; color: var(--green); }}
    .badge-warn {{ background: {T['yellow']}20; color: var(--yellow); }}
    .badge-err {{ background: {T['red']}20; color: var(--red); }}
    .badge-info {{ background: {T['accent']}18; color: var(--accent); }}

    /* ═══ ALERT CARDS ═══ */
    .alert-card {{
        border-radius: 12px; padding: 14px 18px;
        margin: 8px 0; border-left: 4px solid;
    }}
    .al-crit {{ background: {T['red']}15; border-color: var(--red); }}
    .al-warn {{ background: {T['yellow']}15; border-color: var(--yellow); }}
    .al-ok {{ background: {T['green']}15; border-color: var(--green); }}

    /* ═══ CHAT ═══ */
    .chat-msg {{
        padding: 10px 14px; border-radius: 12px;
        margin: 6px 0; max-width: 92%;
        font-size: 0.9rem; line-height: 1.5;
    }}
    .chat-user {{
        background: {T['accent']}15;
        border: 1px solid var(--border); margin-left: auto;
    }}
    .chat-ai {{
        background: var(--card);
        border: 1px solid var(--border);
    }}

    /* ═══ INFO BOX ═══ */
    .comp-box {{
        background: var(--card); border: 1px solid var(--border);
        border-radius: 10px; padding: 10px 14px;
        margin: 8px 0; font-size: 0.82rem;
    }}

    /* ═══ DATAFRAME ═══ */
    .stDataFrame {{
        border: 1px solid var(--border);
        border-radius: 10px; overflow: hidden;
    }}

    /* ═══ BUTTONS & INPUTS ═══ */
    .stButton button {{
        border-radius: 10px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease !important;
    }}
    .stButton button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    }}
    .stTextInput input, .stSelectbox, .stDateInput, .stNumberInput {{
        border-radius: 8px !important;
    }}

    /* ═══ TABS ═══ */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 2px; border-radius: 10px;
        background: var(--card-alt);
        padding: 4px;
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 8px !important;
        padding: 6px 16px !important;
        font-size: 0.82rem !important;
        transition: all 0.2s;
    }}
    .stTabs [aria-selected="true"] {{
        background: var(--card) !important;
        border-color: var(--accent) !important;
    }}

    /* ═══ METRIC CARDS ═══ */
    [data-testid="stMetric"] {{
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 12px 16px;
        transition: all 0.2s;
    }}
    [data-testid="stMetric"]:hover {{
        border-color: var(--accent);
        box-shadow: 0 4px 16px {T['accent']}12;
    }}

    /* ═══ RESPONSIVE ═══ */
    @media (max-width: 1024px) {{
        .kpi-grid {{
            grid-template-columns: repeat(3, 1fr); gap: 10px;
        }}
    }}
    @media (max-width: 768px) {{
        .kpi-grid {{
            grid-template-columns: repeat(2, 1fr); gap: 8px;
        }}
        .kpi-val {{ font-size: 1.4rem; }}
        [data-testid="stMetric"] {{ padding: 8px 10px; }}
    }}
    @media (max-width: 480px) {{
        .kpi-grid {{
            grid-template-columns: 1fr 1fr; gap: 6px;
        }}
        .kpi-val {{ font-size: 1.1rem; }}
        .kpi {{ padding: 10px 8px; }}
        .stTabs [data-baseweb="tab"] {{ padding: 4px 10px !important; font-size: 0.7rem !important; }}
        [data-testid="column"] {{ min-width: auto !important; }}
    }}
    @media (max-width: 360px) {{
        .kpi-grid {{ grid-template-columns: 1fr; }}
    }}

    /* ═══ DESIGN SYSTEM: Typography & Spacing ═══ */
    body, .stApp {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; }}
    h1, h2, h3, h4, h5, h6 {{ font-weight: 700; letter-spacing: -0.02em; }}
    h1 {{ font-size: 1.65rem; }} h2 {{ font-size: 1.35rem; }}
    h3 {{ font-size: 1.1rem; }} h4 {{ font-size: 1rem; }}

    /* ═══ CARD COMPONENT ═══ */
    .card {{
        background: var(--card); border: 1px solid var(--border);
        border-radius: 14px; padding: 20px; margin: 12px 0;
        transition: all 0.3s ease;
    }}
    .card:hover {{ border-color: var(--accent); box-shadow: 0 4px 24px {T['accent']}15; }}

    /* ═══ EXPANDER REFINEMENT ═══ */
    .streamlit-expanderHeader {{
        font-weight: 700 !important; font-size: 0.85rem !important;
        border-radius: 10px !important; padding: 8px 12px !important;
        transition: background 0.2s;
    }}
    .streamlit-expanderHeader:hover {{
        background: var(--card-alt) !important;
    }}

    /* ═══ SELECT/SLIDER/INPUT REFINEMENT ═══ */
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {{
        border-radius: 8px !important;
        border-color: var(--border) !important;
    }}
    div[data-baseweb="slider"] > div {{
        background: var(--border) !important;
    }}

    /* ═══ PROGRESS BAR ═══ */
    .stProgress > div > div > div {{
        background: linear-gradient(90deg, var(--accent), var(--accent2)) !important;
        border-radius: 4px !important;
    }}

    /* ═══ DIVIDER ═══ */
    hr {{
        border-color: var(--border) !important;
        opacity: 0.5;
    }}

    /* ═══ TOAST / SUCCESS / ERROR ═══ */
    .stAlert {{
        border-radius: 10px !important;
        border: 1px solid var(--border) !important;
    }}

    /* ═══ CLEANUP ═══ */
    #MainMenu {{ visibility: hidden; }}
    footer {{ visibility: hidden; }}
    </style>
    """, unsafe_allow_html=True)


_css()

# ═══════════════════════════════════════════════════════════════
# AUTHENTICATION GATE
# ═══════════════════════════════════════════════════════════════


def _get_app_password():
    """Get password from secrets first, then fallback to default."""
    try:
        if "APP_PASSWORD" in st.secrets:
            val = st.secrets["APP_PASSWORD"]
            if val and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return os.environ.get("APP_PASSWORD", "eagleanalytics")


_APP_PASSWORD = _get_app_password()


def _check_auth():
    """Password-gate for the dashboard with proper centered login UI."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if st.session_state["authenticated"]:
        return True
    # Login screen — hide sidebar, centered panel
    st.markdown("""
    <style>
    [data-testid="stSidebar"] {display: none !important;}
    [data-testid="stSidebarNav"] {display: none !important;}
    .block-container {padding-top: 8rem !important;}
    </style>
    """, unsafe_allow_html=True)

    # Centered login card
    _login_logo = ""
    if LOGO_B64:
        _login_logo = f'<img src="data:image/png;base64,{LOGO_B64}" style="width:72px;height:auto;border-radius:14px;margin-bottom:0.8rem;">'
    else:
        _login_logo = '<div style="font-size:2.8rem;margin-bottom:0.5rem;">Eagle3D</div>'
    st.markdown(f"""
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
                min-height:50vh;text-align:center;">
        {_login_logo}
        <div style="font-size:1.8rem;font-weight:800;color:#00D4FF;margin-bottom:0.3rem;">
            Eagle Analytics Hub</div>
        <div style="font-size:0.85rem;color:#94A3C1;margin-bottom:0.2rem;">
            Eagle 3D Streaming — Unified Command Center</div>
        <div style="font-size:0.75rem;color:#5B6B85;margin-bottom:2rem;">
            Secure Dashboard — Authentication Required</div>
    </div>
    """, unsafe_allow_html=True)
    _cols = st.columns([3, 2, 3])
    with _cols[1]:
        _pwd = st.text_input("Password", type="password", key="_auth_pwd",
                             placeholder="Enter password...")
        _login_btn = st.button("🔓 Sign In", use_container_width=True, key="_auth_btn")
        if _login_btn:
            if _pwd == _APP_PASSWORD:
                st.session_state["authenticated"] = True
                st.toast("✅ Access granted", icon="✅")
                st.rerun()
            else:
                st.error("❌ Incorrect password. Try again.")
        st.caption("🔒 This dashboard is private and password-protected.")
    return False


if not _check_auth():
    st.stop()


# ═══════════════════════════════════════════════════════════════
# COMPATIBILITY HELPERS
# ═══════════════════════════════════════════════════════════════


def _pc(fig, **kwargs):
    """Plot chart — handles both old and new Streamlit API."""
    try:
        st.plotly_chart(fig, width="stretch", **kwargs)
    except TypeError:
        try:
            st.plotly_chart(fig, use_container_width=True, **kwargs)
        except TypeError:
            st.plotly_chart(fig, **kwargs)


def _df(df, height=400, **kwargs):
    """Display dataframe — handles both old and new API."""
    try:
        st.dataframe(df, width="stretch", height=height,
                     hide_index=True, **kwargs)
    except TypeError:
        try:
            st.dataframe(df, use_container_width=True, height=height,
                         hide_index=True, **kwargs)
        except TypeError:
            st.dataframe(df, height=height, hide_index=True, **kwargs)


# ═══════════════════════════════════════════════════════════════
# MODULE LOADING
# ═══════════════════════════════════════════════════════════════
MOD = {}


def _imp(name, frm=None):
    try:
        if frm:
            m = __import__(frm)
            for p in frm.split(".")[1:]:
                m = getattr(m, p)
        else:
            m = __import__(name)
        MOD[name] = m
        return True
    except Exception as e:
        MOD[name + "_err"] = str(e)
        return False


for _n, _f in [
    ("kpi_bridge", None), ("ga4_connector", None),
    ("source_intel", "ga4_source_intel"),
    ("smart_qa", "ga4_smart_qa"), ("strategic", "ga4_strategic"),
    ("notifications", "ga4_notifications"),
    ("intelligence", "ga4_intelligence"),
    ("ai_engine", None), ("prediction_engine", None),
    ("report_generator", None), ("source_normalizer", None),
    ("manual_override_engine", None),
]:
    _imp(_n, _f)

# ═══════════════════════════════════════════════════════════════
# CREDENTIALS
# ═══════════════════════════════════════════════════════════════
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_creds_path():
    try:
        if "GOOGLE_CREDS" in st.secrets:
            r = st.secrets["GOOGLE_CREDS"]
            c = json.loads(r) if isinstance(r, str) else dict(r)
            t = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json.dump(c, t)
            t.close()
            return t.name
    except Exception:
        pass
    return None


def get_secret(k, d=None):
    try:
        if k in st.secrets:
            return st.secrets[k]
    except Exception:
        pass
    return d


CREDS_PATH = get_creds_path()
MASTER_SHEET_URL = get_secret("MASTER_SHEET_URL")

# Fallback: try config.py for MASTER_SHEET_URL when not in secrets
# MASTER_SHEET_URL no longer needed — using MongoDB
# Fallback: try ga4_service_account for Google Sheets credentials
if not CREDS_PATH:
    try:
        _sa = dict(st.secrets["ga4_service_account"])
        if "private_key" in _sa:
            _sa["private_key"] = _sa["private_key"].replace("\\n", "\n")
        _tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(_sa, _tf)
        _tf.close()
        CREDS_PATH = _tf.name
    except Exception:
        pass



# ── MONGODB FAST KPI STATS ──
@st.cache_data(ttl=60)
def get_supabase_kpi_fast():
    """Get KPI counts directly from MongoDB - fast and accurate."""
    try:
        from mongo_client import count_accepted
        from mongo_data_loader import get_earliest_upload_date
        _today = datetime.now().strftime("%Y-%m-%d")
        _month_start = datetime.now().strftime("%Y-%m-01")
        _upload_start = get_earliest_upload_date() or "2025-12-01"

        return {
            "today_signups":  count_accepted("signups",  "signup_date",        date_gte=_today),
            "today_uploads":  count_accepted("uploads",  "upload_date",        date_gte=_today),
            "today_paid":     count_accepted("payments", "first_payment_date", date_gte=_today),
            "month_signups":  count_accepted("signups",  "signup_date",        date_gte=_month_start),
            "month_uploads":  count_accepted("uploads",  "upload_date",        date_gte=_month_start),
            "month_paid":     count_accepted("payments", "first_payment_date", date_gte=_month_start),
            "common_signups": count_accepted("signups",  "signup_date",        date_gte=_upload_start),
            "common_uploads": count_accepted("uploads",  "upload_date",        date_gte=_upload_start),
            "common_paid":    count_accepted("payments", "first_payment_date", date_gte=_upload_start),
            "full_signups":   count_accepted("signups",  "signup_date"),
            "full_uploads":   count_accepted("uploads",  "upload_date"),
            "full_paid":      count_accepted("payments", "first_payment_date"),
            "common_start":   _upload_start,
            "today":          _today,
            "month_start":    _month_start,
            "source":         "mongodb",
        }
    except Exception:
        return None


def _browse_supabase(table_key, status_filter, search_val, date_start, date_end, limit=1000):
    """Server-side filtered browse data from MongoDB."""
    try:
        _table_map = {
            "Sign-ups":      ("signups",  "signup_date",        "email"),
            "First Uploads": ("uploads",  "upload_date",        "email"),
            "Stripe":        ("payments", "first_payment_date", "email"),
        }
        if table_key not in _table_map:
            return pd.DataFrame(), {}

        _tbl, _date_col, _email_col = _table_map[table_key]
        _filters = {}

        if date_start:
            _filters.setdefault(_date_col, {})["$gte"] = str(date_start)
        if date_end:
            _filters.setdefault(_date_col, {})["$lte"] = str(date_end)

        if status_filter and status_filter != "All":
            _filters["final_status"] = str(status_filter).upper()

        if search_val:
            _filters[_email_col] = {"$regex": str(search_val), "$options": "i"}

        _db = get_db()
        if _db is None:
            return pd.DataFrame(), {}

        _data = list(_db[_tbl].find(_filters, {"_id": 0}).sort(_date_col, -1).limit(int(limit or 1000)))
        _df = pd.DataFrame(_data) if _data else pd.DataFrame()

        _total = len(_data)
        _accepted = sum(1 for r in _data if str(r.get("final_status", "")).upper() == "ACCEPTED")
        _rejected = _total - _accepted

        return _df, {
            "total": _total,
            "accepted": _accepted,
            "rejected": _rejected,
            "source": "mongodb",
        }
    except Exception:
        return pd.DataFrame(), {}


def get_date_range(preset, cs=None, ce=None):
    t = datetime.now().date()
    y = t - timedelta(days=1)
    R = {
        "Today": (t, t),
        "Yesterday": (y, y),
        "This Week": (t - timedelta(days=t.weekday()), t),
        "Last 7 Days": (t - timedelta(days=6), t),
        "Last 14 Days": (t - timedelta(days=13), t),
        "Last 28 Days": (t - timedelta(days=27), t),
        "Last 30 Days": (t - timedelta(days=29), t),
        "This Month": (t.replace(day=1), t),
        "This Year": (t.replace(month=1, day=1), t),
        "All Time": (datetime(2024, 1, 1).date(), t),
    }
    lwe = t - timedelta(days=t.weekday() + 1)
    R["Last Week"] = (lwe - timedelta(days=6), lwe)
    fp = t.replace(day=1)
    lp = fp - timedelta(days=1)
    R["Last Month"] = (lp.replace(day=1), lp)
    R["Last 3 Months"] = (t - timedelta(days=90), t)
    R["Last 6 Months"] = (t - timedelta(days=180), t)
    R["Last 12 Months"] = (t - timedelta(days=365), t)
    R["Last Year"] = (datetime(t.year - 1, 1, 1).date(),
                      datetime(t.year - 1, 12, 31).date())
    if preset == "Custom Range" and cs and ce:
        return cs, ce
    return R.get(preset, (t - timedelta(days=27), t))


def get_comp_range(ps, pe, mode, cs=None, ce=None):
    if mode == "Previous Period":
        span = (pe - ps).days + 1
        e = ps - timedelta(days=1)
        return e - timedelta(days=span - 1), e
    if mode == "Same Period Last Year":
        try:
            return ps.replace(year=ps.year - 1), pe.replace(year=pe.year - 1)
        except ValueError:
            return None, None
    if mode == "Custom Comparison" and cs and ce:
        return cs, ce
    return None, None


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def CT():
    """Common Plotly theme."""
    return {
        "paper_bgcolor": T["paper_bg"],
        "plot_bgcolor": T["plot_bg"],
        "font_color": T["font_c"],
        "title_font_color": T["text"],
        "legend_bgcolor": T["card"],
    }


CC = [
    "#00D4FF", "#6C5CE7", "#00E676", "#FFD600",
    "#FF5252", "#B388FF", "#FF9100", "#00BFA5",
]


def filter_kpi(df, s, e):
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame()
    d = df.copy()
    d["date"] = d["date"].astype(str)
    # Try multiple parse strategies
    _parsed = pd.to_datetime(d["date"], errors="coerce")
    if _parsed.isna().all() and d["date"].str.match(r"^\d{5}$").any():
        _parsed = pd.to_datetime(d["date"].apply(lambda x: f"{x[:4]}-{x[4:6]}-{x[6:8]}"), errors="coerce")
    d["_d"] = _parsed.dt.date
    d = d.dropna(subset=["_d"])
    return d[(d["_d"] >= s) & (d["_d"] <= e)].drop(columns=["_d"])


def km(df, col):
    """Sum of numeric column, safely."""
    if df is None or df.empty or col not in df.columns:
        return 0
    return int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def fmt_val(v):
    """Format value for KPI card — handles int, float, and string."""
    if isinstance(v, (int, float)):
        try:
            if isinstance(v, float):
                return f"{v:,.1f}"
            return f"{v:,}"
        except (ValueError, TypeError):
            return str(v)
    return str(v)


def delta_h(c, p, inv=False):
    """Delta HTML for KPI card."""
    try:
        c = float(c)
        p = float(p)
    except (ValueError, TypeError):
        return '<span class="kpi-delta d-fl">→ —</span>'
    if p == 0:
        if c > 0:
            return f'<span class="kpi-delta d-up">{int(c):,} total</span>'
        return '<span class="kpi-delta d-fl">→ —</span>'
    pct = (c - p) / p * 100
    pos = pct > 0 if not inv else pct < 0
    if abs(pct) < 0.5:
        return '<span class="kpi-delta d-fl">→ flat</span>'
    if pos:
        return f'<span class="kpi-delta d-up">▲ {pct:+.1f}%</span>'
    return f'<span class="kpi-delta d-dn">▼ {abs(pct):.1f}%</span>'


def kpi_h(label, value, delta, icon=""):
    """KPI card HTML — uses fmt_val to handle any value type."""
    fv = fmt_val(value)
    return (
        f'<div class="kpi">'
        f'<div class="kpi-val">{icon} {fv}</div>'
        f'<div class="kpi-lbl">{label}</div>'
        f'{delta}'
        f'</div>'
    )


def fd(d):
    return d.strftime("%Y-%m-%d") if d else "?"


email, role = require_auth(page_name=st.session_state.get("nav_page", "Dashboard"))
render_user_menu()

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    # Logo
    if LOGO_B64:
        st.markdown(
            f'<div style="text-align:center;padding:6px 0;">'
            f'<img src="data:image/png;base64,{LOGO_B64}" '
            f'style="width:72px;height:auto;border-radius:10px;">'
            f"</div>",
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div style="text-align:center;padding:2px 0 6px 0;">'
        '<a href="https://eagle3d-kpi-automation.streamlit.app/" target="_blank" '
        'style="font-size:0.9rem;font-weight:800;color:var(--accent);'
        'letter-spacing:0.5px;text-decoration:none;">Eagle Analytics Hub</a>'
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # Navigation — organized into expandable category sections
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = "📊 Dashboard"

    _SYS_PAGES = {"📈 Google Analytics", "📺 YouTube", "💼 LinkedIn", "🎯 Customer Success", "🔗 Cross-Platform"}
    _KPI_PAGES = {"📊 Dashboard", "🔍 Browse Data", "🔬 EDA Lab", "✏️ Manual Override", "📋 Reports", "🔔 Alerts"}
    _AI_PAGES = {"🤖 Ask AI", "🤖 AI KPI", "🤖 AI YouTube", "🤖 AI LinkedIn", "🤖 AI GA4", "🤖 AI CS", "🔮 Predictions", "🧠 AI Tools"}

    page = st.session_state["nav_page"]

    with st.expander("📊 KPI", expanded=page in _KPI_PAGES):
        for _label, _key in [("Dashboard", "📊 Dashboard"), ("Browse Data", "🔍 Browse Data"),
                             ("EDA Lab", "🔬 EDA Lab"), ("Manual Override", "✏️ Manual Override"),
                             ("Reports", "📋 Reports"), ("Alerts", "🔔 Alerts")]:
            if st.button(_label, use_container_width=True, key=f"nav_{_key}"):
                st.session_state["nav_page"] = _key
                st.rerun()

    with st.expander("📈 Google Analytics", expanded=page == "📈 Google Analytics"):
        if st.button("📈 Google Analytics", use_container_width=True, key="nav_ga"):
            st.session_state["nav_page"] = "📈 Google Analytics"
            st.rerun()

    with st.expander("📺 YouTube", expanded=page == "📺 YouTube"):
        if st.button("📺 YouTube", use_container_width=True, key="nav_yt"):
            st.session_state["nav_page"] = "📺 YouTube"
            st.rerun()

    with st.expander("💼 LinkedIn", expanded=page == "💼 LinkedIn"):
        if st.button("💼 LinkedIn", use_container_width=True, key="nav_li"):
            st.session_state["nav_page"] = "💼 LinkedIn"
            st.rerun()

    with st.expander("🎯 Customer Success", expanded=page == "🎯 Customer Success"):
        if st.button("🎯 Customer Success", use_container_width=True, key="nav_cs"):
            st.session_state["nav_page"] = "🎯 Customer Success"
            st.rerun()

    with st.expander("🔗 Cross-Platform", expanded=page == "🔗 Cross-Platform"):
        if st.button("🔗 Cross-Platform", use_container_width=True, key="nav_cp"):
            st.session_state["nav_page"] = "🔗 Cross-Platform"
            st.rerun()

    with st.expander("🤖 AI & Insights", expanded=page in _AI_PAGES):
        for _label, _key in [("Ask AI (All)", "🤖 Ask AI"),
                              ("AI - KPI", "🤖 AI KPI"),
                              ("AI - YouTube", "🤖 AI YouTube"),
                              ("AI - LinkedIn", "🤖 AI LinkedIn"),
                              ("AI - GA4", "🤖 AI GA4"),
                              ("AI - Customer Success", "🤖 AI CS"),
                              ("AI Tools", "🧠 AI Tools"),
                              ("Predictions", "🔮 Predictions")]:
            if st.button(_label, use_container_width=True, key=f"nav_{_key}"):
                st.session_state["nav_page"] = _key
                st.rerun()


    # Custom Team Modules
    try:
        from custom_modules_engine import list_modules as _cm_list_modules
        _custom_modules = _cm_list_modules(active_only=True)
    except Exception:
        _custom_modules = []

    with st.expander("🧩 Custom Modules", expanded=str(page).startswith("🧩 Custom:")):
        if _custom_modules:
            for _cm in _custom_modules:
                _cm_name = _cm.get("name", _cm.get("slug", "Custom"))
                _cm_slug = _cm.get("slug", "")
                if st.button(_cm_name, use_container_width=True, key=f"nav_custom_{_cm_slug}"):
                    st.session_state["nav_page"] = f"🧩 Custom:{_cm_slug}"
                    st.rerun()
        else:
            st.caption("No custom modules yet")

        if st.button("➕ Manage Modules", use_container_width=True, key="nav_custom_manage"):
            st.session_state["nav_page"] = "⚙️ Settings"
            st.rerun()

    st.markdown("---")

    # Refresh data button
    if st.button("🔄 Refresh Data", use_container_width=True, key="nav_refresh"):
        st.cache_data.clear()
        st.session_state["_last_refresh"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()
    # Pipeline trigger button (delegated to GitHub Actions)
    _gh_tok = get_secret("GITHUB_TOKEN", "")
    if _gh_tok:
        _repo = "fozayelibnayaz/eagle3d-kpi-automation"
        if st.button("🚀 Run Pipeline", use_container_width=True, key="nav_pipeline"):
            try:
                import urllib.request
                _url = (
                    f"https://api.github.com/repos/{_repo}"
                    "/actions/workflows/daily_pipeline.yml/dispatches"
                )
                _data = json.dumps({"ref": "main"}).encode()
                _req = urllib.request.Request(
                    _url, data=_data, method="POST",
                    headers={
                        "Authorization": f"token {_gh_tok}",
                        "Accept": "application/vnd.github+json"
                    }
                )
                with urllib.request.urlopen(_req, timeout=10) as _r:
                    if _r.status in (200, 204):
                        st.toast("🚀 Pipeline triggered! Refresh in ~5 min")
            except Exception:
                st.error("Pipeline trigger failed")

    st.markdown("---")

    # Universal Settings page (always accessible)
    if st.button("⚙️ Settings", use_container_width=True, key="nav_settings"):
        st.session_state["_go_settings"] = True
        st.rerun()

    # Show last refresh time
    _last_ref = st.session_state.get("_last_refresh", "")
    if _last_ref:
        st.caption(f"🔄 Refreshed at {_last_ref}")

    st.markdown("---")

    # Date range
    date_preset = st.selectbox("Period", DATE_PRESETS, index=8,
                               label_visibility="collapsed")
    custom_s = custom_e = None
    if date_preset == "Custom Range":
        _a, _b = st.columns(2)
        with _a:
            custom_s = st.date_input("Start",
                                     value=datetime.now().date() - timedelta(days=30))
        with _b:
            custom_e = st.date_input("End",
                                     value=datetime.now().date())
    p_start, p_end = get_date_range(date_preset, custom_s, custom_e)

    st.markdown("---")

    # Comparison toggle
    enable_comp = st.toggle("🔄 Enable Comparison", value=False)
    comp_mode = "None"
    comp_s = comp_e = None
    if enable_comp:
        comp_mode = st.selectbox(
            "Compare To",
            ["Previous Period", "Same Period Last Year", "Custom Comparison"],
        )
        if comp_mode == "Custom Comparison":
            _a2, _b2 = st.columns(2)
            with _a2:
                comp_s = st.date_input("Comp Start",
                                       value=p_start - timedelta(days=28))
            with _b2:
                comp_e = st.date_input("Comp End",
                                       value=p_start - timedelta(days=1))
        else:
            comp_s, comp_e = get_comp_range(p_start, p_end, comp_mode)

    st.markdown("---")
    st.markdown(
        f'<div class="comp-box"><b>📅 Current:</b><br>{fd(p_start)} → {fd(p_end)}</div>',
        unsafe_allow_html=True,
    )
    if enable_comp and comp_s and comp_e:
        st.markdown(
            f'<div class="comp-box"><b>🔄 Compare:</b><br>'
            f'{fd(comp_s)} → {fd(comp_e)}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    _ai_mod = MOD.get("ai_engine")
    if _ai_mod:
        _pr, _dbg = _ai_mod._get_provider_debug()
        _ic = {"groq": "⚡", "gemini": "💎", "rule_based": "🧠"}
        _nm = {"groq": "Groq", "gemini": "Gemini", "rule_based": "Rules"}
        st.caption(f"{_ic.get(_pr, '🤖')} AI: {_nm.get(_pr, _pr)}")
        if _pr == "rule_based":
            lines = []
            if _dbg["secret_groq"]:
                lines.append(f"⚠️ GROQ key found ({_dbg['groq_len']} chars) but invalid")
            if _dbg["secret_gemini"]:
                lines.append(f"⚠️ GEMINI key found ({_dbg['gemini_len']} chars) but invalid")
            if not lines:
                lines.append("⚠️ No AI keys in secrets — using rule-based")
            for line in lines:
                st.caption(line)
    
    # ── Connection Status (fast check) ──
    try:
        if _SUPABASE_ACTIVE:
            st.sidebar.success("🟢 MONGODB CONNECTED")
            st.sidebar.caption("Fast mode • Live data")
        else:
            st.sidebar.error("🔴 MONGODB OFFLINE")
            st.sidebar.caption("Using Google Sheets fallback (slow)")
            st.sidebar.caption("Check MONGO_URI in secrets.toml")
    except Exception:
        pass
    st.caption(f"Eagle3D Eagle Analytics Hub v7.2 | {datetime.now().strftime('%H:%M')}")
    # Logout button
    if st.button("🔒 Sign Out", key="_auth_logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

# ═══════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════

# ── Auto-trigger pipeline if data is stale ──
# After data loads, check if Daily_Counts has today's date.
# If not and GITHUB_TOKEN is available, automatically trigger the GitHub Actions pipeline once per day.
_today_str = datetime.now().strftime("%Y-%m-%d")
_auto_trigger_key = f"_auto_triggered_{_today_str}"

with st.spinner("Loading data..."):
    counts_raw = pd.DataFrame(load_tab("Daily_Counts"))
    free_raw = pd.DataFrame(load_tab("Verified_FREE"))
    upload_raw = pd.DataFrame(load_tab("Verified_FIRST_UPLOAD"))
    stripe_raw = pd.DataFrame(load_tab("Verified_STRIPE"))

# ── COLUMN NORMALIZER: ensure MongoDB columns match app.py expectations ──
def _norm_cols(df, col_map):
    if df.empty:
        return df
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]
    return df

# Signups: signup_date -> Account Created On
free_raw = _norm_cols(free_raw, {
    "signup_date": "Account Created On",
    "lead_source": "Lead Source",
    "email_normalized": "__email_normalized__",
})
# Uploads: upload_date -> Upload Date
upload_raw = _norm_cols(upload_raw, {
    "upload_date": "Upload Date",
    "email_normalized": "__email_normalized__",
})
# Payments: first_payment_date -> First payment, total_spend -> Amount
stripe_raw = _norm_cols(stripe_raw, {
    "first_payment_date": "First payment",
    "total_spend": "Amount",
    "email_normalized": "__email_normalized__",
})
if not stripe_raw.empty and "row_date_used" not in stripe_raw.columns:
    for _fc in ("First payment", "first_payment_date"):
        if _fc in stripe_raw.columns:
            stripe_raw["row_date_used"] = stripe_raw[_fc]
            break
# Daily counts: ensure correct column names
counts_raw = _norm_cols(counts_raw, {
    "signups_accepted":  "SignUps_Accepted",
    "uploads_accepted":  "FirstUploads_Accepted",
    "paid_accepted":     "PaidSubscribers_Accepted",
    "signup_details":    "SignUp_Details",
    "upload_details":    "Upload_Details",
    "paid_details":      "Paid_Details",
    "last_updated":      "LastUpdated",
    "date":              "Date",
})

# ── DATA SOURCE BANNER (visible on every page) ──
try:
    _sb_chk = get_connection_status()
    if _sb_chk.get("connected"):
        _rows = _sb_chk.get("daily_kpis_rows", 0)
        st.success(f"🟢 LIVE: MongoDB | daily_kpis={_rows} rows | Local MongoDB")
    else:
        _msg = _sb_chk.get("message", "Unknown")
        st.error(f"🔴 MONGODB NOT CONNECTED: {_msg}")
        st.warning("⚠️ Check MONGO_URI in secrets.toml and restart app")
except Exception as _e:
    st.error(f"🔴 MongoDB check failed: {_e}")



# Auto-trigger check (runs once per day per session)
if not st.session_state.get(_auto_trigger_key):
    _has_today = False
    if not counts_raw.empty:
        _dc = next((c for c in counts_raw.columns if "date" in c.lower()), None)
        if _dc:
            _has_today = _today_str in counts_raw[_dc].astype(str).values
    if not _has_today:
        _gh_tok = get_secret("GITHUB_TOKEN", "")
        if _gh_tok:
            try:
                import urllib.request
                _repo = "fozayelibnayaz/eagle3d-kpi-automation"
                _url = (
                    f"https://api.github.com/repos/{_repo}"
                    "/actions/workflows/daily_pipeline.yml/dispatches"
                )
                _data = json.dumps({"ref": "main"}).encode()
                _req = urllib.request.Request(
                    _url, data=_data, method="POST",
                    headers={
                        "Authorization": f"token {_gh_tok}",
                        "Accept": "application/vnd.github+json"
                    }
                )
                with urllib.request.urlopen(_req, timeout=10) as _r:
                    if _r.status in (200, 204):
                        st.toast(
                            "🚀 Auto-triggered daily pipeline (data was stale) "
                            "— refresh in ~5 min for updated numbers",
                            icon="🔄"
                        )
            except Exception:
                pass
    st.session_state[_auto_trigger_key] = True

kpi_all = pd.DataFrame()

# ── METHOD 1: Compute directly from Verified tabs (MOST RELIABLE — always correct) ──
if not free_raw.empty:
    from collections import defaultdict as _dd
    _daily = _dd(lambda: {"signups": 0, "first_uploads": 0, "paid_customers": 0})
    # Count ACCEPTED signups by date
    for _, _row in free_raw.iterrows():
        _st = str(_row.get("final_status", "")).upper()
        if _st == "ACCEPTED":
            _d = parse_to_date(_row.get("Account Created On", ""))
            if _d:
                _daily[_d.strftime("%Y-%m-%d")]["signups"] += 1
    # Count ACCEPTED uploads by date
    if not upload_raw.empty:
        for _, _row in upload_raw.iterrows():
            _st = str(_row.get("final_status", "")).upper()
            if _st == "ACCEPTED":
                _d = parse_to_date(_row.get("Upload Date", ""))
                if _d:
                    _daily[_d.strftime("%Y-%m-%d")]["first_uploads"] += 1
    # Count ACCEPTED paid by date
    if not stripe_raw.empty:
        for _, _row in stripe_raw.iterrows():
            _st = str(_row.get("final_status", "")).upper()
            if _st == "ACCEPTED":
                _d = parse_to_date(_row.get("First payment", "") or _row.get("row_date_used", "") or _row.get("Created", ""))
                if _d:
                    _daily[_d.strftime("%Y-%m-%d")]["paid_customers"] += 1
    _rows = [{"date": _d, **_daily[_d]} for _d in sorted(_daily.keys())]
    if _rows:
        kpi_all = pd.DataFrame(_rows)

# ── METHOD 2: Read pre-aggregated Daily_Counts (PRIMARY source — most reliable) ──
if not counts_raw.empty:
    df = counts_raw.copy()
    dc = next((c for c in df.columns if "date" in c.lower()), None)
    if dc:
        df = df.rename(columns={dc: "date"})
        _col_map = {}
        for c in df.columns:
            cl = c.lower()
            if cl in ("signups_accepted", "signup_accepted", "signups"):
                _col_map[c] = "signups"
            elif cl in ("firstuploads_accepted", "first_upload_accepted", "first_uploads"):
                _col_map[c] = "first_uploads"
            elif cl in ("paidsubscribers_accepted", "paid_accepted", "paid_customers"):
                _col_map[c] = "paid_customers"
        for col, pats in [
            ("signups", ["signups_accepted", "signup", "free", "sign_up"]),
            ("first_uploads", ["firstuploads_accepted", "first_upload", "upload_accepted"]),
            ("paid_customers", ["paidsubscribers_accepted", "paid", "stripe", "customer"]),
        ]:
            if col not in _col_map.values():
                for c in df.columns:
                    if c in _col_map:
                        continue
                    if any(p in c.lower() for p in pats):
                        if "detail" in c.lower() or "email" in c.lower():
                            continue
                        _col_map[c] = col
                        break
        for old, new in _col_map.items():
            df = df.rename(columns={old: new})
        nc = [c for c in ["signups", "first_uploads", "paid_customers"] if c in df.columns]
        for c in nc:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
        if all(c in df.columns for c in ["date", "signups"]):
            _dc_kpi = df[["date"] + nc].copy()
            # If kpi_all is empty (Method 1 failed), use Daily_Counts as-is
            if kpi_all.empty:
                kpi_all = _dc_kpi
            else:
                # Merge: Daily_Counts overwrites Method 1 for matching dates, adds new dates
                _dc_kpi["date"] = _dc_kpi["date"].astype(str)
                kpi_all["date"] = kpi_all["date"].astype(str)
                _existing_dates = set(kpi_all["date"])
                _new_rows = _dc_kpi[~_dc_kpi["date"].isin(_existing_dates)]
                for _ds in _existing_dates.intersection(set(_dc_kpi["date"])):
                    _mask = kpi_all["date"] == _ds
                    for _c in nc:
                        _dc_val = _dc_kpi.loc[_dc_kpi["date"] == _ds, _c].values
                        if len(_dc_val) > 0:
                            kpi_all.loc[_mask, _c] = _dc_val[0]
                if not _new_rows.empty:
                    kpi_all = pd.concat([kpi_all, _new_rows], ignore_index=True)

# ── METHOD 3: Historical JSON fallback ──
if kpi_all.empty:
    _hist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_output", "historical_accounts.json")
    _paid_path = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_output", "historical_paid.json"))
    if os.path.exists(_hist_path):
        try:
            from collections import defaultdict as _dd
            _daily = _dd(lambda: {"signups": 0, "first_uploads": 0, "paid_customers": 0})
            with open(_hist_path, "r") as _f:
                _accounts = json.load(_f)
            for _email, _info in _accounts.items():
                for _date, _details in _info.get("rows_by_date", {}).items():
                    _daily[_date]["signups"] += 1
                    if _details.get("has_upload_yes", False):
                        _daily[_date]["first_uploads"] += 1
            if os.path.exists(_paid_path):
                with open(_paid_path, "r") as _f:
                    _paid = json.load(_f)
                for _email, _info in _paid.items():
                    if _info.get("has_paid", False):
                        for _d in _info.get("all_created_utc", []):
                            _daily[_d]["paid_customers"] += 1
            _rows = [{"date": _d, **_daily[_d]} for _d in sorted(_daily.keys())]
            if _rows:
                kpi_all = pd.DataFrame(_rows)

        except Exception:
            pass
kpi = filter_kpi(kpi_all, p_start, p_end)

# ── SUPABASE FAST KPI OVERRIDE ──
# Use direct MongoDB counts for today/month (always accurate)
_sb_kpi = get_supabase_kpi_fast()
if _sb_kpi:
    _sb_today_s = _sb_kpi["today_signups"]
    _sb_today_u = _sb_kpi["today_uploads"]
    _sb_today_p = _sb_kpi["today_paid"]
    _sb_month_s = _sb_kpi["month_signups"]
    _sb_month_u = _sb_kpi["month_uploads"]
    _sb_month_p = _sb_kpi["month_paid"]
    _sb_common_s = _sb_kpi["common_signups"]
    _sb_common_u = _sb_kpi["common_uploads"]
    _sb_common_p = _sb_kpi["common_paid"]
    _sb_common_start = _sb_kpi["common_start"]
else:
    _sb_today_s = _sb_today_u = _sb_today_p = 0
    _sb_month_s = _sb_month_u = _sb_month_p = 0
    _sb_common_s = _sb_common_u = _sb_common_p = 0
    _sb_common_start = "2025-12-01"

prev_kpi = (
    filter_kpi(kpi_all, comp_s, comp_e)
    if enable_comp and comp_s
    else pd.DataFrame()
)

# ── HARD OVERRIDE: Always count paid from Verified_STRIPE ACCEPTED rows directly ──
# This ensures the paid count is ALWAYS correct regardless of Daily_Counts column mismatches
# FIX: Never zeros existing paid data — only supplements/overwrites for dates with new ACCEPTED rows
if not stripe_raw.empty:
    _hard_direct_paid = sum(
        1 for _, r in stripe_raw.iterrows()
        if str(r.get("final_status", str(r.get("Final_Status", "")))).upper() == "ACCEPTED"
    )
    _kpi_paid_sum = int(kpi_all["paid_customers"].sum()) if not kpi_all.empty and "paid_customers" in kpi_all.columns else 0
    if _kpi_paid_sum != _hard_direct_paid:
        _paid_by_date = {}
        for _, r in stripe_raw.iterrows():
            _fs = str(r.get("final_status", str(r.get("Final_Status", "")))).upper()
            if _fs == "ACCEPTED":
                _pd = parse_to_date(r.get("First payment", "") or r.get("row_date_used", "") or r.get("Created", ""))
                if _pd:
                    _ds = _pd.strftime("%Y-%m-%d")
                    _paid_by_date[_ds] = _paid_by_date.get(_ds, 0) + 1
        _dated_count = sum(_paid_by_date.values())
        _undated = _hard_direct_paid - _dated_count
        if _undated > 0:
            _today_ds = datetime.now().strftime("%Y-%m-%d")
            _paid_by_date[_today_ds] = _paid_by_date.get(_today_ds, 0) + _undated
        # Apply paid counts per date — only update dates that have ACCEPTED rows
        # Never zero out existing data for dates without ACCEPTED rows
        if not kpi_all.empty and "paid_customers" in kpi_all.columns:
            for _ds, _cnt in _paid_by_date.items():
                _mask = kpi_all["date"] == _ds if "date" in kpi_all.columns else pd.Series([False])
                if _mask.any():
                    kpi_all.loc[_mask, "paid_customers"] = _cnt
                else:
                    _new = {"date": _ds, "signups": 0, "first_uploads": 0, "paid_customers": _cnt}
                    kpi_all = pd.concat([kpi_all, pd.DataFrame([_new])], ignore_index=True)
            # Re-filter
            kpi = filter_kpi(kpi_all, p_start, p_end)
            prev_kpi = filter_kpi(kpi_all, comp_s, comp_e) if enable_comp and comp_s else pd.DataFrame()

free_rows = free_raw.copy()
upload_rows = upload_raw.copy()

# ── Apply manual overrides to in-memory data ──
# Override flow:
#   1. Load overrides from data_output/manual_overrides.json
#   2. Apply to free_rows, upload_rows, stripe_raw (change final_status)
#   3. Compute DELTA: how many rows changed status (ACCEPTED→REJECTED or REJECTED→ACCEPTED)
#   4. Adjust kpi_all by the delta per date so counts reflect overrides
#   5. This avoids rebuilding kpi_all from scratch (which can lose non-parseable-date rows)
_ov_engine = MOD.get("manual_override_engine")
_ov_applied_total = 0
_ov_changed_total = 0  # How many rows actually changed status


def _apply_overrides_to_df(df, tab_name, overrides, norm_fn, mapping):
    """Apply overrides to a DataFrame in-place. Returns (applied, changed) counts."""
    if df.empty or "final_status" not in df.columns or not overrides:
        return 0, 0
    applied = 0
    changed = 0
    for _idx, _row in df.iterrows():
        _em = ""
        for _k in ("Email", "email", "__email_normalized__"):
            if _k in df.columns and pd.notna(_row.get(_k)) and "@" in str(_row[_k]):
                _em = str(_row[_k]).strip().lower()
                break
        _norm = norm_fn(_em) if _em else ""
        if _norm and _norm in overrides:
            _ov = overrides[_norm]
            _ov_tab = _ov.get("target_tab", "ALL")
            if _ov_tab in ("ALL", tab_name):
                _action = _ov.get("action", "")
                _m = mapping.get(_action, {})
                if _m:
                    _old_status = str(df.at[_idx, "final_status"]).upper()
                    _new_status = _m["final_status"]
                    df.at[_idx, "final_status"] = _new_status
                    df.at[_idx, "category"] = _m.get("category", "")
                    applied += 1
                    # Track actual changes (status flipped)
                    if _old_status != _new_status.upper():
                        changed += 1
    return applied, changed


_ovs = {}  # Initialize globally for delta calculation
if _ov_engine:
    try:
        from manual_override_engine import normalize_email, ACTION_TO_STATUS
        _ovs = _ov_engine.load_overrides()
        if _ovs:
            _a1, _c1 = _apply_overrides_to_df(
                free_rows, "Verified_FREE", _ovs, normalize_email, ACTION_TO_STATUS
            )
            _a2, _c2 = _apply_overrides_to_df(
                upload_rows, "Verified_FIRST_UPLOAD", _ovs, normalize_email, ACTION_TO_STATUS
            )
            _a3, _c3 = _apply_overrides_to_df(
                stripe_raw, "Verified_STRIPE", _ovs, normalize_email, ACTION_TO_STATUS
            )
            _ov_applied_total = _a1 + _a2 + _a3
            _ov_changed_total = _c1 + _c2 + _c3

            # Show override toast ONLY once per session (not on every rerun)
            if _ov_changed_total > 0 and not st.session_state.get("_ov_toast_shown"):
                st.toast(f"🔄 {_ov_applied_total} overrides applied ({_ov_changed_total} status changes)", icon="✏️")
                st.session_state["_ov_toast_shown"] = True
            elif _ov_applied_total > 0 and not st.session_state.get("_ov_toast_shown"):
                st.toast(f"ℹ️ {_ov_applied_total} overrides active (no new changes)", icon="📋")
                st.session_state["_ov_toast_shown"] = True

    except Exception:
        pass
# ── Adjust kpi_all by override delta ──
# Instead of rebuilding from verified tabs (risky: may lose rows without parseable dates),
# we compute the delta per date and adjust kpi_all.
if _ov_changed_total > 0 and not kpi_all.empty:
    # Build delta from free_rows (overridden) vs what the status was before override
    _delta = {}  # date -> {"signups_delta": N, "first_uploads_delta": N, "paid_customers_delta": N}
    if "final_status" in free_rows.columns:
        for _, _r in free_rows.iterrows():
            _st = str(_r.get("final_status", "")).upper()
            _norm_email = ""
            for _k in ("Email", "email", "__email_normalized__"):
                if _k in free_rows.columns and pd.notna(_r.get(_k)) and "@" in str(_r[_k]):
                    _norm_email = normalize_email(str(_r[_k]).strip().lower()) if _ov_engine else ""
                    break
            if not _norm_email or _norm_email not in _ovs:
                continue
            _ov = _ovs[_norm_email]
            _orig_cat = str(_ov.get("original_category", "")).upper()
            _new_st = _st
            _d = parse_to_date(_r.get("Account Created On", ""))
            if not _d:
                continue
            _ds = _d.strftime("%Y-%m-%d")
            if _ds not in _delta:
                _delta[_ds] = {"signups_delta": 0, "first_uploads_delta": 0, "paid_customers_delta": 0}
            # If original was ACCEPTED and now REJECTED → -1
            # If original was REJECTED and now ACCEPTED → +1
            if _orig_cat == "ACCEPTED" and _new_st != "ACCEPTED":
                _delta[_ds]["signups_delta"] -= 1
            elif _orig_cat != "ACCEPTED" and _new_st == "ACCEPTED":
                _delta[_ds]["signups_delta"] += 1

    if "final_status" in upload_rows.columns:
        for _, _r in upload_rows.iterrows():
            _st = str(_r.get("final_status", "")).upper()
            _norm_email = ""
            for _k in ("Email", "email", "__email_normalized__"):
                if _k in upload_rows.columns and pd.notna(_r.get(_k)) and "@" in str(_r[_k]):
                    _norm_email = normalize_email(str(_r[_k]).strip().lower()) if _ov_engine else ""
                    break
            if not _norm_email or _norm_email not in _ovs:
                continue
            _ov = _ovs[_norm_email]
            _orig_cat = str(_ov.get("original_category", "")).upper()
            _new_st = _st
            _d = parse_to_date(_r.get("Upload Date", ""))
            if not _d:
                continue
            _ds = _d.strftime("%Y-%m-%d")
            if _ds not in _delta:
                _delta[_ds] = {"signups_delta": 0, "first_uploads_delta": 0, "paid_customers_delta": 0}
            if _orig_cat == "ACCEPTED" and _new_st != "ACCEPTED":
                _delta[_ds]["first_uploads_delta"] -= 1
            elif _orig_cat != "ACCEPTED" and _new_st == "ACCEPTED":
                _delta[_ds]["first_uploads_delta"] += 1

    if "final_status" in stripe_raw.columns:
        for _, _r in stripe_raw.iterrows():
            _st = str(_r.get("final_status", "")).upper()
            _norm_email = ""
            for _k in ("Email", "email", "__email_normalized__"):
                if _k in stripe_raw.columns and pd.notna(_r.get(_k)) and "@" in str(_r[_k]):
                    _norm_email = normalize_email(str(_r[_k]).strip().lower()) if _ov_engine else ""
                    break
            if not _norm_email or _norm_email not in _ovs:
                continue
            _ov = _ovs[_norm_email]
            _orig_cat = str(_ov.get("original_category", "")).upper()
            _new_st = _st
            # Prefer First payment date, then row_date_used, then Created
            _d = parse_to_date(_r.get("First payment", "") or _r.get("row_date_used", "") or _r.get("Created", ""))
            if not _d:
                continue
            _ds = _d.strftime("%Y-%m-%d")
            if _ds not in _delta:
                _delta[_ds] = {"signups_delta": 0, "first_uploads_delta": 0, "paid_customers_delta": 0}
            if _orig_cat == "ACCEPTED" and _new_st != "ACCEPTED":
                _delta[_ds]["paid_customers_delta"] -= 1
            elif _orig_cat != "ACCEPTED" and _new_st == "ACCEPTED":
                _delta[_ds]["paid_customers_delta"] += 1

    # Apply delta to kpi_all
    if _delta and "date" in kpi_all.columns:
        kpi_all = kpi_all.copy()
        for _ds, _deltas in _delta.items():
            _mask = kpi_all["date"] == _ds
            if _mask.any():
                for _col, _key in [("signups", "signups_delta"), ("first_uploads", "first_uploads_delta"), ("paid_customers", "paid_customers_delta")]:
                    if _col in kpi_all.columns and _deltas[_key] != 0:
                        kpi_all.loc[_mask, _col] = kpi_all.loc[_mask, _col] + _deltas[_key]
            else:
                # Date not in kpi_all — add a new row for this date
                _new_row = {"date": _ds, "signups": 0, "first_uploads": 0, "paid_customers": 0}
                for _col, _key in [("signups", "signups_delta"), ("first_uploads", "first_uploads_delta"), ("paid_customers", "paid_customers_delta")]:
                    _new_row[_col] = max(0, _deltas[_key])
                kpi_all = pd.concat([kpi_all, pd.DataFrame([_new_row])], ignore_index=True)

        # Ensure no negative counts
        for _col in ["signups", "first_uploads", "paid_customers"]:
            if _col in kpi_all.columns:
                kpi_all[_col] = kpi_all[_col].clip(lower=0)

        # Re-apply date filter
        kpi = filter_kpi(kpi_all, p_start, p_end)
        prev_kpi = (
            filter_kpi(kpi_all, comp_s, comp_e)
            if enable_comp and comp_s
            else pd.DataFrame()
        )

# ── FINAL PAID OVERRIDE: Force paid count to match Verified_STRIPE ACCEPTED for this period ──
_correct_paid = None
if not stripe_raw.empty and "final_status" in stripe_raw.columns:
    try:
        _fs_s = stripe_raw["final_status"].astype(str).str.upper()
        _stripe_acc = stripe_raw[_fs_s == "ACCEPTED"].copy()
        if not _stripe_acc.empty:
            _stripe_acc["_paid_date"] = _stripe_acc.apply(
                lambda r: parse_to_date(r.get("First payment", "") or r.get("row_date_used", "") or r.get("Created", "")),
                axis=1
            )
            _stripe_acc = _stripe_acc.dropna(subset=["_paid_date"])
            _s_acc_period = _stripe_acc[(_stripe_acc["_paid_date"] >= p_start) & (_stripe_acc["_paid_date"] <= p_end)]
            _correct_paid = len(_s_acc_period)

    except Exception:
        pass
leads_df = pd.DataFrame()
if "kpi_bridge" in MOD and not free_rows.empty:
    try:
        leads_df = MOD["kpi_bridge"].attribute_signups_by_lead_source(
            p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d")
        )
    except Exception:
        pass
if leads_df.empty and "source_normalizer" in MOD and not free_rows.empty:
    try:
        # Apply date filter to free_rows before aggregating sources
        _fr_filtered = free_rows.copy()
        if "Account Created On" in _fr_filtered.columns:
            _fr_filtered["_src_date"] = _fr_filtered["Account Created On"].apply(
                lambda x: parse_to_date(x)
            )
            _fr_filtered = _fr_filtered[
                (_fr_filtered["_src_date"] >= p_start)
                & (_fr_filtered["_src_date"] <= p_end)
            ].drop(columns=["_src_date"])
        if not _fr_filtered.empty:
            leads_df = MOD["source_normalizer"].aggregate_normalized_sources(_fr_filtered)

    except Exception:
        pass
utm_df = pages_df = events_df = geo_df = pd.DataFrame()
prev_utm_df = pd.DataFrame()
if "ga4_connector" in MOD:
    for attr, tgt in [
        ("fetch_utm_traffic", "utm_df"),
        ("fetch_page_performance", "pages_df"),
        ("fetch_event_performance", "events_df"),
        ("fetch_geo_traffic", "geo_df"),
    ]:
        try:
            globals()[tgt] = getattr(MOD["ga4_connector"], attr)(
                p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d")
            )
        except Exception:
            pass
    if enable_comp and comp_s:
        try:
            prev_utm_df = MOD["ga4_connector"].fetch_utm_traffic(
                comp_s.strftime("%Y-%m-%d"), comp_e.strftime("%Y-%m-%d")
            )
        except Exception:
            pass


# ── Time-to-Conversion Analytics ──
def _build_time_to_conversion(free_df, upload_df, stripe_df=None, mode="signup_to_upload", ledger_path=None):
    """Build time-to-conversion analytics for a given funnel stage.
    mode: 'signup_to_upload', 'signup_to_paid', 'upload_to_paid'
    """
    _start_label = {"signup_to_upload": "Sign-up", "signup_to_paid": "Sign-up", "upload_to_paid": "First Upload"}
    _end_label = {"signup_to_upload": "First Upload", "signup_to_paid": "Paid", "upload_to_paid": "Paid"}
    _st_label = _start_label.get(mode, "Start")
    _en_label = _end_label.get(mode, "End")

    if mode == "signup_to_upload":
        if free_df is None or free_df.empty or upload_df is None or upload_df.empty:
            return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label
        _src = free_df.loc[free_df["final_status"].astype(str).str.upper() == "ACCEPTED"].copy() if "final_status" in free_df.columns else free_df.copy()
        _tgt = upload_df.loc[upload_df["final_status"].astype(str).str.upper() == "ACCEPTED"].copy() if "final_status" in upload_df.columns else upload_df.copy()
        if _src.empty or _tgt.empty:
            return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label
    elif mode == "signup_to_paid":
        if free_df is None or (hasattr(free_df, 'empty') and free_df.empty) or stripe_df is None or (hasattr(stripe_df, 'empty') and stripe_df.empty):
            return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label
        _src = free_df.loc[free_df["final_status"].astype(str).str.upper() == "ACCEPTED"].copy() if "final_status" in free_df.columns else free_df.copy()
        _tgt = stripe_df.loc[stripe_df["final_status"].astype(str).str.upper() == "ACCEPTED"].copy() if "final_status" in stripe_df.columns else stripe_df.copy()
        if _src.empty or _tgt.empty:
            return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label
    elif mode == "upload_to_paid":
        if upload_df is None or (hasattr(upload_df, 'empty') and upload_df.empty) or stripe_df is None or (hasattr(stripe_df, 'empty') and stripe_df.empty):
            return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label
        _src = upload_df.loc[upload_df["final_status"].astype(str).str.upper() == "ACCEPTED"].copy() if "final_status" in upload_df.columns else upload_df.copy()
        _tgt = stripe_df.loc[stripe_df["final_status"].astype(str).str.upper() == "ACCEPTED"].copy() if "final_status" in stripe_df.columns else stripe_df.copy()
        if _src.empty or _tgt.empty:
            return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label

    _email_col_src = next((c for c in _src.columns if "email" in c.lower() and "normalized" in c.lower() and not c.startswith("__")), None)
    if not _email_col_src:
        _email_col_src = next((c for c in _src.columns if "email" in c.lower()), None)
    _email_col_tgt = next((c for c in _tgt.columns if "email" in c.lower() and "normalized" in c.lower() and not c.startswith("__")), None)
    if not _email_col_tgt:
        _email_col_tgt = next((c for c in _tgt.columns if "email" in c.lower()), None)
    if not _email_col_src or not _email_col_tgt:
        return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label

    # Source date column
    if mode in ("signup_to_upload", "signup_to_paid"):
        _date_col_src = next((c for c in _src.columns if "created" in c.lower() or "signup" in c.lower() or "account" in c.lower()), None)
        if not _date_col_src:
            _date_col_src = next((c for c in _src.columns if "date" in c.lower()), None)
    else:
        _date_col_src = "Upload Date" if "Upload Date" in _src.columns else next((c for c in _src.columns if "upload" in c.lower() or "date" in c.lower()), None)

    # Target date column
    if mode == "signup_to_upload":
        _date_col_tgt = "Upload Date" if "Upload Date" in _tgt.columns else next((c for c in _tgt.columns if "upload" in c.lower() or "date" in c.lower()), None)
    else:
        _date_col_tgt = next((c for c in _tgt.columns if "created" in c.lower() or "payment" in c.lower() or "date" in c.lower()), None)

    if not _date_col_src or not _date_col_tgt:
        return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label

    _src_map = {}
    for _, r in _src.iterrows():
        _em = str(r.get(_email_col_src, "")).strip().lower()
        _d = parse_to_date(r.get(_date_col_src, ""))
        if _em and _d:
            if _em not in _src_map or _d < _src_map[_em]:
                _src_map[_em] = _d

    _tgt_map = {}
    for _, r in _tgt.iterrows():
        _em = str(r.get(_email_col_tgt, "")).strip().lower()
        _d = parse_to_date(r.get(_date_col_tgt, ""))
        if _em and _d:
            if _em not in _tgt_map or _d < _tgt_map[_em]:
                _tgt_map[_em] = _d

    if mode == "signup_to_upload" and ledger_path and os.path.exists(ledger_path):
        try:
            with open(ledger_path) as _lf:
                _ledger = json.load(_lf)
            for _em, _info in _ledger.items():
                _up_d = parse_to_date(_info.get("first_upload_date", ""))
                if _em and _up_d:
                    if _em not in _tgt_map or _up_d < _tgt_map[_em]:
                        _tgt_map[_em] = _up_d

        except Exception:
            pass
    _rows = []
    for _em, _start_date in _src_map.items():
        _end_date = _tgt_map.get(_em)
        if _end_date:
            _gap = (_end_date - _start_date).days
            _rows.append({"email": _em, "start_date": _start_date, "end_date": _end_date, "gap_days": max(_gap, 0)})
    if not _rows:
        return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label

    _df_rows = pd.DataFrame(_rows)
    for _dt_col in ["start_date", "end_date"]:
        if _dt_col in _df_rows.columns:
            _df_rows[_dt_col] = pd.to_datetime(_df_rows[_dt_col], errors="coerce")
    _df_rows = _df_rows.dropna(subset=["start_date", "end_date"])
    if _df_rows.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), [], _st_label, _en_label
    _df_rows["gap_days"] = (_df_rows["end_date"] - _df_rows["start_date"]).dt.days.clip(lower=0)
    _rows = _df_rows.to_dict("records")
    _gaps = _df_rows["gap_days"]
    _stats = {
        "matched_users": len(_df_rows), "mean_days": round(_gaps.mean(), 1), "median_days": int(_gaps.median()),
        "min_days": int(_gaps.min()), "max_days": int(_gaps.max()),
        "p25_days": int(_gaps.quantile(0.25)), "p75_days": int(_gaps.quantile(0.75)), "p90_days": int(_gaps.quantile(0.90)),
        "within_7d": int((_gaps <= 7).sum()), "within_14d": int((_gaps <= 14).sum()),
        "within_30d": int((_gaps <= 30).sum()), "within_60d": int((_gaps <= 60).sum()),
        "pct_7d": round((_gaps <= 7).mean() * 100, 1), "pct_14d": round((_gaps <= 14).mean() * 100, 1),
        "pct_30d": round((_gaps <= 30).mean() * 100, 1), "pct_60d": round((_gaps <= 60).mean() * 100, 1),
    }
    _bins = list(range(0, min(max(_stats["max_days"], 7) + 7, 365), 7))
    if _bins[-1] < _stats["max_days"]:
        _bins.append(_stats["max_days"] + 1)
    _hist = pd.cut(_df_rows["gap_days"], bins=_bins, right=False)
    _hist_df = _hist.value_counts().sort_index().reset_index()
    _hist_df.columns = ["range", "count"]
    _hist_df["range"] = _hist_df["range"].astype(str)
    _df_rows["start_month"] = _df_rows["start_date"].dt.strftime("%Y-%m")
    _monthly = _df_rows.groupby("start_month").agg(
        users=("email", "count"), median_days=("gap_days", "median"), mean_days=("gap_days", "mean"),
    ).reset_index().sort_values("start_month")
    _monthly.rename(columns={"start_month": "month"}, inplace=True)
    return _stats, _hist_df, _monthly, _rows, _st_label, _en_label


period_label = f"{fd(p_start)} to {fd(p_end)}"

# Universal Settings override
if st.session_state.get("_go_settings"):
    st.session_state["_go_settings"] = False
    page = "⚙️ Settings"

# ═══════════════════════════════════════════════════════════════
# PAGE: 📊 DASHBOARD
# ═══════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.markdown(
        '<div class="sec-head">📊 Executive Dashboard</div>',
        unsafe_allow_html=True,
    )
    # App link — prominent and clickable
    st.markdown(
        'Eagle3D **App URL:** [https://eagle3d-kpi-automation.streamlit.app/](https://eagle3d-kpi-automation.streamlit.app/)',
        unsafe_allow_html=False,
    )

    # ── EXECUTIVE DASHBOARD: Core Business Metrics ──
    with st.expander("📊 Core Business Metrics (Revenue / Signups / Uploads / Growth)", expanded=True):
        try:
            from executive_dashboard_ui import render_executive_dashboard
            render_executive_dashboard()
        except Exception as _ed_err:
            st.error(f"Executive Dashboard error: {_ed_err}")
            import traceback
            st.code(traceback.format_exc()[:1000])


    # Data diagnostics
    _total_all = int(kpi_all["signups"].sum()) if not kpi_all.empty and "signups" in kpi_all.columns else 0
    _total_u_all = int(kpi_all["first_uploads"].sum()) if not kpi_all.empty and "first_uploads" in kpi_all.columns else 0
    _total_p_all = int(kpi_all["paid_customers"].sum()) if not kpi_all.empty and "paid_customers" in kpi_all.columns else 0
    if _total_all > 0 or _total_u_all > 0 or _total_p_all > 0:
        _src = "Daily_Counts" if not counts_raw.empty else "Verified tabs" if not free_raw.empty else "Historical JSON"
        _ov_note = f" | ✏️ {_ov_applied_total} overrides active" if _ov_applied_total > 0 else ""
        st.caption(f"📡 Source: {_src} | All-time: {_total_all:,} sign-ups, {_total_u_all:,} uploads, {_total_p_all:,} paid{_ov_note}")
    else:
        st.warning("⚠️ No KPI data loaded. Check Settings → Secrets Status.")

    cs = km(kpi, "signups")
    cu = km(kpi, "first_uploads")
    cp = _correct_paid if _correct_paid is not None else km(kpi, "paid_customers")
    ps = km(prev_kpi, "signups")
    pu = km(prev_kpi, "first_uploads")
    pp = km(prev_kpi, "paid_customers")

    # ── SUPABASE COMMON PERIOD OVERRIDE for All Time view ──
    # When showing "All Time", force values to common period (Dec 2025 onwards)
    # so all 3 metrics use the same date range = valid conversion rates
    try:
        _is_alltime = str(period).lower().startswith("all") if "period" in dir() else False
    except Exception:
        _is_alltime = False
    if _sb_kpi:
        # If the selected period is All Time, use common period values
        if _is_alltime or (cs > _sb_kpi["common_signups"] * 1.5):
            # Detect if cs is using full DB (much larger than common period)
            cs = _sb_kpi["common_signups"]
            cu = _sb_kpi["common_uploads"]
            cp = _sb_kpi["common_paid"]
        # This Month
        elif "this month" in str(period).lower() if "period" in dir() else False:
            cs = _sb_kpi["month_signups"]
            cu = _sb_kpi["month_uploads"]
            cp = _sb_kpi["month_paid"]
        # Today
        elif "today" in str(period).lower() if "period" in dir() else False:
            cs = _sb_kpi["today_signups"]
            cu = _sb_kpi["today_uploads"]
            cp = _sb_kpi["today_paid"]

    # Paid count is verified from Verified_STRIPE ACCEPTED rows
    s2u = (cu / cs * 100) if cs > 0 else 0
    u2p = (cp / cu * 100) if cu > 0 else 0
    s2p = (cp / cs * 100) if cs > 0 else 0
    ps2u = (pu / ps * 100) if ps > 0 else 0
    pu2p = (pp / pu * 100) if pu > 0 else 0
    ps2p = (pp / ps * 100) if ps > 0 else 0

    h = '<div class="kpi-grid">'
    h += kpi_h("Sign-ups (Accepted)", cs, delta_h(cs, ps), "👥")
    h += kpi_h("First Uploads (Accepted)", cu, delta_h(cu, pu), "📤")
    h += kpi_h("Paid (Accepted)", cp, delta_h(cp, pp), "💳")
    h += kpi_h("S→U Rate", f"{s2u:.1f}%", delta_h(s2u, ps2u), "🔄")
    h += kpi_h("U→P Rate", f"{u2p:.1f}%", delta_h(u2p, pu2p), "💰")
    h += kpi_h("S→P Rate", f"{s2p:.1f}%", delta_h(s2p, ps2p), "🎯")
    h += "</div>"
    st.markdown(h, unsafe_allow_html=True)
    # ── Pattern Analysis Section ──
    with st.expander("📊 Pattern Analysis — Region + Time + Anomalies", expanded=False):
        try:
            from kpi_pattern_ui import render_kpi_pattern_analysis
            pat_tabs = st.tabs(["👥 Sign-ups", "📤 First Uploads", "💳 Paid"])
            with pat_tabs[0]:
                render_kpi_pattern_analysis("signups")
            with pat_tabs[1]:
                render_kpi_pattern_analysis("uploads")
            with pat_tabs[2]:
                render_kpi_pattern_analysis("paid")
        except Exception as _pe:
            st.warning(f"Pattern analysis: {_pe}")


    # ── Conversion-Time & Analytical Metrics ──
    _ct_c1, _ct_c2, _ct_c3, _ct_c4 = st.columns(4)
    # Compute signup→paid time from joined data
    _avg_signup_to_paid = None
    _avg_upload_to_paid = None
    _churn_rate = None
    _avg_sub_len = None
    if not free_rows.empty and not stripe_raw.empty:
        try:
            _free_emails = {}
            for _, _r in free_rows.iterrows():
                _em = str(_r.get("Email", "")).lower().strip()
                _d = parse_to_date(_r.get("Account Created On", ""))
                if _em and "@" in _em and _d and str(_r.get("final_status", "")).upper() == "ACCEPTED":
                    _free_emails[_em] = _d
            _paid_join = []
            for _, _r in stripe_raw.iterrows():
                _em = str(_r.get("Email", "")).lower().strip()
                _pd = parse_to_date(_r.get("First payment", "") or _r.get("row_date_used", "") or _r.get("Created", ""))
                if _em and "@" in _em and _pd and str(_r.get("final_status", "")).upper() == "ACCEPTED":
                    _paid_join.append({"email": _em, "paid_date": _pd})
            _times = []
            for pj in _paid_join:
                if pj["email"] in _free_emails:
                    _diff = (pj["paid_date"] - _free_emails[pj["email"]]).days
                    if _diff >= 0:
                        _times.append(_diff)
            if _times:
                _avg_signup_to_paid = sum(_times) / len(_times)

        except Exception:
            pass
    if not upload_rows.empty and not stripe_raw.empty:
        try:
            _upload_emails = {}
            for _, _r in upload_rows.iterrows():
                _em = str(_r.get("Email", "")).lower().strip()
                _d = parse_to_date(_r.get("Upload Date", "") or _r.get("Account Created On", ""))
                if _em and "@" in _em and _d and str(_r.get("final_status", "")).upper() == "ACCEPTED":
                    _upload_emails[_em] = _d
            _paid_join2 = []
            for _, _r in stripe_raw.iterrows():
                _em = str(_r.get("Email", "")).lower().strip()
                _pd = parse_to_date(_r.get("First payment", "") or _r.get("row_date_used", "") or _r.get("Created", ""))
                if _em and "@" in _em and _pd and str(_r.get("final_status", "")).upper() == "ACCEPTED":
                    _paid_join2.append({"email": _em, "paid_date": _pd})
            _times_u = []
            for pj in _paid_join2:
                if pj["email"] in _upload_emails:
                    _diff = (pj["paid_date"] - _upload_emails[pj["email"]]).days
                    if _diff >= 0:
                        _times_u.append(_diff)
            if _times_u:
                _avg_upload_to_paid = sum(_times_u) / len(_times_u)

        except Exception:
            pass
    # Churn rate: paid customers whose last payment was >90 days ago
    if not stripe_raw.empty:
        try:
            _paid_dates = []
            for _, _r in stripe_raw.iterrows():
                _pd = parse_to_date(_r.get("First payment", "") or _r.get("row_date_used", "") or _r.get("Created", ""))
                if _pd and str(_r.get("final_status", "")).upper() == "ACCEPTED":
                    _paid_dates.append(_pd)
            if len(_paid_dates) >= 5:
                _cutoff = datetime.now() - timedelta(days=90)
                _churned = sum(1 for d in _paid_dates if d <= _cutoff)
                _churn_rate = _churned / len(_paid_dates) * 100
                # Average subscription length
                _now = datetime.now()
                _lengths = [(_now - d).days for d in _paid_dates]
                _avg_sub_len = sum(_lengths) / len(_lengths)

        except Exception:
            pass
    with _ct_c1:
        _ct1_val = f"{_avg_signup_to_paid:.1f}d" if _avg_signup_to_paid is not None else "—"
        st.metric("⏱ Avg Signup→Paid", _ct1_val, help="Average days from account creation to first payment")
    with _ct_c2:
        _ct2_val = f"{_avg_upload_to_paid:.1f}d" if _avg_upload_to_paid is not None else "—"
        st.metric("⏱ Avg Upload→Paid", _ct2_val, help="Average days from first upload to first payment")
    with _ct_c3:
        _ct3_val = f"{_churn_rate:.1f}%" if _churn_rate is not None else "—"
        st.metric("🔄 Churn Rate (>90d)", _ct3_val, help="% of paid customers inactive for 90+ days")
    with _ct_c4:
        _ct4_val = f"{_avg_sub_len:.0f}d" if _avg_sub_len is not None else "—"
        st.metric("📆 Avg Subscription", _ct4_val, help="Average days since first payment (lifetime)")

    st.markdown("---")

    # ── Monthly Goals Tracker ──
    _cur_month = datetime.now().strftime("%Y-%m")
    # Use MongoDB direct counts (fast + accurate)
    if _sb_kpi:
        _month_s = _sb_kpi["month_signups"]
        _month_u = _sb_kpi["month_uploads"]
        _month_p = _sb_kpi["month_paid"]
    else:
        _month_kpi = kpi_all.copy() if not kpi_all.empty else pd.DataFrame()
        if not _month_kpi.empty and "date" in _month_kpi.columns:
            _month_kpi["_d"] = pd.to_datetime(_month_kpi["date"], errors="coerce").dt.strftime("%Y-%m")
            _month_kpi = _month_kpi[_month_kpi["_d"] == _cur_month].drop(columns=["_d"])
        _month_s = int(_month_kpi["signups"].sum()) if not _month_kpi.empty and "signups" in _month_kpi.columns else 0
        _month_u = int(_month_kpi["first_uploads"].sum()) if not _month_kpi.empty and "first_uploads" in _month_kpi.columns else 0
        _month_p = int(_month_kpi["paid_customers"].sum()) if not _month_kpi.empty and "paid_customers" in _month_kpi.columns else 0

    _goals_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_output", "monthly_goals.json")

    def _load_goals():
        if os.path.exists(_goals_file):
            try:
                with open(_goals_file, "r") as _gf:
                    return json.load(_gf)
            except Exception:
                pass
        return {}

    def _save_goals(data):
        os.makedirs(os.path.dirname(_goals_file), exist_ok=True)
        with open(_goals_file, "w") as _gf:
            json.dump(data, _gf, indent=2)

    _goals = _load_goals()
    _goal_s = _goals.get("signups", 100)
    _goal_u = _goals.get("uploads", 30)
    _goal_p = _goals.get("paid", 5)

    with st.expander("🎯 Monthly Goals — " + datetime.now().strftime("%B %Y"), expanded=True):
        _gc1, _gc2, _gc3 = st.columns(3)
        with _gc1:
            _pct_s = (_month_s / _goal_s * 100) if _goal_s > 0 else 0
            st.metric("👥 Sign-ups", f"{_month_s} / {_goal_s}", f"{_pct_s:.0f}% of goal",
                      delta_color="normal" if _pct_s >= 50 else "inverse")
            st.progress(min(_pct_s / 100, 1.0))
        with _gc2:
            _pct_u = (_month_u / _goal_u * 100) if _goal_u > 0 else 0
            st.metric("📤 Uploads", f"{_month_u} / {_goal_u}", f"{_pct_u:.0f}% of goal",
                      delta_color="normal" if _pct_u >= 50 else "inverse")
            st.progress(min(_pct_u / 100, 1.0))
        with _gc3:
            _pct_p = (_month_p / _goal_p * 100) if _goal_p > 0 else 0
            st.metric("💳 Paid", f"{_month_p} / {_goal_p}", f"{_pct_p:.0f}% of goal",
                      delta_color="normal" if _pct_p >= 50 else "inverse")
            st.progress(min(_pct_p / 100, 1.0))

        _g_e1, _g_e2, _g_e3 = st.columns(3)
        with _g_e1:
            _new_gs = st.number_input("Sign-up Goal", value=_goal_s, min_value=1, key="goal_s")
        with _g_e2:
            _new_gu = st.number_input("Upload Goal", value=_goal_u, min_value=1, key="goal_u")
        with _g_e3:
            _new_gp = st.number_input("Paid Goal", value=_goal_p, min_value=1, key="goal_p")
        if st.button("💾 Save Goals", use_container_width=True):
            _save_goals({"signups": _new_gs, "uploads": _new_gu, "paid": _new_gp})
            st.success(f"✅ Goals saved: {_new_gs} sign-ups, {_new_gu} uploads, {_new_gp} paid")
            st.rerun()

    c1, c2 = st.columns([1, 2])
    with c1:
        # Build full funnel: Sessions → Sign-ups → Uploads → Paid
        _sess = int(utm_df["sessions"].sum()) if not utm_df.empty and "sessions" in utm_df.columns else 0
        _funnel_y = ["Sessions"]
        _funnel_x = [_sess if _sess > 0 else cs]
        if _sess > 0:
            _funnel_y += ["Sign-ups", "Uploads", "Paid"]
            _funnel_x += [cs, cu, cp]
        else:
            _funnel_y += ["Sign-ups", "Uploads", "Paid"]
            _funnel_x += [cs, cu, cp]

        fig = go.Figure(
            go.Funnel(
                y=_funnel_y,
                x=_funnel_x,
                textposition="inside",
                textinfo="value+percent initial",
                marker=dict(color=[T["muted"], T["accent"], T["accent2"], T["green"]][:len(_funnel_y)]),
            )
        )
        fig.update_layout(
            title="Conversion Funnel", height=340,
            **CT(), margin=dict(l=0, r=0, t=40, b=0),
        )
        _pc(fig)

    with c2:
        if not kpi.empty and "date" in kpi.columns:
            dk = kpi.copy()
            dk["date"] = pd.to_datetime(dk["date"])
            dk = dk.sort_values("date")
            fig = go.Figure()
            if "signups" in dk.columns:
                fig.add_trace(go.Scatter(
                    x=dk["date"], y=dk["signups"], name="Sign-ups",
                    line=dict(color=T["accent"], width=2),
                ))
            if "first_uploads" in dk.columns:
                fig.add_trace(go.Scatter(
                    x=dk["date"], y=dk["first_uploads"], name="Uploads",
                    line=dict(color=T["accent2"], width=2),
                ))
            if "paid_customers" in dk.columns:
                fig.add_trace(go.Scatter(
                    x=dk["date"], y=dk["paid_customers"], name="Paid",
                    line=dict(color=T["green"], width=2),
                ))
            fig.update_layout(
                title="Daily Trends", height=340,
                **CT(), margin=dict(l=0, r=0, t=40, b=0),
                hovermode="x unified",
            )
            _pc(fig)

    if enable_comp and not prev_kpi.empty:
        st.markdown(
            '<div class="sec-head">📊 Period Comparison</div>',
            unsafe_allow_html=True,
        )
        comp_data = {
            "Metric": ["Sign-ups", "Uploads", "Paid", "S→U", "U→P", "S→P"],
            "Current": [
                cs, cu, cp,
                f"{s2u:.1f}%", f"{u2p:.1f}%", f"{s2p:.1f}%",
            ],
            "Previous": [
                ps, pu, pp,
                f"{ps2u:.1f}%", f"{pu2p:.1f}%", f"{ps2p:.1f}%",
            ],
            "Δ %": [
                f"{((cs - ps) / ps * 100):+.1f}%" if ps > 0 else "—",
                f"{((cu - pu) / pu * 100):+.1f}%" if pu > 0 else "—",
                f"{((cp - pp) / pp * 100):+.1f}%" if pp > 0 else "—",
                f"{(s2u - ps2u):+.1f}pp",
                f"{(u2p - pu2p):+.1f}pp",
                f"{(s2p - ps2p):+.1f}pp",
            ],
        }
        st.dataframe(pd.DataFrame(comp_data), height=250)

    if not leads_df.empty:
        st.markdown(
            '<div class="sec-head">🎯 Lead Sources</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns([2, 1])
        with c1:
            st.dataframe(leads_df, height=300)
        with c2:
            if "Signups" in leads_df.columns:
                fig = px.pie(
                    leads_df.head(8), values="Signups",
                    names="Lead Source", hole=0.5,
                    color_discrete_sequence=CC,
                )
                fig.update_layout(
                    height=300, **CT(),
                    margin=dict(l=0, r=0, t=0, b=0),
                    showlegend=False,
                )
                _pc(fig)

    # ── COMBINED SOURCES: GA4 + CRM (Smart Dedup) ──
    if not utm_df.empty or not leads_df.empty:
        st.markdown(
            '<div class="sec-head">🌐📋 Combined Sources — GA4 Traffic + CRM Sign-ups</div>',
            unsafe_allow_html=True,
        )
        # Use source_normalizer for intelligent deduplication
        _sn_mod = MOD.get("source_normalizer")
        _norm_fn = _sn_mod.normalize_source if _sn_mod else None

        # Accumulate by canonical source name
        _combined = {}  # canonical_name -> {sessions, conversions, signups, type}

        # GA4 traffic sources — normalize each source
        if not utm_df.empty:
            src_col = "source_normalized" if "source_normalized" in utm_df.columns else "sessionSource"
            sess_col = "sessions" if "sessions" in utm_df.columns else src_col
            for src_val, grp in utm_df.groupby(src_col):
                canonical = src_val
                if _norm_fn:
                    try:
                        canonical, _ = _norm_fn(str(src_val))
                    except Exception:
                        canonical = str(src_val).strip()
                else:
                    canonical = str(src_val).strip()
                sessions = int(grp[sess_col].sum()) if sess_col in grp.columns else 0
                conversions = int(grp["conversions"].sum()) if "conversions" in grp.columns else 0
                if canonical not in _combined:
                    _combined[canonical] = {"sessions": 0, "conversions": 0, "signups": 0, "type": "traffic"}
                _combined[canonical]["sessions"] += sessions
                _combined[canonical]["conversions"] += conversions

        # CRM lead sources — normalize and merge with GA4
        if not leads_df.empty:
            ls_col = "Lead Source" if "Lead Source" in leads_df.columns else None
            su_col = "Signups" if "Signups" in leads_df.columns else None
            if ls_col and su_col:
                # First, aggregate CRM by raw source
                _crm_agg = {}
                for _, row in leads_df.iterrows():
                    raw_src = str(row[ls_col]).strip()
                    su = int(row.get(su_col, 0)) if pd.notna(row.get(su_col)) else 0
                    # Normalize
                    canonical = raw_src
                    if _norm_fn:
                        try:
                            canonical, _ = _norm_fn(raw_src)
                        except Exception:
                            canonical = raw_src
                    if canonical not in _crm_agg:
                        _crm_agg[canonical] = 0
                    _crm_agg[canonical] += su
                # Merge into combined
                for canonical, signups in _crm_agg.items():
                    if canonical not in _combined:
                        _combined[canonical] = {"sessions": 0, "conversions": 0, "signups": 0, "type": "signup"}
                    _combined[canonical]["signups"] += signups
                    # Update type
                    if _combined[canonical]["sessions"] > 0 and signups > 0:
                        _combined[canonical]["type"] = "both"
                    elif signups > 0:
                        _combined[canonical]["type"] = _combined[canonical]["type"] if _combined[canonical]["sessions"] > 0 else "signup"

        if _combined:
            combined_rows = []
            for canonical, vals in _combined.items():
                combined_rows.append({
                    "Source": canonical,
                    "GA4 Sessions": vals["sessions"],
                    "GA4 Conversions": vals["conversions"],
                    "CRM Signups": vals["signups"],
                    "Type": vals["type"],
                })
            combined_df = pd.DataFrame(combined_rows)
            combined_df["Total Interactions"] = combined_df["GA4 Sessions"] + combined_df["CRM Signups"]
            combined_df = combined_df.sort_values("Total Interactions", ascending=False)
            combined_df["Conv %"] = (combined_df["GA4 Conversions"] / combined_df["GA4 Sessions"].replace(0, 1) * 100).round(1)
            # Reorder columns
            show_cols = [c for c in ["Source", "GA4 Sessions", "GA4 Conversions", "Conv %", "CRM Signups", "Total Interactions", "Type"] if c in combined_df.columns]
            st.dataframe(combined_df[show_cols].head(30), height=400)

            # Pie chart of combined
            fig = px.pie(combined_df.head(10), values="Total Interactions", names="Source", hole=0.5,
                         color_discrete_sequence=CC)
            fig.update_layout(height=350, **CT(), margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
            _pc(fig)

    # ── Time-to-Conversion Analytics ──
    _ledger_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_output", "first_upload_ledger.json")
    # Build all 3 conversion types with defensive wrappers

    def _ttc_safe(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return {}, pd.DataFrame(), pd.DataFrame(), [], "", ""
    _ttc_s2u = _ttc_safe(_build_time_to_conversion, free_rows, upload_rows, mode="signup_to_upload", ledger_path=_ledger_path)
    _ttc_s2p = _ttc_safe(_build_time_to_conversion, free_rows, upload_rows, stripe_raw, mode="signup_to_paid")
    _ttc_u2p = _ttc_safe(_build_time_to_conversion, pd.DataFrame() if upload_rows is None else upload_rows, stripe_raw, mode="upload_to_paid")

    def _render_ttc(ttc_result):
        _st, _hist, _monthly, _rows, _st_label, _en_label = ttc_result
        if not _rows:
            st.caption("No matched users for this conversion stage.")
            return
        _tc1, _tc2, _tc3, _tc4, _tc5 = st.columns(5)
        with _tc1:
            st.metric("Matched Users", _st["matched_users"])
        with _tc2:
            st.metric("Median (Days)", _st["median_days"])
        with _tc3:
            st.metric("Mean (Days)", _st["mean_days"])
        with _tc4:
            st.metric("Within 7d", f"{_st['pct_7d']}%")
        with _tc5:
            st.metric("Within 30d", f"{_st['pct_30d']}%")
        _tt_ch1, _tt_ch2 = st.columns([2, 1])
        with _tt_ch1:
            if not _hist.empty:
                fig = px.bar(_hist, x="range", y="count",
                             title=f"Distribution: Days from {_st_label} to {_en_label}",
                             labels={"range": "Days", "count": "Users"},
                             color_discrete_sequence=[T["accent"]])
                fig.update_layout(height=350, **CT(), margin=dict(l=0, r=0, t=40, b=0), xaxis_tickangle=-45)
                _pc(fig)
        with _tt_ch2:
            _cum_curve = pd.DataFrame({"day": list(range(0, max(_st["max_days"], 1) + 1))})
            _cum_curve["converted"] = _cum_curve["day"].apply(lambda d: sum(1 for r in _rows if r["gap_days"] <= d))
            _cum_curve["pct"] = (_cum_curve["converted"] / _st["matched_users"] * 100).round(1)
            fig = px.line(_cum_curve, x="day", y="pct",
                          title="Cumulative Conversion",
                          labels={"day": "Days", "pct": "% Converted"},
                          color_discrete_sequence=[T["green"]])
            fig.update_layout(height=350, **CT(), margin=dict(l=0, r=0, t=40, b=0))
            fig.update_traces(fill="tozeroy")
            _pc(fig)
        if not _monthly.empty:
            st.markdown(f"**Monthly Cohort — Median Days to {_en_label}**")
            fig = px.bar(_monthly, x="month", y="median_days",
                         title="Median Days by Month",
                         labels={"month": "Month", "median_days": "Median Days"},
                         color="median_days", color_continuous_scale="Viridis", text_auto=True)
            fig.update_layout(height=350, **CT(), margin=dict(l=0, r=0, t=40, b=0))
            _pc(fig)
        _tt_sorted = sorted(_rows, key=lambda r: r["gap_days"])
        _tt_fastest = pd.DataFrame(_tt_sorted[:20])
        _tt_slowest = pd.DataFrame(reversed(_tt_sorted[-20:]))
        _tt_fc1, _tt_fc2 = st.columns(2)
        with _tt_fc1:
            st.markdown("**⚡ Fastest Conversions (top 20)**")
            if not _tt_fastest.empty:
                _tt_fastest["email"] = _tt_fastest["email"].str[:25]
                _tt_fastest_disp = _tt_fastest[["email", "gap_days"]].copy()
                _tt_fastest_disp.columns = ["Email", "Days"]
                st.dataframe(_tt_fastest_disp, height=300)
        with _tt_fc2:
            st.markdown("**🐌 Slowest Conversions (top 20)**")
            if not _tt_slowest.empty:
                _tt_slowest["email"] = _tt_slowest["email"].str[:25]
                _tt_slowest_disp = _tt_slowest[["email", "gap_days"]].copy()
                _tt_slowest_disp.columns = ["Email", "Days"]
                st.dataframe(_tt_slowest_disp, height=300)

    _has_any = any(r[3] for r in [_ttc_s2u, _ttc_s2p, _ttc_u2p])
    if _has_any:
        with st.expander("⏱️ Time-to-Conversion Analytics", expanded=False):
            _ttc_tab1, _ttc_tab2, _ttc_tab3 = st.tabs(["📝 Sign-up → Upload", "💳 Sign-up → Paid", "📤 Upload → Paid"])
            with _ttc_tab1:
                _render_ttc(_ttc_s2u)
            with _ttc_tab2:
                _render_ttc(_ttc_s2p)
            with _ttc_tab3:
                _render_ttc(_ttc_u2p)

    _ai_mod = MOD.get("ai_engine")
    if _ai_mod:
        st.markdown("---")
        if st.button("⚡ Generate AI Insight"):
            with st.spinner("AI analyzing..."):
                result = _ai_mod.ask_ai(
                    "Give 3 bullet-point insights with specific numbers.",
                    kpi_df=kpi, leads_df=leads_df, utm_df=utm_df,
                    geo_df=geo_df, period_label=period_label,
                    prev_kpi_df=prev_kpi if enable_comp else None,
                    prev_utm_df=prev_utm_df if enable_comp else None,
                )
                st.markdown(result["answer"])

    # ── KPI Quick Alert ──
    st.markdown("---")
    st.markdown("### 📨 KPI System Alert")
    _kpi_tg_bot = get_secret("TELEGRAM_BOT_TOKEN", "")
    _kpi_tg_chat = get_secret("TELEGRAM_CHAT_ID", "")
    if not _kpi_tg_bot or not _kpi_tg_chat:
        st.warning("⚠️ Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to secrets to enable alerts.")
    else:
        _kpi_alert_c1, _kpi_alert_c2 = st.columns(2)
        with _kpi_alert_c1:
            if st.button("📤 Send KPI Report", use_container_width=True, key="dash_kpi_alert"):
                with st.spinner("Sending KPI report..."):
                    try:
                        from reporting_engine import build_kpi_stats, build_telegram_kpi_section, send_telegram
                        _kpi_data = build_kpi_stats()
                        _msg = build_telegram_kpi_section(_kpi_data)
                        _ok = send_telegram(_msg)
                        if _ok:
                            st.success("✅ KPI report sent to Telegram!")
                        else:
                            st.error("❌ Telegram send failed. Check bot token in secrets.")
                    except Exception as _e:
                        st.error(f"❌ Error: {_e}")
        with _kpi_alert_c2:
            if st.button("📤 Send Stripe Report", use_container_width=True, key="dash_stripe_alert"):
                with st.spinner("Sending Stripe report..."):
                    try:
                        from reporting_engine import build_stripe_stats, build_telegram_stripe_section, send_telegram
                        _stripe_data = build_stripe_stats()
                        _msg = build_telegram_stripe_section(_stripe_data)
                        _ok = send_telegram(_msg)
                        if _ok:
                            st.success("✅ Stripe report sent!")
                        else:
                            st.error("❌ Telegram send failed.")
                    except Exception as _e:
                        st.error(f"❌ Error: {_e}")

# ═══════════════════════════════════════════════════════════════
# PAGE: 🚦 TRAFFIC INTEL
# ═══════════════════════════════════════════════════════════════
elif page == "📈 Google Analytics":
    st.markdown(
        '<div class="sec-head">📈 Google Analytics Hub</div>',
        unsafe_allow_html=True,
    )
    try:
        pd_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "pages"
        )
        if pd_dir not in sys.path:
            sys.path.insert(0, pd_dir)
        ti_loaded = False
        for f in os.listdir(pd_dir):
            if "Traffic_Intelligence" in f and f.endswith(".py"):
                # Force reimport to pick up latest code changes
                import importlib
                ti = __import__(f[:-3])
                importlib.reload(ti)
                # Pass current date range via session_state + cache buster
                st.session_state["ti_start"] = p_start.strftime("%Y-%m-%d")
                st.session_state["ti_end"] = p_end.strftime("%Y-%m-%d")
                st.session_state["ti_cache_key"] = f"{p_start.strftime('%Y-%m-%d')}_{p_end.strftime('%Y-%m-%d')}"
                ti.main()
                ti_loaded = True
                break
        if not ti_loaded:
            raise ImportError("Traffic page not found")
    except Exception as e:
        st.warning(f"Traffic Intel module: {e}")
        if not utm_df.empty:
            sc = (
                "source_normalized"
                if "source_normalized" in utm_df.columns
                else "sessionSource"
            )
            agg = utm_df.groupby(sc).agg(
                Sessions=("sessions", "sum")
                if "sessions" in utm_df.columns
                else (sc, "count"),
            ).reset_index().sort_values("Sessions", ascending=False)
            fig = px.bar(
                agg.head(15), x="Sessions", y=sc,
                orientation="h", color_discrete_sequence=[T["accent"]],
            )
            fig.update_layout(
                height=400, **CT(),
                margin=dict(l=0, r=0, t=20, b=0),
            )
            _pc(fig)
            st.dataframe(agg)
        else:
            st.info("No GA4 traffic data available. Configure GA4 connector in Settings.")

    # ── GA4 Quick Alert ──
    st.markdown("---")
    st.markdown("### 📨 GA4 Analytics Alert")
    _ga4_tg_bot = get_secret("TELEGRAM_BOT_TOKEN", "")
    _ga4_tg_chat = get_secret("TELEGRAM_CHAT_ID", "")
    if not _ga4_tg_bot or not _ga4_tg_chat:
        st.warning("⚠️ Add Telegram secrets to enable alerts.")
    else:
        if st.button("📤 Send GA4 Report", use_container_width=True, key="ga4_alert"):
            with st.spinner("Sending GA4 report..."):
                try:
                    from reporting_engine import build_ga4_stats, build_telegram_ga4_section, send_telegram
                    _ga4_data = build_ga4_stats()
                    _msg = build_telegram_ga4_section(_ga4_data)
                    _ok = send_telegram(_msg)
                    if _ok:
                        st.success("✅ GA4 report sent to Telegram!")
                    else:
                        st.error("❌ Send failed. Check bot token.")
                except Exception as _e:
                    st.error(f"❌ Error: {_e}")

# ═══════════════════════════════════════════════════════════════
# PAGE: 🤖 ASK AI — Chat System
# ═══════════════════════════════════════════════════════════════
    # ── GA4 Pattern Analysis Section ──
    with st.expander("📊 Pattern Analysis — Region + Time + Anomalies", expanded=False):
        try:
            from ga4_pattern_ui import render_ga4_pattern_analysis
            render_ga4_pattern_analysis()
        except Exception as _ge:
            st.warning(f"GA4 pattern analysis: {_ge}")

elif page == "🤖 Ask AI":
    try:
        from ai_assistant_ui import render_ai_assistant
        render_ai_assistant("all")
    except Exception as _e:
        st.error(f"AI Assistant error: {_e}")

elif page == "🤖 AI KPI":
    try:
        from ai_assistant_ui import render_ai_assistant
        render_ai_assistant("kpi")
    except Exception as _e:
        st.error(f"AI KPI error: {_e}")

elif page == "🤖 AI YouTube":
    try:
        from ai_assistant_ui import render_ai_assistant
        render_ai_assistant("youtube")
    except Exception as _e:
        st.error(f"AI YouTube error: {_e}")

elif page == "🤖 AI LinkedIn":
    try:
        from ai_assistant_ui import render_ai_assistant
        render_ai_assistant("linkedin")
    except Exception as _e:
        st.error(f"AI LinkedIn error: {_e}")

elif page == "🤖 AI GA4":
    try:
        from ai_assistant_ui import render_ai_assistant
        render_ai_assistant("ga4")
    except Exception as _e:
        st.error(f"AI GA4 error: {_e}")

elif page == "🤖 AI CS":
    try:
        from ai_assistant_ui import render_ai_assistant
        render_ai_assistant("customer_success")
    except Exception as _e:
        st.error(f"AI CS error: {_e}")


elif page == "🧠 AI Tools":
    st.markdown('<div class="sec-head">🧠 AI Power Tools</div>', unsafe_allow_html=True)

    # Platform selector
    _ai_platform = st.selectbox(
        "🎯 Select Platform",
        ["youtube", "kpi", "linkedin", "ga4", "customer_success", "all"],
        format_func=lambda x: {
            "youtube":          "📺 YouTube (30 tools)",
            "kpi":              "📊 KPI (30 tools)",
            "linkedin":         "💼 LinkedIn (30 tools)",
            "ga4":              "🌐 GA4 (30 tools)",
            "customer_success": "🎯 Customer Success (30 tools)",
            "all":              "🔗 Cross-Platform All (30 tools)",
        }.get(x, x),
        index=0,
        key="ai_tools_platform",
    )

    try:
        from ai_assistant_engine import TOOLS, run_tool
    except ImportError:
        st.error("AI engine not available. Check AI configuration")
        st.stop()

    tools = TOOLS.get(_ai_platform, [])
    st.caption(f"⚡ {len(tools)} AI tools that analyze YOUR real {_ai_platform.upper()} data")

    user_email = st.session_state.get("user_email", "anonymous")

    # Show tools in grid
    _cols = st.columns(3)
    for i, tool in enumerate(tools):
        with _cols[i % 3]:
            with st.container(border=True):
                _icon = tool.get("icon", "⚡")
                st.markdown(f"### {_icon} {tool['name']}")
                st.caption(tool["desc"])
                _needs_input = "input" in tool
                _user_input = ""
                if _needs_input:
                    _user_input = st.text_input(
                        f"✏️ {tool['input']}",
                        key=f"ai_tools_in_{_ai_platform}_{tool['id']}",
                        placeholder=tool.get("input", ""),
                    )
                if st.button(f"▶ Run {tool['name']}", key=f"ai_tools_run_{_ai_platform}_{tool['id']}", use_container_width=True):
                    if _needs_input and not _user_input.strip():
                        st.warning(f"Please enter {tool['input']}")
                    else:
                        with st.spinner(f"🤖 Running {tool['name']}..."):
                            result = run_tool(_ai_platform, tool["id"], _user_input, user_email)
                        if result.get("error"):
                            st.error(result["error"])
                        else:
                            st.success(f"✅ {tool['name']} complete")
                            st.markdown(result["answer"])
                            st.caption(f"via {result['source']}")

elif page == "🔮 Predictions":
    st.markdown(
        '<div class="sec-head">🔮 ML Forecasting & Predictions</div>',
        unsafe_allow_html=True,
    )
    _pred = MOD.get("prediction_engine")
    if not _pred:
        st.error("Prediction Engine not loaded")
        st.stop()

    st.markdown(
        '<div class="comp-box">'
        '<b>ℹ️</b> <b style="color:var(--green);">Current Total = REAL DATA</b> '
        'from pipeline. '
        '<b style="color:var(--accent);">Predicted = ML FORECASTS</b>.</div>',
        unsafe_allow_html=True,
    )

    horizon = st.selectbox(
        "Horizon", [7, 14, 21, 30, 60, 90], index=1,
        format_func=lambda x: f"{x} days",
    )
    if st.button("🔮 Generate Forecast", type="primary"):
        with st.spinner("Running ML ensemble..."):
            st.session_state["forecast"] = _pred.generate_forecast_report(
                kpi, horizon=horizon,
                prev_kpi_df=prev_kpi if enable_comp else None,
            )

    if st.session_state.get("forecast"):
        _rpt = st.session_state["forecast"]
        st.markdown(
            f"**Generated:** {_rpt['generated_at']} · "
            f"**Horizon:** {_rpt['horizon_days']} days"
        )
        for _key, _data in _rpt["metrics"].items():
            if _data.get("status") == "insufficient_data":
                st.warning(
                    f"⚠️ {_data['name']}: {_data.get('message', '')}"
                )
                continue
            st.markdown(f"#### {_data['name']}")
            _pk = f"predicted_next_{horizon}d"
            _fh = '<div class="kpi-grid">'
            _fh += kpi_h(
                "Current (Real)", _data["current_total"],
                '<span class="badge badge-ok">REAL DATA</span>',
            )
            _fh += kpi_h(
                "Avg/Day", f"{_data['avg_daily']:.1f}",
                f'<span class="badge badge-info">{_data["confidence"]}</span>',
            )
            _fh += kpi_h(
                f"Next {horizon}d", _data.get(_pk, 0),
                f'<span class="kpi-delta">{_data["trend"]}</span>',
            )
            _fh += kpi_h(
                "Best Case", _data.get("best_case_7d", 0),
                '<span class="kpi-delta d-up">+20%</span>',
            )
            _fh += kpi_h(
                "Worst Case", _data.get("worst_case_7d", 0),
                '<span class="kpi-delta d-dn">−20%</span>',
            )
            _fh += "</div>"
            st.markdown(_fh, unsafe_allow_html=True)

            _dp = _data.get("daily_predictions", [])
            if _dp:
                _ds = [d["date"] for d in _dp[:horizon]]
                _vs = [d["predicted"] for d in _dp[:horizon]]
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=_ds, y=[v * 1.2 for v in _vs],
                    fill=None, mode="lines", line=dict(width=0),
                    showlegend=False,
                ))
                fig.add_trace(go.Scatter(
                    x=_ds, y=[v * 0.8 for v in _vs],
                    fill="tonexty", mode="lines", line=dict(width=0),
                    fillcolor="rgba(0,212,255,0.09)", showlegend=False,
                ))
                fig.add_trace(go.Scatter(
                    x=_ds, y=_vs, mode="lines+markers",
                    name="Forecast",
                    line=dict(color=T["accent"], width=2.5),
                    marker=dict(size=4),
                ))
                fig.update_layout(
                    title=f"{_data['name']} Forecast", height=350,
                    **CT(), margin=dict(l=0, r=0, t=40, b=0),
                    hovermode="x unified",
                )
                _pc(fig)
            st.caption(f"Method: {_data['method']}")

# ═══════════════════════════════════════════════════════════════
# PAGE: 📋 REPORTS
# ═══════════════════════════════════════════════════════════════
elif page == "📋 Reports":
    st.markdown(
        '<div class="sec-head">📋 Automated Reports</div>',
        unsafe_allow_html=True,
    )
    _rep = MOD.get("report_generator")
    if not _rep:
        st.error("Report Generator not loaded")
        st.stop()

    rep_type = st.selectbox(
        "Report Type",
        [
            "weekly", "biweekly", "monthly", "quarterly",
            "business", "marketing", "data_analysis", "executive",
        ],
    )
    _rc1, _rc2, _rc3 = st.columns(3)
    with _rc1:
        if st.button("📝 Generate Report", type="primary",
                     use_container_width=True):
            with st.spinner("Generating..."):
                _report = _rep.generate_report(
                    kpi_df=kpi,
                    prev_kpi_df=prev_kpi if enable_comp else None,
                    leads_df=leads_df, utm_df=utm_df,
                    period_type=rep_type, period_label=period_label,
                )
                st.session_state["report"] = _report
                _fp = _rep.save_report(_report)
                st.success(f"✅ Saved: {_fp}")
    with _rc2:
        if (st.button("📨 Telegram Format", use_container_width=True)
                and st.session_state.get("report")):
            st.code(
                _rep.generate_telegram_report(st.session_state["report"]),
                language="markdown",
            )
    with _rc3:
        if (st.button("📤 Send to Telegram", type="primary", use_container_width=True)
                and st.session_state.get("report")):
            with st.spinner("Sending..."):
                try:
                    from telegram_alerts import _send
                    _tg_msg = _rep.generate_telegram_report(st.session_state["report"])
                    _result = _send(_tg_msg)
                    if _result["ok"]:
                        st.success("✅ Sent to Telegram!")
                    else:
                        st.error(f"❌ Failed: {_result.get('error', 'unknown')}")
                except Exception as _e:
                    st.error(f"❌ Error: {_e}")

    if st.session_state.get("report"):
        st.markdown(st.session_state["report"]["markdown"])
        st.download_button(
            "⬇️ Download",
            st.session_state["report"]["markdown"],
            f"eagle3d_{rep_type}_{datetime.now().strftime('%Y%m%d')}.md",
            "text/markdown",
            use_container_width=True,
        )

    # ── SMART TELEGRAM ALERTS ──
    st.markdown("---")
    st.markdown("### 📨 Smart Telegram Alerts")

    try:
        from telegram_alerts import (
            daily_kpi_report, period_report, anomaly_alerts,
            marketing_performance, top_performer_alert, send,
        )
        _tg_ok = True
    except ImportError:
        _tg_ok = False
        st.warning("telegram_alerts module not found")

    if _tg_ok:
        _tg_c1, _tg_c2 = st.columns(2)
        with _tg_c1:
            st.markdown("#### 📊 Reports")
            if st.button("📤 Send Daily Report", use_container_width=True, key="tg_daily"):
                with st.spinner("Sending daily report..."):
                    _msg = daily_kpi_report(kpi, prev_kpi if enable_comp else None, utm_df, leads_df)
                    _r = send(_msg)
                    st.success("✅ Sent!") if _r["ok"] else st.error(f"❌ {_r.get('error')}")

            if st.button("📤 Send Period Report", use_container_width=True, key="tg_period"):
                with st.spinner("Sending period report..."):
                    _msg = period_report(kpi, prev_kpi if enable_comp else None, utm_df, leads_df, period_type=rep_type)
                    _r = send(_msg)
                    st.success("✅ Sent!") if _r["ok"] else st.error(f"❌ {_r.get('error')}")

            if st.button("📤 Marketing Scorecard", use_container_width=True, key="tg_marketing"):
                with st.spinner("Sending marketing scorecard..."):
                    _msg = marketing_performance(kpi, prev_kpi if enable_comp else None, utm_df, leads_df)
                    _r = send(_msg)
                    st.success("✅ Sent!") if _r["ok"] else st.error(f"❌ {_r.get('error')}")

            if st.button("📤 Top Performer Alert", use_container_width=True, key="tg_top"):
                with st.spinner("Sending..."):
                    _msg = top_performer_alert(kpi, utm_df)
                    _r = send(_msg)
                    st.success("✅ Sent!") if _r["ok"] else st.error(f"❌ {_r.get('error')}")

        with _tg_c2:
            st.markdown("#### 🚨 Anomaly Alerts")
            if st.button("📤 Send Anomaly Scan", use_container_width=True, key="tg_anomaly"):
                with st.spinner("Scanning anomalies..."):
                    _alerts = anomaly_alerts(kpi, prev_kpi if enable_comp else None)
                    for _a in _alerts[:3]:
                        _r = send(_a["msg"])
                        if not _r["ok"]:
                            st.error(f"❌ {_r.get('error')}")
                            break
                    else:
                        st.success(f"✅ Sent {len(_alerts[:3])} alert(s)!")

            # Show current anomalies
            st.markdown("#### Current Anomalies")
            _cur_alerts = anomaly_alerts(kpi, prev_kpi if enable_comp else None)
            for _a in _cur_alerts:
                _colors = {"critical": "#FF5252", "warning": "#FFD600", "positive": "#00E676", "info": "#00D4FF"}
                _c = _colors.get(_a["type"], "#94A3B1")
                st.markdown(f'<div style="border-left:3px solid {_c};padding:8px 12px;margin:4px 0;background:#111D32;border-radius:6px;">{_a["msg"][:200]}</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 📁 Report Archive")
    _saved = _rep.list_saved_reports()
    if _saved:
        for _r in _saved[:20]:
            _rf_path = os.path.join("data_output", "reports", _r['filename'])
            with st.expander(f"📄 {_r['filename']} — {_r['modified']} ({_r['size'] / 1024:.1f} KB)"):
                try:
                    _rf_content = Path(_rf_path).read_text() if os.path.exists(_rf_path) else ""
                    if _rf_content:
                        st.markdown(_rf_content[:5000])
                        if len(_rf_content) > 5000:
                            st.caption(f"... ({len(_rf_content):,} total characters)")
                        st.download_button(
                            "⬇️ Download", _rf_content,
                            file_name=_r['filename'], mime="text/markdown",
                            key=f"dl_{_r['filename']}", use_container_width=True,
                        )
                    else:
                        st.info("Report file not found")
                except Exception as _e:
                    st.error(f"Error reading: {_e}")
    else:
        st.info("No saved reports yet. Generate a report first.")

# ═══════════════════════════════════════════════════════════════
# PAGE: 🔔 ALERTS
# ═══════════════════════════════════════════════════════════════
elif page == "🔔 Alerts":
    st.markdown(
        '<div class="sec-head">🔔 Alerts & Anomaly Detection</div>',
        unsafe_allow_html=True,
    )
    cs = km(kpi, "signups")
    cu = km(kpi, "first_uploads")
    cp = km(kpi, "paid_customers")

    _t1, _t2, _t3 = st.columns(3)
    with _t1:
        wt = st.slider("⚠️ Warning %", 10, 50, 20)
    with _t2:
        ct_val = st.slider("🚨 Critical %", 20, 80, 40)
    with _t3:
        mv = st.number_input("Min value", value=1, min_value=0)

    alerts = []
    if enable_comp and not prev_kpi.empty:
        ps = km(prev_kpi, "signups")
        pu = km(prev_kpi, "first_uploads")
        pp = km(prev_kpi, "paid_customers")
        for nm, c, p in [
            ("Sign-ups", cs, ps), ("Uploads", cu, pu), ("Paid", cp, pp)
        ]:
            if p == 0 or c < mv:
                continue
            ch = (c - p) / p * 100
            if abs(ch) >= ct_val:
                sev = "critical"
            elif abs(ch) >= wt:
                sev = "warning"
            else:
                continue
            em = "🚨" if ch < 0 else "📈"
            dr = "dropped" if ch < 0 else "surged"
            alerts.append({
                "sev": sev, "em": em,
                "t": f"{nm} {dr} {abs(ch):.0f}%",
                "m": f"{p} → {c} ({ch:+.1f}%)",
                "a": f"Investigate {nm.lower()}",
            })
    elif not kpi.empty and "signups" in kpi.columns and len(kpi) >= 5:
        vs = kpi["signups"].astype(float)
        mn = vs.mean()
        sd = vs.std()
        if sd > 0:
            for _, row in kpi.iterrows():
                v = float(row.get("signups", 0))
                z = (v - mn) / sd
                if abs(z) >= 2.0:
                    alerts.append({
                        "sev": "critical" if abs(z) >= 3 else "warning",
                        "em": "🚨" if z < 0 else "📈",
                        "t": f"Anomaly {row.get('date', '?')}: {v:.0f}",
                        "m": f"Z-score: {z:.1f}",
                        "a": "Check data or spike",
                    })

    # ── Performance Alerts ──
    if not kpi.empty:
        # Sign-up rate vs average
        if cs > 0 and not kpi_all.empty and "signups" in kpi_all.columns:
            _avg_s = kpi_all["signups"].astype(float).mean()
            if _avg_s > 0:
                _s_dev = (cs - _avg_s) / _avg_s * 100
                if _s_dev > 50:
                    alerts.append({"sev": "info", "em": "🚀", "t": f"High Sign-up Performance: +{_s_dev:.0f}% above avg", "m": f"Current: {cs} vs Average: {_avg_s:.0f}", "a": "Capitalise on this trend — check traffic sources"})
                elif _s_dev < -50:
                    alerts.append({"sev": "warning", "em": "📉", "t": f"Low Sign-up Performance: {_s_dev:.0f}% below avg", "m": f"Current: {cs} vs Average: {_avg_s:.0f}", "a": "Check for technical issues or traffic drops"})

        # Upload conversion rate
        if cs > 0 and cu > 0:
            _s2u = cu / cs * 100
            if _s2u < 10:
                alerts.append({"sev": "warning", "em": "⚠️", "t": f"Low Upload Rate: {_s2u:.1f}%", "m": f"{cu} uploads from {cs} sign-ups", "a": "Check onboarding UX — users sign up but don't upload"})
            elif _s2u > 50:
                alerts.append({"sev": "info", "em": "🔥", "t": f"High Upload Rate: {_s2u:.1f}%", "m": f"{cu} uploads from {cs} sign-ups", "a": "Great conversion! Document what's working"})

        # Paid conversion rate
        if cu > 0 and cp > 0:
            _u2p = cp / cu * 100
            if _u2p < 5:
                alerts.append({"sev": "warning", "em": "💰", "t": f"Low Paid Conversion: {_u2p:.1f}%", "m": f"{cp} paid from {cu} uploads", "a": "Check pricing, payment flow, or value proposition"})
            elif _u2p > 30:
                alerts.append({"sev": "info", "em": "💎", "t": f"High Paid Conversion: {_u2p:.1f}%", "m": f"{cp} paid from {cu} uploads", "a": "Strong monetisation — scale this funnel"})

        # Zero-data alerts
        if cs == 0:
            alerts.append({"sev": "critical", "em": "🚨", "t": "Zero Sign-ups This Period", "m": "No sign-ups detected — data may not be loading", "a": "Check Google Sheets connection and pipeline health"})
        if cu == 0 and cs > 0:
            alerts.append({"sev": "warning", "em": "📤", "t": "Zero Uploads This Period", "m": f"{cs} sign-ups but 0 uploads", "a": "Check first_upload_logic and upload data"})
        if cp == 0 and cs > 0:
            alerts.append({"sev": "info", "em": "💳", "t": "Zero Paid This Period", "m": f"{cs} sign-ups but 0 paid customers", "a": "Check Stripe scraper and cookies"})

    if not alerts:
        st.markdown(
            '<div class="alert-card al-ok" style="text-align:center;padding:30px;">'
            '<div style="font-size:2.5rem;">✅</div>'
            '<div style="font-size:1.1rem;font-weight:700;color:var(--green);">'
            'All KPIs Normal</div></div>',
            unsafe_allow_html=True,
        )
    else:
        for a in alerts:
            cl = "al-crit" if a["sev"] == "critical" else "al-warn"
            st.markdown(
                f'<div class="alert-card {cl}">'
                f'<div style="font-weight:700;">{a["em"]} {a["t"]}</div>'
                f'<div style="color:var(--text);">{a["m"]}</div>'
                f'<div style="color:var(--muted);font-size:0.8rem;margin-top:6px;">'
                f'💡 {a["a"]}</div></div>',
                unsafe_allow_html=True,
            )

# ═══════════════════════════════════════════════════════════════
# PAGE: 🔬 EDA LAB
# ═══════════════════════════════════════════════════════════════
elif page == "🔬 EDA Lab":
    st.markdown(
        '<div class="sec-head">🔬 Exploratory Data Analysis</div>',
        unsafe_allow_html=True,
    )
    tabs = st.tabs([
        "📊 Distributions", "📈 Correlations", "🔥 Heatmap",
        "📅 Time Series", "🎯 Cohort",
    ])

    with tabs[0]:
        if not kpi.empty:
            mt = st.selectbox(
                "Metric",
                ["signups", "first_uploads", "paid_customers"],
                key="edm",
            )
            if mt in kpi.columns:
                vs = pd.to_numeric(kpi[mt], errors="coerce").dropna()
                if len(vs) > 0:
                    c1, c2 = st.columns(2)
                    with c1:
                        fig = px.histogram(
                            x=vs, nbins=20,
                            color_discrete_sequence=[T["accent"]],
                        )
                        fig.update_layout(
                            title=f"{mt} Distribution", **CT(),
                            margin=dict(l=0, r=0, t=40, b=0),
                        )
                        _pc(fig)
                    with c2:
                        fig = px.box(
                            y=vs,
                            color_discrete_sequence=[T["accent2"]],
                        )
                        fig.update_layout(
                            title=f"{mt} Box Plot", **CT(),
                            margin=dict(l=0, r=0, t=40, b=0),
                        )
                        _pc(fig)
                    st.markdown("#### Statistics")
                    _sc = st.columns(4)
                    _stats = {
                        "Mean": vs.mean(), "Median": vs.median(),
                        "Std": vs.std(), "Min": vs.min(),
                        "Max": vs.max(), "Skew": vs.skew(),
                        "CV%": (vs.std() / vs.mean() * 100
                                if vs.mean() > 0 else 0),
                    }
                    for idx, (k, v) in enumerate(_stats.items()):
                        with _sc[idx % 4]:
                            st.metric(k, f"{v:.2f}" if isinstance(v, float)
                                      else str(v))
        else:
            st.info("No KPI data available.")

    with tabs[1]:
        if not kpi.empty:
            _nc = [c for c in [
                "signups", "first_uploads", "paid_customers"
            ] if c in kpi.columns]
            if len(_nc) >= 2:
                cr = kpi[_nc].astype(float).corr()
                fig = px.imshow(
                    cr, text_auto=".2f",
                    color_continuous_scale="RdBu_r",
                    aspect="auto", zmin=-1, zmax=1,
                )
                fig.update_layout(
                    title="Correlations", **CT(),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                _pc(fig)
                xc = st.selectbox("X", _nc, key="ex")
                yc = st.selectbox("Y", [c for c in _nc if c != xc], key="ey")
                fig = px.scatter(
                    kpi, x=xc, y=yc, trendline="ols",
                    color_discrete_sequence=[T["accent"]],
                )
                fig.update_layout(
                    **CT(), margin=dict(l=0, r=0, t=20, b=0),
                )
                _pc(fig)

    with tabs[2]:
        if (not kpi.empty and "date" in kpi.columns
                and "signups" in kpi.columns):
            _h = kpi.copy()
            _h["date"] = pd.to_datetime(_h["date"])
            _h["wd"] = _h["date"].dt.day_name()
            _h["wk"] = _h["date"].dt.isocalendar().week.astype(int)
            _h["signups"] = pd.to_numeric(_h["signups"], errors="coerce")
            pv = _h.pivot_table(
                values="signups", index="wd",
                columns="wk", aggfunc="sum",
            )
            dn = [
                "Monday", "Tuesday", "Wednesday",
                "Thursday", "Friday", "Saturday", "Sunday",
            ]
            pv = pv.reindex([d for d in dn if d in pv.index])
            fig = px.imshow(
                pv, color_continuous_scale="Viridis", aspect="auto",
            )
            fig.update_layout(
                title="Heatmap", height=350, **CT(),
                margin=dict(l=0, r=0, t=40, b=0),
            )
            _pc(fig)

    with tabs[3]:
        if (not kpi.empty and "date" in kpi.columns
                and "signups" in kpi.columns):
            _ts = kpi.copy()
            _ts["date"] = pd.to_datetime(_ts["date"])
            _ts = _ts.sort_values("date")
            _ts["signups"] = pd.to_numeric(
                _ts["signups"], errors="coerce"
            )
            _ts = _ts.dropna(subset=["signups"])
            if len(_ts) >= 7:
                _ts["MA7"] = _ts["signups"].rolling(7, min_periods=1).mean()
                _ts["MA14"] = _ts["signups"].rolling(
                    14, min_periods=1
                ).mean()
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=_ts["date"], y=_ts["signups"], name="Actual",
                    line=dict(color=T["accent"], width=1), opacity=0.6,
                ))
                fig.add_trace(go.Scatter(
                    x=_ts["date"], y=_ts["MA7"], name="7d MA",
                    line=dict(color=T["accent2"], width=2.5),
                ))
                fig.add_trace(go.Scatter(
                    x=_ts["date"], y=_ts["MA14"], name="14d MA",
                    line=dict(color="#FF9100", width=2.5),
                ))
                fig.update_layout(
                    title="Moving Averages", height=400,
                    **CT(), margin=dict(l=0, r=0, t=40, b=0),
                    hovermode="x unified",
                )
                _pc(fig)

    with tabs[4]:
        st.markdown("#### Cohort Analysis")
        if not free_rows.empty and not upload_rows.empty:
            ecf = next(
                (c for c in free_rows.columns if "email" in c.lower()),
                None,
            )
            dcf = next(
                (c for c in free_rows.columns if "date" in c.lower()),
                None,
            )
            ecu = next(
                (c for c in upload_rows.columns if "email" in c.lower()),
                None,
            )
            dcu = next(
                (c for c in upload_rows.columns if "date" in c.lower()),
                None,
            )
            if ecf and dcf and ecu and dcu:
                fc = free_rows.copy()
                uc = upload_rows.copy()
                fc["_e"] = fc[ecf].astype(str).str.lower().str.strip()
                fc["_d"] = fc[dcf].apply(parse_to_date)
                uc["_e"] = uc[ecu].astype(str).str.lower().str.strip()
                uc["_d"] = uc[dcu].apply(parse_to_date)
                fc = fc.dropna(subset=["_e", "_d"])
                uc = uc.dropna(subset=["_e", "_d"])
                fc["month"] = fc["_d"].apply(lambda d: d.replace(day=1))
                mg = fc[["_e", "_d", "month"]].merge(
                    uc[["_e", "_d"]].rename(columns={"_d": "ud"}),
                    on="_e", how="left",
                )
                mg["conv"] = mg["ud"].notna()
                co = mg.groupby("month").agg(
                    s=("_e", "count"), c=("conv", "sum"),
                ).reset_index()
                co["rate"] = (co["c"] / co["s"] * 100).round(1)
                co["month"] = co["month"].astype(str)
                if not co.empty:
                    fig = px.bar(
                        co, x="month", y=["s", "c"],
                        barmode="group",
                        color_discrete_sequence=[T["accent"], T["green"]],
                    )
                    fig.update_layout(
                        title="Signup Cohort", height=350,
                        **CT(), margin=dict(l=0, r=0, t=40, b=0),
                    )
                    _pc(fig)
                    st.dataframe(co)

# ═══════════════════════════════════════════════════════════════
# PAGE: 🔍 BROWSE DATA
# ═══════════════════════════════════════════════════════════════

elif page == "🔍 Browse Data":
    st.markdown(
        '<div class="sec-head">🔍 Browse Customer Data</div>',
        unsafe_allow_html=True,
    )

    # Global date filter for Browse Data
    _bd_c1, _bd_c2, _bd_c3, _bd_c4 = st.columns(4)
    with _bd_c1:
        _bd_preset = st.selectbox("📅 Date filter:", [
            "This Month", "Last Month", "All Time", "Today", "Yesterday", "This Week", "Last Week",
            "Last 7 Days", "Last 14 Days", "Last 28 Days", "Last 30 Days",
            "Last 3 Months", "Last 6 Months", "This Year", "Custom Range", "Custom Month",
        ], index=0, key="bd_preset")
    with _bd_c2:
        if _bd_preset == "Custom Month":
            _bd_month = st.selectbox("Month:", [
                f"{y}-{m:02d}" for y in range(2026, 2023, -1) for m in range(12, 0, -1)
            ], index=0, key="bd_month_sel")
        else:
            _bd_month = None
    with _bd_c3:
        _bd_status = st.selectbox("Status:", ["All", "ACCEPTED", "REJECTED", "REPEAT", "REPEAT_UPLOAD", "NOT_DETERMINED", "DISPOSABLE", "INTERNAL", "SMTP_REJECTED", "NO_MX", "ZERO_SPEND"], key="bd_status")
    with _bd_c4:
        _bd_search = st.text_input("🔍 Search", placeholder="email, name...", key="bd_search")

    # Compute date range from preset
    _bd_today = datetime.now().date()
    _bd_date_map = {
        "All Time": (datetime(2020, 1, 1).date(), _bd_today),
        "Today": (_bd_today, _bd_today),
        "Yesterday": (_bd_today - timedelta(days=1), _bd_today - timedelta(days=1)),
        "This Week": (_bd_today - timedelta(days=_bd_today.weekday()), _bd_today),
        "Last Week": (_bd_today - timedelta(days=_bd_today.weekday() + 7), _bd_today - timedelta(days=_bd_today.weekday() + 1)),
        "This Month": (_bd_today.replace(day=1), _bd_today),
        "Last Month": ((_bd_today.replace(day=1) - timedelta(days=1)).replace(day=1), _bd_today.replace(day=1) - timedelta(days=1)),
        "Last 7 Days": (_bd_today - timedelta(days=6), _bd_today),
        "Last 14 Days": (_bd_today - timedelta(days=13), _bd_today),
        "Last 28 Days": (_bd_today - timedelta(days=27), _bd_today),
        "Last 30 Days": (_bd_today - timedelta(days=29), _bd_today),
        "Last 3 Months": (_bd_today - timedelta(days=90), _bd_today),
        "Last 6 Months": (_bd_today - timedelta(days=180), _bd_today),
        "This Year": (_bd_today.replace(month=1, day=1), _bd_today),
    }
    if _bd_preset == "Custom Range":
        with _bd_c2:
            _bd_cr_start = st.date_input("Start", value=_bd_today - timedelta(days=30), key="bd_cr_start")
        with _bd_c3:
            _bd_cr_end = st.date_input("End", value=_bd_today, key="bd_cr_end")
        _bd_ds, _bd_de = _bd_cr_start, _bd_cr_end
    elif _bd_preset == "Custom Month" and _bd_month:
        _m_parts = _bd_month.split("-")
        _m_y, _m_m = int(_m_parts[0]), int(_m_parts[1])
        _m_start = datetime(_m_y, _m_m, 1).date()
        if _m_m == 12:
            _m_end = datetime(_m_y + 1, 1, 1).date() - timedelta(days=1)
        else:
            _m_end = datetime(_m_y, _m_m + 1, 1).date() - timedelta(days=1)
        _bd_ds, _bd_de = _m_start, _m_end
    else:
        _bd_ds, _bd_de = _bd_date_map.get(_bd_preset, (datetime(2020, 1, 1).date(), _bd_today))

    st.caption(f"📅 Showing: **{_bd_ds}** → **{_bd_de}**")

    def _apply_browse_filters(df, label):
        """Apply date, status, and search filters to a dataframe.

        Smart date column detection:
        1. Tries ALL date-related columns in the data
        2. Picks the column with the highest parse rate
        3. Always includes row_date_used (YYYY-MM-DD from process_data)
        4. For First Uploads: also uses Account Created On as fallback
        5. If NO column parses >0%, falls back to Account Created On
        """
        fl = df.copy()
        if _bd_preset != "All Time":
            # ── Smart date column detection ──
            _date_candidates = []
            _parse_rates = {}

            # Scan ALL columns that could contain dates
            for _cand in fl.columns:
                _cl = _cand.lower().strip()
                # Specific known date columns (highest priority) - include process_data columns
                if _cl in ("upload date", "account created on", "first payment", "created", 
                           "signup_date", "payment_date", "first_upload_date", "row_date_used", "__scraped_date__"):
                    _date_candidates.append(_cand)
                # Any column with date/created in name
                elif any(k in _cl for k in ["created", "upload date", "date"]):
                    if not any(x in _cl for x in ["detail", "last", "processed", "verify"]):
                        _date_candidates.append(_cand)

            # Pick the best column: highest parse rate with >0% success
            _best_col = None
            _best_rate = 0
            _total_rows = len(fl)
            if _total_rows > 0:
                for _dc in _date_candidates:
                    try:
                        _parsed = fl[_dc].apply(parse_to_date)
                        _valid = int(_parsed.notna().sum())
                        _rate = _valid / _total_rows
                        _parse_rates[_dc] = (_valid, _rate)
                        if _rate > _best_rate:
                            _best_rate = _rate
                            _best_col = _dc
                    except Exception:
                        _parse_rates[_dc] = (0, 0)

            # Fallback: if best rate is 0, try Account Created On as last resort
            if _best_rate == 0 and "Account Created On" in fl.columns:
                _parsed = fl["Account Created On"].apply(parse_to_date)
                _best_rate = int(_parsed.notna().sum()) / _total_rows
                if _best_rate > 0:
                    _best_col = "Account Created On"
                    _parse_rates["Account Created On"] = (int(_parsed.notna().sum()), _best_rate)

            if _best_col and _best_rate > 0:
                fl["_parsed_date"] = fl[_best_col].apply(parse_to_date)
                _has_date = fl["_parsed_date"].notna()
                _in_range = fl["_parsed_date"].between(_bd_ds, _bd_de)
                _no_date_count = int((~_has_date).sum())
                _out_range_count = int((_has_date & ~_in_range).sum())
                fl = fl[_has_date & _in_range]
                fl = fl.drop(columns=["_parsed_date"])
                # Show which date column is used
                st.caption(f"📅 Filtered by **{_best_col}** ({_best_rate*100:.0f}% parse rate) | Period: {_bd_ds} → {_bd_de}")
                if _no_date_count > 0 or _out_range_count > 0:
                    parts = []
                    if _no_date_count > 0:
                        parts.append(f"{_no_date_count} no date")
                    if _out_range_count > 0:
                        parts.append(f"{_out_range_count} outside period")
                    st.caption(f"ℹ️ Excluded: {', '.join(parts)}")
            elif _best_col and _best_rate == 0:
                st.warning(f"⚠️ Found date column '{_best_col}' but 0% of dates are parseable. Showing all rows for {label}.")
                with st.expander("🔧 Debug: Date column parse rates"):
                    for _col, (_valid, _rate) in _parse_rates.items():
                        st.text(f"  {_col}: {_valid}/{_total_rows} ({_rate*100:.0f}%)")
            else:
                st.warning(f"⚠️ No date column found in {label} data. Showing all rows.")
                st.caption(f"Available columns: {', '.join(fl.columns[:15])}")
        # Status filter
        if _bd_status != "All" and "final_status" in fl.columns:
            fl = fl[fl["final_status"].astype(str).str.upper() == _bd_status]
        # Search
        if _bd_search:
            msk = pd.Series([False] * len(fl), index=fl.index)
            for c in fl.columns:
                msk = msk | fl[c].astype(str).str.contains(_bd_search, case=False, na=False)
            fl = fl[msk]
        return fl

    # ── Data diagnostics (shows column names and date info) ──
    with st.expander("🔧 Data Diagnostics", expanded=False):
        _dcols1, _dcols2, _dcols3 = st.columns(3)
        with _dcols1:
            st.markdown("**📥 Sign-ups columns:**")
            if not free_rows.empty:
                st.text(", ".join(free_rows.columns.tolist()))
                _date_cols = [c for c in free_rows.columns if any(k in c.lower() for k in ["date", "created", "row_date"])]
                if _date_cols:
                    st.text(f"Date cols: {', '.join(_date_cols)}")
                    for _dc in _date_cols[:3]:
                        _sample = free_rows[_dc].dropna().head(3).tolist()
                        st.text(f"  {_dc}: {_sample}")
            else:
                st.text("No data")
        with _dcols2:
            st.markdown("**📦 First Uploads columns:**")
            if not upload_rows.empty:
                st.text(", ".join(upload_rows.columns.tolist()))
                _date_cols = [c for c in upload_rows.columns if any(k in c.lower() for k in ["date", "created", "row_date"])]
                if _date_cols:
                    st.text(f"Date cols: {', '.join(_date_cols)}")
                    for _dc in _date_cols[:3]:
                        _sample = upload_rows[_dc].dropna().head(3).tolist()
                        st.text(f"  {_dc}: {_sample}")
            else:
                st.text("No data")
        with _dcols3:
            st.markdown("**💳 Stripe columns:**")
            if not stripe_raw.empty:
                st.text(", ".join(stripe_raw.columns.tolist()))
                _date_cols = [c for c in stripe_raw.columns if any(k in c.lower() for k in ["date", "created", "payment", "row_date"])]
                if _date_cols:
                    st.text(f"Date cols: {', '.join(_date_cols)}")
                    for _dc in _date_cols[:3]:
                        _sample = stripe_raw[_dc].dropna().head(3).tolist()
                        st.text(f"  {_dc}: {_sample}")
            else:
                st.text("No data")

    # ── INLINE OVERRIDE ENGINE ──
    _mo_engine = MOD.get("manual_override_engine")

    tabs = st.tabs(["📥 Sign-ups", "📦 First Uploads", "💳 Stripe"])
    for _tab, (_lb, _df_data) in zip(
        tabs,
        [
            ("Sign-ups", free_rows),
            ("First Uploads", upload_rows),
            ("Stripe", stripe_raw),
        ],
    ):
        with _tab:
            # Try MongoDB server-side filtered browse first (fast)
            _sb_browse_df, _sb_diag = _browse_supabase(
                _lb, _bd_status, _bd_search,
                _bd_ds if _bd_preset != "All Time" else None,
                _bd_de if _bd_preset != "All Time" else None,
                limit=2000,
            )
            if _sb_browse_df is not None and not _sb_browse_df.empty:
                fl = _sb_browse_df
                _acc = _sb_diag.get("accepted", 0)
                _rej = _sb_diag.get("rejected", 0)
                _sc1, _sc2, _sc3, _sc4 = st.columns(4)
                _sc1.metric("✅ Accepted", _acc)
                _sc2.metric("❌ Rejected", _rej)
                _sc3.metric("📋 Total", len(fl))
                _sc4.metric("🗄️ Source", "MongoDB")
                if _bd_preset != "All Time":
                    st.caption(f"📅 MongoDB filtered: {_bd_ds} → {_bd_de} | Status: {_bd_status}")
            elif _sb_browse_df is not None and _sb_browse_df.empty:
                st.info(f"No {_lb} records found for selected filters.")
                st.caption(f"📅 Period: {_bd_ds} → {_bd_de} | Status: {_bd_status}")
                if _sb_diag.get("error"):
                    st.caption(f"Error: {_sb_diag['error']}")
                continue
            else:
                # Fallback: client-side filter from loaded DataFrame
                if _df_data.empty:
                    st.warning(f"No {_lb} data — check MongoDB connection")
                    continue
                fl = _apply_browse_filters(_df_data, _lb)
                if "final_status" in fl.columns:
                    _acc = sum(1 for _, r in fl.iterrows() if str(r.get("final_status","")).upper() in ("ACCEPTED","ALREADY_COUNTED"))
                    _rej = len(fl) - _acc
                    _sc1, _sc2, _sc3 = st.columns(3)
                    _sc1.metric("✅ Accepted", _acc)
                    _sc2.metric("❌ Rejected", _rej)
                    _sc3.metric("📋 Total", len(fl))

            # Status summary
            if "final_status" in fl.columns:
                _acc = sum(1 for _, r in fl.iterrows() if str(r.get("final_status", "")).upper() in ("ACCEPTED", "ALREADY_COUNTED"))
                _rej = len(fl) - _acc
                _sc1, _sc2, _sc3 = st.columns(3)
                with _sc1:
                    st.metric("✅ Accepted", f"{_acc}")
                with _sc2:
                    st.metric("❌ Rejected", f"{_rej}")
                with _sc3:
                    st.metric("📋 Total", f"{len(fl)}")

            # Sort + display controls
            c1, c2, c3 = st.columns(3)
            with c1:
                _sort_cols = ["—"] + [c for c in fl.columns if c]
                _sort_sel = st.selectbox("Sort by:", _sort_cols, key=f"sort_{_lb}")
            with c2:
                _sort_asc = st.radio("Direction", ["↓ Desc", "↑ Asc"], key=f"sortd_{_lb}", horizontal=True)
            with c3:
                mr = st.number_input("Rows", value=500, min_value=10, max_value=10000, key=f"r_{_lb}")

            # Apply sorting
            if _sort_sel != "—" and _sort_sel in fl.columns:
                _ascending = (_sort_asc == "↑ Asc")
                try:
                    fl[_sort_sel] = pd.to_numeric(fl[_sort_sel], errors="ignore")
                except Exception:
                    pass
                fl = fl.sort_values(by=_sort_sel, ascending=_ascending, na_position="last")

            st.metric("Showing", f"{len(fl)} rows")

            # ── INLINE OVERRIDE SECTION ──
            if _mo_engine and "final_status" in fl.columns:
                with st.expander("✏️ Override Labels", expanded=False):
                    st.caption("Select emails to change their status. Changes apply to the override system.")
                    _email_col = None
                    for _ec in fl.columns:
                        if "email" in _ec.lower():
                            _email_col = _ec
                            break
                    if _email_col:
                        _avail_emails = fl[_email_col].unique().tolist()
                        _sel_emails = st.multiselect(
                            f"Select emails from {_lb}:",
                            _avail_emails[:200],
                            key=f"ov_sel_{_lb}",
                        )
                        _ov_action = st.selectbox(
                            "Change to:",
                            ["ACCEPTED", "REJECTED", "REPEAT_UPLOAD", "DISPOSABLE", "NOT_DETERMINED"],
                            key=f"ov_act_{_lb}",
                        )
                        _ov_reason = st.text_input("Reason (optional):", key=f"ov_reason_{_lb}")
                        if _sel_emails and st.button(f"✅ Apply Override ({len(_sel_emails)} emails)", type="primary", key=f"ov_btn_{_lb}", use_container_width=True):
                            _ov_count = 0
                            for _se in _sel_emails:
                                # Get the ORIGINAL status from raw data (before any overrides)
                                _orig_df = {"Sign-ups": free_raw, "First Uploads": upload_raw, "Stripe": stripe_raw}.get(_lb, free_raw)
                                _orig = _orig_df.loc[_orig_df[_email_col] == _se, "final_status"].values if _email_col in _orig_df.columns else []
                                _orig_status = str(_orig[0]) if len(_orig) > 0 else "UNKNOWN"
                                _action_map = {
                                    "ACCEPTED": "accept", "REJECTED": "reject",
                                    "REPEAT_UPLOAD": "repeat_upload", "DISPOSABLE": "disposable",
                                    "NOT_DETERMINED": "not_determined",
                                }
                                _mo_engine.apply_override(
                                    email=_se,
                                    action=_action_map.get(_ov_action, "not_determined"),
                                    target_tab="ALL",
                                    reason=_ov_reason or f"Changed to {_ov_action} via Browse Data",
                                    original_category=_orig_status,
                                )
                                _ov_count += 1
                            st.success(f"✅ Overrode {_ov_count} emails → {_ov_action}. Counts updated everywhere!")
                            st.session_state["_ov_toast_shown"] = False  # Reset so delta toast shows
                            st.cache_data.clear()
                            st.rerun()
                    else:
                        st.info("No email column found for override.")
            elif not _mo_engine:
                st.caption("⚠️ Manual override engine not loaded")

            # Make App URL column clickable hyperlinks in the table
            _display_fl = fl.head(mr).copy()
            if "App URL" in _display_fl.columns:
                _display_fl["App URL"] = _display_fl["App URL"].apply(
                    lambda x: f"[🔗 Open]({x})" if str(x).startswith("http") else str(x)
                )
            st.dataframe(_display_fl, height=450)
            st.download_button(
                "⬇️ Download",
                data=fl.to_csv(index=False).encode("utf-8"),
                file_name=f"{_lb.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

            # Stripe data check
            if _lb == "Stripe" and fl.empty:
                st.warning("⚠️ No Stripe data loaded. The Stripe scraper may be timing out. Check pipeline logs.")

# ═══════════════════════════════════════════════════════════════
# PAGE: ✏️ MANUAL OVERRIDE
# ═══════════════════════════════════════════════════════════════
elif page == "✏️ Manual Override":
    st.markdown(
        '<div class="sec-head">✏️ Manual Data Entry & Override</div>',
        unsafe_allow_html=True,
    )
    _mo_tab1, _mo_tab2, _mo_tab3, _mo_tab4 = st.tabs([
        "📝 Add Daily Entry", "📂 Bulk CSV Import", "📋 Entries Log", "🔧 Override Manager",
    ])
    MANUAL_DATA_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data_output", "manual_kpi_data.json",
    )

    def _load_manual():
        if os.path.exists(MANUAL_DATA_FILE):
            try:
                with open(MANUAL_DATA_FILE, "r") as _f:
                    return json.load(_f)
            except Exception:
                pass
        return {"daily": []}

    def _save_manual(data):
        os.makedirs(os.path.dirname(MANUAL_DATA_FILE), exist_ok=True)
        with open(MANUAL_DATA_FILE, "w") as _f:
            json.dump(data, _f, indent=2)

    with _mo_tab1:
        st.markdown("#### 📝 Add a Daily KPI Entry")
        _oc1, _oc2 = st.columns(2)
        with _oc1:
            _entry_date = st.date_input("Date", value=datetime.now().date(), key="mo_date")
        with _oc2:
            _entry_signups = st.number_input("Sign-ups", min_value=0, value=0, key="mo_s")
        _oc3, _oc4 = st.columns(2)
        with _oc3:
            _entry_uploads = st.number_input("First Uploads", min_value=0, value=0, key="mo_u")
        with _oc4:
            _entry_paid = st.number_input("Paid Customers", min_value=0, value=0, key="mo_p")
        if st.button("💾 Save Entry", type="primary", use_container_width=True):
            _md = _load_manual()
            _date_str = _entry_date.strftime("%Y-%m-%d")
            _found = False
            for _row in _md["daily"]:
                if _row.get("date") == _date_str:
                    _row["signups"] = _entry_signups
                    _row["first_uploads"] = _entry_uploads
                    _row["paid_customers"] = _entry_paid
                    _found = True
                    break
            if not _found:
                _md["daily"].append({
                    "date": _date_str,
                    "signups": _entry_signups,
                    "first_uploads": _entry_uploads,
                    "paid_customers": _entry_paid,
                })
            try:
                _save_manual(_md)
                st.success(f"✅ Saved: {_date_str} — {_entry_signups} sign-ups, {_entry_uploads} uploads, {_entry_paid} paid")
            except OSError:
                st.warning("⚠️ Cannot write on Streamlit Cloud (read-only). Works locally only.")

    with _mo_tab2:
        st.markdown("#### 📂 Bulk CSV Import")
        st.caption("Upload a CSV with columns: date, signups, first_uploads, paid_customers")
        _csv_file = st.file_uploader("Choose CSV", type=["csv"], key="mo_csv")
        if _csv_file is not None:
            try:
                _csv_df = pd.read_csv(_csv_file)
                st.dataframe(_csv_df.head(10), use_container_width=True)
                if st.button("📥 Import All Rows", type="primary"):
                    _md = _load_manual()
                    _existing = {r["date"] for r in _md["daily"]}
                    _added = 0
                    for _, _row in _csv_df.iterrows():
                        _d = str(_row.get("date", ""))
                        if _d and _d not in _existing:
                            _md["daily"].append({
                                "date": _d,
                                "signups": int(pd.to_numeric(_row.get("signups", 0), errors="coerce") or 0),
                                "first_uploads": int(pd.to_numeric(_row.get("first_uploads", 0), errors="coerce") or 0),
                                "paid_customers": int(pd.to_numeric(_row.get("paid_customers", 0), errors="coerce") or 0),
                            })
                            _added += 1
                    try:
                        _save_manual(_md)
                        st.success(f"✅ Imported {_added} new entries")
                    except OSError:
                        st.warning("⚠️ Cannot write on Streamlit Cloud.")
            except Exception as _e:
                st.error(f"CSV error: {_e}")

    with _mo_tab3:
        st.markdown("#### 📋 Current Manual Entries")
        _md = _load_manual()
        if _md["daily"]:
            _log_df = pd.DataFrame(_md["daily"])
            st.dataframe(_log_df, height=400)
            if st.button("🗑️ Clear All Manual Entries", type="secondary"):
                try:
                    _save_manual({"daily": []})
                    st.success("Cleared!")
                    st.rerun()
                except OSError:
                    st.warning("⚠️ Cannot write on Streamlit Cloud.")
        else:
            st.info("No manual entries yet.")

    # ── OVERRIDE MANAGER TAB ──
    with _mo_tab4:
        st.markdown("#### 🔧 Override Manager")
        st.caption("View, manage, and remove label overrides. Changes update counts everywhere instantly.")
        _mo_engine4 = MOD.get("manual_override_engine")
        if _mo_engine4:
            _ov_summary = _mo_engine4.get_override_summary()
            if _ov_summary["total"] > 0:
                # Show impact summary
                st.metric("Active Overrides", _ov_summary["total"])
                c_a1, c_a2 = st.columns(2)
                with c_a1:
                    for act, cnt in _ov_summary.get("by_action", {}).items():
                        _act_label = {
                            "accept": "✅ Accepted", "reject": "❌ Rejected",
                            "disposable": "🗑️ Disposable", "duplicate": "📋 Duplicate",
                            "repeat_upload": "🔄 Repeat Upload", "not_determined": "❓ Not Determined",
                        }.get(act, act)
                        st.metric(_act_label, cnt)
                with c_a2:
                    st.metric("Impact", f"{_ov_summary['total']} emails affected")

                if st.button("🗑️ Clear All Overrides", type="secondary", use_container_width=True):
                    _mo_engine4.save_overrides({})
                    st.session_state["_ov_toast_shown"] = False
                    st.success("✅ All overrides cleared! Counts restored to original.")
                    st.cache_data.clear()
                    st.rerun()

                st.markdown("---")
                st.markdown("##### Override Details")
                st.caption("Click ❌ to remove an override. The email will revert to its original status.")
                _ovs = _mo_engine4.load_overrides()
                for _ov_em, _ov_data in _ovs.items():
                    c_r1, c_r2, c_r3, c_r4 = st.columns([3, 2, 2, 1])
                    with c_r1:
                        st.text(f"📧 {_ov_em}")
                    with c_r2:
                        _act_nice = {
                            "accept": "→ ACCEPTED", "reject": "→ REJECTED",
                            "disposable": "→ DISPOSABLE", "duplicate": "→ DUPLICATE",
                            "repeat_upload": "→ REPEAT_UPLOAD", "not_determined": "→ NOT_DETERMINED",
                        }.get(_ov_data.get("action", "?"), f"→ {_ov_data.get('action', '?')}")
                        st.text(_act_nice)
                    with c_r3:
                        _orig = _ov_data.get("original_category", "Unknown")
                        st.text(f"was: {_orig}")
                    with c_r4:
                        if st.button("❌", key=f"rm_ov_{_ov_em}", help=f"Remove override for {_ov_em}"):
                            _mo_engine4.remove_override(_ov_em)
                            st.session_state["_ov_toast_shown"] = False
                            st.cache_data.clear()
                            st.rerun()
            else:
                st.info("No active overrides. Use Browse Data → Override Labels to add them.")
        else:
            st.warning("⚠️ Override engine not loaded")


# ═══════════════════════════════════════════════════════════════
# PAGE: 📺 YOUTUBE ANALYTICS (Full Command Center)
# ═══════════════════════════════════════════════════════════════
elif page == "📺 YouTube":
    try:
        from youtube_command_center_ui import render_youtube_command_center
        render_youtube_command_center()
    except Exception as _e:
        st.error(f"YouTube Command Center error: {_e}")
        st.caption("Check youtube_command_center.py and youtube_command_center_ui.py exist")

elif page == "💼 LinkedIn":
    try:
        from linkedin_command_center_ui import render_linkedin_command_center
        render_linkedin_command_center()
    except Exception as _le:
        st.error(f"LinkedIn Command Center error: {_le}")
        import traceback
        st.code(traceback.format_exc()[:1000])

elif page == "🎯 Customer Success":
    try:
        from customer_success_ui import render_customer_success
        render_customer_success()
    except Exception as _ce:
        st.error(f"Customer Success error: {_ce}")
        import traceback
        st.code(traceback.format_exc()[:1000])

elif page == "🔗 Cross-Platform":
    st.markdown(
        '<div class="sec-head">🔗 Cross-Platform Intelligence Hub</div>',
        unsafe_allow_html=True,
    )
    st.caption("Correlate data across KPI, GA4, YouTube, LinkedIn & Stripe — measure what matters.")

    try:
        from cross_platform_engine import (
            build_unified_timeline, compute_correlations,
            compute_attribution, compute_cross_platform_funnel,
            compute_growth_analysis,
            generate_cross_insights,
        )
        from youtube_connector import get_channel_info, get_daily_analytics
        from linkedin_connector import get_cached_metrics, get_manual_history
    except Exception as e:
        st.error(f"Cross-platform engine not loaded: {e}")
        st.stop()
    _ga4_ok = bool(os.environ.get("GA4_PROPERTY_ID") or True)  # GA4 is already configured

    _ps1, _ps2, _ps3, _ps4 = st.columns(4)
    with _ps1:
        _kpi_status = "✅" if not kpi_all.empty else "⚠️"
        st.metric("KPI Data", f"{_kpi_status} ({len(kpi_all)} days)")
    with _ps2:
        st.metric("GA4 Traffic", "✅" if _ga4_ok else "❌")
    with _ps3:
        try:
            import youtube_connector as _yt_mod
            _yt_status = _yt_mod.get_status() if hasattr(_yt_mod, "get_status") else {"configured": _yt_mod.is_configured()}
        except Exception:
            _yt_status = {"configured": False}
        st.metric("YouTube", "✅" if _yt_status.get("configured") else "❌")
    with _ps4:
        try:
            import linkedin_connector as _li_mod
            _li_status = _li_mod.get_status() if hasattr(_li_mod, "get_status") else {"configured": _li_mod.is_configured()}
        except Exception:
            _li_status = {"configured": False}
        st.metric("LinkedIn", "✅" if _li_status.get("configured") else "❌")

    st.markdown("---")

    # Period selection
    _cp_start = p_start.strftime("%Y-%m-%d")
    _cp_end = p_end.strftime("%Y-%m-%d")

    # ── Build unified timeline ──
    _yt_daily = pd.DataFrame()
    _li_daily = pd.DataFrame()
    _ga4_daily = pd.DataFrame()

    # Get GA4 data
    try:
        _ga4_mod = MOD.get("ga4_connector")
        if _ga4_mod and hasattr(_ga4_mod, "fetch_utm_traffic"):
            _ga4_daily = _ga4_mod.fetch_utm_traffic(_cp_start, _cp_end)
    except Exception:
        pass

    # Get YouTube data
    if _yt_status.get("configured"):
        try:
            _yt_daily = get_daily_analytics(_cp_start, _cp_end)
        except Exception:
            _yt_daily = pd.DataFrame()
        # Fallback 1: build YouTube daily from public video data if no OAuth analytics
        if _yt_daily.empty:
            try:
                _yt_vids = get_channel_videos(max_videos=200)
                if _yt_vids:
                    from collections import defaultdict as _dd3
                    _yt_dd = _dd3(lambda: {"youtube_views": 0, "youtube_likes": 0, "youtube_comments": 0})
                    for _v in _yt_vids:
                        _vd = _v.get("published_at", "")
                        if _vd:
                            _vdate = _vd[:10]
                            if _cp_start <= _vdate <= _cp_end:
                                _yt_dd[_vdate]["youtube_views"] += _v.get("views", 0)
                                _yt_dd[_vdate]["youtube_likes"] += _v.get("likes", 0)
                                _yt_dd[_vdate]["youtube_comments"] += _v.get("comments", 0)
                    if _yt_dd:
                        _yt_daily = pd.DataFrame([
                            {"date": d, **_yt_dd[d]} for d in sorted(_yt_dd.keys())
                        ])
            except Exception:
                pass
        # Fallback 2: use saved youtube_daily.json from pipeline
        if _yt_daily.empty:
            try:
                _yt_daily_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_output", "youtube_daily.json")
                if os.path.exists(_yt_daily_path):
                    with open(_yt_daily_path, "r") as _yf:
                        _yt_daily_data = json.load(_yf)
                    if _yt_daily_data:
                        _yt_rows = []
                        for _d, _vals in _yt_daily_data.items():
                            if _cp_start <= _d <= _cp_end:
                                _yt_rows.append({"date": _d, **_vals})
                        if _yt_rows:
                            _yt_daily = pd.DataFrame(_yt_rows)

            except Exception:
                pass
    # Get LinkedIn data
    _li_hist = get_manual_history()
    if not _li_hist.empty:
        _li_daily = _li_hist
    else:
        # Fallback: use cached metrics as single-day entry
        _li_cached = get_cached_metrics()
        if _li_cached and not _li_cached.get("error"):
            _li_daily = pd.DataFrame([{
                "date": datetime.now().strftime("%Y-%m-%d"),
                "followers": _li_cached.get("followers", 0),
                "company_name": _li_cached.get("company_name", ""),
            }])
        else:
            _li_daily = pd.DataFrame()

    # Build unified
    _unified = build_unified_timeline(
        kpi_df=kpi_all,
        ga4_df=_ga4_daily,
        youtube_daily=_yt_daily,
        linkedin_daily=_li_daily,
        start_date=_cp_start,
        end_date=_cp_end,
    )

    _cp_tabs = st.tabs([
        "🔄 Unified Timeline", "🔗 Correlations", "🎯 Attribution",
        "📊 Funnel", "📈 Growth", "💡 Insights",
    ])

    with _cp_tabs[0]:  # Unified Timeline
        st.markdown("#### 🔄 Unified Cross-Platform Timeline")
        if not _unified.empty:
            _avail_cols = []
            for c in _unified.columns:
                if c != "date":
                    try:
                        if pd.api.types.is_numeric_dtype(_unified[c]) and _unified[c].sum() > 0:
                            _avail_cols.append(c)
                    except Exception:
                        pass
            if _avail_cols:
                # Let user pick metrics to chart
                _sel_metrics = st.multiselect(
                    "Select metrics to chart",
                    _avail_cols,
                    default=_avail_cols[:5] if len(_avail_cols) >= 5 else _avail_cols,
                )
                if _sel_metrics:
                    fig = go.Figure()
                    colors = [T["accent"], T["accent2"], T["green"], T["yellow"], T["red"], "#FF6B6B", "#4ECDC4"]
                    for i, m in enumerate(_sel_metrics):
                        fig.add_trace(go.Scatter(
                            x=_unified["date"], y=_unified[m],
                            name=m.replace("_", " ").title(),
                            line=dict(color=colors[i % len(colors)], width=2),
                        ))
                    fig.update_layout(
                        height=500, **CT(),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02),
                        margin=dict(l=50, r=20, t=50, b=30),
                    )
                    _pc(fig)

                st.dataframe(_unified.tail(30))
            else:
                st.info("No data with non-zero values found in the selected period.")
        else:
            st.warning("⚠️ No data available from any platform for the selected period.")

    with _cp_tabs[1]:  # Correlations
        st.markdown("#### 🔗 Cross-Platform Correlations")
        if not _unified.empty and len(_unified) >= 3:
            _corr = compute_correlations(_unified)
            if _corr.get("error"):
                st.info(_corr["error"])
            else:
                _strong = _corr.get("strong_correlations", [])
                if _strong:
                    st.markdown("##### Strongest Correlations")
                    for c in _strong[:10]:
                        _dir = "📈" if c["direction"] == "positive" else "📉"
                        _str = "🔥" if c["strength"] == "strong" else "🔸"
                        st.markdown(
                            f"{_str} {_dir} <code>{c['metric_a']}</code> ↔ <code>{c['metric_b']}</code> "
                            f"— r = <b>{c['correlation']}</b> ({c['strength']})",
                            unsafe_allow_html=True,
                        )

                    # Correlation heatmap
                    _mat = _corr.get("matrix", {})
                    if _mat:
                        _mat_df = pd.DataFrame(_mat)
                        fig = go.Figure(data=go.Heatmap(
                            z=_mat_df.values,
                            x=_mat_df.columns,
                            y=_mat_df.index,
                            colorscale="RdBu",
                            zmin=-1, zmax=1,
                        ))
                        fig.update_layout(
                            height=max(400, len(_mat_df) * 30),
                            **CT(),
                            margin=dict(l=150, r=20, t=30, b=100),
                            xaxis=dict(tickangle=45),
                        )
                        _pc(fig)
                else:
                    st.info("No significant correlations found (r > 0.3). Need more data or different metrics.")

                st.caption(f"Analyzed {_corr.get('metric_count', 0)} metrics over {_corr.get('day_count', 0)} days")
        else:
            st.info("Need at least 3 days of data from multiple platforms for correlation analysis.")

    with _cp_tabs[2]:  # Attribution
        st.markdown("#### 🎯 Channel Attribution")
        st.caption("Which platform metrics best predict your KPI conversions?")
        if not _unified.empty and len(_unified) >= 7:
            _attr = compute_attribution(_unified)
            if isinstance(_attr, dict) and not _attr.get("error"):
                for _kpi_name, _predictors in _attr.items():
                    if _predictors:
                        st.markdown(f"##### {_kpi_name.replace('_', ' ').title()}")
                        for p in _predictors[:5]:
                            _lag = f" (leads by {p['lag_days']}d)" if p["lag_days"] > 0 else " (same-day)"
                            st.markdown(
                                f"- 🎯 <code>{p['metric']}</code> ({p['platform']}) — "
                                f"r={p['correlation']}{_lag}",
                                unsafe_allow_html=True,
                            )
            else:
                st.info(_attr.get("error", "Not enough data for attribution analysis."))
        else:
            st.info("Need at least 7 days of data for attribution analysis.")

    with _cp_tabs[3]:  # Funnel
        st.markdown("#### 📊 Cross-Platform Funnel")
        _yt_info = get_channel_info() if _yt_status["configured"] else {}
        _li_metrics = get_cached_metrics()

        _yt_views = int(_unified.filter(like="yt_views").sum().sum()) if not _unified.empty else 0
        _li_impressions = int(_unified.filter(like="li_impressions").sum().sum()) if not _unified.empty else 0
        _ga4_sessions = int(_unified.filter(like="ga4_sessions").sum().sum()) if not _unified.empty else 0

        _funnel = compute_cross_platform_funnel(
            kpi_df=kpi_all if not kpi_all.empty else pd.DataFrame({"signups": [0], "first_uploads": [0], "paid_customers": [0]}),
            ga4_sessions=_ga4_sessions,
            yt_views=_yt_views,
            li_impressions=_li_impressions,
            period_label=f"{_cp_start} to {_cp_end}",
        )

        # Draw funnel
        _stages = _funnel.get("stages", [])
        if _stages:
            fig = go.Figure(go.Funnel(
                y=[s["stage"] for s in _stages],
                x=[max(s["value"], 1) for s in _stages],
                textinfo="value+percent initial+percent previous",
                marker={"color": [T["accent"], T["accent2"], T["green"], T["yellow"], T["red"]]},
            ))
            fig.update_layout(height=450, **CT())
            _pc(fig)

            # Conversion rates
            _conv = _funnel.get("conversion_rates", {})
            if _conv:
                st.markdown("##### Conversion Rates")
                for k, v in _conv.items():
                    if v > 0:
                        st.markdown(f"- <code>{k.replace('_', ' ').title()}</code>: <b>{v}%</b>", unsafe_allow_html=True)

    with _cp_tabs[4]:  # Growth
        st.markdown("#### 📈 Cross-Platform Growth")
        if not _unified.empty and len(_unified) >= 6:
            _growth = compute_growth_analysis(_unified)
            if _growth.get("error"):
                st.info(_growth["error"])
            else:
                _g_metrics = _growth.get("metrics", {})
                _g_rows = []
                for m, d in _g_metrics.items():
                    _g_rows.append({
                        "Metric": m.replace("_", " ").title(),
                        "Current": d["current_period"],
                        "Previous": d["previous_period"],
                        "Change": d["change"],
                        "% Change": f"{d['pct_change']}%",
                        "Trend": {"growing": "📈", "declining": "📉", "stable": "➡️"}[d["trend"]],
                    })
                if _g_rows:
                    st.dataframe(pd.DataFrame(_g_rows))
        else:
            st.info("Need more data for growth analysis.")

    with _cp_tabs[5]:  # Insights
        st.markdown("#### 💡 Cross-Platform Insights")
        _corr_data = {}
        _attr_data = {}
        _growth_data = {}
        _funnel_data = {}

        if not _unified.empty and len(_unified) >= 3:
            _corr_data = compute_correlations(_unified)
        if not _unified.empty and len(_unified) >= 7:
            _attr_data = compute_attribution(_unified)
        if not _unified.empty and len(_unified) >= 6:
            _growth_data = compute_growth_analysis(_unified)
        _funnel_data = compute_cross_platform_funnel(
            kpi_df=kpi_all if not kpi_all.empty else pd.DataFrame({"signups": [0]}),
            ga4_sessions=0, yt_views=0, li_impressions=0,
        )

        _insights = generate_cross_insights(_corr_data, _attr_data, _growth_data, _funnel_data)
        for insight in _insights:
            st.markdown(f"<div style='padding:8px 12px;margin:4px 0;background:{T['card']};border-radius:8px;border-left:3px solid {T['accent']};'>{insight}</div>", unsafe_allow_html=True)

        if not _insights:
            st.info("Connect more platforms (YouTube, LinkedIn) for richer cross-platform insights.")


# ═══════════════════════════════════════════════════════════════
# PAGE: ⚙️ SETTINGS (with Run Pipeline + Secrets Editor + Cache Clear)
# ═══════════════════════════════════════════════════════════════

elif str(page).startswith("🧩 Custom:"):
    try:
        from custom_modules_ui import render_custom_module_page
        _custom_slug = str(page).split(":", 1)[1]
        render_custom_module_page(_custom_slug)
    except Exception as _custom_page_error:
        st.error(f"Custom module error: {_custom_page_error}")
        import traceback
        st.code(traceback.format_exc()[:2000])

elif page == "⚙️ Settings":

    # ── CUSTOM TEAM MODULES ──
    try:
        from custom_modules_ui import render_custom_module_settings
        with st.expander("🧩 Custom Team Modules", expanded=False):
            render_custom_module_settings()
        st.divider()
    except Exception as _cm_settings_error:
        st.warning(f"Custom module settings unavailable: {_cm_settings_error}")


    # ── TELEGRAM ALERTS CONTROL CENTER ──
    st.markdown("### 📨 Telegram Alerts Control")
    st.caption("Send all alerts to the main Telegram group")

    if "_alert_msg" not in st.session_state:
        st.session_state["_alert_msg"] = None
    _amsg = st.session_state.get("_alert_msg")
    if _amsg:
        st.success(_amsg["text"]) if _amsg["type"]=="success" else st.error(_amsg["text"])
        st.session_state["_alert_msg"] = None

    def _acb(name, mn, fn):
        try:
            m = __import__(mn); f = getattr(m, fn)
            from comprehensive_alerts import _send_telegram
            c = f()
            ok = _send_telegram(c) if c and str(c).strip() else False
            st.session_state["_alert_msg"] = {"type":"success" if ok else "error", "text":("✅ " if ok else "❌ ") + name}
        except Exception as e:
            st.session_state["_alert_msg"] = {"type":"error", "text":"❌ " + name + ": " + str(e)}

    def _sall():
        try:
            from all_alerts import run_all; n = run_all()
            st.session_state["_alert_msg"] = {"type":"success", "text":"✅ Sent " + str(n) + "/12 alerts"}
        except Exception as e:
            st.session_state["_alert_msg"] = {"type":"error", "text":"❌ " + str(e)}

    c1, c2 = st.columns(2)
    c1.button("📤 Send ALL 12 Alerts", type="primary", use_container_width=True, key="tg_all12", on_click=_sall)
    c2.button("📊 Legacy Report", use_container_width=True, key="tg_leg", on_click=lambda: _acb("Legacy","reporting_engine","main"))

    st.markdown("**Individual:**")
    for ri, (l,m,f) in enumerate([
        ("📊 KPI","comprehensive_alerts","alert_kpi_detailed"),
        ("🌐 GA4","comprehensive_alerts","alert_ga4"),
        ("📺 YouTube","comprehensive_alerts","alert_youtube"),
        ("💼 LinkedIn","comprehensive_alerts","alert_linkedin"),
        ("💳 Stripe","comprehensive_alerts","alert_stripe"),
        ("🎯 CS","comprehensive_alerts","alert_customer_success"),
        ("🔗 Cross","comprehensive_alerts","alert_cross_platform"),
        ("🤖 AI","comprehensive_alerts","alert_ai_insights"),
        ("☀️ Standup","role_alerts","daily_standup"),
        ("📊 Marketer","role_alerts","marketer_weekly"),
        ("🚨 CS Lead","role_alerts","cs_lead_weekly"),
        ("📈 Founder","role_alerts","founder_monthly"),
    ]):
        if ri % 4 == 0:
            cols = st.columns(4)
        cols[ri%4].button(l, use_container_width=True, key=f"tg_{ri}", on_click=lambda n=l,mn=m,fn=f: _acb(n,mn,fn))
    st.divider()


    # ── ACCESS CONTROL MANAGEMENT ──
    with st.expander("👥 User Access Management", expanded=True):
        try:
            from access_control import list_users, add_email, remove_email, get_access_logs

            # Initialize message state
            if "_user_mgmt_msg" not in st.session_state:
                st.session_state["_user_mgmt_msg"] = None

            # Show last action result
            msg = st.session_state.get("_user_mgmt_msg")
            if msg:
                if msg["type"] == "success":
                    st.success(msg["text"])
                else:
                    st.error(msg["text"])
                st.session_state["_user_mgmt_msg"] = None

            # Current users
            users = list_users()
            active = [u for u in users if u.get("is_active")]
            st.markdown(f"### Authorized Users ({len(active)} active / {len(users)} total)")
            if users:
                import pandas as _pd
                _df = _pd.DataFrame(users)
                _cols = [c for c in ["email","role","is_active","added_by","added_at","notes"] if c in _df.columns]
                st.dataframe(_df[_cols], use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("### ➕ Add New User")

            _ac1, _ac2 = st.columns([2, 1])
            with _ac1:
                _add_email_val = st.text_input("Email address",
                                                key="ac_new_email",
                                                placeholder="user@example.com")
            with _ac2:
                _add_role_val = st.selectbox("Role", ["viewer","editor","admin"], key="ac_new_role")
            _add_notes_val = st.text_input("Notes (optional)",
                                            key="ac_new_notes",
                                            placeholder="What is this user for?")

            # Define callback for add button
            def _do_add_user():
                em = st.session_state.get("ac_new_email", "").strip().lower()
                role = st.session_state.get("ac_new_role", "viewer")
                notes = st.session_state.get("ac_new_notes", "")
                if not em or "@" not in em:
                    st.session_state["_user_mgmt_msg"] = {"type":"error", "text":"Please enter a valid email address"}
                    return
                try:
                    from access_control import add_email as _add_em
                    result = _add_em(em, role, st.session_state.get("user_email","admin"), notes)
                    if result.get("success"):
                        st.session_state["_user_mgmt_msg"] = {"type":"success", "text":f"Added: {em} as {role}"}
                        # Clear inputs
                        st.session_state["ac_new_email"] = ""
                        st.session_state["ac_new_notes"] = ""
                    else:
                        st.session_state["_user_mgmt_msg"] = {"type":"error", "text":f"Failed: {result.get('message','Unknown error')}"}
                except Exception as e:
                    st.session_state["_user_mgmt_msg"] = {"type":"error", "text":f"Exception: {e}"}

            st.button("➕ ADD USER", key="ac_add_btn", type="primary",
                       use_container_width=True, on_click=_do_add_user)

            st.markdown("---")
            st.markdown("### ❌ Revoke Access")
            _rc1, _rc2 = st.columns([3, 1])
            with _rc1:
                _rem_email_val = st.text_input("Email to revoke", key="ac_rem_email", placeholder="user@example.com")
            with _rc2:
                _rem_reason_val = st.text_input("Reason", key="ac_rem_reason", placeholder="Why?")

            def _do_revoke():
                em = st.session_state.get("ac_rem_email","").strip().lower()
                reason = st.session_state.get("ac_rem_reason","")
                if not em or "@" not in em:
                    st.session_state["_user_mgmt_msg"] = {"type":"error", "text":"Please enter a valid email"}
                    return
                try:
                    from access_control import remove_email as _rem_em
                    r = _rem_em(em, st.session_state.get("user_email","admin"))
                    if r.get("success"):
                        st.session_state["_user_mgmt_msg"] = {"type":"success", "text":f"Revoked: {em}"}
                        st.session_state["ac_rem_email"] = ""
                    else:
                        st.session_state["_user_mgmt_msg"] = {"type":"error", "text":f"Failed: {r.get('message','Unknown')}"}
                except Exception as e:
                    st.session_state["_user_mgmt_msg"] = {"type":"error", "text":f"Exception: {e}"}

            st.button("❌ REVOKE ACCESS", key="ac_rem_btn",
                       use_container_width=True, on_click=_do_revoke)

            st.markdown("---")
            st.markdown("### 📊 Recent Access Logs (last 30)")
            try:
                _logs = get_access_logs(30)
                if _logs:
                    import pandas as _pd
                    _ldf = _pd.DataFrame(_logs)
                    _lcols = [c for c in ["timestamp","email","action","success","ip"] if c in _ldf.columns]
                    st.dataframe(_ldf[_lcols], use_container_width=True, hide_index=True)
                else:
                    st.info("No access logs yet")
            except Exception as _le:
                st.warning(f"Log read error: {_le}")
        except Exception as _e:
            st.error(f"Access management error: {_e}")
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])

    # ── MODULE STATUS ──
    st.markdown('<div class="sec-head">🏥 Module Status</div>', unsafe_allow_html=True)
    _mods = {
        "KPI Bridge":         "kpi_bridge",
        "Strategic":          "ga4_strategic",
        "Predictions":        "prediction_engine",
        "GA4 Connector":      "ga4_connector",
        "Notifications":      "notifications",
        "Reports":            "report_generator",
        "Source Intel":       "ga4_source_intel",
        "Intelligence":       "ml_intelligence",
        "Source Normalizer": "source_normalizer",
    }
    _mc = st.columns(4)
    _act = 0
    for _i, (_mname, _ky) in enumerate(_mods.items()):
        with _mc[_i % 4]:
            _ok = _ky in MOD
            if _ok:
                _act += 1
            _bd = (
                '<span class="badge badge-ok">✅</span>'
                if _ok
                else '<span class="badge badge-err">❌</span>'
            )
            st.markdown(f"**{_mname}** {_bd}", unsafe_allow_html=True)
    st.metric("Active", f"{_act}/{len(_mods)}")

    st.markdown("#### 🤖 AI Provider")
    _ai_mod = MOD.get("ai_engine")
    if _ai_mod:
        _pr = _ai_mod._get_provider()
        _pi2 = {
            "groq": ("⚡ Groq Cloud", "Ultra-fast"),
            "gemini": ("💎 Gemini", "Reasoning"),
            "rule_based": ("🧠 Rule-Based", "No key"),
        }
        _n2, _d2 = _pi2.get(_pr, ("?", ""))
        st.info(f"{_n2} — {_d2}")
        if _pr == "rule_based":
            _has_grok = False
            _has_gem = False
            try:
                if st.secrets.get("GROQ_API_KEY", ""):
                    _has_grok = True
                if st.secrets.get("GEMINI_API_KEY", ""):
                    _has_gem = True
            except Exception:
                pass
            if not _has_grok and not _has_gem:
                st.warning(
                    "💡 Add API keys in **Streamlit Cloud → Settings → Secrets**:\n\n"
                    "```toml\n"
                    'GROQ_API_KEY = "your-key"\n'
                    'GEMINI_API_KEY = "your-key"\n'
                    "```\n\n"
                    "Get free keys: [Groq](https://console.groq.com) · "
                    "[Gemini](https://aistudio.google.com)"
                )
            else:
                st.error(f"⚠️ Keys found in secrets but detection failed! Groq={_has_grok}, Gemini={_has_gem}")
    else:
        st.error("AI Engine not loaded")

    st.markdown("#### 🔐 Secrets Status")
    for _ky, _ds in [
        ("MONGO_URI", "MongoDB URI"),
        ("GOOGLE_CREDS", "Google Credentials"),
        ("GROQ_API_KEY", "Groq AI"),
        ("GEMINI_API_KEY", "Gemini AI"),
        ("TELEGRAM_BOT_TOKEN", "Telegram Bot"),
        ("TELEGRAM_CHAT_ID", "Telegram Chat ID"),
        ("YOUTUBE_API_KEY", "YouTube Data API"),
        ("YOUTUBE_CHANNEL_ID", "YouTube Channel ID"),
        ("YOUTUBE_OAUTH_TOKEN", "YouTube OAuth Token"),
        ("YOUTUBE_REFRESH_TOKEN", "YouTube Refresh Token"),
        ("YOUTUBE_CLIENT_ID", "YouTube Client ID"),
        ("YOUTUBE_CLIENT_SECRET", "YouTube Client Secret"),
        ("LINKEDIN_COMPANY_PAGE", "LinkedIn Company Page"),
        ("LINKEDIN_COOKIES_JSON", "LinkedIn Cookies"),
        ("MONGO_URI", "MongoDB URI"),
        ("MONGO_DB", "MongoDB Database"),
        ("STRIPE_SECRET_KEY", "Stripe API Key"),
        ("STRIPE_COOKIES_JSON", "Stripe Cookies"),
    ]:
        _vl = get_secret(_ky)
        if _vl:
            st.success(f"✅ {_ds}")
        else:
            st.warning(f"⚠️ {_ds}: Not set")

    st.markdown("---")
    st.markdown("#### 📊 Data Summary")
    _total_s = int(kpi_all["signups"].sum()) if not kpi_all.empty and "signups" in kpi_all.columns else 0
    _total_u = int(kpi_all["first_uploads"].sum()) if not kpi_all.empty and "first_uploads" in kpi_all.columns else 0
    _total_p = int(kpi_all["paid_customers"].sum()) if not kpi_all.empty and "paid_customers" in kpi_all.columns else 0
    _data_src = "MongoDB (local)" if not counts_raw.empty else "Historical JSON (offline)"
    _di = {
        "Data Source": _data_src,
        "KPI Rows": f"{len(kpi_all):,}",
        "Total Sign-ups": f"{_total_s:,}",
        "Total Uploads": f"{_total_u:,}",
        "Total Paid": f"{_total_p:,}",
        "Period Rows": f"{len(kpi):,}",
        "Sheet Sign-ups": f"{len(free_rows):,}",
        "Sheet Uploads": f"{len(upload_rows):,}",
    }
    _ic = st.columns(3)
    for _idx, (_l, _c) in enumerate(_di.items()):
        with _ic[_idx % 3]:
            st.metric(_l, _c)

    st.markdown("---")
    st.markdown("#### 💳 Stripe Data Diagnostics")
    if not stripe_raw.empty:
        _s_acc = sum(1 for _, r in stripe_raw.iterrows() if str(r.get("final_status", "")).upper() == "ACCEPTED")
        _s_rej = sum(1 for _, r in stripe_raw.iterrows() if str(r.get("final_status", "")).upper() == "REJECTED")
        _s_has_fp = sum(1 for _, r in stripe_raw.iterrows() if str(r.get("First payment", "")).strip() not in ("", "nan", "None", "—"))
        _s_has_spend = sum(1 for _, r in stripe_raw.iterrows() if str(r.get("Total spend", "")).strip() not in ("", "nan", "None", "—", "$0.00", "$0"))
        _s_cur_month = datetime.now().strftime("%Y-%m")
        _s_fp_month = 0
        _s_created_month = 0
        for _, r in stripe_raw.iterrows():
            if str(r.get("final_status", "")).upper() == "ACCEPTED":
                _fp = str(r.get("First payment", "")).strip()
                _cr = str(r.get("Created", "")).strip()
                _rd = str(r.get("row_date_used", "")).strip()
                if _fp and _fp.startswith(_s_cur_month):
                    _s_fp_month += 1
                if _cr and _cr.startswith(_s_cur_month):
                    _s_created_month += 1
                if _rd and _rd.startswith(_s_cur_month):
                    _s_created_month += 1  # row_date_used counts too

        _sc1, _sc2, _sc3, _sc4 = st.columns(4)
        with _sc1:
            st.metric("Total Rows", f"{len(stripe_raw):,}")
        with _sc2:
            st.metric("✅ ACCEPTED", f"{_s_acc:,}")
        with _sc3:
            st.metric("❌ REJECTED", f"{_s_rej:,}")
        with _sc4:
            st.metric("This Month (Accepted)", f"{_s_fp_month} (FP) / {_s_created_month} (Created)")

        # Stripe API Live Verification
        _stripe_api_key = get_secret("STRIPE_SECRET_KEY", "")
        if _stripe_api_key and str(_stripe_api_key).startswith("sk_"):
            with st.expander("🟢 Stripe API Live Verification", expanded=True):
                if st.button("🔍 Verify with Stripe API", key="verify_stripe_api"):
                    try:
                        import stripe as _stripe_lib
                        _stripe_lib.api_key = str(_stripe_api_key)
                        _now = datetime.now()
                        _ms = int(datetime(_now.year, _now.month, 1).timestamp())
                        _all_pi = []
                        _has_more = True
                        _sa = None
                        while _has_more:
                            _params = {"created": {"gte": _ms}, "limit": 100}
                            if _sa:
                                _params["starting_after"] = _sa
                            _resp = _stripe_lib.PaymentIntent.list(**_params)
                            _all_pi.extend(_resp.data)
                            _has_more = _resp.has_more
                            if _has_more and _resp.data:
                                _sa = _resp.data[-1].id
                        _api_total = len(_all_pi)
                        _api_accepted = sum(1 for i in _all_pi if i.status == "succeeded")
                        _api_declined = sum(
                            1 for i in _all_pi if i.status in ["requires_payment_method", "canceled", "payment_failed"]
                        )
                        _api_revenue = sum(i.amount / 100 for i in _all_pi if i.status == "succeeded")
                        _va1, _va2, _va3, _va4 = st.columns(4)
                        with _va1:
                            st.metric("API Total Payments", f"{_api_total:,}")
                        with _va2:
                            st.metric("API Succeeded (Accepted)", f"{_api_accepted:,}")
                        with _va3:
                            st.metric("API Declined", f"{_api_declined:,}")
                        with _va4:
                            st.metric("API Revenue", f"${_api_revenue:,.2f}")
                        if _api_accepted != _s_acc:
                            st.warning(f"⚠️ Mismatch: Sheets ACCEPTED={_s_acc} vs API Succeeded={_api_accepted}. Pipeline may need to re-run.")
                        else:
                            st.success(f"✅ Verified: Sheets ACCEPTED ({_s_acc}) matches API Succeeded ({_api_accepted})")
                    except Exception as _e:
                        st.error(f"❌ Stripe API error: {_e}")
        elif not _stripe_api_key:
            with st.expander("⚪ Stripe API Verification (Not Connected)"):
                st.info("💡 Add `STRIPE_SECRET_KEY` to Streamlit secrets for optional live Stripe API verification (cross-check sheet data).")
                st.caption("Stripe data is already scraped via session cookies (`STRIPE_COOKIES_JSON`). The API key is only for verification.")

        with st.expander("🔍 Stripe Details — Accept/Reject Breakdown"):
            if "category" in stripe_raw.columns:
                _cat_counts = stripe_raw.groupby("category").size().reset_index(name="Count").sort_values("Count", ascending=False)
                st.dataframe(_cat_counts, height=300, use_container_width=True, hide_index=True)

            if _s_has_fp < _s_acc:
                st.warning(
                    f"⚠️ Only {_s_has_fp}/{_s_acc} ACCEPTED rows have 'First payment' date. "
                    f"Rows without First payment use 'Created' date instead. "
                    f"If this seems wrong, check if Stripe scraper is capturing the 'first_payment' column."
                )

            st.caption(f"💡 Rows with 'First payment' date: {_s_has_fp} | Rows with 'Total spend' > $0: {_s_has_spend}")
            st.caption("💡 Pipeline must re-run after code update to re-categorize Stripe data with the new logic.")

        # Show sample of recent Stripe data
        with st.expander("📋 Recent Stripe Data (first 10 rows)"):
            _show_cols = [c for c in ["Email", "Customer", "First payment", "Created", "Total spend", "final_status", "category"] if c in stripe_raw.columns]
            if _show_cols:
                st.dataframe(stripe_raw[_show_cols].head(10), height=300)
            else:
                st.dataframe(stripe_raw.head(10), height=300)
    else:
        st.error("❌ No Stripe data loaded! Either Verified_STRIPE sheet is empty or connection failed.")
        st.caption("💡 This means the pipeline hasn't successfully scraped Stripe data. "
                   "Check that STRIPE_COOKIES_JSON secret is set and valid in GitHub repo secrets.")
    st.caption("The pipeline fetches fresh data from all sources. Auto-trigger runs daily when data is stale.")

    # Auto-trigger status
    _gh_token = get_secret("GITHUB_TOKEN", "")
    _auto_enabled = st.toggle("🔄 Auto-Trigger Pipeline (when data is stale)", value=True, key="auto_pipeline_toggle")
    if _auto_enabled and not _gh_token:
        st.warning("⚠️ Add `GITHUB_TOKEN` (GitHub PAT) to secrets to enable auto-trigger.")

    # Show data freshness
    _today_str2 = datetime.now().strftime("%Y-%m-%d")
    _has_today_data = False
    if not counts_raw.empty:
        _dc2 = next((c for c in counts_raw.columns if "date" in c.lower()), None)
        if _dc2:
            _has_today_data = _today_str2 in counts_raw[_dc2].astype(str).values
    if _has_today_data:
        st.success(f"✅ Data is fresh — today ({_today_str2}) data exists")
    else:
        st.warning(f"⚠️ Data is stale — no data for today ({_today_str2})")

    # Manual trigger buttons
    _trig_c1, _trig_c2 = st.columns(2)
    with _trig_c1:
        if st.button("🚀 Run Pipeline (Local)", type="secondary", use_container_width=True):
            with st.spinner("Running pipeline..."):
                try:
                    import subprocess
                    _root_dir = os.path.dirname(os.path.abspath(__file__))
                    _result = subprocess.run(
                        ["python3", "daily_pipeline.py"],
                        capture_output=True, text=True, timeout=180,
                        cwd=_root_dir,
                    )
                    if _result.returncode == 0:
                        st.success("✅ Pipeline completed! Refresh page to see updated data.")
                        if _result.stdout:
                            st.code(_result.stdout[-800:])
                        st.cache_data.clear()
                    else:
                        st.warning("Pipeline finished with warnings")
                        if _result.stderr:
                            st.code(_result.stderr[-800:])
                except FileNotFoundError:
                    st.info("Pipeline scripts not available on Streamlit Cloud. Use Remote trigger.")
                except Exception as _e:
                    st.info(f"Run manually: `python3 daily_pipeline.py` ({_e})")

    with _trig_c2:
        if _gh_token:
            if st.button("⚡ Trigger Remote Pipeline", type="primary", use_container_width=True):
                try:
                    import urllib.request
                    import json as _json
                    _repo = "fozayelibnayaz/eagle3d-kpi-automation"
                    _url = f"https://api.github.com/repos/{_repo}/actions/workflows/daily_pipeline.yml/dispatches"
                    _data = _json.dumps({"ref": "main"}).encode()
                    _req = urllib.request.Request(
                        _url, data=_data, method="POST",
                        headers={"Authorization": f"token {_gh_token}", "Accept": "application/vnd.github+json"}
                    )
                    with urllib.request.urlopen(_req, timeout=15) as _r:
                        if _r.status in (200, 204):
                            st.success("✅ Pipeline triggered! Data updates in ~5 min. Refresh then.")
                except Exception as _e:
                    st.error(f"Failed: {_e}")
        else:
            st.button("⚡ Trigger Remote Pipeline", disabled=True, use_container_width=True)
            st.caption("🔑 Add `GITHUB_TOKEN` (a GitHub PAT with `repo` + `workflow` scope) to secrets to enable this button.")
            st.markdown("[👉 Trigger Manually on GitHub →](https://github.com/fozayelibnayaz/eagle3d-kpi-automation/actions/workflows/daily_pipeline.yml)")

    st.markdown("---")
    st.markdown("#### 🔧 Add / Update Secrets (Local Only)")
    st.caption("For Streamlit Cloud, add secrets at **share.streamlit.io → Settings → Secrets**.")
    with st.expander("📝 Edit local secrets.toml"):
        _secret_text = st.text_area("secrets.toml content", value="""# API Keys
GROQ_API_KEY = "your-groq-key"
GEMINI_API_KEY = "your-gemini-key"
""", height=180)
        if st.button("💾 Save secrets.toml"):
            try:
                os.makedirs(".streamlit", exist_ok=True)
                with open(".streamlit/secrets.toml", "w") as _f:
                    _f.write(_secret_text)
                st.success("✅ Saved! Refresh page to apply.")
            except OSError:
                st.warning("⚠️ Cannot write here (read-only). Add secrets in share.streamlit.io → Settings → Secrets.")

    st.markdown("---")
    st.markdown("#### 🔄 Clear Cache & Refresh Data")
    if st.button("🔄 Clear All Cache", use_container_width=True):
        st.cache_data.clear()
        st.success("✅ Cache cleared! Refresh page to reload all data.")

# ═══════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════
st.divider()
_fc1, _fc2, _fc3 = st.columns(3)
with _fc1:
    st.caption(
        f"Eagle3D Eagle Analytics Hub v7.2 | "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
with _fc2:
    st.caption("Pipeline: Daily 12:00 UTC")
with _fc3:
    _ai_mod = MOD.get("ai_engine")
    if _ai_mod:
        _pr = _ai_mod._get_provider()
        _prl = (
            "⚡ Groq" if _pr == "groq"
            else "💎 Gemini" if _pr == "gemini"
            else "🧠 Rules"
        )
        st.caption(f"AI: {_prl}")
