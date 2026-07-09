"""
pages_registry.py — Eagle 3D Streaming Analytics Hub
======================================================
Wires the new dark UI shell into the EXISTING full-featured page modules.
All original features preserved. Sub-tabs added per your (1b) preference.

Each page renders:
  1. Hero + period banner (new UI shell)
  2. Sub-tabs (Dashboard / Browse / Manual Override / Reports / etc.)
  3. Delegates content to the existing module functions
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from period_engine import get_period
from ui_helpers import empty_state, page_error_boundary
from editable_tables import render_editable_table, render_audit_log


# ─────────────────────────────────────────────────────────────────
# SHARED SHELL
# ─────────────────────────────────────────────────────────────────
def _hero(icon: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="e3-fade-up" style="display:flex;align-items:center;gap:20px;">
          <div style="width:52px;height:52px;border-radius:14px;
                      background:linear-gradient(135deg,#9EFF2F,#5EF46A);
                      display:flex;align-items:center;justify-content:center;
                      font-size:26px;box-shadow:0 4px 20px rgba(158,255,47,0.3);">
            {icon}
          </div>
          <div>
            <div class="e3-hero-greeting">{title}</div>
            <div class="e3-hero-sub">{subtitle}</div>
          </div>
        </div>
        <div style="margin-top:28px;"></div>
        """,
        unsafe_allow_html=True,
    )


