"""
app.py — Eagle 3D Streaming Analytics Hub
Premium Monetra-style dark dashboard. MongoDB-only.
"""
from __future__ import annotations
from kpi_totals_resolver import resolve_period_kpis

import base64
from datetime import datetime, date
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from period_engine import get_period, get_period_button_label, render_period_picker, PRESETS, COMPARE_MODES

# ─── Page config ─────────────────────────────────────────────────
st.set_page_config(
    page_title="Eagle 3D Streaming — Analytics Hub",
    page_icon="static/eagle3d_logo2.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Constants ───────────────────────────────────────────────────
BRAND_NAME = "Eagle 3D Streaming"
_AUTH_OK = True

NAV_PAGES = [
    ("dashboard", "Dashboard"),
    ("kpi",       "KPI Analytics"),
    ("ga4",       "Traffic"),
    ("youtube",   "YouTube"),
    ("linkedin",  "LinkedIn"),
    ("cs",        "Customers"),
    ("cross",     "Cross-Platform"),
    ("ai",        "AI Insights"),
    ("custom",    "Custom Modules"),
    ("settings",  "Settings"),
]

SIDEBAR_ICONS = [
    ("dashboard", "⊞",  "Dashboard"),
    ("kpi",       "📊", "KPI Analytics"),
    ("ga4",       "<img src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iI0Y5QUIwMCI+PHBhdGggZD0iTTIyLjg0IDIuOTk4djE3Ljk5OWEyLjk4MyAyLjk4MyAwIDAxLTIuOTk4IDIuOTk4IDIuOTgzIDIuOTgzIDAgMDEtMi45OTgtMi45OThWMi45OThBMi45ODMgMi45ODMgMCAwMTE5Ljg0MiAwYTIuOTgzIDIuOTgzIDAgMDEyLjk5OCAyLjk5OHpNOC4xNTggMTQuODQ1djYuMTUzYTIuOTk4IDIuOTk4IDAgMTA1Ljk5NiAwdi02LjE1M2EyLjk5OCAyLjk5OCAwIDEwLTUuOTk2IDB6TTMgMjAuOTk4YTIuOTk4IDIuOTk4IDAgMTA1Ljk5NiAwIDIuOTk4IDIuOTk4IDAgMDAtNS45OTYgMHoiLz48L3N2Zz4=' width='20' height='20' style='display:block;'/>", "Traffic + Events"),
    ("youtube",   "<img src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iI0ZGMDAwMCI+PHBhdGggZD0iTTIzLjQ5OCA2LjE4NmEyLjk5OSAyLjk5OSAwIDAwLTIuMTA5LTIuMTE3QzE5LjQ3MiAzLjUgMTIgMy41IDEyIDMuNXMtNy40NzIgMC05LjM4OS41NjlBMi45OTkgMi45OTkgMCAwMC41MDIgNi4xODZDMCA4LjA5IDAgMTIgMCAxMnMwIDMuOTEuNTAyIDUuODE0YTIuOTk5IDIuOTk5IDAgMDAyLjEwOSAyLjExN0M0LjUyOCAyMC41IDEyIDIwLjUgMTIgMjAuNXM3LjQ3MiAwIDkuMzg5LS41NjlhMi45OTkgMi45OTkgMCAwMDIuMTA5LTIuMTE3QzI0IDE1LjkxIDI0IDEyIDI0IDEyczAtMy45MS0uNTAyLTUuODE0ek05Ljc1IDE1LjU2OFY4LjQzMkwxNS44MTggMTJsLTYuMDY4IDMuNTY4eiIvPjwvc3ZnPg==' width='22' height='22' style='display:block;'/>", "YouTube"),
    ("linkedin",  "<img src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iIzBBNjZDMiI+PHBhdGggZD0iTTIwLjUgMmgtMTdBMS41IDEuNSAwIDAwMiAzLjV2MTdBMS41IDEuNSAwIDAwMy41IDIyaDE3YTEuNSAxLjUgMCAwMDEuNS0xLjV2LTE3QTEuNSAxLjUgMCAwMDIwLjUgMnpNOCAxOUg1di05aDN6TTYuNSA4LjI1QTEuNzUgMS43NSAwIDExOC4zIDYuNWExLjc4IDEuNzggMCAwMS0xLjggMS43NXpNMTkgMTloLTN2LTQuNzRjMC0xLjQyLS42LTEuOTMtMS4zOC0xLjkzQTEuNzQgMS43NCAwIDAwMTMgMTQuMTlhLjY2LjY2IDAgMDAwIC4xNFYxOWgtM3YtOWgyLjl2MS4zYTMuMTEgMy4xMSAwIDAxMi43LTEuNGMxLjU1IDAgMy4zNi44NiAzLjM2IDMuNjZ6Ii8+PC9zdmc+' width='20' height='20' style='display:block;'/>", "LinkedIn"),
    ("cs",        "🎯", "Customer Success"),
    ("cross",     "🔗", "Cross-Platform"),
    ("ai",        "✦",  "AI Insights"),
    ("custom",    "🧩", "Custom Modules"),
]
SIDEBAR_FOOTER_ICONS = [
    ("settings",  "⚙",  "Settings"),
    ("_logout",   "⏻",  "Logout"),
]

# ─── Auth ────────────────────────────────────────────────────────
def _require_auth():
    if not _AUTH_OK:
        return "dev@eagle3dstreaming.com", "admin"
    try:
        from auth_guard import require_auth
        return require_auth("Dashboard")
    except Exception as e:
        st.error(f"Auth error: {e}")
        st.stop()

# ─── Logo loader ─────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_logo(filename: str) -> str:
    f = Path("static") / filename
    if f.exists():
        return base64.b64encode(f.read_bytes()).decode()
    return ""

LOGO_MAIN = _load_logo("eagle3d_logo2.png")   # primary (rounded/dark bg)
LOGO_ALT  = _load_logo("eagle3d_logo.png")    # alt

def _logo_img(size: int = 36, which: str = "main") -> str:
    b64 = LOGO_MAIN if which == "main" else LOGO_ALT
    if not b64:
        return ""
    return (
        f'<img src="data:image/png;base64,{b64}" '
        f'style="width:{size}px;height:{size}px;object-fit:contain;'
        f'display:block;" alt="Eagle 3D Streaming">'
    )

# ─── CSS ─────────────────────────────────────────────────────────
def _inject_css():
    ext = ""
    p = Path("static/monetra.css")
    if p.exists():
        ext = p.read_text(encoding="utf-8")

    critical = """
    /* HIDE Streamlit chrome */
    #MainMenu, header, footer,
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="collapsedControl"],
    section[data-testid="stSidebar"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] {
        display: none !important;
        visibility: hidden !important;
        width: 0 !important;
    }

    html, body, [data-testid="stApp"] {
        background: #080808 !important;
        color: #fff !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont,
                     'Segoe UI', sans-serif !important;
        margin: 0; padding: 0;
        overflow-x: hidden;
    }

    .main .block-container {
        padding: 0 !important;
        max-width: 100% !important;
        margin: 0 !important;
    }

    /* ═══════ TOP NAVBAR ═══════ */
    .e3-topbar {
        position: fixed;
        top: 0; left: 0; right: 0;
        height: 72px;
        background: rgba(8,8,8,0.92);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-bottom: 1px solid rgba(255,255,255,0.06);
        display: flex;
        align-items: center;
        padding: 0 28px;
        gap: 20px;
        z-index: 9000;
        box-sizing: border-box;
    }

    .e3-toggle-btn {
        width: 42px; height: 42px;
        border-radius: 12px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        color: #fff;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
        font-size: 20px;
        transition: all 0.2s ease;
        flex-shrink: 0;
        user-select: none;
    }
    .e3-toggle-btn:hover {
        background: rgba(158,255,47,0.08);
        border-color: rgba(158,255,47,0.3);
        color: #9EFF2F;
    }
    .e3-toggle-btn.open {
        background: linear-gradient(135deg, #9EFF2F, #5EF46A);
        border-color: transparent;
        color: #000;
    }

    .e3-logo {
        display: flex;
        align-items: center;
        gap: 12px;
        text-decoration: none;
        flex-shrink: 0;
    }
    .e3-logo-icon {
        width: 40px; height: 40px;
        border-radius: 12px;
        overflow: hidden;
        display: flex; align-items: center; justify-content: center;
        background: transparent;
    }
    .e3-logo-name {
        color: #fff;
        font-size: 15px;
        font-weight: 600;
        letter-spacing: -0.01em;
        white-space: nowrap;
    }

    .e3-nav-tabs {
        display: flex;
        gap: 4px;
        background: rgba(255,255,255,0.03);
        padding: 5px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.06);
        margin: 0 auto;
    }
    .e3-nav-tab {
        padding: 8px 20px;
        border-radius: 999px;
        color: #9CA3AF;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        text-decoration: none !important;
        white-space: nowrap;
    }
    .e3-nav-tab:hover { color: #fff; }
    .e3-nav-tab.active {
        background: linear-gradient(135deg, #9EFF2F, #5EF46A);
        color: #000 !important;
        font-weight: 600;
        box-shadow: 0 4px 16px rgba(158,255,47,0.25);
    }

    .e3-nav-actions {
        display: flex;
        gap: 10px;
        align-items: center;
        flex-shrink: 0;
        margin-left: auto;
    }
    .e3-icon-btn {
        width: 40px; height: 40px;
        border-radius: 50%;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.06);
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
        color: #9CA3AF;
        font-size: 16px;
        transition: all 0.2s ease;
        position: relative;
        text-decoration: none;
    }
    .e3-icon-btn:hover {
        background: rgba(255,255,255,0.08);
        color: #fff;
    }
    .e3-icon-btn.notif::after {
        content: '';
        position: absolute;
        top: 8px; right: 8px;
        width: 8px; height: 8px;
        background: #EF4444;
        border-radius: 50%;
        border: 2px solid #080808;
    }
    .e3-avatar {
        width: 40px; height: 40px;
        border-radius: 50%;
        background: linear-gradient(135deg, #9EFF2F, #5EF46A);
        display: flex; align-items: center; justify-content: center;
        color: #000;
        font-weight: 700;
        font-size: 15px;
        cursor: pointer;
    }
    .e3-avatar:hover {
        transform: scale(1.08);
        box-shadow: 0 4px 20px rgba(158,255,47,0.4);
    }

    /* ═══════ FLOATING SIDEBAR ═══════ */
    .e3-sidebar {
        position: fixed;
        left: 24px;
        top: 96px;
        background: rgba(17,17,17,0.96);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 26px;
        padding: 14px 10px;
        z-index: 8500;
        display: flex;
        flex-direction: column;
        gap: 4px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.7);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);

        opacity: 0;
        pointer-events: none;
        transform: translateX(-80px);
        transition: opacity 0.25s ease,
                    transform 0.3s cubic-bezier(0.34,1.56,0.64,1);
    }
    .e3-sidebar.visible {
        opacity: 1;
        pointer-events: all;
        transform: translateX(0);
    }
    .e3-sidebar-divider {
        width: 100%; height: 1px;
        background: rgba(255,255,255,0.06);
        margin: 6px 0;
    }
    .e3-side-btn {
        width: 46px; height: 46px;
        border-radius: 14px;
        background: transparent;
        border: 1px solid transparent;
        color: #6B7280;
        display: flex; align-items: center; justify-content: center;
        font-size: 18px;
        cursor: pointer;
        transition: all 0.18s ease;
        text-decoration: none !important;
        position: relative;
        flex-shrink: 0;
    }
    .e3-side-btn:hover {
        color: #fff;
        background: rgba(255,255,255,0.05);
        border-color: rgba(255,255,255,0.08);
    }
    .e3-side-btn.active {
        background: linear-gradient(135deg,
            rgba(158,255,47,0.15),
            rgba(94,244,106,0.08));
        border-color: rgba(158,255,47,0.4);
        color: #9EFF2F;
        box-shadow: 0 0 20px rgba(158,255,47,0.2);
    }
    .e3-side-btn.active::before {
        content: '';
        position: absolute;
        left: -13px; top: 50%;
        transform: translateY(-50%);
        width: 3px; height: 22px;
        background: #9EFF2F;
        border-radius: 999px;
        box-shadow: 0 0 12px rgba(158,255,47,0.7);
    }

    /* Tooltip */
    .e3-side-btn::after {
        content: attr(title);
        position: absolute;
        left: calc(100% + 14px);
        top: 50%; transform: translateY(-50%);
        background: rgba(17,17,17,0.98);
        border: 1px solid rgba(255,255,255,0.1);
        color: #fff;
        font-size: 12px;
        font-weight: 500;
        padding: 6px 12px;
        border-radius: 8px;
        white-space: nowrap;
        pointer-events: none;
        opacity: 0;
        transition: opacity 0.15s ease;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    }
    .e3-side-btn:hover::after { opacity: 1; }

    /* ═══════ CARDS / TYPOGRAPHY ═══════ */
    .e3-card {
        background: #111;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 24px;
        padding: 28px;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    .e3-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        border-color: rgba(255,255,255,0.1);
    }
    .e3-metric-card {
        background: #111;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 20px;
        padding: 24px 26px;
        transition: all 0.3s ease;
    }
    .e3-metric-icon {
        width: 28px; height: 28px;
        border-radius: 8px;
        background: rgba(255,255,255,0.04);
        display: flex; align-items: center; justify-content: center;
        font-size: 13px;
    }
    .e3-hero-greeting {
        font-size: 40px;
        font-weight: 700;
        color: #fff;
        letter-spacing: -0.03em;
        margin: 0;
        line-height: 1.15;
    }
    .e3-hero-sub {
        color: #9CA3AF;
        font-size: 15px;
        margin-top: 8px;
    }
    .e3-section-title {
        font-size: 18px;
        font-weight: 600;
        color: #fff;
        margin: 0 0 4px 0;
        letter-spacing: -0.01em;
    }
    .e3-section-sub {
        color: #6B7280;
        font-size: 13px;
        margin: 0 0 20px 0;
    }
    .e3-badge {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 11px; font-weight: 600;
        letter-spacing: 0.03em;
    }
    .e3-badge.success { background: rgba(74,222,128,0.1); color: #4ADE80; }
    .e3-badge.danger  { background: rgba(239,68,68,0.1);  color: #EF4444; }
    .e3-badge.primary { background: rgba(158,255,47,0.1); color: #9EFF2F; }
    .e3-badge.warning { background: rgba(250,204,21,0.12); color: #FACC15; }
    .e3-status-dot {
        display: inline-block; width: 8px; height: 8px;
        border-radius: 50%; margin-right: 6px;
    }
    .e3-status-dot.ok  { background: #4ADE80; box-shadow: 0 0 8px rgba(74,222,128,0.5); }
    .e3-status-dot.err { background: #EF4444; box-shadow: 0 0 8px rgba(239,68,68,0.5); }

    /* Streamlit metric override */
    [data-testid="stMetric"] {
        background: #111 !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
        border-radius: 20px !important;
        padding: 22px 24px !important;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 12px 40px rgba(0,0,0,0.4);
        border-color: rgba(255,255,255,0.1) !important;
    }
    [data-testid="stMetricLabel"] {
        color: #9CA3AF !important;
        font-weight: 500 !important;
        font-size: 12px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
    }
    [data-testid="stMetricValue"] {
        color: #fff !important;
        font-weight: 700 !important;
        font-size: 30px !important;
        letter-spacing: -0.03em !important;
    }
    [data-testid="stMetricDelta"] { font-weight: 600 !important; }

    .stButton > button {
        border-radius: 14px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        padding: 10px 20px !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        background: rgba(255,255,255,0.04) !important;
        color: #fff !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #9EFF2F, #5EF46A) !important;
        color: #000 !important;
        border: none !important;
    }

    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #080808; }
    ::-webkit-scrollbar-thumb { background: #222; border-radius: 999px; }
    ::-webkit-scrollbar-thumb:hover { background: #333; }

    @keyframes fadeUp {
        from { opacity: 0; transform: translateY(16px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    .e3-fade-up { animation: fadeUp 0.45s cubic-bezier(0.34,1.56,0.64,1) forwards; }

    .e3-placeholder {
        text-align: center;
        padding: 80px 40px;
        background: #111;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 24px;
        margin-top: 32px;
    }




        /* ═══════ PERIOD MOUNT POINT (in topbar beside bell) ═══════ */
    .e3-period-mount {
        display: inline-flex !important;
        align-items: center !important;
        margin-right: 6px !important;
    }

    /* Any element moved inside .e3-period-mount */
    .e3-period-mount > div {
        margin: 0 !important;
        padding: 0 !important;
        width: auto !important;
    }
    .e3-period-mount [data-testid="stPopover"] {
        margin: 0 !important;
        padding: 0 !important;
        width: auto !important;
    }
    .e3-period-mount [data-testid="stPopover"] > div {
        margin: 0 !important;
        padding: 0 !important;
        width: auto !important;
    }
    .e3-period-mount button {
        background: rgba(158,255,47,0.12) !important;
        border: 1px solid rgba(158,255,47,0.35) !important;
        color: #fff !important;
        border-radius: 999px !important;
        padding: 0 16px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        height: 40px !important;
        min-height: 40px !important;
        line-height: 40px !important;
        white-space: nowrap !important;
        margin: 0 !important;
        cursor: pointer !important;
    }
    .e3-period-mount button:hover {
        background: rgba(158,255,47,0.20) !important;
        border-color: rgba(158,255,47,0.60) !important;
        box-shadow: 0 4px 20px rgba(158,255,47,0.25) !important;
    }
    .e3-period-mount button p {
        margin: 0 !important;
        color: #fff !important;
        font-size: 13px !important;
        font-weight: 600 !important;
    }

    /* Hide the wrapper's element container (empty placeholder left behind) */
    div[data-testid="element-container"]:has(#e3-period-src-wrapper) {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    /* Popover dropdown panel */
    [data-testid="stPopoverBody"] {
        background: rgba(17,17,17,0.98) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 16px !important;
        box-shadow: 0 20px 60px rgba(0,0,0,0.7) !important;
        padding: 20px !important;
        min-width: 340px !important;
    }

    @media (max-width: 1024px) {
        .e3-period-mount { display: none; }
    }

        @media (max-width: 1024px) { .e3-nav-tabs { display: none; } }
    @media (max-width: 768px) {
        .e3-topbar { padding: 0 16px; }
        .e3-hero-greeting { font-size: 28px; }
        .e3-sidebar { left: 12px; }
    }
    """
    st.markdown(f"<style>{ext}\n{critical}</style>", unsafe_allow_html=True)

# ─── Chrome (navbar + sidebar + JS toggle) ───────────────────────
def _render_chrome(current_page: str, user_email: str) -> None:
    """
    Renders topbar + floating sidebar + JS toggle in a SINGLE HTML block
    injected at document level via components.html with window.parent access.
    This is the only reliable way to bind JS events to DOM created by markdown.
    """
    logo_html = _logo_img(32, "main") or "🦅"

    # Top pill nav
    top_nav = [
        ("dashboard", "Dashboard"),
        ("kpi",       "KPI"),
        ("ga4",       "Traffic"),
        ("youtube",   "YouTube"),
        ("linkedin",  "LinkedIn"),
        ("cs",        "CS"),
        ("cross",     "Cross"),
        ("ai",        "AI"),
        ("custom",    "Custom"),
    ]
    tabs_html = "".join(
        f'<a class="e3-nav-tab{" active" if k == current_page else ""}" '
        f'href="?page={k}" target="_top">{lbl}</a>'
        for k, lbl in top_nav
    )
    initial = (user_email[0].upper() if user_email else "A")

    # Sidebar buttons
    def _sbtn(k, ic, lbl, active):
        cls = "e3-side-btn" + (" active" if active else "")
        return (
            f'<a class="{cls}" href="?page={k}" '
            f'target="_top" title="{lbl}">{ic}</a>'
        )

    top_btns = "".join(
        _sbtn(k, ic, lbl, k == current_page) for k, ic, lbl in SIDEBAR_ICONS
    )
    bot_btns = "".join(
        _sbtn(k, ic, lbl, k == current_page) for k, ic, lbl in SIDEBAR_FOOTER_ICONS
    )

    # Inject into PARENT document via <script> that runs from an iframe
    # (components.html always sandboxes, so we use window.parent)
    chrome_html = f"""
    <div id="e3-topbar" class="e3-topbar">
      <div class="e3-toggle-btn" id="e3-toggle" title="Toggle sidebar">☰</div>
      <a class="e3-logo" href="?page=dashboard" target="_top">
        <div class="e3-logo-icon">{logo_html}</div>
        <span class="e3-logo-name">{BRAND_NAME}</span>
      </a>
      <div class="e3-nav-tabs">{tabs_html}</div>
      <div class="e3-nav-actions">
        <div id="e3-period-mount" class="e3-period-mount"></div>
        <div class="e3-icon-btn notif" title="Notifications">🔔</div>
        <a class="e3-icon-btn" href="?page=settings" target="_top" title="Settings">⚙</a>
        <div class="e3-avatar" title="{user_email}">{initial}</div>
      </div>
    </div>

    <div id="e3-sidebar" class="e3-sidebar">
      {top_btns}
      <div class="e3-sidebar-divider"></div>
      {bot_btns}
    </div>
    """

    # Step 1: inject chrome HTML directly (renders in main doc, styles apply)
    st.markdown(chrome_html, unsafe_allow_html=True)

    # Step 2: inject JS via components.html which can access window.parent
    toggle_js = """
    <script>
    (function() {
        const doc = window.parent.document;

        function setup() {
            const toggle  = doc.getElementById('e3-toggle');
            const sidebar = doc.getElementById('e3-sidebar');
            if (!toggle || !sidebar) {
                setTimeout(setup, 150);
                return;
            }
            if (toggle.dataset.wired === '1') return;
            toggle.dataset.wired = '1';

            // Restore state
            let open = sessionStorage.getItem('e3_sb') === '1';
            if (open) {
                sidebar.classList.add('visible');
                toggle.classList.add('open');
            }

            toggle.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                open = !open;
                sessionStorage.setItem('e3_sb', open ? '1' : '0');
                if (open) {
                    sidebar.classList.add('visible');
                    toggle.classList.add('open');
                } else {
                    sidebar.classList.remove('visible');
                    toggle.classList.remove('open');
                }
            });

            // Click-outside to close
            doc.addEventListener('click', function(e) {
                if (!open) return;
                if (sidebar.contains(e.target)) return;
                if (toggle.contains(e.target)) return;
                open = false;
                sessionStorage.setItem('e3_sb', '0');
                sidebar.classList.remove('visible');
                toggle.classList.remove('open');
            });

            // ESC key
            doc.addEventListener('keydown', function(e) {
                if (e.key === 'Escape' && open) {
                    open = false;
                    sessionStorage.setItem('e3_sb', '0');
                    sidebar.classList.remove('visible');
                    toggle.classList.remove('open');
                }
            });
        }
        setup();
    })();
    </script>
    """
    components.html(toggle_js, height=0, width=0)

# ─── Router ──────────────────────────────────────────────────────
def _get_current_page() -> str:
    valid = {p[0] for p in NAV_PAGES}
    page = st.query_params.get("page", None)
    if page and page in valid:
        st.session_state["current_page"] = page
        return page
    return st.session_state.get("current_page", "dashboard")

def _placeholder(title: str, sub: str, icon: str = "🚧") -> None:
    st.markdown(
        f"""
        <div class="e3-fade-up">
          <h1 class="e3-hero-greeting">{title}</h1>
          <p class="e3-hero-sub">{sub}</p>
        </div>
        <div class="e3-placeholder e3-fade-up">
          <div style="font-size:56px;margin-bottom:20px;">{icon}</div>
          <div style="font-size:22px;font-weight:700;color:#fff;
                      margin-bottom:8px;">Coming Soon</div>
          <div style="color:#6B7280;font-size:14px;">Ships in the next phase.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
def route(page: str, user_email: str) -> None:
    if page == "dashboard":
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
    elif page == "ai":
        from pages_registry import render_ai_page
        render_ai_page(user_email)
    elif page == "cross":
        from pages_registry import render_cross_page
        render_cross_page(user_email)
    elif page == "custom":
        from pages_registry import render_custom_page
        render_custom_page(user_email)
    elif page == "settings":
        st.info("Settings page is available through the app controls.")
    elif page == "_logout":
        for k in ("_pwd_ok", "_auth_ok", "user_email", "user_role", "current_page"):
            st.session_state.pop(k, None)
        st.query_params.clear()
        st.rerun()
    else:
        st.warning(f"Unknown page: {page}")
def _render_dashboard(user_email: str) -> None:
    from period_engine import get_period
    from ui_helpers import (
        empty_state, wallet_card, quick_actions_panel, activity_feed,
        page_error_boundary, animated_number,
    )

    with page_error_boundary("Dashboard"):
        name = "there"
        if user_email:
            try:
                name = user_email.split("@")[0].split(".")[0].capitalize()
            except Exception:
                pass

        period = get_period()
        logo_hero = _logo_img(52, "main")

        compare_html = (
            f' &middot; <span style="color:#FACC15;">↔ {period.compare_label}</span>'
            if period.compare_enabled else ""
        )
        hero_meta = (
            f'<span style="color:#9EFF2F;font-weight:600;">{period.label}</span> '
            f'&middot; {period.start_iso()} → {period.end_iso()} '
            f'&middot; {period.days} days{compare_html}'
        )
        logo_block = (
            f'<div style="width:52px;height:52px;">{logo_hero}</div>'
            if logo_hero else ""
        )

        st.markdown(
            f'''<div class="e3-fade-up" style="display:flex;align-items:center;gap:20px;">{logo_block}<div><div class="e3-hero-greeting">{_greeting()}, {name}</div><div class="e3-hero-sub">{hero_meta}</div></div></div>''',
            unsafe_allow_html=True,
        )
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)

        # ══════════════════════════════════════════════════════════════
        # Fetch counts from daily_kpis (POST-DEDUP + POST-VALIDATION)
        # ══════════════════════════════════════════════════════════════
        signups = uploads = payments = 0
        prev_signups = prev_uploads = prev_payments = 0
        revenue = 0.0
        db_connected = False
        colls = daily = 0
        activity_events = []

        try:
            from mongo_client import find_all, get_mongo_status
            s = get_mongo_status()
            db_connected = s.get("connected", False)
            colls = s.get("collections", 0)
            daily = s.get("daily_kpis_count", 0)

            def _sum_kpis(start_iso, end_iso):
                rows = find_all("daily_kpis",
                                filters={"date": {"$gte": start_iso, "$lte": end_iso}},
                                sort=[("date", 1)])
                s_ = sum(int(r.get("signups", 0) or 0) for r in rows)
                u_ = sum(int(r.get("first_uploads", 0) or 0) for r in rows)
                p_ = sum(int(r.get("new_paid_customers",    0) or 0) for r in rows)
                return s_, u_, p_

            if db_connected:
                signups, uploads, payments = _sum_kpis(period.start_iso(), period.end_iso())

                if period.compare_enabled and period.compare_start and period.compare_end:
                    prev_signups, prev_uploads, prev_payments = _sum_kpis(
                        period.compare_start_iso(), period.compare_end_iso()
                    )

                pay_docs = find_all("payments", {
                    "final_status": "ACCEPTED",
                    "first_payment_date": {"$gte": period.start_iso(),
                                            "$lte": period.end_iso()},
                })
                revenue = sum(float(p.get("total_spend", 0) or 0) for p in pay_docs)

                # Build activity feed (recent events across signups/uploads/payments)
                recent_sign = find_all("signups",
                                        filters={"final_status": "ACCEPTED"},
                                        sort=[("signup_date", -1)], limit=6)
                recent_up = find_all("uploads",
                                      filters={"final_status": "ACCEPTED"},
                                      sort=[("upload_date", -1)], limit=5)
                recent_pay = find_all("payments",
                                       filters={"final_status": "ACCEPTED"},
                                       sort=[("first_payment_date", -1)], limit=5)

                from datetime import datetime as _dt
                def _rel_time(iso_str):
                    if not iso_str: return "?"
                    try:
                        dt = _dt.fromisoformat(str(iso_str)[:10])
                        days = (_dt.now() - dt).days
                        if days == 0: return "today"
                        if days == 1: return "yesterday"
                        if days < 7:  return f"{days}d ago"
                        if days < 30: return f"{days//7}w ago"
                        return f"{days//30}mo ago"
                    except: return str(iso_str)[:10]

                for r in recent_sign:
                    activity_events.append({
                        "icon":  "👥",
                        "text":  f"New sign-up: {r.get('email_normalized', 'unknown')[:32]}",
                        "when":  _rel_time(r.get("signup_date")),
                        "color": "#9EFF2F",
                    })
                for r in recent_up:
                    activity_events.append({
                        "icon":  "📤",
                        "text":  f"First upload: {r.get('email_normalized', 'unknown')[:32]}",
                        "when":  _rel_time(r.get("upload_date")),
                        "color": "#5EF46A",
                    })
                for r in recent_pay:
                    activity_events.append({
                        "icon":  "💳",
                        "text":  f"Paid: {r.get('email_normalized', 'unknown')[:28]} (${float(r.get('total_spend', 0) or 0):,.0f})",
                        "when":  _rel_time(r.get("first_payment_date")),
                        "color": "#4ADE80",
                    })
        except Exception as e:
            st.warning(f"Data fetch: {e}")

        # DB banner
        if db_connected:
            st.markdown(
                '<div class="e3-badge success" style="margin-bottom:24px;">'
                '<span class="e3-status-dot ok"></span>MongoDB Connected'
                ' &middot; source: daily_kpis (post-dedup)</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="e3-badge danger" style="margin-bottom:24px;">'
                '<span class="e3-status-dot err"></span>MongoDB Offline</div>',
                unsafe_allow_html=True,
            )

        # ── Pipeline controls + health ──
        pipe_c1, pipe_c2, pipe_c3 = st.columns([1, 1, 1])
        with pipe_c1:
            if st.button("🚀 Run Pipeline Now", type="primary", key="run_pipe_btn"):
                import subprocess, sys
                with st.spinner("Running pipeline... (may take 5-15 min)"):
                    try:
                        r = subprocess.Popen(
                            [sys.executable, "daily_pipeline.py"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        )
                        st.success(f"✅ Pipeline started (PID {r.pid}). "
                                   f"Check terminal for progress. Refresh in a few minutes.")
                    except Exception as e:
                        st.error(f"Failed to launch: {e}")

        with pipe_c2:
            if st.button("♻ Rebuild daily_kpis", key="rebuild_kpis_btn",
                          help="Recomputes daily_kpis from raw ACCEPTED counts (fast)"):
                try:
                    from pipeline_gap_scanner import rebuild_from_raw
                    with st.spinner("Rebuilding..."):
                        r = rebuild_from_raw()
                        st.success(
                            f"✅ Rebuilt {r.get('rebuilt_days', 0)} days | "
                            f"S:{r.get('signups_total', 0)} U:{r.get('uploads_total', 0)} "
                            f"P:{r.get('paid_total', 0)}"
                        )
                        st.rerun()
                except Exception as e:
                    st.error(f"Rebuild failed: {e}")

        with pipe_c3:
            if st.button("🔍 Scan for gaps", key="scan_gaps_btn"):
                try:
                    from pipeline_gap_scanner import scan_gaps
                    r = scan_gaps()
                    if r["missing_count"] == 0 and r["zero_count"] == 0:
                        st.success(f"✅ 100% coverage ({r['expected_days']} days)")
                    else:
                        st.warning(
                            f"⚠️ {r['missing_count']} missing + {r['zero_count']} zero-only "
                            f"days in last {r['lookback_days']}d "
                            f"({r['health_pct']}% healthy)"
                        )
                        if r["missing_count"] > 0:
                            with st.expander("Missing dates"):
                                st.code("\n".join(r["missing_dates"][:50]))
                except Exception as e:
                    st.error(f"Scan error: {e}")

        # Pipeline health badge
        try:
            from pipeline_gap_scanner import scan_gaps
            gap = scan_gaps()
            hp = gap["health_pct"]
            badge_color = "success" if hp >= 95 else ("warning" if hp >= 80 else "danger")
            st.markdown(
                f'<div class="e3-badge {badge_color}" style="margin:12px 0;">'
                f'🔧 Pipeline health: {hp}% | {gap["expected_days"]} days tracked | '
                f'{gap["missing_count"]} missing | {gap["zero_count"]} zero-only</div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass

        st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)

        def _delta(current, prev):
            if not period.compare_enabled or prev is None:
                return None
            if prev == 0:
                return f"+{current} new" if current > 0 else "—"
            pct = (current - prev) / prev * 100
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct:.1f}% vs prev"

        # ── Layout: Left = hero revenue + KPIs, Right = wallet + quick actions ──
        left, right = st.columns([2.5, 1])

        with left:
            # Big animated revenue number
            animated_number(revenue, "Total Revenue in Period", prefix="$",
                            decimals=0, color="#9EFF2F", duration_ms=1400)

            st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)

            # KPI cards row
            st.markdown('<p class="e3-section-title">Overview</p>', unsafe_allow_html=True)
            st.markdown(
                f'<p class="e3-section-sub">Verified for <b>{period.label}</b> — post-dedup</p>',
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            c1.metric("👥 Sign-ups",        f"{signups:,}",  _delta(signups, prev_signups))
            c2.metric("📤 First Uploads",   f"{uploads:,}",  _delta(uploads, prev_uploads))
            c3.metric("💳 New Paying Customers", f"{payments:,}", _delta(payments, prev_payments))

        with right:
            # Wallet card
            wallet_card(
                title="Revenue Balance",
                balance=revenue,
                subtitle=f"{period.label} — {payments} new paying customers",
                holder=(user_email.upper()[:24] if user_email else "EAGLE 3D STREAMING"),
            )
            st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)

            # Quick actions
            quick_actions_panel([
                {"icon": "📊", "label": "Full KPI Analysis",  "href": "?page=kpi"},
                {"icon": "📈", "label": "Traffic Analytics",   "href": "?page=ga4"},
                {"icon": "▶",  "label": "YouTube Channel",     "href": "?page=youtube"},
                {"icon": "💼", "label": "LinkedIn Insights",   "href": "?page=linkedin"},
                {"icon": "🎯", "label": "Customer Success",    "href": "?page=cs"},
                {"icon": "✦",  "label": "Ask AI",              "href": "?page=ai"},
                {"icon": "⚙",  "label": "Settings",            "href": "?page=settings"},
            ])

        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)

        # ── ALL SYSTEMS SUMMARY (YouTube + LinkedIn + CS + GA4) ──
        st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
        st.markdown('<p class="e3-section-title">All Channels — Latest Snapshot</p>',
                    unsafe_allow_html=True)

        try:
            from mongo_client import find_one, find_all as _fa, count_docs
            from pathlib import Path as _P
            import json as _json

            # YouTube
            ch = find_one("youtube_channel", {}) or {}
            yt_subs   = int(ch.get("subscribers", 0) or 0)
            yt_views  = int(ch.get("view_count", 0) or 0)
            yt_videos = int(ch.get("video_count", 0) or 0)

            # LinkedIn
            hl_rows = _fa("linkedin_highlights_daily",
                           sort=[("snapshot_date", -1)], limit=1)
            hl = hl_rows[0] if hl_rows else {}
            li_followers  = int(hl.get("total_followers", 0) or 0)
            li_impressions= int(hl.get("impressions", 0) or 0)
            li_reactions  = int(hl.get("reactions", 0) or 0)

            # GA4 (cached)
            ga4_c = _P("data_output/ga4_traffic_cache.json")
            ga4_sessions = 0
            ga4_users = 0
            if ga4_c.exists():
                d = _json.loads(ga4_c.read_text())
                ga4_sessions = int(d.get("total_sessions", 0) or 0)
                ga4_users    = int(d.get("total_users", 0) or 0)

            # CS
            cs_count = count_docs("customer_success_master")

            sc1, sc2, sc3, sc4 = st.columns(4)
            with sc1:
                st.metric("▶ YouTube Subs",  f"{yt_subs:,}",
                            f"{yt_videos} videos · {yt_views:,} views")
            with sc2:
                st.metric("💼 LinkedIn Followers", f"{li_followers:,}",
                            f"{li_impressions:,} imp · {li_reactions} reactions")
            with sc3:
                st.metric("🌐 GA4 Sessions", f"{ga4_sessions:,}",
                            f"{ga4_users:,} users")
            with sc4:
                st.metric("🎯 CS Rows",       f"{cs_count:,}",
                            "customer records")
        except Exception as _e:
            st.info(f"All-systems summary unavailable: {_e}")

        st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)

        # ── Funnel ──
        su = round(uploads / signups * 100, 1) if signups else 0
        up = round(payments / uploads * 100, 1) if uploads else 0
        sp = round(payments / signups * 100, 1) if signups else 0
        st.markdown('<p class="e3-section-title">Funnel Conversion</p>', unsafe_allow_html=True)
        st.markdown('<p class="e3-section-sub">Rates for the selected period</p>',
                    unsafe_allow_html=True)
        r1, r2, r3 = st.columns(3)
        r1.metric("🔄 Sign-up → Upload", f"{su}%", "Activation")
        r2.metric("💰 Upload → Paid",    f"{up}%", "Monetisation")
        r3.metric("🎯 Sign-up → Paid",   f"{sp}%", "End-to-end")

        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)

        # ── Chart + Activity Feed ──
        col_chart, col_activity = st.columns([2, 1])
        with col_chart:
            st.markdown(
                f'<p class="e3-section-title">Daily Trend ({period.days} days)</p>',
                unsafe_allow_html=True,
            )
            try:
                import plotly.graph_objects as go
                from mongo_client import find_all as fa
                import pandas as pd

                rows = fa("daily_kpis",
                          filters={"date": {"$gte": period.start_iso(),
                                             "$lte": period.end_iso()}},
                          sort=[("date", 1)])
                if rows:
                    df = pd.DataFrame(rows)
                    df = df[df["date"].notna()].sort_values("date")
                    for col in ["signups", "first_uploads", "new_paid_customers"]:
                        if col not in df.columns:
                            df[col] = 0
                        df[col] = df[col].fillna(0).astype(int)

                    fig = go.Figure()
                    for key, label, color, fill in [
                        ("signups", "Sign-ups", "#9EFF2F", "rgba(158,255,47,0.10)"),
                        ("first_uploads", "Uploads",  "#5EF46A", "rgba(94,244,106,0.08)"),
                        ("new_paid_customers",    "Paid",     "#4ADE80", "rgba(74,222,128,0.06)"),
                    ]:
                        fig.add_trace(go.Scatter(
                            x=df["date"], y=df[key],
                            name=label, mode="lines",
                            line=dict(color=color, width=2.5, shape="spline"),
                            fill="tozeroy", fillcolor=fill,
                        ))
                    fig.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#9CA3AF", family="Inter"),
                        margin=dict(l=0, r=0, t=10, b=0),
                        height=340,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                    xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
                        xaxis=dict(gridcolor="rgba(255,255,255,0.04)",
                                   showline=False, zeroline=False),
                        yaxis=dict(gridcolor="rgba(255,255,255,0.04)",
                                   showline=False, zeroline=False),
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig, width='stretch')
                else:
                    empty_state("No trend data",
                                f"No daily KPI rows in {period.label}",
                                icon="📈")
            except Exception as e:
                st.info(f"Chart: {e}")

        with col_activity:
            if activity_events:
                activity_feed(activity_events, title="Recent Activity", max_show=10)
            else:
                empty_state("No recent activity",
                            "Events will appear here as they happen",
                            icon="🕰️")

        # ── Command palette hint (bottom right) ──
        st.markdown(
            '<div class="e3-cmd-hint">Press <kbd>?</kbd> for help</div>',
            unsafe_allow_html=True,
        )


# ─── Settings ────────────────────────────────────────────────────
def _render_settings(user_email: str) -> None:
    logo_hero = _logo_img(52, "main")
    st.markdown(
        f"""
        <div class="e3-fade-up" style="display:flex;align-items:center;gap:20px;">
          {f'<div style="width:52px;height:52px;">{logo_hero}</div>' if logo_hero else ''}
          <div>
            <h1 class="e3-hero-greeting">Settings</h1>
            <p class="e3-hero-sub">System status, access control & configuration.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)

    st.markdown("### 🗄️ Database Status")
    try:
        from mongo_client import get_mongo_status
        s = get_mongo_status()
        if s.get("connected"):
            st.success(
                f"✅ MongoDB connected — `{s.get('db')}` | "
                f"{s.get('collections', 0)} collections | "
                f"{s.get('daily_kpis_count', 0):,} daily KPI rows"
            )
        else:
            st.error(f"❌ MongoDB offline — {s.get('message', '')}")
    except Exception as e:
        st.error(f"MongoDB check failed: {e}")

    st.markdown("---")
    st.markdown("### 👥 Access Control")
    try:
        from access_control import list_users, add_email, remove_email
        users = list_users()
        if users:
            import pandas as pd
            df = pd.DataFrame(users)[["email", "role", "is_active", "added_at"]]
            st.dataframe(df, width='stretch')
        else:
            st.info("No users in allow-list.")

        with st.expander("➕ Add User"):
            with st.form("add_user"):
                em = st.text_input("Email")
                rl = st.selectbox("Role", ["viewer", "editor", "admin"])
                if st.form_submit_button("Add", type="primary"):
                    r = add_email(em, rl, added_by=user_email)
                    (st.success if r.get("success") else st.error)(r["message"])
                    if r.get("success"):
                        st.rerun()
    except Exception as e:
        st.error(f"Access control: {e}")

    st.markdown("---")
    st.markdown("### 📋 Recent Access Log")
    try:
        from access_control import get_access_logs
        import pandas as pd
        logs = get_access_logs(limit=20)
        if logs:
            df = pd.DataFrame(logs)[["timestamp", "email", "action",
                                      "success", "role", "ip"]]
            st.dataframe(df, width='stretch')
        else:
            st.info("No log entries.")
    except Exception as e:
        st.error(f"Logs: {e}")

    st.markdown("---")
    st.caption(f"Logged in as: **{user_email}**")
    if st.button("🚪 Logout", type="primary"):
        try:
            from auth_guard import logout
            logout()
        except Exception:
            for k in ("_pwd_ok", "_auth_ok", "user_email", "user_role"):
                st.session_state.pop(k, None)
        st.query_params.clear()
        st.rerun()


def _sync_period_from_url():
    """
    Three-layer persistence:
      1. MongoDB user_prefs (per-user, survives everything)
      2. URL query params (survives nav clicks)
      3. session_state (fast in-memory)
    """
    email = st.session_state.get("user_email", "")
    qp = st.query_params

    # LOAD from Mongo (first time this session)
    if email and "_period_loaded" not in st.session_state:
        try:
            from user_prefs import get_pref
            saved_preset = get_pref(email, "period_preset")
            saved_cmp    = get_pref(email, "period_compare")
            if saved_preset and saved_preset in PRESETS:
                st.session_state["period_preset"] = saved_preset
            if saved_cmp and saved_cmp in COMPARE_MODES:
                st.session_state["period_compare"] = saved_cmp
            st.session_state["_period_loaded"] = True
        except Exception:
            pass

    # URL overrides (nav click)
    url_preset = qp.get("prd", None)
    if url_preset and url_preset in PRESETS:
        if st.session_state.get("period_preset") != url_preset:
            st.session_state["period_preset"] = url_preset

    url_cmp = qp.get("cmp", None)
    if url_cmp and url_cmp in COMPARE_MODES:
        if st.session_state.get("period_compare") != url_cmp:
            st.session_state["period_compare"] = url_cmp

    # SAVE — push to URL + Mongo
    cur_preset  = st.session_state.get("period_preset", "This Month")
    cur_compare = st.session_state.get("period_compare", "Off")

    if qp.get("prd") != cur_preset:
        qp["prd"] = cur_preset
    if qp.get("cmp") != cur_compare:
        qp["cmp"] = cur_compare

    if email:
        try:
            from user_prefs import set_pref, get_pref
            if get_pref(email, "period_preset") != cur_preset:
                set_pref(email, "period_preset", cur_preset)
            if get_pref(email, "period_compare") != cur_compare:
                set_pref(email, "period_compare", cur_compare)
        except Exception:
            pass
# ─── Main ────────────────────────────────────────────────────────
def main() -> None:
    _inject_css()

    user_email, user_role = _require_auth()

    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "dashboard"

    current_page = _get_current_page()

    # Render chrome (topbar + sidebar + JS toggle in one call)
    _render_chrome(current_page, user_email)

    # Spacer for fixed navbar (72px + breathing room)
    st.markdown("<div style='height:92px;'></div>", unsafe_allow_html=True)

    # Main content wrapper
    st.markdown("<div style='padding:0 36px 40px 36px;'>", unsafe_allow_html=True)

    # Period picker — Streamlit popover wrapped in a source marker.
    # JavaScript will physically MOVE this into #e3-period-mount in the topbar.
    st.markdown('<div class="e3-period-source"></div>', unsafe_allow_html=True)
    with st.popover(f"📅 {get_period_button_label()}", width='content'):
        render_period_picker(key_prefix="navbar_period")
    st.markdown('<div class="e3-period-source-end"></div>', unsafe_allow_html=True)

    # ─── JS: physically move the period popover into the topbar mount point ───
    components.html(
        """
        <script>
        (function() {
            const doc = window.parent.document;

            function findAndMove() {
                const mount = doc.getElementById('e3-period-mount');
                if (!mount) { return false; }

                // Already moved?
                if (mount.querySelector('[data-testid="stPopover"]')) {
                    return true;
                }

                // Find the .e3-period-source marker in the body
                const source = doc.querySelector('.e3-period-source');
                if (!source) { return false; }

                // Walk up to the parent stElementContainer, then find the
                // NEXT sibling element that contains the popover.
                let container = source.closest('[data-testid="element-container"]');
                if (!container) { return false; }

                // The popover is in the next sibling element-container
                let sibling = container.nextElementSibling;
                let popoverContainer = null;
                let hops = 0;
                while (sibling && hops < 5) {
                    const pop = sibling.querySelector('[data-testid="stPopover"]');
                    if (pop) {
                        popoverContainer = sibling;
                        break;
                    }
                    sibling = sibling.nextElementSibling;
                    hops++;
                }

                if (!popoverContainer) { return false; }

                // Move the WHOLE element-container that holds the popover into mount
                mount.appendChild(popoverContainer);

                // Style overrides applied via CSS (.e3-period-mount ...)
                return true;
            }

            // Try immediately
            if (findAndMove()) return;

            // Otherwise poll (Streamlit renders async) + watch for mutations
            let attempts = 0;
            const interval = setInterval(() => {
                attempts++;
                if (findAndMove() || attempts > 60) {
                    clearInterval(interval);
                }
            }, 150);

            // Also observe for re-renders (Streamlit rerun rebuilds DOM)
            const observer = new MutationObserver(() => {
                findAndMove();
            });
            observer.observe(doc.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        height=0, width=0,
    )


    route(current_page, user_email)
    st.markdown("</div>", unsafe_allow_html=True)


# --- runtime-safe aliases for dashboard/router ---
try:
    route
except NameError:
    try:
        route = _route
    except NameError:
        pass

try:
    render_dashboard
except NameError:
    try:
        render_dashboard = _render_dashboard
    except NameError:
        try:
            render_dashboard = render_dashboard_preview
        except NameError:
            pass


main()
