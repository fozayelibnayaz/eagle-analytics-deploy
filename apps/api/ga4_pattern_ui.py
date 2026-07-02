#!/usr/bin/env python3
"""GA4 Pattern Analysis - region + time + anomalies"""
import streamlit as st
import pandas as pd
import plotly.express as px
import os
import json
import urllib.request
from datetime import datetime, timedelta
from collections import Counter, defaultdict


def _get_ga4_client():
    """Get authenticated GA4 client."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2 import service_account
    except ImportError:
        return None
    creds = None
    try:
        sa = dict(st.secrets["ga4_service_account"])
        if "private_key" in sa:
            sa["private_key"] = sa["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(
            sa, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    except Exception:
        pass
    if not creds:
        try:
            creds = service_account.Credentials.from_service_account_file(
                "google_creds.json",
                scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        except Exception:
            return None
    return BetaAnalyticsDataClient(credentials=creds)


def _ga4_property_id():
    pid = os.environ.get("GA4_PROPERTY_ID", "")
    if not pid:
        try:
            pid = str(st.secrets.get("GA4_PROPERTY_ID", "")).strip()
        except Exception:
            pass
    return pid or "374525971"


def render_ga4_pattern_analysis():
    st.markdown("### 📊 GA4 Pattern Analysis - Region + Time + Anomalies")
    st.caption("Analyzing website traffic by country, region, and time patterns")

    client = _get_ga4_client()
    pid = _ga4_property_id()
    if not client or not pid:
        st.error("GA4 client not available. Check ga4_service_account in secrets.")
        return

    try:
        from google.analytics.data_v1beta.types import (
            RunReportRequest, DateRange, Dimension, Metric, OrderBy
        )
    except ImportError:
        st.error("google.analytics.data_v1beta not installed")
        return

    # Period selector
    period = st.selectbox("📅 Period", [
        "Last 7 Days", "Last 28 Days", "Last 30 Days", "Last 90 Days",
        "Last 365 Days", "This Year", "All Time (last 2 yrs)"
    ], index=3, key="ga4_pattern_period")

    days_map = {
        "Last 7 Days": 7, "Last 28 Days": 28, "Last 30 Days": 30,
        "Last 90 Days": 90, "Last 365 Days": 365, "This Year": 365,
        "All Time (last 2 yrs)": 730,
    }
    days = days_map.get(period, 90)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    with st.spinner(f"Loading GA4 data for {period}..."):
        # 1. Country distribution
        try:
            req_geo = RunReportRequest(
                property=f"properties/{pid}",
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="country")],
                metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
                limit=50,
            )
            geo_resp = client.run_report(req_geo)
            geo_data = []
            for row in geo_resp.rows:
                geo_data.append({
                    "country": row.dimension_values[0].value,
                    "sessions": int(row.metric_values[0].value),
                    "users": int(row.metric_values[1].value),
                })
        except Exception as e:
            st.error(f"Geo data error: {e}")
            return

        # 2. Time patterns - daily breakdown
        try:
            req_daily = RunReportRequest(
                property=f"properties/{pid}",
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="date")],
                metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
                order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
            )
            daily_resp = client.run_report(req_daily)
            daily_data = []
            for row in daily_resp.rows:
                d = row.dimension_values[0].value
                dt = datetime.strptime(d, "%Y%m%d")
                daily_data.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "datetime": dt,
                    "month": dt.strftime("%B"),
                    "day_of_week": dt.strftime("%A"),
                    "year": dt.year,
                    "sessions": int(row.metric_values[0].value),
                    "users": int(row.metric_values[1].value),
                })
        except Exception as e:
            st.error(f"Daily data error: {e}")
            return

    # ── Regional Distribution ──
    st.subheader("🌍 Regional Distribution")
    total_sessions = sum(g["sessions"] for g in geo_data)
    total_users = sum(g["users"] for g in geo_data)

    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Total Sessions", f"{total_sessions:,}")
    rc2.metric("Total Users", f"{total_users:,}")
    rc3.metric("Countries", len(geo_data))

    if geo_data:
        df_geo = pd.DataFrame(geo_data)
        col_a, col_b = st.columns([2, 1])
        with col_a:
            fig = px.bar(df_geo.head(15), x="country", y="sessions",
                         title="Top 15 Countries by Sessions",
                         color="sessions", color_continuous_scale="Viridis",
                         text="sessions")
            fig.update_traces(textposition="outside")
            fig.update_layout(xaxis_tickangle=-45, height=400)
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            df_geo_display = df_geo.head(15).copy()
            df_geo_display["%"] = (df_geo_display["sessions"] / total_sessions * 100).round(1)
            st.dataframe(df_geo_display, use_container_width=True, hide_index=True)

    # ── Time Patterns ──
    if daily_data:
        df = pd.DataFrame(daily_data)
        st.subheader("📅 Time Patterns")

        # Peak month
        month_order = ["January","February","March","April","May","June",
                       "July","August","September","October","November","December"]
        by_month = df.groupby("month")["sessions"].sum().reindex(month_order).fillna(0)
        peak_month = by_month.idxmax()
        peak_month_val = int(by_month.max())
        low_month = by_month.idxmin()
        low_month_val = int(by_month.min())

        # Peak day of week
        dow_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        by_dow = df.groupby("day_of_week")["sessions"].sum().reindex(dow_order).fillna(0)
        peak_dow = by_dow.idxmax()
        peak_dow_val = int(by_dow.max())

        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("📆 Peak Month", peak_month, f"{peak_month_val:,} sessions")
        tc2.metric("📅 Peak Day", peak_dow, f"{peak_dow_val:,} sessions")
        tc3.metric("📊 Date Range", f"{df['date'].min()} -> {df['date'].max()}")

        # Monthly distribution
        st.markdown("**Sessions by Month**")
        df_month = pd.DataFrame({"Month": by_month.index, "Sessions": by_month.values.astype(int)})
        fig = px.bar(df_month, x="Month", y="Sessions",
                     color="Sessions", color_continuous_scale="Blues",
                     text="Sessions")
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        st.info(
            f"🔥 **Highest traffic month:** {peak_month} ({peak_month_val:,} sessions)  \n"
            f"❄️ **Lowest traffic month:** {low_month} ({low_month_val:,} sessions)  \n"
            f"📈 **Seasonal swing:** {(peak_month_val - low_month_val) / max(low_month_val, 1) * 100:.0f}% more in peak vs trough"
        )

        # Day of week
        st.markdown("**Sessions by Day of Week**")
        df_dow = pd.DataFrame({"Day": by_dow.index, "Sessions": by_dow.values.astype(int)})
        fig = px.bar(df_dow, x="Day", y="Sessions",
                     color="Sessions", color_continuous_scale="Plasma",
                     text="Sessions")
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        # Yearly trend
        st.markdown("**Yearly Trend**")
        by_year = df.groupby("year")["sessions"].sum().reset_index()
        if len(by_year) >= 1:
            col_y1, col_y2 = st.columns([2, 1])
            with col_y1:
                fig = px.line(by_year, x="year", y="sessions",
                              title="GA4 Sessions by Year", markers=True, text="sessions")
                fig.update_traces(textposition="top center")
                st.plotly_chart(fig, use_container_width=True)
            with col_y2:
                st.dataframe(by_year, use_container_width=True, hide_index=True)

        # Monthly timeline
        st.markdown("**Monthly Timeline**")
        df["year_month"] = df["datetime"].dt.strftime("%Y-%m")
        by_ym = df.groupby("year_month")["sessions"].sum().reset_index()
        fig = px.line(by_ym, x="year_month", y="sessions",
                      title="GA4 Sessions Monthly Timeline", markers=True)
        fig.update_layout(xaxis_tickangle=-45, height=400)
        st.plotly_chart(fig, use_container_width=True)

        # Fluctuations
        st.subheader("⚡ Fluctuation & Anomaly Detection")
        values = df["sessions"].values
        mean = values.mean()
        std = values.std()
        spike_threshold = mean + 2 * std
        drop_threshold = max(0, mean - 2 * std)
        spikes = df[df["sessions"] > spike_threshold].sort_values("sessions", ascending=False)
        drops = df[df["sessions"] < drop_threshold].sort_values("sessions")

        fc1, fc2, fc3, fc4 = st.columns(4)
        fc1.metric("📈 Avg Sessions/Day", f"{mean:.0f}")
        fc2.metric("📊 Std Dev", f"{std:.0f}")
        fc3.metric("🚀 Spike Days", len(spikes))
        fc4.metric("📉 Drop Days", len(drops))

        col_s, col_d = st.columns(2)
        with col_s:
            st.markdown("**🚀 Top 10 Best Days**")
            top10 = df.sort_values("sessions", ascending=False).head(10)
            st.dataframe(top10[["date","sessions","users"]], use_container_width=True, hide_index=True)
        with col_d:
            st.markdown("**📉 Bottom 10 Slow Days**")
            bottom10 = df.sort_values("sessions").head(10)
            st.dataframe(bottom10[["date","sessions","users"]], use_container_width=True, hide_index=True)

        if len(spikes) > 0:
            with st.expander(f"🚀 All {len(spikes)} spike days (>2 sigma above mean)"):
                st.dataframe(spikes[["date","sessions","users"]], use_container_width=True, hide_index=True)

    # AI Insight
    st.subheader("🤖 AI Pattern Insight")
    if st.button("Generate AI insight for GA4 traffic", key="ga4_ai_insight"):
        with st.spinner("AI analyzing GA4 patterns..."):
            insight = _ga4_ai_insight(geo_data, daily_data if daily_data else [])
        st.markdown(insight)


def _ga4_ai_insight(geo_data, daily_data):
    groq_key = os.environ.get("GROQ_API_KEY","")
    if not groq_key:
        try:
            groq_key = str(st.secrets.get("GROQ_API_KEY","")).strip()
        except Exception:
            pass
    if not groq_key:
        return "GROQ_API_KEY not configured"

    summary = {
        "total_sessions": sum(g["sessions"] for g in geo_data),
        "total_users":    sum(g["users"] for g in geo_data),
        "top_10_countries": geo_data[:10],
        "date_range":  {"start": daily_data[0]["date"] if daily_data else "", "end": daily_data[-1]["date"] if daily_data else ""},
        "days_analyzed": len(daily_data),
    }
    prompt = f"""You are a web analytics expert. Analyze this GA4 traffic data.

DATA: {json.dumps(summary, indent=2)}

Provide insights in these exact sections:

GEOGRAPHIC INSIGHT
[Which countries dominate? What does this say about target market?]

TRAFFIC TRAJECTORY
[Is traffic growing, stable, declining? What is the trend?]

SEASONAL PATTERN
[Which months/days are strongest? Why?]

ACTION PLAN
[3 specific actions to capitalize on these patterns]

Be specific. Reference actual numbers."""
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role":"system","content":"You are an expert web analytics consultant."},
                    {"role":"user","content":prompt},
                ],
                "max_tokens": 1500,
                "temperature": 0.3,
            }).encode(),
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI error: {e}"
