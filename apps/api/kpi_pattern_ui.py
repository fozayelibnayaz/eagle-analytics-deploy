#!/usr/bin/env python3
"""UI component for KPI Pattern Analysis - renders region + time analysis"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def render_kpi_pattern_analysis(metric_type="signups"):
    """Render full KPI pattern analysis: region + time + fluctuations + AI insight."""
    try:
        from kpi_pattern_analyzer import analyze_signups_by_region, analyze_time_patterns, detect_fluctuation_patterns
    except ImportError:
        st.error("kpi_pattern_analyzer.py not found")
        return

    metric_label = {"signups": "Sign-ups", "uploads": "First Uploads", "paid": "Paid Customers"}.get(metric_type, metric_type)

    st.markdown(f"### 📊 {metric_label} Pattern Analysis")
    st.caption(f"Analyzing {metric_type} by region and time to find patterns")

    with st.spinner(f"Analyzing {metric_label} patterns..."):
        region   = analyze_signups_by_region(metric_type)
        time_p   = analyze_time_patterns(metric_type)
        fluct    = detect_fluctuation_patterns(metric_type)

    if region.get("error"):
        st.error(f"Region error: {region['error']}")
        return

    # ── REGION ANALYSIS ──
    st.subheader("🌍 Regional Distribution")

    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Total Records", f"{region.get('total', 0):,}")
    rc2.metric("Countries", region.get("unique_countries", 0))
    top_country = region.get("top_countries", [{}])[0] if region.get("top_countries") else {}
    rc3.metric(f"Top: {top_country.get('country', 'N/A')}", f"{top_country.get('count', 0)} ({top_country.get('percentage', 0)}%)")

    if region.get("top_countries"):
        df_country = pd.DataFrame(region["top_countries"])
        col_a, col_b = st.columns([2, 1])
        with col_a:
            fig = px.bar(df_country.head(15), x="country", y="count",
                         title=f"Top 15 Countries - {metric_label}",
                         color="count", color_continuous_scale="Viridis")
            fig.update_layout(xaxis_tickangle=-45, height=400)
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            st.markdown("**Top Countries**")
            st.dataframe(df_country.head(15), use_container_width=True, hide_index=True)

    # ── TIME PATTERNS ──
    if time_p.get("error"):
        st.warning(f"Time analysis: {time_p['error']}")
    else:
        st.subheader("📅 Time Patterns")

        tc1, tc2, tc3 = st.columns(3)
        peak_m = time_p.get("peak_month", {})
        peak_d = time_p.get("peak_day", {})
        tc1.metric("📆 Peak Month", peak_m.get("name", "N/A"), f"{peak_m.get('count', 0)} records")
        tc2.metric("📅 Peak Day", peak_d.get("name", "N/A"), f"{peak_d.get('count', 0)} records")
        dr = time_p.get("date_range", {})
        tc3.metric("📊 Date Range", f"{dr.get('first', '')} → {dr.get('last', '')}")

        # Month of year chart
        st.markdown("**Distribution by Month of Year**")
        moy = time_p.get("by_month_of_year", [])
        if moy:
            df_moy = pd.DataFrame(moy, columns=["Month", "Count"])
            fig = px.bar(df_moy, x="Month", y="Count",
                         title=f"{metric_label} by Month - All Years Combined",
                         color="Count", color_continuous_scale="Blues",
                         text="Count")
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

            peak_idx = max(range(len(moy)), key=lambda i: moy[i][1])
            low_idx  = min(range(len(moy)), key=lambda i: moy[i][1])
            st.info(
                f"🔥 **Highest activity month:** {moy[peak_idx][0]} ({moy[peak_idx][1]} records)  \n"
                f"❄️ **Lowest activity month:** {moy[low_idx][0]} ({moy[low_idx][1]} records)  \n"
                f"📈 **Seasonal swing:** {(moy[peak_idx][1] - moy[low_idx][1]) / max(moy[low_idx][1], 1) * 100:.0f}% more in peak vs trough"
            )

        # Day of week chart
        st.markdown("**Distribution by Day of Week**")
        dow = time_p.get("by_day_of_week", [])
        if dow:
            df_dow = pd.DataFrame(dow, columns=["Day", "Count"])
            fig = px.bar(df_dow, x="Day", y="Count",
                         color="Count", color_continuous_scale="Plasma",
                         text="Count")
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

        # Year-over-year
        st.markdown("**Year-over-Year Growth**")
        yoy = time_p.get("year_over_year", {})
        if yoy:
            yoy_rows = []
            for year, d in yoy.items():
                yoy_rows.append({
                    "Year":       year,
                    "Count":      d.get("count", 0),
                    "Growth %":   str(round(d["growth_pct"], 1)) + "%" if d.get("growth_pct") is not None else "—",
                })
            df_yoy = pd.DataFrame(yoy_rows)
            col_y1, col_y2 = st.columns([2, 1])
            with col_y1:
                fig = px.line(df_yoy, x="Year", y="Count",
                              title=f"{metric_label} Yearly Trend",
                              markers=True, text="Count")
                fig.update_traces(textposition="top center")
                st.plotly_chart(fig, use_container_width=True)
            with col_y2:
                st.dataframe(df_yoy, use_container_width=True, hide_index=True)

        # Monthly trend (full timeline)
        st.markdown("**Monthly Timeline**")
        ym = time_p.get("by_year_month", {})
        if ym:
            df_ym = pd.DataFrame([{"Month": k, "Count": v} for k, v in ym.items()])
            fig = px.line(df_ym, x="Month", y="Count",
                          title=f"{metric_label} Over Time (Monthly)",
                          markers=True)
            fig.update_layout(xaxis_tickangle=-45, height=400)
            st.plotly_chart(fig, use_container_width=True)

    # ── FLUCTUATION DETECTION ──
    if not fluct.get("error"):
        st.subheader("⚡ Fluctuation & Anomaly Detection")
        fc1, fc2, fc3, fc4 = st.columns(4)
        fc1.metric("📈 Avg/Day", f"{fluct.get('mean_per_day', 0):.1f}")
        fc2.metric("📊 Std Dev", f"{fluct.get('std', 0):.1f}")
        fc3.metric("🚀 Spike Days", fluct.get("spike_count", 0))
        fc4.metric("📉 Drop Days", fluct.get("drop_count", 0))

        col_s, col_d = st.columns(2)
        with col_s:
            st.markdown("**🚀 Top 10 Best Days**")
            best = fluct.get("best_days", [])
            if best:
                df_best = pd.DataFrame(best)
                st.dataframe(df_best, use_container_width=True, hide_index=True)
        with col_d:
            st.markdown("**📉 Bottom 10 Slow Days**")
            worst = fluct.get("worst_days", [])
            if worst:
                df_worst = pd.DataFrame(worst)
                st.dataframe(df_worst, use_container_width=True, hide_index=True)

        if fluct.get("spikes"):
            with st.expander(f"🚀 All {fluct['spike_count']} spike days (>2σ above mean)"):
                df_sp = pd.DataFrame(fluct["spikes"])
                st.dataframe(df_sp, use_container_width=True, hide_index=True)

    # ── AI INSIGHT ──
    st.subheader("🤖 AI Pattern Insight")
    if st.button(f"Generate AI insight for {metric_label}", key=f"ai_pattern_{metric_type}"):
        with st.spinner("AI analyzing patterns..."):
            insight = _ai_pattern_insight(metric_label, region, time_p, fluct)
        st.markdown(insight)


def _ai_pattern_insight(metric_label, region, time_p, fluct):
    """Generate AI insight from pattern data."""
    import json as _json
    import os as _os
    import urllib.request as _ur
    import urllib.error as _ue

    groq_key = _os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        try:
            import streamlit as st
            groq_key = str(st.secrets.get("GROQ_API_KEY", "")).strip()
        except Exception:
            pass

    summary = {
        "metric":         metric_label,
        "total":          region.get("total", 0),
        "top_5_countries": region.get("top_countries", [])[:5],
        "peak_month":     time_p.get("peak_month", {}),
        "peak_day":       time_p.get("peak_day", {}),
        "year_over_year": time_p.get("year_over_year", {}),
        "spike_count":    fluct.get("spike_count", 0),
        "best_days":      fluct.get("best_days", [])[:5],
        "mean_per_day":   fluct.get("mean_per_day", 0),
    }

    prompt = f"""You are a data analyst. Analyze this {metric_label} pattern data and provide actionable insights.

DATA:
{_json.dumps(summary, indent=2, default=str)}

Provide analysis in these sections (use exact headers):

GEOGRAPHIC INSIGHT
[Which regions dominate and why? What does this tell us about target market?]

SEASONAL PATTERN
[Which months/seasons are strongest? Why? What action to take?]

WEEKLY PATTERN
[Which day of week is strongest? What does this mean for marketing timing?]

GROWTH TRAJECTORY
[Year over year: growing, declining, stagnant? What is the trend?]

ANOMALY INSIGHT
[What do the spike days mean? Were there campaigns/events that drove them?]

ACTION PLAN
[3 specific actions to capitalize on these patterns]

Be specific. Reference actual numbers. No generic advice."""

    if not groq_key:
        return "GROQ_API_KEY not configured. Add to Streamlit secrets to enable AI insights."

    try:
        req = _ur.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=_json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You are an expert KPI analyst. Provide concrete data-driven insights."},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens":  1500,
                "temperature": 0.3,
            }).encode(),
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with _ur.urlopen(req, timeout=20) as resp:
            return _json.loads(resp.read())["choices"][0]["message"]["content"]
    except _ue.HTTPError as e:
        return f"Groq error {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return f"Error: {e}"