def _period_banner() -> None:
    p = get_period()
    st.markdown(
        f"""
        <div class="e3-badge primary" style="margin-bottom:24px;">
          📅 {p.label} · {p.start_iso()} → {p.end_iso()} · {p.days} days
          {f' · ↔ {p.compare_label}' if p.compare_enabled else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _safe_call(fn_getter, *args, **kwargs):
    """Call a function safely — catches ImportError + AttributeError + runtime errors."""
    try:
        fn = fn_getter()
        if fn is None:
            st.warning("Feature module not available.")
            return
        fn(*args, **kwargs)
    except ImportError as e:
        st.error(f"❌ Module missing: {e}")
    except AttributeError as e:
        st.error(f"❌ Function not found in module: {e}")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        with st.expander("🐛 Traceback"):
            import traceback
            st.code(traceback.format_exc(), language="python")


# ═════════════════════════════════════════════════════════════════
# PAGE 1: KPI ANALYTICS (with all sub-features)
# ═════════════════════════════════════════════════════════════════
def render_kpi_page(user_email: str = "") -> None:
    _hero("📊", "KPI Analytics",
          "Sign-ups, uploads & paying customers — full analysis suite.")
    _period_banner()

    with page_error_boundary("KPI"):
        tabs = st.tabs([
            "📊 Dashboard",
            "🔍 Browse Data",
            "🧪 EDA Lab",
            "✏️ Manual Override",
            "📄 Reports",
            "🔔 Alerts",
            "📈 Trend Analysis",
        ])

        with tabs[0]:
            _render_kpi_dashboard(user_email)

        with tabs[1]:
            _render_browse_data()

        with tabs[2]:
            _render_eda_lab()

        with tabs[3]:
            _render_manual_override(user_email)

        with tabs[4]:
            _render_reports()

        with tabs[5]:
            _render_alerts()

        with tabs[6]:
            _safe_call(lambda: __import__("trend_analysis_ui").render_trend_section,
                       platform="kpi")


def _render_kpi_dashboard(user_email: str) -> None:
    """KPI Dashboard sub-tab — post-dedup counts + pattern analysis."""
    from mongo_client import find_all
    period = get_period()

    def _sum_kpis(s_iso, e_iso):
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": s_iso, "$lte": e_iso}})
        return (
            sum(int(r.get("signups_accepted", 0) or 0) for r in rows),
            sum(int(r.get("uploads_accepted", 0) or 0) for r in rows),
            sum(int(r.get("paid_accepted",    0) or 0) for r in rows),
        )

    sign, up, pay = _sum_kpis(period.start_iso(), period.end_iso())
    prev_s = prev_u = prev_p = 0
    if period.compare_enabled and period.compare_start:
        prev_s, prev_u, prev_p = _sum_kpis(period.compare_start_iso(),
                                            period.compare_end_iso())

    def _pct(cur, prv):
        if not period.compare_enabled: return None
        if prv == 0: return f"+{cur} new" if cur else "—"
        return f"{'+' if cur >= prv else ''}{(cur-prv)/prv*100:.1f}% vs prev"

    st.markdown('<p class="e3-section-title">Verified Counts (post-dedup)</p>',
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("👥 Sign-ups",  f"{sign:,}", _pct(sign, prev_s))
    c2.metric("📤 Uploads",   f"{up:,}",   _pct(up, prev_u))
    c3.metric("💳 Paid",       f"{pay:,}",  _pct(pay, prev_p))

    # Funnel
    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    st.markdown('<p class="e3-section-title">Funnel</p>', unsafe_allow_html=True)
    su = round(up/sign*100, 1) if sign else 0
    upr= round(pay/up*100, 1) if up else 0
    sp = round(pay/sign*100, 1) if sign else 0
    r1, r2, r3 = st.columns(3)
    r1.metric("🔄 Sign→Upload", f"{su}%")
    r2.metric("💰 Upload→Paid", f"{upr}%")
    r3.metric("🎯 Sign→Paid",   f"{sp}%")

    # Chart
    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    st.markdown('<p class="e3-section-title">Daily Trend</p>', unsafe_allow_html=True)
    try:
        import plotly.graph_objects as go
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": period.start_iso(),
                                           "$lte": period.end_iso()}},
                        sort=[("date", 1)])
        if rows:
            df = pd.DataFrame(rows)
            df = df[df["date"].notna()].sort_values("date")
            for c in ["signups_accepted", "uploads_accepted", "paid_accepted"]:
                if c not in df.columns: df[c] = 0
                df[c] = df[c].fillna(0).astype(int)
            fig = go.Figure()
            for k, lbl, col, fill in [
                ("signups_accepted", "Sign-ups", "#9EFF2F", "rgba(158,255,47,0.10)"),
                ("uploads_accepted", "Uploads",  "#5EF46A", "rgba(94,244,106,0.08)"),
                ("paid_accepted",    "Paid",     "#4ADE80", "rgba(74,222,128,0.06)"),
            ]:
                fig.add_trace(go.Scatter(x=df["date"], y=df[k], name=lbl,
                                          mode="lines", line=dict(color=col, width=2.5),
                                          fill="tozeroy", fillcolor=fill))
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font=dict(color="#9CA3AF"), height=300,
                              margin=dict(l=0,r=0,t=10,b=0),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                          xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
                              xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
                              yaxis=dict(gridcolor="rgba(255,255,255,0.04)"))
            st.plotly_chart(fig, width='stretch')
        else:
            empty_state("No trend data", f"No daily_kpis rows in {period.label}", icon="📈")
    except Exception as e:
        st.info(f"Chart: {e}")

    # Pattern analysis (calls existing module)
    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    with st.expander("📊 Pattern Analysis (region + time + fluctuations)", expanded=False):
        metric = st.selectbox("Metric", ["signups", "uploads", "paid"],
                              key="kpi_pattern_metric")
        _safe_call(lambda: __import__("kpi_pattern_ui").render_kpi_pattern_analysis,
                   metric_type=metric)


def _render_browse_data() -> None:
    """Browse + EDIT raw data — Google Sheets-style inline editing."""
    st.markdown('<p class="e3-section-title">Browse & Edit Data</p>',
                unsafe_allow_html=True)
    st.caption("Edit any cell inline. Add or delete rows. "
                "Changes save to MongoDB in real-time and are audit-logged.")

    c1, c2 = st.columns([1, 3])
    with c1:
        source = st.selectbox("Source",
                                ["signups", "uploads", "payments"],
                                key="browse_source_edit")

    user_email = st.session_state.get("user_email", "")

    display_cols_map = {
        "signups": ["email_normalized", "signup_date", "lead_source",
                    "final_status", "reason", "is_overridden"],
        "uploads": ["email_normalized", "upload_date", "signup_date",
                    "days_signup_to_upload", "final_status", "reason",
                    "is_overridden"],
        "payments":["email_normalized", "first_payment_date", "total_spend",
                    "customer_type", "final_status", "reason"],
    }

    render_editable_table(
        collection=source,
        user_email=user_email,
        key_field="email_normalized",
        display_columns=display_cols_map.get(source),
        max_rows=500,
    )

    # ── Audit log expander ──
    with st.expander("📋 Recent edits audit log"):
        render_audit_log(user_email=user_email, limit=30)


def _render_eda_lab() -> None:
    """Exploratory Data Analysis."""
    from mongo_client import find_all
    st.markdown('<p class="e3-section-title">EDA Lab</p>', unsafe_allow_html=True)
    st.caption("Exploratory data analysis with custom charts")

    source = st.selectbox("Source collection",
                          ["signups", "uploads", "payments", "daily_kpis"],
                          key="eda_source")
    chart_type = st.selectbox("Chart type",
                               ["Bar", "Histogram", "Box", "Scatter", "Line"],
                               key="eda_chart")

    rows = find_all(source, limit=5000)
    if not rows:
        empty_state("No data", "Collection is empty")
        return

    df = pd.DataFrame(rows)
    cols = df.columns.tolist()

    c1, c2 = st.columns(2)
    x_col = c1.selectbox("X", cols, key="eda_x")
    y_col = c2.selectbox("Y (optional)", ["(none)"] + cols, key="eda_y")

    try:
        import plotly.express as px
        y = None if y_col == "(none)" else y_col
        if chart_type == "Bar":
            if y:
                fig = px.bar(df.head(50), x=x_col, y=y)
            else:
                counts = df[x_col].value_counts().head(30)
                fig = px.bar(x=counts.index, y=counts.values,
                             labels={"x": x_col, "y": "count"})
        elif chart_type == "Histogram":
            fig = px.histogram(df, x=x_col, nbins=30)
        elif chart_type == "Box":
            fig = px.box(df, x=x_col, y=y) if y else px.box(df, y=x_col)
        elif chart_type == "Scatter":
            fig = px.scatter(df.head(500), x=x_col, y=y) if y else px.scatter(df.head(500), x=x_col)
        elif chart_type == "Line":
            fig = px.line(df.sort_values(x_col).head(200), x=x_col, y=y) if y else None

        if fig:
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font=dict(color="#9CA3AF"),
                              xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
                              yaxis=dict(gridcolor="rgba(255,255,255,0.04)"))
            st.plotly_chart(fig, width='stretch')
    except Exception as e:
        st.error(f"Chart error: {e}")


def _render_manual_override(user_email: str) -> None:
    """Manual override — force ACCEPTED/REJECTED."""
    from mongo_client import find_one, get_raw_db
    st.markdown('<p class="e3-section-title">Manual Override</p>', unsafe_allow_html=True)
    st.caption("Force a row's status. All changes are audit-logged.")

    with st.form("override_form"):
        c1, c2 = st.columns(2)
        with c1:
            source = st.selectbox("Source", ["signups", "uploads", "payments"])
            email  = st.text_input("Email (exact match)")
        with c2:
            new_status = st.selectbox("New status",
                                       ["ACCEPTED", "REJECTED", "PENDING"])
            reason = st.text_input("Reason (required)")

        if st.form_submit_button("💾 Apply Override", type="primary"):
            if not email or not reason:
                st.error("Email and reason required")
            else:
                db = get_raw_db()
                if db is None:
                    st.error("MongoDB offline")
                else:
                    result = db[source].update_one(
                        {"email_normalized": email.strip().lower()},
                        {"$set": {
                            "final_status":       new_status,
                            "is_overridden":      True,
                            "override_reason":    reason,
                            "override_user":      user_email,
                            "override_timestamp": datetime.utcnow().isoformat(),
                        }},
                    )
                    if result.matched_count:
                        db["override_audit_log"].insert_one({
                            "source":     source,
                            "email":      email,
                            "new_status": new_status,
                            "reason":     reason,
                            "user":       user_email,
                            "timestamp":  datetime.utcnow().isoformat(),
                        })
                        st.success(f"✅ Override applied to {email}")
                    else:
                        st.error("Email not found in that collection")


def _render_reports() -> None:
    """Generate + send reports."""
    st.markdown('<p class="e3-section-title">Reports</p>', unsafe_allow_html=True)
    st.caption("Generate markdown reports for stakeholders")

    report_type = st.selectbox("Report type",
                                ["weekly", "biweekly", "monthly", "quarterly"],
                                key="report_type")

    if st.button("📝 Generate Report", type="primary"):
        try:
            from reporting_engine import build_report
            with st.spinner("Generating..."):
                md = build_report(report_type)
                st.text_area("Report", md, height=500)
                st.download_button("💾 Download .md", md,
                                    file_name=f"report_{report_type}.md")
        except Exception as e:
            st.error(f"Report error: {e}")


def _render_alerts() -> None:
    """Alert configuration + send test."""
    st.markdown('<p class="e3-section-title">Alerts</p>', unsafe_allow_html=True)
    st.caption("Configure and test Telegram/email alert sending")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("📤 Send Test Telegram Alert", width='stretch'):
            try:
                from reporting_engine import send_telegram
                r = send_telegram("🧪 Test alert from Eagle 3D Analytics Hub")
                if r:
                    st.success("✅ Telegram alert sent")
                else:
                    st.error("❌ Failed — check TELEGRAM_BOT_TOKEN")
            except Exception as e:
                st.error(f"Error: {e}")
    with c2:
        if st.button("🔔 Send All Alerts Now", width='stretch'):
            try:
                from all_alerts import run_all
                with st.spinner("Sending..."):
                    n = run_all()
                    st.success(f"✅ Sent {n} alerts")
            except Exception as e:
                st.error(f"Error: {e}")

    st.markdown("---")
    st.markdown("### Anomaly Detection")
    if st.button("🔍 Check for anomalies now", type="primary"):
        try:
            from anomaly_detector import detect_anomalies
            anoms = detect_anomalies()
            if not anoms:
                st.success("✅ No anomalies")
            else:
                for a in anoms:
                    st.warning(a["message"])
        except Exception as e:
            st.error(f"Error: {e}")


# ═════════════════════════════════════════════════════════════════
# PAGE 2: GOOGLE ANALYTICS (delegates to your existing module)
# ═════════════════════════════════════════════════════════════════
def render_ga4_page(user_email: str = "") -> None:
    _hero("📈", "Google Analytics",
          "GA4 traffic, sources, attribution & pattern analysis.")
    _period_banner()

    with page_error_boundary("GA4"):
        tabs = st.tabs([
            "�� Overview",
            "🚦 Traffic Intelligence",
            "📊 Pattern Analysis",
            "📈 Trend Analysis",
        ])

        with tabs[0]:
            _render_ga4_overview()

        with tabs[1]:
            # Delegate to your existing full ga4 UI if any exists
            try:
                # Try importing the full ga4 experience
                from ga4_source_intel import render_source_intel
                render_source_intel()
            except (ImportError, AttributeError):
                _render_ga4_overview()

        with tabs[2]:
            _safe_call(lambda: __import__("ga4_pattern_ui").render_ga4_pattern_analysis)

        with tabs[3]:
            _safe_call(lambda: __import__("trend_analysis_ui").render_trend_section,
                       platform="ga4")


def _render_ga4_overview() -> None:
    """Fetch GA4 data (live or from cache)."""
    period = get_period()
    ga4_ok = False
    try:
        from ga4_connector import is_configured, fetch_utm_traffic, fetch_geo_traffic
        ga4_ok = is_configured()
    except Exception:
        pass

    if not ga4_ok:
        st.warning(
            "⚠️ GA4 not configured. Add `GA4_PROPERTY_ID` and "
            "`[ga4_service_account]` (as TOML table) to `.streamlit/secrets.toml`."
        )
        # Show cache
        try:
            from pathlib import Path
            import json
            cache = Path("data_output/ga4_traffic_cache.json")
            if cache.exists():
                d = json.loads(cache.read_text())
                st.info(f"📦 Cached snapshot from {d.get('scraped_at', '?')}")
                c1, c2 = st.columns(2)
                c1.metric("🌐 Sessions", f"{d.get('total_sessions', 0):,}")
                c2.metric("👥 Users",    f"{d.get('total_users', 0):,}")
                if d.get("top_sources"):
                    st.markdown("**Top Sources:**")
                    st.dataframe(pd.DataFrame(d["top_sources"],
                                               columns=["Source", "Sessions"]),
                                 width='stretch', hide_index=True)
                if d.get("top_countries"):
                    st.markdown("**Top Countries:**")
                    st.dataframe(pd.DataFrame(d["top_countries"],
                                               columns=["Country", "Sessions"]),
                                 width='stretch', hide_index=True)
        except Exception as e:
            empty_state("GA4 not available", str(e), icon="📊")
        return

    # Live GA4
    try:
        with st.spinner("Fetching GA4..."):
            utm = fetch_utm_traffic(period.start_iso(), period.end_iso())
            geo = fetch_geo_traffic(period.start_iso(), period.end_iso())

        sess = int(utm["sessions"].sum()) if not utm.empty and "sessions" in utm.columns else 0
        users = int(utm["activeUsers"].sum()) if not utm.empty and "activeUsers" in utm.columns else 0

        c1, c2 = st.columns(2)
        c1.metric("🌐 Sessions", f"{sess:,}")
        c2.metric("👥 Users",    f"{users:,}")

        if not utm.empty and "sourceMedium" in utm.columns:
            st.markdown('<p class="e3-section-title">Top Sources</p>', unsafe_allow_html=True)
            top = utm.groupby("sourceMedium")["sessions"].sum().sort_values(ascending=False).head(15)
            st.dataframe(pd.DataFrame({"Source": top.index, "Sessions": top.values}),
                         width='stretch', hide_index=True)

        if not geo.empty and "country" in geo.columns:
            st.markdown('<p class="e3-section-title">Top Countries</p>', unsafe_allow_html=True)
            top = geo.groupby("country")["sessions"].sum().sort_values(ascending=False).head(20)
            st.dataframe(pd.DataFrame({"Country": top.index, "Sessions": top.values}),
                         width='stretch', hide_index=True)
    except Exception as e:
        st.error(f"GA4 error: {e}")


# ═════════════════════════════════════════════════════════════════
# PAGE 3: YOUTUBE — delegate to your full command center
# ═════════════════════════════════════════════════════════════════
def render_youtube_page(user_email: str = "") -> None:
    _hero("▶", "YouTube Command Center",
          "Full channel analytics, per-video AI insights & OAuth data.")

    with page_error_boundary("YouTube"):
        try:
            from youtube_page_v2 import render_youtube_page_v2
            render_youtube_page_v2()
        except ImportError:
            # Fallback to old UI if v2 missing
            _safe_call(lambda: __import__("youtube_command_center_ui").render_youtube_command_center)


# ═════════════════════════════════════════════════════════════════
# PAGE 4: LINKEDIN — delegate to your full command center
# ═════════════════════════════════════════════════════════════════
def render_linkedin_page(user_email: str = "") -> None:
    _hero("💼", "LinkedIn Command Center",
          "Followers, posts, visitors, competitors & search keywords.")

    with page_error_boundary("LinkedIn"):
        _safe_call(lambda: __import__("linkedin_command_center_ui").render_linkedin_command_center)


# ═════════════════════════════════════════════════════════════════
# PAGE 5: CUSTOMER SUCCESS — delegate + add analytics tab
# ═════════════════════════════════════════════════════════════════
def render_cs_page(user_email: str = "") -> None:
    _hero("��", "Customer Success Hub",
          "Master view, enriched funnel, Stripe live, deep analytics.")

    with page_error_boundary("Customer Success"):
        tabs = st.tabs([
            "🎯 Hub",
            "📊 Deep Analytics (15 sections)",
            "💔 Churn / Unsubscribes",
        ])

        with tabs[0]:
            _safe_call(lambda: __import__("customer_success_ui").render_customer_success)

        with tabs[1]:
            _safe_call(lambda: __import__("customer_success_analytics_ui").render_cs_analytics)

        with tabs[2]:
            # unsubscribe_ui has no top-level render function; render inline
            try:
                import unsubscribe_ui  # noqa: F401
                # find any callable that looks like a renderer
                import inspect
                mod = __import__("unsubscribe_ui")
                candidates = [f for name, f in inspect.getmembers(mod, inspect.isfunction)
                              if not name.startswith("_") and name != "st"]
                if candidates:
                    candidates[0]()
                else:
                    st.info("unsubscribe_ui module loaded but no public render function found.")
            except Exception as e:
                st.error(f"Churn module: {e}")


# ═════════════════════════════════════════════════════════════════
# PAGE 6: CROSS-PLATFORM (combined view — new)
# ═════════════════════════════════════════════════════════════════
def render_cross_page(user_email: str = "") -> None:
    _hero("🔗", "Cross-Platform Intelligence",
          "Unified view across KPI, GA4, YouTube, LinkedIn & Customer Success.")
    _period_banner()

    with page_error_boundary("Cross-Platform"):
        try:
            from cross_platform_engine import get_unified_snapshot
            snapshot = get_unified_snapshot()

            st.markdown('<p class="e3-section-title">All-Platform Overview</p>',
                        unsafe_allow_html=True)
            cols = st.columns(4)
            metrics = [
                ("👥 KPI Sign-ups", snapshot.get("kpi_signups", 0)),
                ("💳 KPI Paid",     snapshot.get("kpi_payments", 0)),
                ("🌐 GA4 Sessions", snapshot.get("ga4_sessions", 0)),
                ("▶ YT Subs",       snapshot.get("youtube_subs", 0)),
            ]
            for c, (label, val) in zip(cols, metrics):
                c.metric(label, f"{val:,}" if isinstance(val, (int, float)) else str(val))

            cols2 = st.columns(4)
            metrics2 = [
                ("👁 YT Views",     snapshot.get("youtube_views", 0)),
                ("💼 LI Followers", snapshot.get("linkedin_followers", 0)),
                ("📣 LI Posts",     snapshot.get("linkedin_posts", 0)),
                ("🎯 CS Rows",      snapshot.get("cs_rows", 0)),
            ]
            for c, (label, val) in zip(cols2, metrics2):
                c.metric(label, f"{val:,}" if isinstance(val, (int, float)) else str(val))

            st.markdown("---")
            if "correlations" in snapshot:
                st.markdown("### 🔗 Cross-Platform Correlations")
                st.write(snapshot["correlations"])
        except ImportError:
            # Fallback: compute inline
            _render_cross_inline()


def _render_cross_inline() -> None:
    """Compute cross-platform metrics inline when engine missing."""
    from mongo_client import count_accepted, count_docs, find_all, find_one

    period = get_period()
    sign = count_accepted("signups", "signup_date",
                           date_gte=period.start_iso(), date_lte=period.end_iso())
    pay  = count_accepted("payments", "first_payment_date",
                           date_gte=period.start_iso(), date_lte=period.end_iso())
    yt   = find_one("youtube_channel", {}) or {}
    li   = (find_all("linkedin_highlights_daily", sort=[("snapshot_date", -1)],
                     limit=1) or [{}])[0]
    cs   = count_docs("customer_success_master")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👥 Sign-ups (period)", f"{sign:,}")
    c2.metric("💳 Paid (period)",      f"{pay:,}")
    c3.metric("▶ YT Subs",              f"{int(yt.get('subscribers', 0) or 0):,}")
    c4.metric("💼 LI Followers",        f"{int(li.get('total_followers', 0) or 0):,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("👁 YT Views",     f"{int(yt.get('view_count', 0) or 0):,}")
    c6.metric("🎬 YT Videos",    f"{int(yt.get('video_count', 0) or 0):,}")
    c7.metric("👁 LI Impressions", f"{int(li.get('impressions', 0) or 0):,}")
    c8.metric("🎯 CS Records",    f"{cs:,}")

    st.info(
        "💡 To enable full cross-platform correlations, ensure "
        "`cross_platform_engine.get_unified_snapshot()` exists in your codebase."
    )


# ═════════════════════════════════════════════════════════════════
# PAGE 7: AI INSIGHTS — delegate to your existing AI assistant UI
# ═════════════════════════════════════════════════════════════════
def render_ai_page(user_email: str = "") -> None:
    _hero("✦", "AI Insights",
          "Multi-turn memory · streaming · live queries · chart generation.")

    with page_error_boundary("AI"):
        tabs = st.tabs([
            "🚀 Enhanced Chat",
            "💬 Legacy Chat (All)",
            "📊 Legacy KPI",
        ])

        with tabs[0]:
            try:
                from ai_enhanced_ui import render_ai_enhanced_page
                render_ai_enhanced_page(user_email)
            except Exception as e:
                st.error(f"Enhanced AI error: {e}")
                import traceback
                with st.expander("Traceback"):
                    st.code(traceback.format_exc())

        with tabs[1]:
            st.info("Legacy chat kept for reference. Use Enhanced Chat above for best results.")
            with st.expander("Show legacy chat (All)", expanded=False):
                _safe_call(lambda: __import__("ai_assistant_ui").render_ai_assistant,
                           default_platform="all")

        with tabs[2]:
            st.info("Legacy KPI chat. Use Enhanced Chat above for best results.")
            with st.expander("Show legacy KPI chat", expanded=False):
                _safe_call(lambda: __import__("ai_assistant_ui").render_ai_assistant,
                           default_platform="kpi")


# ═════════════════════════════════════════════════════════════════
# PAGE 8: CUSTOM MODULES — user-created dashboards from sheets
# ═════════════════════════════════════════════════════════════════
def render_custom_page(user_email: str = "") -> None:
    _hero("🧩", "Custom Modules",
          "Upload any Google Sheet / Excel → auto-generated dashboard.")

    with page_error_boundary("Custom Modules"):
        try:
            from custom_modules_engine import list_modules
            modules = list_modules() or []
        except Exception:
            modules = []

        tabs_labels = ["⚙️ Manage"] + [m.get("name", m.get("slug", "?")) for m in modules]
        tabs = st.tabs(tabs_labels)

        with tabs[0]:
            _safe_call(lambda: __import__("custom_modules_ui").render_custom_module_settings)

        for i, m in enumerate(modules):
            with tabs[i + 1]:
                _safe_call(lambda slug=m.get("slug"): __import__("custom_modules_ui").render_custom_module_page,
                           m.get("slug"))
