#!/usr/bin/env python3
"""Customer Success Dashboard - reads from MongoDB"""
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


def render_customer_success():
    st.markdown('<div class="sec-head">🎯 Customer Success Hub</div>', unsafe_allow_html=True)
    st.caption("Unified view: CS Sheet + Signups + Uploads + Payments + Stripe Live")

    sb = _get_sb()
    if sb is None:
        st.error("MongoDB not configured")
        return

    # ── Action bar ──
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("🔄 Run Full Pipeline", key="cs_run"):
            with st.spinner("Scraping CS sheet + enriching..."):
                try:
                    from customer_success_scraper import run_full_pipeline
                    res = run_full_pipeline()
                    st.success(f"Done: {res}")
                except Exception as e:
                    st.error(f"Error: {e}")
    with c2:
        if st.button("📥 Scrape Sheet Only", key="cs_scrape"):
            with st.spinner("Scraping..."):
                try:
                    from customer_success_scraper import scrape_all_tabs, upsert_to_db
                    s = scrape_all_tabs()
                    if s.get("error"):
                        st.error(s["error"])
                    else:
                        u = upsert_to_db(s)
                        st.success(f"Scraped {len(s.get('tabs', {}))} tabs, {u}")
                except Exception as e:
                    st.error(f"Error: {e}")
    with c3:
        if st.button("💳 Enrich Stripe", key="cs_stripe"):
            with st.spinner("Fetching Stripe..."):
                try:
                    from customer_success_scraper import enrich_stripe_live
                    r = enrich_stripe_live()
                    st.success(str(r))
                except Exception as e:
                    st.error(f"Error: {e}")
    with c4:
        if st.button("🔃 Refresh View", key="cs_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── Count summary ──
    try:
        cs_cnt = sb.table("customer_success_master").select("count", count="exact").execute().count
        en_cnt = sb.table("customer_success_enriched").select("count", count="exact").execute().count
    except Exception:
        cs_cnt, en_cnt = 0, 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📋 CS Rows", f"{cs_cnt:,}")
    m2.metric("👤 Enriched Customers", f"{en_cnt:,}")
    try:
        active = sb.table("customer_success_enriched").select("count", count="exact").eq("subscription_status", "active").execute().count
        m3.metric("✅ Active Subs", f"{active:,}")
    except Exception:
        m3.metric("✅ Active Subs", "—")
    try:
        canceled = sb.table("customer_success_enriched").select("count", count="exact").eq("subscription_status", "canceled").execute().count
        m4.metric("❌ Canceled", f"{canceled:,}")
    except Exception:
        m4.metric("❌ Canceled", "—")

    st.divider()

    # ── Tabs ──
    tabs = st.tabs(["📊 Master View", "🔗 Enriched Funnel", "📋 CS Sheet by Tab", "💳 Stripe Live", "🎯 At-Risk Customers", "📊 Deep Analytics"])

    # ── TAB 1: MASTER VIEW ──
    with tabs[0]:
        st.subheader("All Customer Success Data + Funnel")
        try:
            enriched = sb.table("customer_success_enriched").select("*").order("first_payment_date", desc=True).limit(2000).execute().data
        except Exception as e:
            st.error(f"Read error: {e}")
            enriched = []

        if not enriched:
            st.info("No enriched data yet. Click 'Run Full Pipeline'.")
        else:
            df = pd.DataFrame(enriched)
            search = st.text_input("🔍 Search email", key="cs_search")
            if search:
                df = df[df["email"].str.contains(search, case=False, na=False)]
            status = st.selectbox("Filter by status",
                                  ["All", "active", "canceled", "trialing", "past_due"],
                                  key="cs_filter")
            if status != "All":
                df = df[df["subscription_status"] == status]

            display_cols = [c for c in [
                "email", "subscription_status", "mrr", "total_spend", "payment_count",
                "signup_date", "first_upload_date", "first_payment_date",
                "days_signup_to_upload", "days_signup_to_paid",
                "lead_source", "stripe_delinquent",
            ] if c in df.columns]
            st.dataframe(df[display_cols], width='stretch', hide_index=True)

    # ── TAB 2: ENRICHED FUNNEL ──
    with tabs[1]:
        st.subheader("Customer Funnel Analysis")
        try:
            enr = sb.table("customer_success_enriched").select("signup_date,first_upload_date,first_payment_date,days_signup_to_upload,days_signup_to_paid").execute().data
        except Exception:
            enr = []

        if enr:
            df = pd.DataFrame(enr)
            total = len(df)
            with_signup = df["signup_date"].notna().sum()
            with_upload = df["first_upload_date"].notna().sum()
            with_paid = df["first_payment_date"].notna().sum()
            fc1, fc2, fc3, fc4 = st.columns(4)
            fc1.metric("Total in CS", f"{total:,}")
            fc2.metric("Signed Up", f"{with_signup:,}", f"{with_signup/total*100:.0f}%")
            fc3.metric("Uploaded", f"{with_upload:,}", f"{with_upload/total*100:.0f}%")
            fc4.metric("Paid", f"{with_paid:,}", f"{with_paid/total*100:.0f}%")

            # Funnel chart
            funnel_df = pd.DataFrame({
                "stage": ["In CS Sheet", "Signed Up", "First Uploaded", "First Paid"],
                "count": [total, with_signup, with_upload, with_paid],
            })
            fig = px.funnel(funnel_df, x="count", y="stage", title="Customer Funnel")
            st.plotly_chart(fig, width='stretch')

            # Time-to-conversion distributions
            if "days_signup_to_upload" in df.columns:
                valid = df["days_signup_to_upload"].dropna()
                if len(valid):
                    st.markdown("**⏱ Days from Signup → First Upload**")
                    st.write(f"Avg: {valid.mean():.1f} days | Median: {valid.median():.0f} | Max: {valid.max():.0f}")
                    fig = px.histogram(valid, nbins=30, title="Time to First Upload")
                    st.plotly_chart(fig, width='stretch')

            if "days_signup_to_paid" in df.columns:
                valid = df["days_signup_to_paid"].dropna()
                if len(valid):
                    st.markdown("**⏱ Days from Signup → Paid**")
                    st.write(f"Avg: {valid.mean():.1f} days | Median: {valid.median():.0f} | Max: {valid.max():.0f}")
                    fig = px.histogram(valid, nbins=30, title="Time to Paid")
                    st.plotly_chart(fig, width='stretch')
        else:
            st.info("No data yet")

    # ── TAB 3: CS SHEET BY TAB ──
    with tabs[2]:
        st.subheader("Raw Customer Success Sheet Data")
        try:
            tabs_data = sb.table("customer_success_master").select("tab_name,tab_slug").execute().data
            unique_tabs = sorted(set(t["tab_name"] for t in tabs_data if t.get("tab_name")))
        except Exception:
            unique_tabs = []

        if unique_tabs:
            sel_tab = st.selectbox("Select tab", unique_tabs, key="cs_tab_sel")
            try:
                rows = sb.table("customer_success_master").select("*").eq("tab_name", sel_tab).execute().data
                if rows:
                    expanded = []
                    for r in rows:
                        rd = r.get("row_data", {}) or {}
                        expanded.append({**rd, "_email_detected": r.get("email", ""), "_scraped": r.get("scraped_at", "")[:10]})
                    df = pd.DataFrame(expanded)
                    st.dataframe(df, width='stretch', hide_index=True)
                    st.caption(f"{len(df)} rows in {sel_tab}")
            except Exception as e:
                st.error(f"Error: {e}")
        else:
            st.info("No tabs scraped yet")

    # ── TAB 4: STRIPE LIVE ──
    with tabs[3]:
        st.subheader("Stripe Live Data (per customer)")
        try:
            stripe_rows = sb.table("customer_success_enriched").select("email,stripe_customer_id,subscription_status,mrr,stripe_balance,stripe_delinquent,total_spend,payment_count,stripe_enriched_at").not_.is_("stripe_customer_id", "null").order("mrr", desc=True).limit(500).execute().data
            if stripe_rows:
                df = pd.DataFrame(stripe_rows)
                st.dataframe(df, width='stretch', hide_index=True)
                total_mrr = sum(r.get("mrr", 0) or 0 for r in stripe_rows)
                st.metric("Total MRR (Stripe live)", f"${total_mrr:,.2f}")
            else:
                st.info("No Stripe enrichment yet. Click 'Enrich Stripe'.")
        except Exception as e:
            st.error(f"Error: {e}")

    # ── TAB 5: AT-RISK ──
    with tabs[4]:
        st.subheader("🎯 At-Risk Customers")
        st.caption("Customers showing churn risk signals")
        try:
            at_risk = sb.table("customer_success_enriched").select("*").or_("stripe_delinquent.eq.true,subscription_status.eq.past_due").execute().data
            canceled = sb.table("customer_success_enriched").select("*").eq("subscription_status", "canceled").order("enriched_at", desc=True).limit(50).execute().data

            ar1, ar2 = st.columns(2)
            ar1.metric("🚨 Delinquent/Past Due", len(at_risk))
            ar2.metric("❌ Recently Canceled", len(canceled))

            if at_risk:
                st.markdown("**🚨 Active At-Risk**")
                st.dataframe(pd.DataFrame(at_risk)[["email", "subscription_status", "mrr", "stripe_delinquent", "total_spend"]],
                             width='stretch', hide_index=True)
            if canceled:
                st.markdown("**❌ Recently Canceled**")
                st.dataframe(pd.DataFrame(canceled)[["email", "first_payment_date", "total_spend", "payment_count"]],
                             width='stretch', hide_index=True)
        except Exception as e:
            st.error(f"Error: {e}")


    # ── TAB 6: DEEP ANALYTICS ──
    with tabs[5]:
        try:
            from customer_success_analytics_ui import render_cs_analytics
            render_cs_analytics()
        except Exception as _ae:
            st.error(f"Analytics error: {_ae}")
            import traceback
            st.code(traceback.format_exc()[:2000])
