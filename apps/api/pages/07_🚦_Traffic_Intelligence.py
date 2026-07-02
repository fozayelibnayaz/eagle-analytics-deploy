"""
Eagle 3D Eagle Analytics Hub Hub v4.0
========================================
COMPLETE REBUILD with fixes:
  - FIXED: Date filtering now actually changes GA4 data (removed stale caching)
  - FIXED: Direct GA4 API calls per date range with proper cache invalidation
  - 14 tabs of GA4 analytics with deep analysis
  - Source dedup, UTM tracking, CRM linking, AI Q&A
  - User engagement, content analysis, landing pages, first-touch attribution
  - Hourly patterns, geo deep-dive, device/tech analysis
  - Retention analysis, conversion paths, referral tracking
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys, os, hashlib

# Theme detection
IS_DARK = st.session_state.get("theme_mode", "dark") == "dark"

# ── Page config ──────────────────────────────────────────────
try:
    st.set_page_config(
        page_title="Eagle Analytics Hub | Eagle 3D",
        page_icon="🚦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
except Exception:
    pass

# ── Theme helpers ─────────────────────────────────────────────
TH = {"paper_bgcolor": "#0A1628", "plot_bgcolor": "#0A1628", "font_color": "#a0b4cc"}
CHART_CFG = {"responsive": True}

try:
    from ga4_responsive_css import get_responsive_css, get_chart_config, get_chart_theme
    st.markdown(get_responsive_css(), unsafe_allow_html=True)
    TH = get_chart_theme()
    CHART_CFG = get_chart_config()
except ImportError:
    pass

# ── Module loading ────────────────────────────────────────────
MOD = {}

try:
    from ga4_connector import (
        fetch_utm_traffic, fetch_daily_traffic_summary,
        fetch_page_performance, fetch_event_performance,
        fetch_geo_traffic, fetch_device_traffic,
        fetch_signup_source_correlation, fetch_event_attribution,
        fetch_event_attribution_extended, fetch_available_events,
        # NEW extended functions
        fetch_landing_pages, fetch_user_engagement,
        fetch_content_analysis, fetch_source_medium_deep,
        fetch_geo_deep, fetch_device_deep,
        fetch_first_user_source, fetch_conversion_paths,
        fetch_hourly_pattern, fetch_retention_cohort,
        fetch_browser_tech, fetch_referral_paths,
    )
    MOD["ga4"] = True
except ImportError as e:
    MOD["ga4"] = False
    MOD["ga4_err"] = str(e)

try:
    from kpi_bridge import (
        fetch_daily_kpis, fetch_signup_details,
        calculate_funnel_metrics, attribute_signups_by_lead_source,
    )
    MOD["kpi"] = True
except ImportError as e:
    MOD["kpi"] = False
    MOD["kpi_err"] = str(e)

try:
    from ga4_source_intel import classify_source, classify_dataframe, filter_real_visitors
    MOD["source_intel"] = True
except ImportError:
    MOD["source_intel"] = False

try:
    from source_normalizer import normalize_source, normalize_dataframe_sources
    MOD["source_norm"] = True
except ImportError:
    MOD["source_norm"] = False

try:
    from ga4_smart_qa import answer_free_text_question
    MOD["qa"] = True
except ImportError as e:
    MOD["qa"] = False
    MOD["qa_err"] = str(e)

try:
    from ga4_strategic import get_all_strategic_questions, answer_question
    MOD["strat"] = True
except ImportError:
    MOD["strat"] = False

try:
    from ga4_notifications import (
        detect_page_anomalies, detect_event_anomalies,
        detect_source_anomalies, detect_conversion_anomalies,
        build_notification_summary,
    )
    MOD["notif"] = True
except ImportError:
    MOD["notif"] = False

try:
    from ga4_intelligence import generate_traffic_analysis, generate_daily_notification
    MOD["intel"] = True
except ImportError:
    MOD["intel"] = False


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _fmt(n):
    """Format number with commas."""
    try:
        if pd.isna(n) or n == 0:
            return "0"
        return f"{int(n):,}"
    except Exception:
        return str(n)

def _pct(new, old):
    """Compute percentage change."""
    try:
        if old == 0 or pd.isna(old):
            return 0.0
        return round((new - old) / old * 100, 1)
    except Exception:
        return 0.0

def _safe_sum(df, col):
    """Safe column sum."""
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").sum())

def _safe_mean(df, col):
    """Safe column mean."""
    if df is None or df.empty or col not in df.columns:
        return 0.0
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    return float(vals.mean()) if len(vals) > 0 else 0.0

def _delta_html(pct):
    """HTML delta badge."""
    if pct > 0:
        return f'<span style="color:#00E676;font-weight:600;">▲ {pct:+.1f}%</span>'
    elif pct < 0:
        return f'<span style="color:#FF5252;font-weight:600;">▼ {abs(pct):.1f}%</span>'
    c = "#5B6B85" if IS_DARK else "#64748B"
    return f'<span style="color:{c};">→ flat</span>'

def _kpi_card(title, value, delta="", color="#00D4FF"):
    """HTML KPI card — theme-aware."""
    _bg = "#111D32" if IS_DARK else "#FFFFFF"
    _border = "#1B3054" if IS_DARK else "#CBD5E1"
    _lbl = "#5B6B85" if IS_DARK else "#64748B"
    _val_color = color if IS_DARK else "#0077B6"
    return f"""<div style="background:{_bg};border:1px solid {_border};border-radius:12px;padding:16px;text-align:center;min-width:120px;">
        <div style="font-size:0.75rem;color:{_lbl};text-transform:uppercase;letter-spacing:0.5px;">{title}</div>
        <div style="font-size:1.6rem;font-weight:800;color:{_val_color};margin:4px 0;">{value}</div>
        {f'<div style="font-size:0.8rem;">{delta}</div>' if delta else ''}
    </div>"""


# ══════════════════════════════════════════════════════════════
# DATE RANGE SYSTEM
# ══════════════════════════════════════════════════════════════

DATE_PRESETS = [
    "Yesterday", "Last 7 Days", "Last 14 Days", "Last 28 Days",
    "Last 30 Days", "Last 90 Days", "Last 3 Months", "Last 6 Months",
    "Last 12 Months", "This Month", "Last Month", "This Year",
    "Last Year", "Custom Range",
]

def compute_date_range(opt, custom_start=None, custom_end=None):
    today = datetime.now()
    yd = today - timedelta(days=1)

    presets = {
        "Yesterday":      (yd, yd),
        "Last 7 Days":    (today - timedelta(days=7), yd),
        "Last 14 Days":   (today - timedelta(days=14), yd),
        "Last 28 Days":   (today - timedelta(days=28), yd),
        "Last 30 Days":   (today - timedelta(days=30), yd),
        "Last 90 Days":   (today - timedelta(days=90), yd),
        "Last 3 Months":  (today - timedelta(days=90), yd),
        "Last 6 Months":  (today - timedelta(days=180), yd),
        "Last 12 Months": (today - timedelta(days=365), yd),
        "This Month":     (today.replace(day=1), yd),
        "This Year":      (today.replace(month=1, day=1), yd),
    }

    if opt == "Last Month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        presets["Last Month"] = (last_prev.replace(day=1), last_prev)

    if opt == "Last Year":
        ly = today.year - 1
        presets["Last Year"] = (datetime(ly, 1, 1), datetime(ly, 12, 31))

    if opt == "Custom Range" and custom_start and custom_end:
        s, e = custom_start, custom_end
    else:
        s, e = presets.get(opt, presets["Last 28 Days"])

    return s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")

def prev_period(s, e):
    sd = datetime.strptime(s, "%Y-%m-%d")
    ed = datetime.strptime(e, "%Y-%m-%d")
    d = (ed - sd).days + 1
    pe = sd - timedelta(days=1)
    ps = pe - timedelta(days=d - 1)
    return ps.strftime("%Y-%m-%d"), pe.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
# DATA LOADING — KEY FIX: cache includes date hash for proper invalidation
# ══════════════════════════════════════════════════════════════

def _ga(func_name, s, e):
    """Call a GA4 fetch function. No stale caching — always fresh for unique dates."""
    if not MOD["ga4"]:
        return pd.DataFrame()
    try:
        func = globals().get(func_name)
        if func is None:
            # Import from ga4_connector
            import ga4_connector
            func = getattr(ga4_connector, func_name, None)
        if func:
            return func(s, e)
    except Exception as ex:
        print(f"GA4 {func_name} error: {ex}")
    return pd.DataFrame()


@st.cache_data(ttl=600, show_spinner=False, max_entries=20)
def _cached_ga(func_name, s, e, _hash):
    """Cached GA4 call — _hash ensures proper invalidation."""
    return _ga(func_name, s, e)


def _load(func_name, s, e, use_cache=True):
    """Smart data loader with short TTL cache."""
    if use_cache:
        h = hashlib.md5(f"{func_name}:{s}:{e}".encode()).hexdigest()[:8]
        return _cached_ga(func_name, s, e, h)
    return _ga(func_name, s, e)


def normalize_sources(df):
    """Apply source normalization if available."""
    if df is None or df.empty or not MOD["source_norm"]:
        return df
    if "sessionSource" not in df.columns:
        return df
    df = df.copy()
    normalized, categories = [], []
    for src in df["sessionSource"]:
        canon, cat = normalize_source(str(src))
        normalized.append(canon)
        categories.append(cat)
    df["source_normalized"] = normalized
    df["source_category"] = categories
    return df


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    st.markdown("""
    <div style="border-bottom:2px solid #1B3054;padding-bottom:10px;margin-bottom:16px;">
        <h2 style="color:#00D4FF;margin:0;">🚦 Eagle Analytics Hub Hub</h2>
        <p style="color:#5B6B85;margin:4px 0 0 0;font-size:0.85rem;">
            GA4 Deep Analytics · UTM Tracking · Source Attribution · AI Insights · 14 Analysis Views
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not MOD["ga4"]:
        st.error(f"⚠️ GA4 module not available: `{MOD.get('ga4_err', 'unknown')}`")
        st.info("Check that `ga4_connector.py` exists and GA4 credentials are in Streamlit secrets.")
        return

    # ── Date Range ────────────────────────────────────────────
    _parent_start = st.session_state.get("ti_start")
    _parent_end = st.session_state.get("ti_end")
    _use_parent = bool(_parent_start and _parent_end)

    if _use_parent:
        s_str, e_str = _parent_start, _parent_end
    else:
        with st.sidebar:
            st.markdown("### 🚦 Date Range")
            date_opt = st.selectbox("📅 Period", DATE_PRESETS, index=3, key="ti_date_opt")
            custom_s = custom_e = None
            if date_opt == "Custom Range":
                c1, c2 = st.columns(2)
                with c1:
                    custom_s = st.date_input("Start", datetime.now().date() - timedelta(days=30))
                with c2:
                    custom_e = st.date_input("End", datetime.now().date())
            s_str, e_str = compute_date_range(date_opt, custom_s, custom_e)

    ps_str, pe_str = prev_period(s_str, e_str)

    # Show active date range prominently
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0A1628,#111D32);border:1px solid #1B3054;
                border-radius:12px;padding:14px 20px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;">
        <div>
            <span style="color:#5B6B85;font-size:0.85rem;">📅 Current Period</span><br>
            <span style="color:#00D4FF;font-weight:700;font-size:1.1rem;">{s_str} → {e_str}</span>
        </div>
        <div style="text-align:right;">
            <span style="color:#5B6B85;font-size:0.85rem;">🔄 Compare To</span><br>
            <span style="color:#6C5CE7;font-weight:600;font-size:0.95rem;">{ps_str} → {pe_str}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Load Data ─────────────────────────────────────────────
    with st.spinner("Loading GA4 data..."):
        # Core data — current period
        utm = normalize_sources(_load("fetch_utm_traffic", s_str, e_str))
        p_utm = normalize_sources(_load("fetch_utm_traffic", ps_str, pe_str))
        daily = _load("fetch_daily_traffic_summary", s_str, e_str)
        p_daily = _load("fetch_daily_traffic_summary", ps_str, pe_str)
        pages = _load("fetch_page_performance", s_str, e_str)
        p_pages = _load("fetch_page_performance", ps_str, pe_str)
        events = _load("fetch_event_performance", s_str, e_str)
        p_events = _load("fetch_event_performance", ps_str, pe_str)
        geo = _load("fetch_geo_traffic", s_str, e_str)
        dev = _load("fetch_device_traffic", s_str, e_str)
        kpi = _load("fetch_daily_kpis", s_str, e_str) if MOD["kpi"] else pd.DataFrame()
        p_kpi = _load("fetch_daily_kpis", ps_str, pe_str) if MOD["kpi"] else pd.DataFrame()
        leads = _load("fetch_signup_source_correlation", s_str, e_str)

        # Extended data — loaded on demand per tab (lighter cache)
        engagement = _load("fetch_user_engagement", s_str, e_str)
        p_engagement = _load("fetch_user_engagement", ps_str, pe_str)
        source_deep = _load("fetch_source_medium_deep", s_str, e_str)
        p_source_deep = _load("fetch_source_medium_deep", ps_str, pe_str)
        first_touch = _load("fetch_first_user_source", s_str, e_str)
        conv_paths = _load("fetch_conversion_paths", s_str, e_str)
        landing = _load("fetch_landing_pages", s_str, e_str)
        content = _load("fetch_content_analysis", s_str, e_str)
        hourly = _load("fetch_hourly_pattern", s_str, e_str)
        retention = _load("fetch_retention_cohort", s_str, e_str)
        geo_deep = _load("fetch_geo_deep", s_str, e_str)
        device_deep = _load("fetch_device_deep", s_str, e_str)
        referrals = _load("fetch_referral_paths", s_str, e_str)

    # ── Debug info (collapsible) ──────────────────────────────
    with st.expander("🔧 Data Loading Status", expanded=False):
        data_status = {
            "UTM Traffic": utm.shape, "Daily Summary": daily.shape,
            "Pages": pages.shape, "Events": events.shape,
            "Geo": geo.shape, "Devices": dev.shape,
            "KPI (Sheets)": kpi.shape, "Leads": leads.shape,
            "Engagement": engagement.shape, "Source Deep": source_deep.shape,
            "First Touch": first_touch.shape, "Conversion Paths": conv_paths.shape,
            "Landing Pages": landing.shape, "Content": content.shape,
            "Hourly": hourly.shape, "Retention": retention.shape,
            "Geo Deep": geo_deep.shape, "Device Deep": device_deep.shape,
            "Referrals": referrals.shape,
        }
        for name, shape in data_status.items():
            icon = "✅" if shape[0] > 0 else "⚠️"
            st.caption(f"{icon} **{name}**: {shape[0]} rows × {shape[1]} cols")
        st.caption(f"📅 Date range: {s_str} → {e_str}")
        st.caption(f"🔄 Comparison: {ps_str} → {pe_str}")
        st.caption(f"📦 Modules: " + " | ".join(f"{'✅' if v else '❌'} {k}" for k, v in MOD.items() if not k.endswith("_err")))

    # ══════════════════════════════════════════════════════════
    # OVERVIEW KPI CARDS
    # ══════════════════════════════════════════════════════════
    sess = _safe_sum(utm, "sessions") or _safe_sum(utm, "totalUsers")
    users = _safe_sum(utm, "totalUsers")
    new_users = _safe_sum(utm, "newUsers")
    conv = _safe_sum(utm, "conversions")
    eng_rate = _safe_mean(utm, "bounceRate")
    avg_dur = _safe_mean(utm, "averageSessionDuration")

    p_sess = _safe_sum(p_utm, "sessions") or _safe_sum(p_utm, "totalUsers")
    p_users = _safe_sum(p_utm, "totalUsers")
    p_conv = _safe_sum(p_utm, "conversions")

    funnel = {}
    if MOD["kpi"] and kpi is not None and not kpi.empty:
        funnel = calculate_funnel_metrics(kpi)

    signups = funnel.get("signups", 0)
    uploads = funnel.get("uploads", 0)
    paid = funnel.get("paid", 0)
    cr = (conv / sess * 100) if sess > 0 else 0
    p_cr = (p_conv / p_sess * 100) if p_sess > 0 else 0

    st.markdown("### 📊 Overview")
    cols = st.columns(8)
    cards = [
        ("Sessions", _fmt(sess), _delta_html(_pct(sess, p_sess))),
        ("Users", _fmt(users), _delta_html(_pct(users, p_users))),
        ("New Users", _fmt(new_users), ""),
        ("Conversions", _fmt(conv), _delta_html(_pct(conv, p_conv))),
        ("Conv Rate", f"{cr:.2f}%", f'<span style="color:#FFD600;">{(cr-p_cr):+.2f}pp</span>'),
        ("Sign-ups", str(signups), ""),
        ("Avg Duration", f"{avg_dur:.0f}s", ""),
        ("Bounce Rate", f"{(100-eng_rate):.1f}%", ""),
    ]
    for i, (title, val, delta) in enumerate(cards):
        with cols[i % 8]:
            st.markdown(_kpi_card(title, val, delta), unsafe_allow_html=True)

    st.markdown("---")

    # ══════════════════════════════════════════════════════════
    # TABS — 14 analysis views
    # ══════════════════════════════════════════════════════════
    tabs = st.tabs([
        "🌐 Sources",           # 0
        "📄 Pages",             # 1
        "⚡ Events",            # 2
        "🗺️ Geo",              # 3
        "🎯 Leads",             # 4
        "📊 Funnel",            # 5
        "🔔 Alerts",            # 6
        "🤖 AI",                # 7
        "💡 Q&A",               # 8
        "📉 Engagement",        # 9
        "🏠 Landing Pages",     # 10
        "🔄 Attribution",       # 11
        "⏰ Patterns",          # 12
        "🖥️ Tech & Devices",    # 13
    ])

    with tabs[0]:  _tab_sources(utm, p_utm, source_deep, p_source_deep)
    with tabs[1]:  _tab_pages(pages, p_pages, content)
    with tabs[2]:  _tab_events(events, p_events, conv_paths)
    with tabs[3]:  _tab_geo(geo, geo_deep, dev)
    with tabs[4]:  _tab_leads(leads, kpi)
    with tabs[5]:  _tab_funnel(kpi, utm, funnel, engagement)
    with tabs[6]:  _tab_alerts(pages, p_pages, events, p_events, utm, p_utm, daily, p_daily)
    with tabs[7]:  _tab_ai(utm, pages, events, daily, kpi)
    with tabs[8]:  _tab_qa(utm, pages, events, kpi, p_kpi, leads, geo_deep, device_deep)
    with tabs[9]:  _tab_engagement(engagement, p_engagement)
    with tabs[10]: _tab_landing(landing, referrals)
    with tabs[11]: _tab_attribution(first_touch, source_deep, leads)
    with tabs[12]: _tab_patterns(hourly, daily, retention)
    with tabs[13]: _tab_tech(device_deep, dev)


