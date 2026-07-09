#!/usr/bin/env python3
"""

LinkedIn Command Center UI - Reads from MongoDB
Displays all data from 8 LinkedIn tables with rich visualization.
"""
from collections import Counter, defaultdict


import os
import re
import json
from datetime import datetime, timedelta, date

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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





def _get_sb():
    return get_db()


def _fetch(table, order_col=None, desc=True, limit=10000, filters=None):
    sb = _get_sb()
    if sb is None:
        return []
    try:
        q = sb.table(table).select("*")
        if filters:
            for k, v in filters.items():
                q = q.eq(k, v)
        if order_col:
            q = q.order(order_col, desc=desc)
        q = q.limit(limit)
        return q.execute().data or []
    except Exception as e:
        st.warning(f"Could not load {table}: {e}")
        return []


def render_linkedin_command_center():
    st.markdown('<div class="sec-head">💼 LinkedIn Command Center</div>', unsafe_allow_html=True)

    sb = _get_sb()
    if sb is None:
        st.error("MongoDB not configured")
        return

    # ── Period + Refresh ──
    pc1, pc2, pc3, pc4 = st.columns([2, 1, 1, 1])
    with pc1:
        period = st.selectbox("📅 Period", [
            "Today", "Last 7 Days", "Last 14 Days", "Last 28 Days",
            "Last 30 Days", "This Month", "Last Month",
            "Last 90 Days", "Last 6 Months", "Last 365 Days", "All Time",
        ], index=9, key="li_cc_period")
    with pc2:
        if st.button("🔄 Run Pipeline", key="li_run_pipeline"):
            st.info("Run locally: `python3 linkedin_daily_pipeline.py`")
    with pc3:
        if st.button("🔃 Refresh", key="li_refresh"):
            st.cache_data.clear()
            st.rerun()

    # Compute date range
    today = date.today()
    if period == "Today":
        start_date = today
    elif period == "Last 7 Days":
        start_date = today - timedelta(days=7)
    elif period == "Last 14 Days":
        start_date = today - timedelta(days=14)
    elif period == "Last 28 Days":
        start_date = today - timedelta(days=28)
    elif period == "Last 30 Days":
        start_date = today - timedelta(days=30)
    elif period == "This Month":
        start_date = today.replace(day=1)
    elif period == "Last Month":
        last_first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        start_date = last_first
    elif period == "Last 90 Days":
        start_date = today - timedelta(days=90)
    elif period == "Last 6 Months":
        start_date = today - timedelta(days=180)
    elif period == "Last 365 Days":
        start_date = today - timedelta(days=365)
    else:
        start_date = date(2024, 1, 1)
    start_str = start_date.strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    # ── HIGHLIGHTS HEADER ──
    highlights = _fetch("linkedin_highlights_daily", order_col="snapshot_date", desc=True, limit=1)
    latest = highlights[0] if highlights else {}

    st.divider()
    h1, h2, h3, h4, h5, h6 = st.columns(6)
    h1.metric("👥 Followers", f"{latest.get('total_followers', 0):,}")
    h2.metric("👁️ Impressions", f"{latest.get('impressions', 0):,}")
    h3.metric("👍 Reactions", f"{latest.get('reactions', 0):,}")
    h4.metric("💬 Comments", f"{latest.get('comments', 0):,}")
    h5.metric("🔁 Reposts", f"{latest.get('reposts', 0):,}")
    h6.metric("📧 Newsletter", f"{latest.get('newsletter_subscribers', 0):,}")

    h7, h8, h9 = st.columns(3)
    h7.metric("📄 Page Views", f"{latest.get('page_views', 0):,}")
    h8.metric("🧍 Unique Visitors", f"{latest.get('unique_visitors', 0):,}")
    h9.metric("📅 Last Sync", latest.get("snapshot_date", "Never"))

    # ── TABS ──
    tabs = st.tabs([
        "📊 Overview", "📝 All Posts", "👥 Followers Trend",
        "🧍 Visitors Trend", "🏢 Competitors", "📰 Newsletter",
        "🔍 Search Keywords", "📈 Trend Analysis",
    ])

    # ── TAB 1: OVERVIEW ──
    with tabs[0]:
        st.subheader("Latest Snapshot")
        if not highlights:
            st.info("No data yet. Run the pipeline locally to populate.")
            return

        # Highlights timeline
        all_hl = _fetch("linkedin_highlights_daily", order_col="snapshot_date")
        if len(all_hl) >= 2:
            df = pd.DataFrame(all_hl)
            df = df[df["snapshot_date"] >= start_str]
            if not df.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df["snapshot_date"], y=df["impressions"], name="Impressions", mode="lines+markers"))
                fig.add_trace(go.Scatter(x=df["snapshot_date"], y=df["reactions"], name="Reactions", mode="lines+markers", yaxis="y2"))
                fig.update_layout(
                    title="Engagement Timeline",
                    yaxis=dict(title="Impressions"),
                    yaxis2=dict(title="Reactions", overlaying="y", side="right"),
                    height=400,
                )
                st.plotly_chart(fig, width='stretch')
        else:
            st.caption(f"Only {len(all_hl)} day(s) of history. Run pipeline daily to build trend.")

    # ── TAB 2: ALL POSTS ──
    with tabs[1]:
        st.subheader("All Posts (latest snapshot per post)")
        posts = _fetch("linkedin_posts", order_col="impressions", desc=True)
        if not posts:
            st.warning("No posts in MongoDB. Check scraper logs.")
        else:
            st.caption(f"{len(posts)} posts tracked")
            df = pd.DataFrame(posts)

            # Search/filter
            search = st.text_input("🔍 Search post text", key="li_post_search")
            if search:
                df = df[df["title"].str.contains(search, case=False, na=False)]

            sort_by = st.selectbox("Sort by", [
                "impressions", "reactions", "comments", "clicks", "ctr",
                "engagement_rate", "last_updated",
            ], key="li_post_sort")
            df = df.sort_values(by=sort_by, ascending=False)

            for idx, row in df.iterrows():
                with st.container():
                    cols = st.columns([0.5, 4, 1, 1, 1])
                    cols[0].markdown(f"**{idx+1}**")
                    title = (row.get("title", "") or "")[:200]
                    cols[1].markdown(f"**{title}**")
                    cols[1].caption(f"{row.get('post_type', '')} · {row.get('audience', '')}")
                    cols[2].metric("Impr", f"{row.get('impressions', 0):,}", label_visibility="visible")
                    cols[3].metric("React", row.get('reactions', 0))
                    cols[4].metric("ER", f"{row.get('engagement_rate', 0):.1f}%")

                    # Growth history per post
                    daily_history = _fetch("linkedin_posts_daily",
                                           filters={"post_urn": row["urn"]},
                                           order_col="snapshot_date")
                    if len(daily_history) >= 2:
                        hist_df = pd.DataFrame(daily_history)
                        with st.expander(f"📈 Growth history ({len(daily_history)} snapshots)"):
                            fig = px.line(hist_df, x="snapshot_date",
                                          y=["impressions", "reactions", "comments"],
                                          title="Post Metrics Over Time")
                            st.plotly_chart(fig, width='stretch', key=f"hist_{idx}")
                    st.divider()

    # ── TAB 3: FOLLOWERS TREND ──
    with tabs[2]:
        st.subheader("Followers Growth")
        followers = _fetch("linkedin_followers_daily", order_col="snapshot_date")
        if not followers:
            st.info("No follower history yet")
        else:
            df = pd.DataFrame(followers)
            df = df[df["snapshot_date"] >= start_str]
            if not df.empty:
                c1, c2, c3 = st.columns(3)
                c1.metric("Current Total", f"{int(df['total'].iloc[-1]):,}")
                c2.metric("Total Gained (period)", f"{int(df['delta_total'].sum()):+,}")
                c3.metric("Days Tracked", len(df))

                fig = px.line(df, x="snapshot_date", y="total",
                              title="Total Followers Over Time", markers=True)
                st.plotly_chart(fig, width='stretch')

                fig2 = px.bar(df, x="snapshot_date", y="delta_total",
                              title="Daily Follower Change", color="delta_total",
                              color_continuous_scale="RdYlGn")
                st.plotly_chart(fig2, width='stretch')

                st.dataframe(df, width='stretch', hide_index=True)
            else:
                st.info(f"No data in period since {start_str}")

    # ── TAB 4: VISITORS TREND ──
    with tabs[3]:
        st.subheader("Visitors Analytics")
        visitors = _fetch("linkedin_visitors_daily", order_col="snapshot_date")
        if not visitors:
            st.info("No visitor history yet")
        else:
            df = pd.DataFrame(visitors)
            df = df[df["snapshot_date"] >= start_str]
            if not df.empty:
                c1, c2, c3 = st.columns(3)
                c1.metric("Latest Page Views", f"{int(df['page_views'].iloc[-1]):,}")
                c2.metric("Latest Unique", f"{int(df['unique_visitors'].iloc[-1]):,}")
                c3.metric("Days Tracked", len(df))

                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df["snapshot_date"], y=df["page_views"],
                                         name="Page Views", mode="lines+markers"))
                fig.add_trace(go.Scatter(x=df["snapshot_date"], y=df["unique_visitors"],
                                         name="Unique Visitors", mode="lines+markers"))
                fig.update_layout(title="Visitor Timeline", height=400)
                st.plotly_chart(fig, width='stretch')
                st.dataframe(df, width='stretch', hide_index=True)

    # ── TAB 5: COMPETITORS ──
    with tabs[4]:
        st.subheader("Competitors Comparison")
        comps = _fetch("linkedin_competitors_daily", order_col="snapshot_date", desc=True)
        if not comps:
            st.info("No competitor data yet")
        else:
            df = pd.DataFrame(comps)
            latest_date = df["snapshot_date"].max()
            latest_df = df[df["snapshot_date"] == latest_date]
            # Clean noisy rows (header rows scraped accidentally)
            latest_df = latest_df[latest_df["followers"] > 0]
            st.dataframe(latest_df[["name", "followers", "follower_growth",
                                    "post_engagements", "engagement_rate", "posts"]],
                         width='stretch', hide_index=True)

            if len(latest_df) > 0:
                fig = px.bar(latest_df, x="name", y="followers",
                             title="Competitor Followers", color="followers")
                st.plotly_chart(fig, width='stretch')

    # ── TAB 6: NEWSLETTER ──
    with tabs[5]:
        st.subheader("Newsletter Articles")
        st.metric("Subscribers", f"{latest.get('newsletter_subscribers', 0):,}")
        articles = _fetch("linkedin_newsletter_articles", order_col="last_updated")
        if articles:
            df = pd.DataFrame(articles)
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.info("No newsletter articles tracked yet")

    # ── TAB 7: SEARCH KEYWORDS ──
    with tabs[6]:
        st.subheader("Search Appearance Keywords")
        keywords = _fetch("linkedin_search_keywords", order_col="snapshot_date", desc=True)
        if keywords:
            df = pd.DataFrame(keywords)
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.info("No search keyword data yet")

    # ── TAB 8: TREND ANALYSIS ──
    with tabs[7]:
        try:
            from trend_analysis_ui import render_trend_section
            render_trend_section("linkedin")
        except Exception as e:
            st.warning(f"Trend analysis: {e}")

    st.divider()
    st.caption(f"📡 Source: MongoDB | Pipeline must run daily to update | Last data: {latest.get('snapshot_date', 'never')}")
