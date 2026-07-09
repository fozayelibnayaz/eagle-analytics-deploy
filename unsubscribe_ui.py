#!/usr/bin/env python3
"""Unsubscribe / Churn Analytics UI"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter, defaultdict


import os
import re
import json
from datetime import datetime, timedelta, date

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





def _func():
    st.markdown("### 🔻 Unsubscribe & Churn Analytics")
    st.caption("Track customer cancellations, reasons, and lost revenue")

    try:
        from unsubscribe_analytics import compute_churn_metrics, get_ai_churn_insight, save_to_db
    except ImportError:
        st.error("unsubscribe_analytics.py not found")
        return

    days = st.selectbox("Analysis period", [30, 60, 90, 180, 365], index=2, key="unsub_days")

    if st.button("🔄 Fetch Stripe Cancellations", key="unsub_fetch"):
        with st.spinner(f"Fetching last {days} days from Stripe..."):
            metrics = compute_churn_metrics(days=days)
            st.session_state["unsub_metrics"] = metrics
            save_to_db(metrics)

    metrics = st.session_state.get("unsub_metrics")
    if not metrics:
        st.info("Click 'Fetch Stripe Cancellations' to start. Requires STRIPE_SECRET_KEY in secrets.")
        return

    if metrics.get("error"):
        st.error(f"Error: {metrics['error']}")
        st.caption("Add STRIPE_SECRET_KEY (sk_live_... or sk_test_...) to Streamlit secrets")
        return

    # ── ALERT BANNER ──
    if metrics.get("alert"):
        st.error(metrics["alert"])

    # ── TOP METRICS ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👥 Active Subs",      f"{metrics['active_subscriptions']:,}")
    c2.metric("❌ Cancels (period)", f"{metrics['canceled_total']:,}")
    c3.metric("📉 Churn Rate (mo)",  f"{metrics['monthly_churn_rate']}%")
    c4.metric("⏱️ Avg Lifetime",     f"{metrics['avg_subscription_days']:.0f}d")

    # ── MONTH COMPARISON ──
    st.subheader("📅 This Month vs Last Month")
    m1, m2, m3 = st.columns(3)
    delta_count = metrics['canceled_this_month'] - metrics['canceled_last_month']
    m1.metric("Cancels This Month", metrics['canceled_this_month'], f"{delta_count:+d} vs last")
    m2.metric("Cancels Last Month", metrics['canceled_last_month'])
    delta_mrr = metrics['lost_mrr_delta']
    m3.metric("Lost MRR This Mo", f"${metrics['lost_mrr_this_month']:,.2f}", f"${delta_mrr:+,.2f} vs last")

    # ── CANCEL REASONS ──
    st.subheader("🎯 Why People Cancel")
    rc1, rc2 = st.columns(2)
    with rc1:
        reasons = metrics.get("cancel_reasons", {})
        if reasons:
            df = pd.DataFrame([{"Reason": k, "Count": v} for k, v in reasons.items()])
            fig = px.pie(df, values="Count", names="Reason", title="Cancellation Reasons")
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No reasons captured. Enable 'Cancellation reason' in Stripe Customer Portal settings.")
    with rc2:
        feedback = metrics.get("cancel_feedback", {})
        if feedback:
            df = pd.DataFrame([{"Feedback": k, "Count": v} for k, v in feedback.items()])
            fig = px.bar(df, x="Feedback", y="Count", title="Cancellation Feedback")
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No feedback captured. Stripe → Customer Portal → Cancellation reasons")

    # ── DAILY TIMELINE ──
    if metrics.get("daily_timeline"):
        st.subheader("📊 Daily Cancellation Timeline")
        df = pd.DataFrame(metrics["daily_timeline"])
        fig = px.bar(df, x="date", y="canceled", title=f"Daily Cancellations - Last {days} Days", color="canceled")
        st.plotly_chart(fig, width='stretch')

    # ── CUSTOMER COMMENTS ──
    if metrics.get("comments"):
        st.subheader("💬 Customer Exit Comments")
        for c in metrics["comments"][:15]:
            with st.container():
                st.markdown(f"**📅 {c.get('date', 'N/A')}** | Feedback: `{c.get('feedback', 'N/A')}` | Amount: ${c.get('amount', 0):.2f}")
                st.info(c.get("comment", ""))

    # ── AI INSIGHT ──
    st.subheader("🤖 AI Churn Strategist")
    if st.button("Generate AI Insight (Groq)", key="churn_ai"):
        with st.spinner("AI analyzing churn patterns..."):
            insight = get_ai_churn_insight(metrics)
        st.markdown(insight)

    st.divider()
    st.caption("💡 To capture cancellation reasons: Stripe Dashboard → Settings → Customer Portal → enable 'Ask for a cancellation reason'")
