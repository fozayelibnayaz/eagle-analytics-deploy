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
