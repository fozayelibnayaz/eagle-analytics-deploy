#!/usr/bin/env python3
"""CS Deep Analytics UI - 15 comprehensive sections"""

import streamlit as st
import pandas as pd
import plotly.express as px


def render_cs_analytics():
    st.markdown('### 📊 Customer Success Deep Analytics')
    st.caption("Every dimension from all 9 CS sheet tabs - 15 analysis sections")

    try:
        from customer_success_analytics import get_all_insights
        with st.spinner("Computing comprehensive insights..."):
            data = get_all_insights()
    except Exception as e:
        st.error(f"Error: {e}")
        return

    sections = st.tabs([
        "💔 Churn", "📊 Health Index", "⏱️ Streaming", "🎯 Sessions",
        "📺 Last Streamed", "📅 Subscriptions", "�� Revenue",
        "🔗 Correlations", "🚫 No Sub Users",
        "📞 Contact Info", "☎️ Phone Calls", "🌍 Geography",
        "🏢 Parent Accounts", "📈 Recent Activity", "💎 Customer Tiers",
    ])

    # 1. CHURN
    with sections[0]:
        try:
            ch = data["churn"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Churned", ch["total_churned"])
            c2.metric("Monthly Revenue Lost", f"${ch['monthly_revenue_lost']:,.2f}")
            c3.metric("Annualized Loss", f"${ch['annual_revenue_lost']:,.2f}")
            if ch["by_month"]:
                df = pd.DataFrame([{"Month": m, "Churned": v} for m, v in ch["by_month"].items()])
                st.plotly_chart(px.bar(df, x="Month", y="Churned", color="Churned",
                                       color_continuous_scale="Reds", text="Churned"),
                              use_container_width=True)
            if ch["customers"]:
                st.dataframe(pd.DataFrame(ch["customers"]), use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 0 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 2. HEALTH INDEX
    with sections[1]:
        try:
            h = data["health"]
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Total Customers", h["total_customers"])
            m2.metric("Avg Recurring", h["avg_recurring"])
            m3.metric("Max Recurring", h["max_recurring"])
            m4.metric("No Payments", h["no_recurring_count"])
            c1,c2 = st.columns(2)
            with c1:
                df = pd.DataFrame([{"Plan":k,"Count":v} for k,v in h["plans"].items()])
                st.plotly_chart(px.pie(df, values="Count", names="Plan", title="Plans"), use_container_width=True)
                st.dataframe(df, use_container_width=True, hide_index=True)
            with c2:
                df = pd.DataFrame([{"Status":k,"Count":v} for k,v in h["statuses"].items()])
                st.plotly_chart(px.bar(df, x="Status", y="Count", color="Count", title="Status"), use_container_width=True)
            c3,c4 = st.columns(2)
            with c3:
                df = pd.DataFrame([{"Size":k,"Count":v} for k,v in h["company_sizes"].items()])
                st.plotly_chart(px.bar(df, x="Size", y="Count", color="Count", color_continuous_scale="Blues",
                                       title="Company Size"), use_container_width=True)
            with c4:
                df = pd.DataFrame([{"Fit":k,"Count":v} for k,v in h["perfect_fit"].items()])
                st.plotly_chart(px.pie(df, values="Count", names="Fit", title="Perfect Fit Customer"), use_container_width=True)
    
        except Exception as _se:
            st.error(f'Section 1 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 3. STREAMING
    with sections[2]:
        try:
            s = data["streaming"]
            m1,m2,m3 = st.columns(3)
            m1.metric("Active Streamers", s["active_streamers"])
            m2.metric("Non-Streamers", s["non_streamers"])
            m3.metric("Total Hours", f"{s['total_stream_hours']:,.1f}")
            if s["period_totals"]:
                df = pd.DataFrame([{"Period":k,"Hours":v} for k,v in s["period_totals"].items()])
                df["Period"] = df["Period"].str.replace("Total Stream Time ","").str[:30]
                fig = px.line(df, x="Period", y="Hours", markers=True, title="Bi-Weekly Stream Time")
                fig.update_layout(xaxis_tickangle=-45, height=400)
                st.plotly_chart(fig, use_container_width=True)
            st.subheader("Top 50 Streamers")
            st.dataframe(pd.DataFrame(s["top_50_streamers"]), use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 2 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 4. SESSIONS
    with sections[3]:
        try:
            sn = data["sessions"]
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Total Clients", sn["total_clients"])
            m2.metric("Total Sessions", f"{sn['sessions']:,}")
            m3.metric("Connected Success %", f"{sn['connected_success_rate']}%")
            m4.metric("Streamed Success %", f"{sn['streamed_success_rate']}%")
            c1,c2 = st.columns(2)
            with c1:
                df = pd.DataFrame({"Type":["Success","Failure"],
                                  "Count":[sn["connected_success"], sn["connected_failure"]]})
                st.plotly_chart(px.pie(df, values="Count", names="Type", title="Connection Success",
                                       color_discrete_map={"Success":"green","Failure":"red"}), use_container_width=True)
            with c2:
                df = pd.DataFrame({"Type":["Success","Failure"],
                                  "Count":[sn["streamed_success"], sn["streamed_failure"]]})
                st.plotly_chart(px.pie(df, values="Count", names="Type", title="Streaming Success",
                                       color_discrete_map={"Success":"green","Failure":"red"}), use_container_width=True)
            st.subheader("🏆 Top 30 Clients")
            st.dataframe(pd.DataFrame(sn["top_30_clients"]), use_container_width=True, hide_index=True)
            st.subheader("🚨 High Failure Clients (need attention)")
            if sn["high_failure_clients"]:
                st.dataframe(pd.DataFrame(sn["high_failure_clients"]), use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 3 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 5. LAST STREAMED
    with sections[4]:
        try:
            s1 = data["sheet1"]
            m1,m2 = st.columns(2)
            m1.metric("Total Customers", s1["total_customers"])
            m2.metric("Dormant Paying (30+d)", len(s1["dormant_paying"]))
            c1,c2,c3 = st.columns(3)
            with c1:
                df = pd.DataFrame([{"Color":k,"Count":v} for k,v in s1["color_dist"].items() if k])
                if not df.empty:
                    st.plotly_chart(px.pie(df, values="Count", names="Color", title="Color"), use_container_width=True)
            with c2:
                df = pd.DataFrame([{"CHI":k,"Count":v} for k,v in s1["chi_dist"].items() if k])
                st.dataframe(df, use_container_width=True, hide_index=True)
            with c3:
                df = pd.DataFrame([{"Plan":k,"Count":v} for k,v in s1["plan_dist"].items()])
                st.dataframe(df, use_container_width=True, hide_index=True)
            st.subheader("🚨 DANGER: Paying but Dormant 30+ days")
            if s1["dormant_paying"]:
                st.dataframe(pd.DataFrame(s1["dormant_paying"]), use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 4 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 6. SUBSCRIPTIONS
    with sections[5]:
        try:
            sub = data["subscriptions"]
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("🆕 New", sub["count_new"])
            m2.metric("⏰ Ending 30d", sub["count_ending"])
            m3.metric("❌ Expired", sub["count_expired"])
            m4.metric("💎 Long-term", sub["count_long_term"])
            st.subheader("🔥 Ending in 30 days - URGENT")
            if sub["ending_in_30d"]:
                st.dataframe(pd.DataFrame(sub["ending_in_30d"]), use_container_width=True, hide_index=True)
            st.subheader("💎 Long-term Loyal (12+ payments)")
            if sub["long_term_customers"]:
                st.dataframe(pd.DataFrame(sub["long_term_customers"]), use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 5 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 7. REVENUE
    with sections[6]:
        try:
            r = data["revenue"]
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Previous", f"${r['total_previous']:,.2f}")
            m2.metric("Current", f"${r['total_current']:,.2f}")
            m3.metric("Net Change", f"${r['total_deviation']:+,.2f}")
            m4.metric("Loss Customers", r["loss_customers"])
            if r["conversion_losses"]:
                df = pd.DataFrame(r["conversion_losses"])
                st.dataframe(df, use_container_width=True, hide_index=True)
            st.subheader("Stream Time Trend")
            st_trend = data["stream_trend"]
            if st_trend:
                df = pd.DataFrame(st_trend)
                st.plotly_chart(px.line(df, x="period", y="stream_time", markers=True), use_container_width=True)
    
        except Exception as _se:
            st.error(f'Section 6 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 8. CORRELATIONS
    with sections[7]:
        try:
            cor = data["correlations"]
            st.subheader("🏢 Churn Rate by Company Size")
            rate = cor["company_size_churn_rate"]
            if rate:
                df = pd.DataFrame([{"Size":k,"Total":cor["size_totals"].get(k,0),"Churn %":v}
                                  for k,v in rate.items()]).sort_values("Churn %", ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.plotly_chart(px.bar(df, x="Size", y="Churn %", color="Churn %", color_continuous_scale="Reds"),
                              use_container_width=True)
            st.subheader("📊 Churn Rate by Plan")
            if cor["plan_churn_rate"]:
                df = pd.DataFrame([{"Plan":k,"Total":cor["plan_totals"].get(k,0),"Churn %":v}
                                  for k,v in cor["plan_churn_rate"].items()]).sort_values("Churn %", ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)
            st.subheader("🎯 Churn Rate by Perfect Fit")
            if cor["perfect_fit_churn_rate"]:
                df = pd.DataFrame([{"Fit":k,"Total":cor["fit_totals"].get(k,0),"Churn %":v}
                                  for k,v in cor["perfect_fit_churn_rate"].items()]).sort_values("Churn %", ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 7 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 9. NO SUB
    with sections[8]:
        try:
            n = data["no_sub"]
            st.metric("Total No-Sub Users", n["total"])
            c1,c2,c3 = st.columns(3)
            with c1:
                st.dataframe(pd.DataFrame([{"Plan":k,"Count":v} for k,v in n["by_plan"].items()]), use_container_width=True, hide_index=True)
            with c2:
                st.dataframe(pd.DataFrame([{"Size":k,"Count":v} for k,v in n["by_size"].items()]), use_container_width=True, hide_index=True)
            with c3:
                st.dataframe(pd.DataFrame([{"Fit":k,"Count":v} for k,v in n["by_fit"].items()]), use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 8 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 10. CONTACT INFO (NEW)
    with sections[9]:
        try:
            cc = data["contact"]
            m1,m2,m3 = st.columns(3)
            m1.metric("Total Customers", cc["total_customers"])
            m2.metric("Fully Complete", cc["fully_complete"])
            m3.metric("Missing All Contact", cc["missing_all_contact"])
            st.subheader("Field Completeness")
            df = pd.DataFrame([{"Field":f, "Filled":cc["field_completeness"][f],
                               "Completeness %":cc["completeness_pct"][f]}
                              for f in cc["field_completeness"]])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.plotly_chart(px.bar(df, x="Field", y="Completeness %", color="Completeness %",
                                  color_continuous_scale="RdYlGn", title="Contact Field Completeness"),
                          use_container_width=True)
    
        except Exception as _se:
            st.error(f'Section 9 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 11. PHONE CALLS (NEW)
    with sections[10]:
        try:
            ph = data["phone_calls"]
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Total Calls Made", ph["total_calls_made"])
            m2.metric("Customers Called", ph["customers_called"])
            m3.metric("Answered", ph["answered_calls"])
            m4.metric("Answer Rate", f"{ph['answer_rate']}%")
            if ph["call_statuses"]:
                st.subheader("Call Status Distribution")
                df = pd.DataFrame([{"Status":k,"Count":v} for k,v in ph["call_statuses"].items()])
                st.plotly_chart(px.bar(df, x="Status", y="Count", color="Count"), use_container_width=True)
            if ph["person_calling"]:
                st.subheader("Person Making Calls")
                st.dataframe(pd.DataFrame([{"Person":k,"Calls":v} for k,v in ph["person_calling"].items()]),
                           use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 10 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 12. GEOGRAPHY (NEW)
    with sections[11]:
        try:
            g = data["geography"]
            m1,m2 = st.columns(2)
            m1.metric("Unique Locations", g["unique_locations"])
            m2.metric("Unique Timezones", g["unique_timezones"])
            c1,c2 = st.columns(2)
            with c1:
                st.subheader("Top Locations")
                df = pd.DataFrame([{"Location":k,"Count":v} for k,v in g["top_locations"].items()])
                if not df.empty:
                    st.plotly_chart(px.bar(df.head(20), x="Location", y="Count", color="Count",
                                          color_continuous_scale="Viridis"), use_container_width=True)
                    st.dataframe(df, use_container_width=True, hide_index=True)
            with c2:
                st.subheader("Top Timezones")
                df = pd.DataFrame([{"Timezone":k,"Count":v} for k,v in g["top_timezones"].items()])
                if not df.empty:
                    st.dataframe(df, use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 11 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 13. PARENT ACCOUNTS (NEW)
    with sections[12]:
        try:
            pa = data["parent_accounts"]
            m1,m2 = st.columns(2)
            m1.metric("Customers with Parent", pa["customers_with_parent"])
            m2.metric("Unique Parent Accounts", pa["unique_parent_accounts"])
            if pa["top_parent_accounts"]:
                st.subheader("Top Parent Accounts")
                df = pd.DataFrame([{"Parent":k,"Sub-accounts":v} for k,v in pa["top_parent_accounts"].items()])
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.plotly_chart(px.bar(df.head(15), x="Parent", y="Sub-accounts", color="Sub-accounts"),
                              use_container_width=True)
    
        except Exception as _se:
            st.error(f'Section 12 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 14. RECENT ACTIVITY (NEW)
    with sections[13]:
        try:
            ra = data["recent_activity"]
            m1,m2,m3 = st.columns(3)
            m1.metric("🚀 Growing", ra["count_growing"])
            m2.metric("📉 Declining", ra["count_declining"])
            m3.metric("➡️ Steady", ra["count_steady"])
            st.subheader("🚀 Growing (recent 3 periods vs prior)")
            if ra["growing"]:
                st.dataframe(pd.DataFrame(ra["growing"]), use_container_width=True, hide_index=True)
            st.subheader("📉 Declining - URGENT outreach")
            if ra["declining"]:
                st.dataframe(pd.DataFrame(ra["declining"]), use_container_width=True, hide_index=True)
                st.error(f"⚠️ {ra['count_declining']} customers showing declining usage")
    
        except Exception as _se:
            st.error(f'Section 13 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])
    # 15. CUSTOMER VALUE TIERS (NEW)
    with sections[14]:
        try:
            vt = data["value_tiers"]
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("💎 VIP (18+)", vt["vip_count"])
            m2.metric("⭐ High (12+)", vt["high_count"])
            m3.metric("👤 Mid (6+)", vt["mid_count"])
            m4.metric("🆕 Low (1-5)", vt["low_count"])
            # Pie chart
            df = pd.DataFrame({
                "Tier":["VIP","High","Mid","Low"],
                "Count":[vt["vip_count"],vt["high_count"],vt["mid_count"],vt["low_count"]]
            })
            st.plotly_chart(px.pie(df, values="Count", names="Tier", title="Customer Value Distribution",
                                  color_discrete_map={"VIP":"purple","High":"gold","Mid":"blue","Low":"gray"}),
                          use_container_width=True)
            st.subheader("💎 VIP Customers - Treat Like Royalty")
            if vt["vip_customers"]:
                st.dataframe(pd.DataFrame(vt["vip_customers"]), use_container_width=True, hide_index=True)
    
        except Exception as _se:
            st.error(f'Section 14 error: {_se}')
            import traceback as _tb
            st.code(_tb.format_exc()[:1500])