# ══════════════════════════════════════════════════════════════
# TAB 0: 🌐 SOURCES
# ══════════════════════════════════════════════════════════════

def _tab_sources(utm, p_utm, source_deep, p_source_deep):
    st.markdown("### 🌐 Traffic Sources")
    if utm.empty:
        st.info("No source data for this period")
        return

    src_col = "source_normalized" if "source_normalized" in utm.columns else "sessionSource"
    sessions_col = "sessions" if "sessions" in utm.columns else src_col

    # Aggregate by source
    by_src = utm.groupby(src_col).agg(
        Sessions=(sessions_col, "sum"),
    ).reset_index().sort_values("Sessions", ascending=False)

    if "conversions" in utm.columns:
        conv_agg = utm.groupby(src_col)["conversions"].sum().reset_index()
        by_src = by_src.merge(conv_agg, on=src_col, how="left")
        by_src["Conv_%"] = (by_src["conversions"] / by_src["Sessions"].replace(0, 1) * 100).round(2)

    if "totalUsers" in utm.columns:
        users_agg = utm.groupby(src_col)["totalUsers"].sum().reset_index()
        by_src = by_src.merge(users_agg, on=src_col, how="left")

    total = by_src["Sessions"].sum()
    by_src["Share_%"] = (by_src["Sessions"] / total * 100).round(1)

    # Source category cards
    if "source_category" in utm.columns:
        cats = utm.groupby("source_category").agg(Sessions=(sessions_col, "sum")).reset_index()
        cats = cats.sort_values("Sessions", ascending=False)
        cat_colors = {
            "search": "#00D4FF", "social": "#6C5CE7", "ai": "#B388FF",
            "referral": "#FF9100", "direct": "#5B6B85", "community": "#00E676",
            "email": "#FFD600", "messaging": "#FF5252", "unknown": "#94A3B1",
        }
        cat_cols = st.columns(min(len(cats), 8))
        for i, (_, row) in enumerate(cats.iterrows()):
            with cat_cols[i % len(cat_cols)]:
                color = cat_colors.get(str(row["source_category"]), "#94A3C1")
                share = row["Sessions"] / total * 100 if total > 0 else 0
                st.markdown(f"""
                <div style="background:#111D32;border:1px solid #1B3054;border-radius:10px;padding:10px;text-align:center;">
                    <div style="font-size:0.7rem;color:#5B6B85;text-transform:uppercase;">{row["source_category"]}</div>
                    <div style="font-size:1.2rem;font-weight:700;color:{color};">{share:.0f}%</div>
                    <div style="font-size:0.7rem;color:#94A3C1;">{int(row["Sessions"]):,} sessions</div>
                </div>
                """, unsafe_allow_html=True)

    # Comparison with previous period
    if not p_utm.empty:
        p_src_col = "source_normalized" if "source_normalized" in p_utm.columns else "sessionSource"
        p_by = p_utm.groupby(p_src_col)[sessions_col].sum().reset_index()
        p_by.columns = [src_col, "Prev_Sessions"]
        by_src = by_src.merge(p_by, on=src_col, how="left")
        by_src["Prev_Sessions"] = by_src["Prev_Sessions"].fillna(0)
        by_src["Change_%"] = ((_safe_sum(by_src, "Sessions") - by_src["Prev_Sessions"]) / by_src["Prev_Sessions"].replace(0, 1) * 100).round(1)

    # Chart
    chart_col = "Conv_%" if "Conv_%" in by_src.columns else None
    fig = px.bar(
        by_src.head(20), x="Sessions", y=src_col, orientation="h",
        color=chart_col,
        color_continuous_scale="RdYlGn" if chart_col else None,
        color_discrete_sequence=["#00D4FF"] if not chart_col else None,
    )
    fig.update_layout(height=max(400, len(by_src.head(20)) * 28), **TH, margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

    # Source + Medium Deep Dive
    st.markdown("#### 🔍 Source × Medium Breakdown")
    if not source_deep.empty:
        sd = source_deep.copy()
        if "sessions" in sd.columns:
            sd["sessions"] = pd.to_numeric(sd["sessions"], errors="coerce")
            sd = sd.sort_values("sessions", ascending=False)
            # Add comparison
            if not p_source_deep.empty:
                psd = p_source_deep.copy()
                psd["sessions"] = pd.to_numeric(psd["sessions"], errors="coerce")
                # Merge on source+medium
                merge_cols = [c for c in ["sessionSource", "sessionMedium"] if c in sd.columns and c in psd.columns]
                if merge_cols:
                    psd_agg = psd.groupby(merge_cols)["sessions"].sum().reset_index()
                    psd_agg.columns = merge_cols + ["Prev_Sessions"]
                    sd = sd.merge(psd_agg, on=merge_cols, how="left")
                    sd["Prev_Sessions"] = sd["Prev_Sessions"].fillna(0)
                    sd["Δ%"] = ((sd["sessions"] - sd["Prev_Sessions"]) / sd["Prev_Sessions"].replace(0, 1) * 100).round(1)
        show_cols = [c for c in sd.columns if c not in ["sessionCampaignName"] and c in sd.columns]
        st.dataframe(sd[show_cols].head(50), use_container_width=True, height=400, hide_index=True)

    # Full source table
    st.markdown("#### 📋 All Sources")
    st.dataframe(by_src, use_container_width=True, height=350, hide_index=True)


# ══════════════════════════════════════════════════════════════
# TAB 1: 📄 PAGES
# ══════════════════════════════════════════════════════════════

def _tab_pages(pages, p_pages, content):
    st.markdown("### 📄 Page Performance")
    if pages.empty and content.empty:
        st.info("No page data for this period")
        return

    # Use content_analysis for richer data if available, fall back to pages
    if not content.empty:
        df = content.copy()
        for col in ["screenPageViews", "uniqueScreenPageViews", "totalUsers", "conversions", "eventCount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "screenPageViews" in df.columns:
            df = df.sort_values("screenPageViews", ascending=False)

        # Add engagement metrics
        if "engagementRate" in df.columns:
            df["Engagement_%"] = (pd.to_numeric(df["engagementRate"], errors="coerce") * 100).round(1)
        if "averageSessionDuration" in df.columns:
            df["Avg_Time_s"] = pd.to_numeric(df["averageSessionDuration"], errors="coerce").round(1)
        if all(c in df.columns for c in ["conversions", "totalUsers"]):
            df["Conv_%"] = (df["conversions"] / df["totalUsers"].replace(0, 1) * 100).round(2)

        # Comparison
        if not p_pages.empty:
            pp = p_pages.copy()
            if "screenPageViews" in pp.columns:
                pp["screenPageViews"] = pd.to_numeric(pp["screenPageViews"], errors="coerce")
                pp_agg = pp.groupby("pagePath")["screenPageViews"].sum().reset_index()
                pp_agg.columns = ["pagePath", "Prev_Views"]
                df = df.merge(pp_agg, on="pagePath", how="left")

        # Top pages chart
        top = df.head(20)
        if "screenPageViews" in top.columns:
            fig = px.bar(top, x="screenPageViews", y="pagePath", orientation="h",
                         color="Conv_%" if "Conv_%" in top.columns else "engagementRate" if "engagementRate" in top.columns else None,
                         color_continuous_scale="RdYlGn")
            fig.update_layout(height=max(500, len(top) * 25), **TH, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

        show_cols = [c for c in ["pagePath", "pageTitle", "screenPageViews", "uniqueScreenPageViews",
                                  "totalUsers", "Conv_%", "Engagement_%", "Avg_Time_s", "bounceRate", "Prev_Views"]
                     if c in df.columns]
        st.dataframe(df[show_cols].head(50), use_container_width=True, height=400, hide_index=True)

    elif not pages.empty:
        # Fallback to pages data
        top = pages.groupby("pagePath").agg(
            Views=("screenPageViews", "sum"), Sessions=("sessions", "sum"),
            Conversions=("conversions", "sum"),
        ).reset_index().sort_values("Views", ascending=False)
        top["Conv_%"] = ((top["Conversions"] / top["Sessions"].replace(0, 1)) * 100).round(2)

        fig = px.bar(top.head(20), x="Views", y="pagePath", orientation="h",
                     color="Conv_%", color_continuous_scale="RdYlGn")
        fig.update_layout(height=500, **TH, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
        st.dataframe(top.head(50), use_container_width=True, height=400)


# ══════════════════════════════════════════════════════════════
# TAB 2: ⚡ EVENTS
# ══════════════════════════════════════════════════════════════

def _tab_events(events, p_events, conv_paths):
    st.markdown("### ⚡ Events Analysis")
    if events.empty:
        st.info("No event data for this period")
        return

    signals = ["sign_up", "signup", "form_submit", "purchase", "trial", "register", "convert"]

    # Event summary
    agg = events.groupby("eventName").agg(
        Count=("eventCount", "sum"), Conversions=("conversions", "sum"),
        Users=("totalUsers", "sum") if "totalUsers" in events.columns else ("eventCount", "count"),
    ).reset_index().sort_values("Count", ascending=False)
    agg["Signal"] = agg["eventName"].apply(
        lambda e: "🎯" if any(s in str(e).lower() for s in signals) else "—"
    )

    # Comparison
    if not p_events.empty:
        p_agg = p_events.groupby("eventName")["eventCount"].sum().reset_index()
        p_agg.columns = ["eventName", "Prev_Count"]
        agg = agg.merge(p_agg, on="eventName", how="left")
        agg["Prev_Count"] = agg["Prev_Count"].fillna(0)
        agg["Δ%"] = ((agg["Count"] - agg["Prev_Count"]) / agg["Prev_Count"].replace(0, 1) * 100).round(1)

    fig = px.bar(agg.head(25), x="Count", y="eventName", orientation="h",
                 color="Conversions", color_continuous_scale="Viridis")
    fig.update_layout(height=max(500, len(agg.head(25)) * 25), **TH, margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
    st.dataframe(agg, use_container_width=True, height=350, hide_index=True)

    # Conversion Paths (which events + sources drive conversions)
    if not conv_paths.empty:
        st.markdown("#### 🎯 Conversion Event Paths")
        st.caption("Which events from which sources drive conversions")
        cp = conv_paths.copy()
        for col in ["eventCount", "conversions"]:
            if col in cp.columns:
                cp[col] = pd.to_numeric(cp[col], errors="coerce")
        cp = cp.sort_values("conversions", ascending=False) if "conversions" in cp.columns else cp
        show = [c for c in ["eventName", "sessionSource", "sessionMedium", "pagePath", "eventCount", "conversions"] if c in cp.columns]
        st.dataframe(cp[show].head(50), use_container_width=True, height=350, hide_index=True)


# ══════════════════════════════════════════════════════════════
# TAB 3: 🗺️ GEO
# ══════════════════════════════════════════════════════════════

def _tab_geo(geo, geo_deep, dev):
    st.markdown("### 🗺️ Geography & Devices")
    
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("#### 🌍 Countries")
        if not geo.empty:
            country = geo.groupby("country").agg(
                Sessions=("sessions", "sum"),
            ).reset_index().sort_values("Sessions", ascending=False)
            if "conversions" in geo.columns:
                conv_c = geo.groupby("country")["conversions"].sum().reset_index()
                country = country.merge(conv_c, on="country", how="left")
                country["Conv_%"] = (country["conversions"] / country["Sessions"].replace(0, 1) * 100).round(2)

            fig = px.choropleth(country, locations="country", locationmode="country names",
                                color="Sessions", color_continuous_scale="Blues",
                                hover_data=["Sessions", "Conv_%"] if "Conv_%" in country.columns else ["Sessions"])
            fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
            st.dataframe(country.head(20), use_container_width=True, height=300, hide_index=True)
        else:
            st.info("No geo data")

        # Geo Deep Dive
        if not geo_deep.empty:
            st.markdown("#### 🏙️ Top Cities")
            gd = geo_deep.copy()
            for col in ["sessions", "totalUsers", "newUsers", "conversions"]:
                if col in gd.columns:
                    gd[col] = pd.to_numeric(gd[col], errors="coerce")
            city = gd.groupby(["country", "city"]).agg(
                Sessions=("sessions", "sum"),
                Users=("totalUsers", "sum"),
                Convs=("conversions", "sum"),
            ).reset_index().sort_values("Sessions", ascending=False)
            city["Conv_%"] = (city["Convs"] / city["Sessions"].replace(0, 1) * 100).round(2)
            st.dataframe(city.head(30), use_container_width=True, height=350, hide_index=True)

    with c2:
        st.markdown("#### 📱 Devices")
        if not dev.empty:
            dc = dev.groupby("deviceCategory")["sessions"].sum().reset_index()
            dc["sessions"] = pd.to_numeric(dc["sessions"], errors="coerce")
            fig = px.pie(dc, names="deviceCategory", values="sessions", hole=0.45,
                         color_discrete_sequence=["#00D4FF", "#6C5CE7", "#FFD600", "#00E676"])
            fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

            # OS breakdown
            if "operatingSystem" in dev.columns:
                os_data = dev.groupby("operatingSystem")["sessions"].sum().reset_index()
                os_data["sessions"] = pd.to_numeric(os_data["sessions"], errors="coerce")
                os_data = os_data.sort_values("sessions", ascending=False).head(10)
                fig2 = px.bar(os_data, x="sessions", y="operatingSystem", orientation="h",
                              color_discrete_sequence=["#6C5CE7"])
                fig2.update_layout(height=300, **TH, margin=dict(l=0, r=0, t=20, b=0))
                st.plotly_chart(fig2, use_container_width=True, config=CHART_CFG)


# ══════════════════════════════════════════════════════════════
# TAB 4: 🎯 LEADS
# ══════════════════════════════════════════════════════════════

def _tab_leads(leads, kpi):
    st.markdown("### 🎯 Lead Sources & Sign-up Attribution")

    if leads is not None and not leads.empty:
        st.markdown("#### GA4 Conversion Attribution")
        # Show raw data
        show_cols = [c for c in leads.columns if c in leads.columns]
        st.dataframe(leads[show_cols].head(50), use_container_width=True, height=350, hide_index=True)

        # Source-level aggregation
        if "sessionSource" in leads.columns and "conversions" in leads.columns:
            src_leads = leads.groupby("sessionSource").agg(
                Conversions=("conversions", "sum"),
                Users=("totalUsers", "sum") if "totalUsers" in leads.columns else ("conversions", "count"),
            ).reset_index().sort_values("Conversions", ascending=False)
            fig = px.pie(src_leads.head(10), values="Conversions", names="sessionSource", hole=0.5,
                         color_discrete_sequence=["#00D4FF", "#6C5CE7", "#00E676", "#FFD600", "#FF5252", "#B388FF"])
            fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=0, b=0), showlegend=True)
            st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

    # KPI bridge leads
    if MOD["kpi"]:
        try:
            # Get dates from session_state or default to last 90 days
            _s = st.session_state.get("ti_start", (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
            _e = st.session_state.get("ti_end", datetime.now().strftime("%Y-%m-%d"))
            kpi_leads = attribute_signups_by_lead_source(_s, _e)
            if kpi_leads is not None and not kpi_leads.empty:
                st.markdown("#### 📋 CRM Lead Sources (from KPI Bridge)")
                st.dataframe(kpi_leads, use_container_width=True, height=300, hide_index=True)
                if "Signups" in kpi_leads.columns:
                    fig = px.pie(kpi_leads.head(10), values="Signups", names="Lead Source", hole=0.5,
                                 color_discrete_sequence=["#00D4FF", "#6C5CE7", "#00E676", "#FFD600", "#FF5252"])
                    fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=0, b=0), showlegend=True)
                    st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
        except Exception:
            pass

    if (leads is None or leads.empty) and (kpi is None or kpi.empty):
        st.info("No lead data for this period")


# ══════════════════════════════════════════════════════════════
# TAB 5: 📊 FUNNEL
# ══════════════════════════════════════════════════════════════

def _tab_funnel(kpi, utm, funnel, engagement):
    st.markdown("### 📊 Conversion Funnel")

    if not funnel and (kpi is None or kpi.empty):
        st.info("No funnel data available")
        return

    sess = _safe_sum(utm, "sessions") or _safe_sum(utm, "totalUsers")
    signups = funnel.get("signups", 0)
    uploads = funnel.get("uploads", 0)
    paid = funnel.get("paid", 0)

    # Main funnel
    fig = go.Figure(go.Funnel(
        y=["GA4 Sessions", "Sign-ups", "Uploads", "Paid"],
        x=[sess, signups, uploads, paid],
        textposition="inside", textinfo="value+percent initial",
        marker=dict(color=["#00D4FF", "#6C5CE7", "#FFD700", "#00E676"]),
    ))
    fig.update_layout(title="Visitor → Customer Journey", height=400, **TH, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

    # Stage conversion rates
    c1, c2, c3 = st.columns(3)
    s2u = (signups / sess * 100) if sess > 0 else 0
    u2p = (uploads / signups * 100) if signups > 0 else 0
    p2paid = (paid / uploads * 100) if uploads > 0 else 0
    with c1:
        st.metric("Session → Sign-up", f"{s2u:.2f}%")
    with c2:
        st.metric("Sign-up → Upload", f"{u2p:.2f}%")
    with c3:
        st.metric("Upload → Paid", f"{p2paid:.2f}%")

    # Daily breakdown
    if kpi is not None and not kpi.empty:
        st.markdown("#### 📅 Daily Funnel Data")
        display = kpi.copy()
        if "date" in display.columns:
            display["date_fmt"] = pd.to_datetime(display["date"]).dt.strftime("%b %d")
            display["S→U %"] = (display["first_uploads"] / display["signups"].replace(0, 1) * 100).round(2)
            display["U→P %"] = (display["paid_customers"] / display["first_uploads"].replace(0, 1) * 100).round(2)
            show_cols = [c for c in ["date_fmt", "signups", "first_uploads", "paid_customers", "S→U %", "U→P %"] if c in display.columns]
            st.dataframe(display[show_cols], use_container_width=True, height=400)

        # Daily trend chart
        if "date" in kpi.columns:
            fig2 = make_subplots(rows=3, cols=1, shared_xaxes=True,
                                 subplot_titles=("Sign-ups", "Uploads", "Paid"))
            if "signups" in kpi.columns:
                fig2.add_trace(go.Scatter(x=kpi["date"], y=kpi["signups"], name="Sign-ups",
                                         line=dict(color="#00D4FF")), row=1, col=1)
            if "first_uploads" in kpi.columns:
                fig2.add_trace(go.Scatter(x=kpi["date"], y=kpi["first_uploads"], name="Uploads",
                                         line=dict(color="#FFD700")), row=2, col=1)
            if "paid_customers" in kpi.columns:
                fig2.add_trace(go.Scatter(x=kpi["date"], y=kpi["paid_customers"], name="Paid",
                                         line=dict(color="#00E676")), row=3, col=1)
            fig2.update_layout(height=500, **TH, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
            st.plotly_chart(fig2, use_container_width=True, config=CHART_CFG)


# ══════════════════════════════════════════════════════════════
# TAB 6: 🔔 ALERTS
# ══════════════════════════════════════════════════════════════

def _tab_alerts(pages, p_pages, events, p_events, utm, p_utm, daily, p_daily):
    st.markdown("### 🔔 Smart Alerts & Anomaly Detection")

    if not MOD["notif"]:
        st.info("Alerts module not available — checking manually")
        _manual_alerts(pages, p_pages, events, p_events, utm, p_utm)
        return

    page_al = detect_page_anomalies(pages, p_pages)
    event_al = detect_event_anomalies(events, p_events)
    src_al = detect_source_anomalies(utm, p_utm)
    conv_al = detect_conversion_anomalies(daily, p_daily, None, None)

    all_al = conv_al + src_al + event_al + page_al
    summary = build_notification_summary(all_al)

    bc = "#FF4B6E" if summary["has_urgency"] else "#00E676"
    st.markdown(f"""
    <div style="background:{bc}22;border:1px solid {bc};border-radius:10px;padding:16px;margin-bottom:16px;">
        <b style="color:{bc};">{summary.get("emoji", "✅")} {"URGENT" if summary["has_urgency"] else "Healthy"}</b><br>
        <span style="color:#ccc;">{summary["summary_line"]}</span>
    </div>
    """, unsafe_allow_html=True)

    for sev in ["critical", "warnings", "positives", "info"]:
        alerts = summary.get(sev, [])
        if alerts:
            icons = {"critical": "🔴", "warnings": "🟡", "positives": "🟢", "info": "🔵"}
            st.markdown(f"#### {icons.get(sev, '')} {sev.title()} ({len(alerts)})")
            for a in alerts[:10]:
                color_map = {"critical": "#FF5252", "warnings": "#FFD600", "positives": "#00E676", "info": "#00D4FF"}
                c = color_map.get(sev, "#94A3C1")
                st.markdown(f"""
                <div style="background:#111D32;border-left:3px solid {c};border-radius:8px;padding:10px 14px;margin:6px 0;">
                    <b>{a.emoji} {a.title}</b><br>
                    <span style="color:#ccc;">{a.message}</span><br>
                    <span style="color:#5B6B85;font-size:0.8rem;">💡 {a.recommendation}</span>
                </div>
                """, unsafe_allow_html=True)

    if not all_al:
        st.success("✅ No anomalies detected")


def _manual_alerts(pages, p_pages, events, p_events, utm, p_utm):
    """Manual alert detection when ga4_notifications not available."""
    alerts = []

    # Check session drops
    cur_sess = _safe_sum(utm, "sessions")
    prev_sess = _safe_sum(p_utm, "sessions")
    if prev_sess > 0 and cur_sess > 0:
        change = (cur_sess - prev_sess) / prev_sess * 100
        if change < -20:
            alerts.append(("🔴", f"Sessions dropped {abs(change):.1f}%", "Investigate source changes"))
        elif change > 30:
            alerts.append(("🟢", f"Sessions up {change:.1f}%", "Identify and double down on what's working"))

    # Check conversion changes
    cur_conv = _safe_sum(utm, "conversions")
    prev_conv = _safe_sum(p_utm, "conversions")
    if prev_conv > 0:
        conv_change = (cur_conv - prev_conv) / prev_conv * 100
        if conv_change < -30:
            alerts.append(("🔴", f"Conversions dropped {abs(conv_change):.1f}%", "Check sign-up flow and landing pages"))
        elif conv_change > 30:
            alerts.append(("🟢", f"Conversions up {conv_change:.1f}%", "Great! Document what changed"))

    if not alerts:
        st.success("✅ No significant changes detected vs previous period")
    else:
        for icon, msg, rec in alerts:
            st.markdown(f"{icon} **{msg}** — *{rec}*")


# ══════════════════════════════════════════════════════════════
# TAB 7: 🤖 AI ANALYSIS
# ══════════════════════════════════════════════════════════════

def _tab_ai(utm, pages, events, daily, kpi):
    st.markdown("### 🤖 AI-Powered Analysis")

    if not MOD["intel"]:
        st.info("AI intelligence module not available. Providing rule-based insights instead.")
        _rule_based_insights(utm, pages, events, kpi)
        return

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🤖 Generate Traffic Analysis", type="primary", use_container_width=True, key="ai_analysis_btn"):
            with st.spinner("Analyzing traffic patterns..."):
                signups_ext = int(kpi["signups"].sum()) if kpi is not None and not kpi.empty and "signups" in kpi.columns else None
                st.session_state["ai_analysis"] = generate_traffic_analysis(utm, pages, events, signups_ext)
    with c2:
        if st.button("📬 Daily Briefing", use_container_width=True, key="ai_briefing_btn"):
            with st.spinner("Generating daily briefing..."):
                st.session_state["ai_briefing"] = generate_daily_notification(pages, events, utm)

    if "ai_analysis" in st.session_state:
        st.markdown("---")
        st.markdown(st.session_state["ai_analysis"])
    if "ai_briefing" in st.session_state:
        st.markdown("---")
        st.markdown(st.session_state["ai_briefing"])

    # Always show rule-based insights alongside AI
    st.markdown("---")
    _rule_based_insights(utm, pages, events, kpi)


def _rule_based_insights(utm, pages, events, kpi):
    """Rule-based traffic insights that always work without AI."""
    st.markdown("#### 📊 Quick Insights")

    insights = []
    if not utm.empty and "sessions" in utm.columns:
        total_sess = _safe_sum(utm, "sessions")
        total_conv = _safe_sum(utm, "conversions")
        cr = (total_conv / total_sess * 100) if total_sess > 0 else 0

        # Top source
        src_col = "source_normalized" if "source_normalized" in utm.columns else "sessionSource"
        by_src = utm.groupby(src_col)["sessions"].sum().sort_values(ascending=False)
        if len(by_src) > 0:
            top_src = by_src.index[0]
            top_pct = by_src.iloc[0] / total_sess * 100
            insights.append(f"🌐 **Top source**: {top_src} ({top_pct:.0f}% of traffic)")

        # Conversion insight
        if cr > 5:
            insights.append(f"🎯 **Conv rate {cr:.1f}%** — above average")
        elif cr > 0:
            insights.append(f"🎯 **Conv rate {cr:.1f}%** — room to improve")

        # Source diversity
        if len(by_src) > 0:
            top3_pct = by_src.head(3).sum() / total_sess * 100
            if top3_pct > 80:
                insights.append(f"⚠️ **Concentration risk**: Top 3 sources = {top3_pct:.0f}% — diversify traffic")

    if not pages.empty and "pagePath" in pages.columns:
        top_page = pages.groupby("pagePath")["screenPageViews"].sum().sort_values(ascending=False)
        if len(top_page) > 0:
            insights.append(f"📄 **Top page**: {top_page.index[0]} ({int(top_page.iloc[0]):,} views)")

    if not events.empty and "eventName" in events.columns:
        top_events = events.groupby("eventName")["eventCount"].sum().sort_values(ascending=False)
        if len(top_events) > 0:
            insights.append(f"⚡ **Top event**: {top_events.index[0]} ({int(top_events.iloc[0]):,} occurrences)")

    for ins in insights:
        st.markdown(f"- {ins}")

    if not insights:
        st.info("Load data first to see insights")


# ══════════════════════════════════════════════════════════════
# TAB 8: 💡 Q&A
# ══════════════════════════════════════════════════════════════

def _tab_qa(utm, pages, events, kpi, p_kpi, leads, geo, dev):
    st.markdown("### 💓 Strategic Q&A")

    # Free-text Q&A
    st.markdown("#### 🤖 Ask Your Own Question")
    st.caption("Analyzes GA4 + CRM data to answer questions about your traffic")

    if not MOD["qa"]:
        st.warning(f"Q&A engine not loaded: {MOD.get('qa_err', 'unknown')}")
    else:
        with st.expander("💭 Example Questions", expanded=False):
            st.markdown("""
            - How many signups from Google this month?
            - What's the conversion rate by source?
            - Which pages drive the most sign-ups?
            - Compare this month vs last month traffic
            - What's my best performing channel?
            - How many users from India?
            - Predict next week's traffic
            """)

        q = st.text_input("Your question:", placeholder="e.g., How many signups from Google?",
                          key="ti_question")
        if st.button("🚀 Get Answer", type="primary", key="ti_qa_btn"):
            if q:
                with st.spinner("Analyzing..."):
                    try:
                        answer = answer_free_text_question(
                            q, utm_df=utm, pages_df=pages, events_df=events,
                            geo_df=geo, dev_df=dev, kpi_df=kpi, p_kpi_df=p_kpi,
                            lead_sources_df=leads,
                        )
                        st.session_state["ti_qa_answer"] = answer
                        st.session_state["ti_qa_q"] = q
                    except Exception as e:
                        st.error(f"Error: {e}")

        if "ti_qa_answer" in st.session_state:
            st.markdown("---")
            st.markdown(f"**Q:** {st.session_state.get('ti_qa_q', '')}")
            st.markdown(st.session_state["ti_qa_answer"])

    # Strategic questions
    st.markdown("---")
    st.markdown("#### 📚 Pre-built Strategic Questions")

    if MOD["strat"]:
        questions = get_all_strategic_questions()
        selected = st.selectbox("Pick a question:", [q[0] for q in questions], key="ti_strat_sel")
        selected_key = next((q[1] for q in questions if q[0] == selected), None)

        if st.button("🧠 Get Strategic Answer", key="ti_strat_btn"):
            if selected_key:
                with st.spinner("Analyzing..."):
                    try:
                        answer = answer_question(selected_key, utm_df=utm, pages_df=pages,
                                                 events_df=events, kpi_df=kpi)
                        st.session_state["ti_strat_answer"] = answer
                    except Exception as e:
                        st.error(f"Error: {e}")

        if "ti_strat_answer" in st.session_state:
            st.markdown("---")
            st.markdown(st.session_state["ti_strat_answer"])


# ══════════════════════════════════════════════════════════════
# TAB 9: 📉 ENGAGEMENT  (NEW)
# ══════════════════════════════════════════════════════════════

def _tab_engagement(engagement, p_engagement):
    st.markdown("### 📉 User Engagement Over Time")
    if engagement.empty:
        st.info("No engagement data for this period")
        return

    df = engagement.copy()
    for col in df.columns:
        if col != "date":
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Daily trend chart
    if "date" in df.columns:
        st.markdown("#### 📊 Daily Metrics Trend")
        metrics_to_show = []
        for metric, color, name in [
            ("sessions", "#00D4FF", "Sessions"),
            ("conversions", "#00E676", "Conversions"),
            ("totalUsers", "#6C5CE7", "Users"),
            ("newUsers", "#B388FF", "New Users"),
        ]:
            if metric in df.columns:
                metrics_to_show.append((metric, color, name))

        selected_metrics = st.multiselect(
            "Select metrics to display:",
            [m[2] for m in metrics_to_show],
            default=[m[2] for m in metrics_to_show[:3]],
            key="eng_metrics_sel",
        )

        fig = go.Figure()
        for metric, color, name in metrics_to_show:
            if name in selected_metrics:
                fig.add_trace(go.Scatter(x=df["date"], y=df[metric], name=name,
                                         line=dict(color=color, width=2)))
        fig.update_layout(height=400, **TH, margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

        # Engagement rate trend
        if "engagementRate" in df.columns:
            st.markdown("#### 🎯 Engagement Rate Trend")
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=df["date"], y=df["engagementRate"] * 100,
                                      name="Engagement %", line=dict(color="#00E676", width=2),
                                      fill="tozeroy", fillcolor="rgba(0,230,118,0.1)"))
            fig2.update_layout(height=300, yaxis_title="Engagement %", **TH, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig2, use_container_width=True, config=CHART_CFG)

        # Avg session duration trend
        if "averageSessionDuration" in df.columns:
            st.markdown("#### ⏱️ Average Session Duration")
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=df["date"], y=df["averageSessionDuration"],
                                      name="Duration (s)", line=dict(color="#FFD600", width=2),
                                      fill="tozeroy", fillcolor="rgba(255,214,0,0.1)"))
            fig3.update_layout(height=300, yaxis_title="Seconds", **TH, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig3, use_container_width=True, config=CHART_CFG)

        # Pages per session
        if "screenPageViewsPerSession" in df.columns:
            st.markdown("#### 📄 Pages per Session")
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(x=df["date"], y=df["screenPageViewsPerSession"],
                                      name="Pages/Session", line=dict(color="#6C5CE7", width=2),
                                      fill="tozeroy", fillcolor="rgba(108,92,231,0.1)"))
            fig4.update_layout(height=300, yaxis_title="Pages", **TH, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig4, use_container_width=True, config=CHART_CFG)

    # Summary stats
    st.markdown("#### 📋 Period Summary")
    summary_data = {}
    for col in ["sessions", "totalUsers", "newUsers", "conversions", "eventCount"]:
        if col in df.columns:
            summary_data[col] = {
                "Total": _fmt(df[col].sum()),
                "Daily Avg": f"{df[col].mean():.1f}",
                "Peak": f"{df[col].max():,.0f}",
            }
    if summary_data:
        st.dataframe(pd.DataFrame(summary_data).T, use_container_width=True)

    # Period comparison
    if not p_engagement.empty:
        st.markdown("#### 🔄 vs Previous Period")
        p_df = p_engagement.copy()
        for col in p_df.columns:
            if col != "date":
                p_df[col] = pd.to_numeric(p_df[col], errors="coerce")
        
        comp = []
        for col in ["sessions", "totalUsers", "conversions", "newUsers"]:
            if col in df.columns and col in p_df.columns:
                cur = df[col].sum()
                prev = p_df[col].sum()
                change = _pct(cur, prev)
                comp.append({"Metric": col, "Current": _fmt(cur), "Previous": _fmt(prev), "Δ%": f"{change:+.1f}%"})
        if comp:
            st.dataframe(pd.DataFrame(comp), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
# TAB 10: 🏠 LANDING PAGES (NEW)
# ══════════════════════════════════════════════════════════════

def _tab_landing(landing, referrals):
    st.markdown("### 🏠 Landing Pages & Referrals")

    if not landing.empty:
        st.markdown("#### 🔝 Top Landing Pages by Source")
        ld = landing.copy()
        for col in ["sessions", "totalUsers", "newUsers", "conversions"]:
            if col in ld.columns:
                ld[col] = pd.to_numeric(ld[col], errors="coerce")

        # Aggregate by landing page
        page_agg = ld.groupby("landingPage").agg(
            Sessions=("sessions", "sum"),
            Users=("totalUsers", "sum"),
            New=("newUsers", "sum"),
            Convs=("conversions", "sum"),
        ).reset_index().sort_values("Sessions", ascending=False)
        page_agg["Conv_%"] = (page_agg["Convs"] / page_agg["Sessions"].replace(0, 1) * 100).round(2)
        page_agg["New_%"] = (page_agg["New"] / page_agg["Users"].replace(0, 1) * 100).round(1)

        fig = px.bar(page_agg.head(20), x="Sessions", y="landingPage", orientation="h",
                     color="Conv_%", color_continuous_scale="RdYlGn")
        fig.update_layout(height=max(400, len(page_agg.head(20)) * 28), **TH, margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

        st.dataframe(page_agg.head(40), use_container_width=True, height=350, hide_index=True)

        # Landing page by source
        st.markdown("#### 🔗 Landing Page × Source")
        src_page = ld.groupby(["landingPage", "sessionSource"]).agg(
            Sessions=("sessions", "sum"),
            Convs=("conversions", "sum"),
        ).reset_index().sort_values("Sessions", ascending=False)
        st.dataframe(src_page.head(50), use_container_width=True, height=350, hide_index=True)

    elif not referrals.empty:
        st.markdown("#### 🔗 Referral Traffic")
        rf = referrals.copy()
        for col in ["sessions", "totalUsers", "conversions"]:
            if col in rf.columns:
                rf[col] = pd.to_numeric(rf[col], errors="coerce")
        st.dataframe(rf.head(50), use_container_width=True, height=400, hide_index=True)
    else:
        st.info("No landing page or referral data for this period")

    # Referral analysis
    if not referrals.empty:
        st.markdown("#### 🔗 Referral Sources & Landing Pages")
        rf = referrals.copy()
        for col in ["sessions", "conversions"]:
            if col in rf.columns:
                rf[col] = pd.to_numeric(rf[col], errors="coerce")

        ref_agg = rf.groupby("sessionSource").agg(
            Sessions=("sessions", "sum"),
            Convs=("conversions", "sum"),
        ).reset_index().sort_values("Sessions", ascending=False)
        ref_agg["Conv_%"] = (ref_agg["Convs"] / ref_agg["Sessions"].replace(0, 1) * 100).round(2)

        fig = px.bar(ref_agg.head(15), x="Sessions", y="sessionSource", orientation="h",
                     color="Conv_%", color_continuous_scale="RdYlGn")
        fig.update_layout(height=400, **TH, margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)


# ══════════════════════════════════════════════════════════════
# TAB 11: 🔄 ATTRIBUTION (NEW)
# ══════════════════════════════════════════════════════════════

def _tab_attribution(first_touch, source_deep, leads):
    st.markdown("### 🔄 Attribution Analysis")

    # First-touch attribution
    if not first_touch.empty:
        st.markdown("#### 🥇 First-Touch Attribution")
        st.caption("How did users FIRST find your site?")
        ft = first_touch.copy()
        for col in ["newUsers", "totalUsers", "sessions", "conversions"]:
            if col in ft.columns:
                ft[col] = pd.to_numeric(ft[col], errors="coerce")

        ft_agg = ft.groupby("firstUserSource").agg(
            New_Users=("newUsers", "sum"),
            Total=("totalUsers", "sum"),
            Sessions=("sessions", "sum"),
            Convs=("conversions", "sum"),
        ).reset_index().sort_values("New_Users", ascending=False)
        ft_agg["Conv_%"] = (ft_agg["Convs"] / ft_agg["Sessions"].replace(0, 1) * 100).round(2)

        fig = px.bar(ft_agg.head(15), x="New_Users", y="firstUserSource", orientation="h",
                     color="Conv_%", color_continuous_scale="RdYlGn")
        fig.update_layout(height=max(400, len(ft_agg.head(15)) * 28), **TH, margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
        st.dataframe(ft_agg, use_container_width=True, height=350, hide_index=True)

        # First-touch by channel group
        if "firstUserDefaultChannelGroup" in ft.columns:
            st.markdown("#### 📊 First-Touch by Channel Group")
            ch_agg = ft.groupby("firstUserDefaultChannelGroup").agg(
                New_Users=("newUsers", "sum"),
                Convs=("conversions", "sum"),
            ).reset_index().sort_values("New_Users", ascending=False)
            fig2 = px.pie(ch_agg, values="New_Users", names="firstUserDefaultChannelGroup", hole=0.5,
                          color_discrete_sequence=["#00D4FF", "#6C5CE7", "#00E676", "#FFD600", "#FF5252", "#B388FF", "#FF9100"])
            fig2.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig2, use_container_width=True, config=CHART_CFG)
    else:
        st.info("No first-touch attribution data")

    # Channel comparison
    if not source_deep.empty:
        st.markdown("#### 📊 Last-Touch Channel Breakdown")
        sd = source_deep.copy()
        if "sessionDefaultChannelGroup" in sd.columns and "sessions" in sd.columns:
            sd["sessions"] = pd.to_numeric(sd["sessions"], errors="coerce")
            ch = sd.groupby("sessionDefaultChannelGroup").agg(
                Sessions=("sessions", "sum"),
            ).reset_index().sort_values("Sessions", ascending=False)
            total = ch["Sessions"].sum()
            ch["Share_%"] = (ch["Sessions"] / total * 100).round(1)
            st.dataframe(ch, use_container_width=True, height=300, hide_index=True)


# ══════════════════════════════════════════════════════════════
# TAB 12: ⏰ PATTERNS (NEW)
# ══════════════════════════════════════════════════════════════

def _tab_patterns(hourly, daily, retention):
    st.markdown("### ⏰ Traffic Patterns & Timing")

    # Hourly heatmap
    if not hourly.empty:
        st.markdown("#### 🕐 Traffic by Hour & Day of Week")
        hd = hourly.copy()
        for col in ["sessions", "totalUsers", "conversions"]:
            if col in hd.columns:
                hd[col] = pd.to_numeric(hd[col], errors="coerce")

        if "hour" in hd.columns and "dayOfWeek" in hd.columns:
            day_map = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat"}

            metric_choice = st.selectbox("Heatmap metric:", ["sessions", "conversions", "totalUsers"],
                                         key="pattern_metric")
            if metric_choice in hd.columns:
                pivot = hd.pivot_table(index="dayOfWeek", columns="hour", values=metric_choice,
                                       aggfunc="sum", fill_value=0)
                pivot.index = [day_map.get(str(d), str(d)) for d in pivot.index]

                fig = px.imshow(pivot, aspect="auto",
                                color_continuous_scale="Blues",
                                labels=dict(x="Hour", y="Day", color=metric_choice))
                fig.update_layout(height=350, **TH, margin=dict(l=40, r=0, t=20, b=0))
                st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

        # Best time summary
        if "sessions" in hd.columns and "hour" in hd.columns:
            best_hour = hd.groupby("hour")["sessions"].sum()
            peak_hour = best_hour.idxmax()
            peak_sessions = best_hour.max()
            st.markdown(f"**🕐 Peak hour:** {peak_hour}:00 ({int(peak_sessions):,} sessions)")

        if "conversions" in hd.columns and "hour" in hd.columns:
            best_conv_hour = hd.groupby("hour")["conversions"].sum()
            peak_conv = best_conv_hour.idxmax()
            st.markdown(f"**🎯 Best conversion hour:** {peak_conv}:00")
    else:
        st.info("No hourly pattern data for this period")

    # Daily trend from daily summary
    if not daily.empty:
        st.markdown("#### 📅 Daily Traffic Trend")
        dd = daily.copy()
        for col in ["sessions", "totalUsers", "conversions"]:
            if col in dd.columns:
                dd[col] = pd.to_numeric(dd[col], errors="coerce")

        if "date" in dd.columns and "sessions" in dd.columns:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=dd["date"], y=dd["sessions"],
                                     name="Sessions", line=dict(color="#00D4FF", width=2)))
            if "conversions" in dd.columns:
                fig.add_trace(go.Scatter(x=dd["date"], y=dd["conversions"],
                                         name="Conversions", line=dict(color="#00E676", width=2),
                                         yaxis="y2"))
                fig.update_layout(yaxis2=dict(overlaying="y", side="right", title="Conversions"))
            fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

    # Retention
    if not retention.empty:
        st.markdown("#### 🔄 New vs Returning Users")
        ret = retention.copy()
        for col in ["sessions", "totalUsers", "conversions"]:
            if col in ret.columns:
                ret[col] = pd.to_numeric(ret[col], errors="coerce")

        if "newVsReturning" in ret.columns:
            nr = ret.groupby("newVsReturning").agg(
                Sessions=("sessions", "sum"),
                Users=("totalUsers", "sum"),
                Convs=("conversions", "sum"),
            ).reset_index()

            fig = px.pie(nr, values="Users", names="newVsReturning", hole=0.5,
                         color="newVsReturning", color_discrete_sequence=["#00D4FF", "#6C5CE7"])
            fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

            # Daily retention trend
            if "date" in ret.columns:
                pivot = ret.pivot_table(index="date", columns="newVsReturning", values="Users", fill_value=0)
                fig2 = go.Figure()
                colors = {"new": "#00D4FF", "returning": "#6C5CE7"}
                for col in pivot.columns:
                    fig2.add_trace(go.Scatter(x=pivot.index, y=pivot[col], name=col.title(),
                                              line=dict(color=colors.get(col.lower(), "#94A3C1"))))
                fig2.update_layout(height=300, **TH, margin=dict(l=0, r=0, t=20, b=0))
                st.plotly_chart(fig2, use_container_width=True, config=CHART_CFG)


# ══════════════════════════════════════════════════════════════
# TAB 13: 🖥️ TECH & DEVICES (NEW)
# ══════════════════════════════════════════════════════════════

def _tab_tech(device_deep, dev):
    st.markdown("### 🖥️ Technology & Devices")

    if device_deep.empty and dev.empty:
        st.info("No device data for this period")
        return

    if not device_deep.empty:
        dd = device_deep.copy()
        for col in ["sessions", "totalUsers", "conversions"]:
            if col in dd.columns:
                dd[col] = pd.to_numeric(dd[col], errors="coerce")

        # Device category
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 📱 Device Categories")
            if "deviceCategory" in dd.columns:
                dc = dd.groupby("deviceCategory").agg(
                    Sessions=("sessions", "sum"),
                    Convs=("conversions", "sum"),
                ).reset_index().sort_values("Sessions", ascending=False)
                dc["Conv_%"] = (dc["Convs"] / dc["Sessions"].replace(0, 1) * 100).round(2)

                fig = px.pie(dc, values="Sessions", names="deviceCategory", hole=0.45,
                             color_discrete_sequence=["#00D4FF", "#6C5CE7", "#FFD600", "#00E676"])
                fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
                st.dataframe(dc, use_container_width=True, height=200, hide_index=True)

        with c2:
            st.markdown("#### 🌐 Top Browsers")
            if "browser" in dd.columns:
                bc = dd.groupby("browser").agg(
                    Sessions=("sessions", "sum"),
                    Convs=("conversions", "sum"),
                ).reset_index().sort_values("Sessions", ascending=False).head(10)
                bc["Conv_%"] = (bc["Convs"] / bc["Sessions"].replace(0, 1) * 100).round(2)
                fig = px.bar(bc, x="Sessions", y="browser", orientation="h",
                             color="Conv_%", color_continuous_scale="RdYlGn")
                fig.update_layout(height=350, **TH, margin=dict(l=0, r=0, t=20, b=0))
                st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

        # OS breakdown
        st.markdown("#### 💻 Operating Systems")
        if "operatingSystem" in dd.columns:
            os_data = dd.groupby("operatingSystem").agg(
                Sessions=("sessions", "sum"),
                Convs=("conversions", "sum"),
            ).reset_index().sort_values("Sessions", ascending=False)
            os_data["Conv_%"] = (os_data["Convs"] / os_data["Sessions"].replace(0, 1) * 100).round(2)
            st.dataframe(os_data, use_container_width=True, height=300, hide_index=True)

        # Engagement by device
        if "engagementRate" in dd.columns and "deviceCategory" in dd.columns:
            st.markdown("#### 📊 Engagement by Device")
            eng = dd.groupby("deviceCategory").agg(
                Sessions=("sessions", "sum"),
                Eng_Rate=("engagementRate", "mean"),
                Avg_Dur=("averageSessionDuration", "mean") if "averageSessionDuration" in dd.columns else ("sessions", "count"),
            ).reset_index()
            eng["Eng_Rate_%"] = (eng["Eng_Rate"] * 100).round(1)
            st.dataframe(eng, use_container_width=True, height=200, hide_index=True)

    # Full data download
    if not device_deep.empty:
        with st.expander("📋 Full Device Data"):
            st.dataframe(device_deep, use_container_width=True, height=400, hide_index=True)


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
