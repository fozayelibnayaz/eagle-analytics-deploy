"""
events_page_ui.py — Website Events Tracking (GTM → GA4)
Rendered as a sub-tab inside the Traffic page.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from events_tracker import (
    list_registered_events, register_event, deregister_event,
    fetch_events_from_ga4, fetch_events_combined, fetch_event_breakdown,
    seed_default_events, detect_event_anomalies,
)
from period_picker_shared import render_period_picker


def render_events_page(user_email: str = "") -> None:
    st.markdown("### 🎯 Website Event Tracking")
    st.caption("GTM events firing on eagle3dstreaming.com → GA4 → live performance metrics.")

    # Seed default events if empty
    if not list_registered_events(active_only=False):
        seed_default_events()

    # ── Unified period picker ──
    start, end, period_label = render_period_picker("events", "This Month")

    st.markdown("---")

    tabs = st.tabs([
        "📊 Performance",
        "🏆 Top Events",
        "🔍 Event Deep-Dive",
        "📋 Registered",
        "➕ Add New",
        "🔔 Anomalies",
    ])

    # ── PERFORMANCE ──
    with tabs[0]:
        st.markdown(f"#### Overview — {period_label} ({start} → {end})")

        with st.spinner("Fetching..."):
            result = fetch_events_combined(start, end)
            counts = result["counts"]
            source = result["source"]

        if source == "GA4 live":
            st.success(f"📡 Live data from GA4")
        elif source == "MongoDB history (cached)":
            st.info(f"📦 Showing cached historical data (GA4 empty for period)")

        if not counts:
            st.warning(
                "⚠️ No GA4 events yet. Common reasons:\n"
                "- GTM tag deployed <24h ago (GA4 has processing delay)\n"
                "- GA4 property ID not connected\n"
                "- Events not firing on eagle3dstreaming.com — verify in GTM Preview mode"
            )
            return

        registered = {e["event_name"] for e in list_registered_events()}

        total_events = sum(counts.values())
        tracked_count = sum(v for k, v in counts.items() if k in registered)
        untracked_count = total_events - tracked_count
        unique_events = len(counts)
        registered_count = len([k for k in counts if k in registered])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🎯 Total event fires", f"{total_events:,}")
        m2.metric("📊 Unique events",     f"{unique_events}")
        m3.metric("✅ Registered fires",   f"{tracked_count:,}",
                    f"{tracked_count/total_events*100:.0f}% of total" if total_events else None)
        m4.metric("👀 New/untracked",     f"{untracked_count:,}",
                    f"{unique_events - registered_count} unique")

        st.markdown("---")

        # Chart: top events
        st.markdown("#### Top 15 events by fire count")
        try:
            import plotly.express as px
            rows = [{"event": k, "count": v, "registered": k in registered}
                     for k, v in sorted(counts.items(), key=lambda x: -x[1])[:15]]
            df = pd.DataFrame(rows)
            fig = px.bar(df, x="event", y="count", color="registered",
                          color_discrete_map={True: "#9EFF2F", False: "#EF4444"},
                          labels={"event": "Event Name", "count": "Fires"})
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#9CA3AF"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                height=380,
                showlegend=True,
            )
            st.plotly_chart(fig, width='stretch')
        except Exception as e:
            st.info(f"Chart error: {e}")

    # ── TOP EVENTS TABLE ──
    with tabs[1]:
        st.markdown(f"#### All events fired in period")
        with st.spinner("Fetching..."):
            counts = fetch_events_combined(start, end)["counts"]

        if not counts:
            st.info("No data for this period.")
        else:
            registered = {e["event_name"] for e in list_registered_events()}
            registered_meta = {e["event_name"]: e for e in list_registered_events()}

            rows = []
            for name, count in sorted(counts.items(), key=lambda x: -x[1]):
                meta = registered_meta.get(name, {})
                rows.append({
                    "Event":       name,
                    "Category":    meta.get("category", "—"),
                    "Fires":       count,
                    "Registered":  "✅" if name in registered else "❌",
                    "Description": meta.get("description", "—")[:60],
                })
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    # ── DEEP DIVE ──
    with tabs[2]:
        st.markdown("#### Drill into a specific event")
        events = list_registered_events()
        if not events:
            st.info("Register events first (see Add New tab)")
        else:
            names = sorted({e["event_name"] for e in events})
            picked = st.selectbox("Event to analyze", names, key="dive_event")

            picked_meta = next((e for e in events if e["event_name"] == picked), {})
            params = picked_meta.get("params", []) or []

            dim_options = ["pagePath", "sourceMedium", "country",
                            "deviceCategory", "browser"] + params
            dim = st.selectbox("Break down by", dim_options, key="dive_dim")

            with st.spinner(f"Analyzing '{picked}' by {dim}..."):
                rows = fetch_event_breakdown(picked, start, end, dim)

            if rows:
                df = pd.DataFrame(rows)
                df = df.rename(columns={"value": dim, "count": "Fires"})
                df = df.sort_values("Fires", ascending=False).head(30)

                m1, m2 = st.columns(2)
                m1.metric(f"Total '{picked}' fires", int(df["Fires"].sum()))
                m2.metric("Unique values", len(df))

                # Chart
                try:
                    import plotly.express as px
                    fig = px.bar(df.head(15), x=dim, y="Fires",
                                  color_discrete_sequence=["#5EF46A"])
                    fig.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#9CA3AF"),
                        height=340,
                    )
                    st.plotly_chart(fig, width='stretch')
                except Exception:
                    pass

                st.dataframe(df, width='stretch', hide_index=True)
            else:
                st.info(f"No breakdown data for '{picked}' in this period.")

    # ── REGISTERED EVENTS LIST ──
    with tabs[3]:
        st.markdown("#### Currently tracked events")
        events = list_registered_events(active_only=False)
        if events:
            df = pd.DataFrame(events)
            cols = [c for c in ["category", "event_name", "description",
                                 "params", "is_active", "registered_at"]
                     if c in df.columns]
            st.dataframe(df[cols], width='stretch', hide_index=True)

            st.markdown("---")
            with st.expander("🗑️ Deactivate event"):
                names = [e["event_name"] for e in events if e.get("is_active")]
                if names:
                    to_deact = st.selectbox("Pick event", names, key="deact_ev")
                    if st.button("Deactivate", type="secondary"):
                        deregister_event(to_deact)
                        st.success(f"Deactivated: {to_deact}")
                        st.rerun()

    # ── ADD NEW ──
    with tabs[4]:
        st.markdown("#### Register a new event to track")
        st.caption("Tell the system about new GTM events your dev sets up.")

        with st.form("add_event_form"):
            c1, c2 = st.columns(2)
            with c1:
                new_name = st.text_input(
                    "Event name (as fired in GTM)",
                    placeholder="e.g. video_play, footer_link_click")
                new_cat = st.selectbox("Category",
                                         ["engagement", "content", "pricing",
                                          "demos", "signup", "conversion", "custom"])
            with c2:
                new_params = st.text_input(
                    "Params (comma-separated)",
                    placeholder="e.g. video_title, duration_seconds")
            new_desc = st.text_area(
                "Description",
                placeholder="What does this event mean? When does it fire?")

            if st.form_submit_button("➕ Register Event", type="primary"):
                if not new_name:
                    st.error("Event name required")
                else:
                    params_list = [p.strip() for p in new_params.split(",")
                                    if p.strip()]
                    if register_event(new_name, new_cat, new_desc, params_list):
                        st.success(f"✅ Registered: {new_name}")
                        st.rerun()

    # ── ANOMALIES ──
    with tabs[5]:
        st.markdown("#### Event spike/drop detection")
        st.caption("Compares last 7d vs previous 7d for every registered event.")

        if st.button("🔍 Check now", type="primary"):
            with st.spinner("Analyzing..."):
                anoms = detect_event_anomalies()
                if not anoms:
                    st.success("✅ No anomalies detected")
                else:
                    for a in anoms:
                        icon = "🚀" if a["type"] == "spike" else "📉"
                        (st.success if a["type"] == "spike" else st.warning)(
                            f"{icon} **{a['event']}** — {a['current']} vs {a['previous']} prev 7d"
                        )
