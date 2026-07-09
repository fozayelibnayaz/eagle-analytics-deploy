#!/usr/bin/env python3
"""Trend Analysis UI - MoM comparison with quality vs quantity insights"""

import streamlit as st
import pandas as pd
import plotly.express as px

def _safe_df(rows):
    """Convert rows to DataFrame with all object columns as string (Arrow-safe)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].astype(str)
    return df




def _format_metric_card(label, current, previous, delta, delta_pct, format_str="{:,.0f}"):
    """Render a metric card with current value + delta vs previous month."""
    cur_str = format_str.format(current)
    if delta_pct is None:
        delta_str = "no prev data"
    else:
        sign = "+" if delta_pct >= 0 else ""
        delta_str = f"{sign}{delta_pct:.1f}% vs last mo"
    return st.metric(label, cur_str, delta_str)


def render_trend_section(platform="kpi", current_month=None):
    """Render trend analysis for any platform."""
    from trend_analysis_engine import (
        get_full_trend_kpi, get_full_trend_linkedin,
        get_full_trend_ga4, get_full_trend_youtube,
    )

    if platform == "kpi":
        data = get_full_trend_kpi(current_month)
        st.markdown("### 📈 KPI Month vs Month Trend")
        if not data:
            st.info("No data")
            return
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            s = data.get("signups", {})
            _format_metric_card("Sign-ups", s.get("current_value", 0), s.get("previous_value", 0), s.get("delta"), s.get("delta_pct"))
        with c2:
            u = data.get("uploads", {})
            _format_metric_card("Uploads", u.get("current_value", 0), u.get("previous_value", 0), u.get("delta"), u.get("delta_pct"))
        with c3:
            p = data.get("paid", {})
            _format_metric_card("Paid", p.get("current_value", 0), p.get("previous_value", 0), p.get("delta"), p.get("delta_pct"))
        with c4:
            r = data.get("revenue", {})
            _format_metric_card("Revenue", r.get("current_value", 0), r.get("previous_value", 0), r.get("delta"), r.get("delta_pct"), "${:,.2f}")

        with st.expander("📊 Side-by-side comparison"):
            rows = []
            for metric_name in ["signups", "uploads", "paid", "revenue"]:
                m = data.get(metric_name, {})
                rows.append({
                    "Metric":         metric_name.title(),
                    "Current Month":  m.get("current_value", 0),
                    "Previous Month": m.get("previous_value", 0),
                    "Delta":          m.get("delta", 0),
                    "% Change":       f"{m.get('delta_pct', 0):.1f}%" if m.get("delta_pct") is not None else "—",
                })
            st.dataframe(pd.DataFrame(rows).astype(str), width='stretch', hide_index=True)

    elif platform == "linkedin":
        data = get_full_trend_linkedin(current_month)
        st.markdown("### 📈 LinkedIn Month vs Month Trend")
        if not data or not data.get("metrics"):
            st.info("No LinkedIn snapshot data yet - run pipeline first")
            return
        metrics = data["metrics"]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            m = metrics.get("impressions", {})
            _format_metric_card("Impressions", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))
        with c2:
            m = metrics.get("reactions", {})
            _format_metric_card("Reactions", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))
        with c3:
            m = metrics.get("comments", {})
            _format_metric_card("Comments", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))
        with c4:
            m = metrics.get("posts_active", {})
            _format_metric_card("Posts Active", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))

        # Quality vs quantity insight
        eff = data.get("efficiency", {}).get("impressions_per_post", {})
        if eff:
            st.markdown("#### 🎯 Quality vs Quantity Insight")
            qc1, qc2, qc3 = st.columns(3)
            qc1.metric("Impressions/Post (current)", f"{eff.get('current', 0):,.0f}")
            qc2.metric("Impressions/Post (previous)", f"{eff.get('previous', 0):,.0f}")
            qc3.metric("Δ Quality", f"{eff.get('delta_pct', 0):+.1f}%" if eff.get('delta_pct') is not None else "—")
            st.info(f"💡 **Insight:** {eff.get('interpretation', 'N/A')}")

            posts_now = metrics.get("posts_active", {}).get("current", 0)
            posts_prev = metrics.get("posts_active", {}).get("previous", 0)
            imps_now = metrics.get("impressions", {}).get("current", 0)
            imps_prev = metrics.get("impressions", {}).get("previous", 0)
            st.caption(
                f"Last month: **{posts_prev} posts** got **{imps_prev:,} impressions** "
                f"({(imps_prev / posts_prev if posts_prev else 0):.0f}/post)  \n"
                f"This month: **{posts_now} posts** got **{imps_now:,} impressions** "
                f"({(imps_now / posts_now if posts_now else 0):.0f}/post)"
            )

        with st.expander("📊 All LinkedIn metrics comparison"):
            rows = []
            for k, v in metrics.items():
                rows.append({
                    "Metric": k,
                    "Current": v.get("current", 0),
                    "Previous": v.get("previous", 0),
                    "Δ": v.get("delta", 0),
                    "% Change": f"{v.get('delta_pct', 0):+.1f}%" if v.get("delta_pct") is not None else "—",
                })
            st.dataframe(pd.DataFrame(rows).astype(str), width='stretch', hide_index=True)

    elif platform == "ga4":
        data = get_full_trend_ga4(current_month)
        st.markdown("### 📈 GA4 Month vs Month Trend")
        if not data or data.get("error"):
            st.warning(data.get("error", "No GA4 data"))
            return
        metrics = data.get("metrics", {})
        c1, c2, c3 = st.columns(3)
        with c1:
            m = metrics.get("sessions", {})
            _format_metric_card("Sessions", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))
        with c2:
            m = metrics.get("users", {})
            _format_metric_card("Users", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))
        with c3:
            m = metrics.get("pageviews", {})
            _format_metric_card("Pageviews", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))

    elif platform == "youtube":
        data = get_full_trend_youtube(current_month)
        st.markdown("### 📈 YouTube Month vs Month Trend")
        if not data or data.get("error"):
            st.warning(data.get("error", "No YouTube data"))
            return
        metrics = data.get("metrics", {})
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            m = metrics.get("views", {})
            _format_metric_card("Views", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))
        with c2:
            m = metrics.get("watch_hours", {})
            _format_metric_card("Watch Hours", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"), "{:,.1f}")
        with c3:
            m = metrics.get("subscribers_gained", {})
            _format_metric_card("Subs Gained", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))
        with c4:
            m = metrics.get("videos_published", {})
            _format_metric_card("Videos Published", m.get("current", 0), m.get("previous", 0), m.get("delta"), m.get("delta_pct"))

        # Quality vs quantity for YouTube
        vids = metrics.get("videos_published", {})
        views = metrics.get("views", {})
        if vids and views:
            cur_v = vids.get("current", 0)
            prev_v = vids.get("previous", 0)
            cur_views = views.get("current", 0)
            prev_views = views.get("previous", 0)
            cur_eff = (cur_views / cur_v) if cur_v else 0
            prev_eff = (prev_views / prev_v) if prev_v else 0
            delta_pct = ((cur_eff - prev_eff) / prev_eff * 100) if prev_eff else None
            st.markdown("#### 🎯 YouTube Quality vs Quantity")
            qc1, qc2, qc3 = st.columns(3)
            qc1.metric("Views/Video (current)", f"{cur_eff:,.0f}")
            qc2.metric("Views/Video (previous)", f"{prev_eff:,.0f}")
            qc3.metric("Δ Quality", f"{delta_pct:+.1f}%" if delta_pct is not None else "—")
