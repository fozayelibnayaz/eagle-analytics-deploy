"""
youtube_page_v2.py — Eagle 3D Streaming Analytics Hub
=======================================================
Full YouTube dashboard matching AI-YouTube-Command-Center Next.js UI.

Uses:
  - youtube_analytics.py (OAuth-based real per-video metrics)
  - youtube_connector.py (public API for channel + videos list)
  - Groq/Gemini for AI "Why did this work/fail?"
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st


# ─── Helpers ─────────────────────────────────────────────────────
def _fmt_num(n: Any) -> str:
    try:
        n = int(n or 0)
    except Exception:
        return "0"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return f"{n:,}"


def _fmt_duration(secs: Any) -> str:
    try:
        s = int(secs or 0)
    except Exception:
        return "0:00"
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _engagement_label(eng: float) -> str:
    if eng >= 10: return "Excellent — Top 5% of creators"
    if eng >= 6:  return "Very Good — Strong engagement"
    if eng >= 3:  return "Good — Above average"
    if eng >= 1.5: return "Average — Industry average"
    if eng >= 0.5: return "Below Avg — Needs improvement"
    if eng > 0:   return "Low — Audience not engaging"
    return "No data — Need views to measure"


def _score_engagement_color(score: int) -> str:
    if score >= 50: return "#4ADE80"  # green
    if score >= 30: return "#FACC15"  # yellow
    return "#EF4444"  # red


def _period_days(label: str) -> int:
    return {"Last 7 Days": 7, "Last 28 Days": 28, "Last 30 Days": 30,
             "Last 90 Days": 90, "Last 180 Days": 180,
             "Last 12 Months": 365, "All Time": 3650}.get(label, 90)


# ─── Ask AI helper ────────────────────────────────────────────────
def _ask_ai(question: str, video_context: Dict[str, Any]) -> str:
    system = f"""You are a YouTube growth analyst for Eagle 3D Streaming.
Answer concisely with 3-5 bullet points explaining reasons and 2-3 actionable next steps.

Video data:
- Title: {video_context.get('title')}
- Views: {video_context.get('views')}
- Likes: {video_context.get('likes')}
- Comments: {video_context.get('comments')}
- Engagement: {video_context.get('engagement_rate')}%
- Published: {video_context.get('published_at')}
- Watch time: {video_context.get('watch_time_minutes', 'unknown')} min
- Avg view %: {video_context.get('avg_view_percentage', 'unknown')}%
"""
    try:
        from openai import OpenAI
        api_key = st.secrets.get("GROQ_API_KEY", "")
        if api_key:
            client = OpenAI(api_key=api_key,
                            base_url="https://api.groq.com/openai/v1")
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role":"system","content":system},
                           {"role":"user","content":question}],
                temperature=0.4, max_tokens=500,
            )
            return r.choices[0].message.content
    except Exception:
        pass
    try:
        import google.generativeai as genai
        api_key = st.secrets.get("GEMINI_API_KEY", "")
        if api_key:
            genai.configure(api_key=api_key)
            m = genai.GenerativeModel("gemini-1.5-flash")
            r = m.generate_content(f"{system}\n\nQ: {question}")
            return r.text
    except Exception:
        pass
    return "AI unavailable"


# ─── Main render ─────────────────────────────────────────────────
def render_youtube_page_v2() -> None:
    from mongo_client import find_one, find_all
    from youtube_analytics import (
        get_daily_views, get_revenue, get_traffic_sources,
        get_top_videos, get_batch_video_analytics, get_video_analytics,
        get_retention_curve, get_demographics, get_subscriber_growth,
    )

    # ── Hero + connection status ──
    channel = find_one("youtube_channel", {})
    if not channel:
        st.warning("No YouTube data yet. Run the pipeline to fetch.")
        return

    ch_title = channel.get("title", "Channel")
    ch_subs  = int(channel.get("subscribers", 0) or 0)
    ch_vids  = int(channel.get("video_count", 0) or 0)

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,rgba(158,255,47,0.10),transparent);
                    border:1px solid rgba(158,255,47,0.25);
                    border-radius:16px;padding:18px 22px;margin-bottom:20px;">
          <div style="display:flex;align-items:center;gap:14px;">
            <div style="width:12px;height:12px;border-radius:50%;
                        background:#9EFF2F;box-shadow:0 0 12px rgba(158,255,47,0.7);"></div>
            <div>
              <div style="color:#9EFF2F;font-weight:600;font-size:14px;">
                YouTube Connected — REAL Data Active
              </div>
              <div style="color:#9CA3AF;font-size:12px;margin-top:2px;">
                {ch_title} · {_fmt_num(ch_subs)} subs · {ch_vids} videos
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Period selector + action buttons ──
    period_options = ["Last 7 Days", "Last 28 Days", "Last 30 Days",
                       "Last 90 Days", "Last 180 Days", "Last 12 Months", "All Time"]
    c1, c2, c3, c4, c5 = st.columns([2.5, 1, 1, 1, 1])
    with c1:
        period = st.selectbox("📅 Period", period_options, index=3,
                                key="yt_period")
    with c2:
        preview = st.button("👁 Preview", width='stretch')
    with c3:
        alerts = st.button("🔔 Alerts", width='stretch')
    with c4:
        test = st.button("🧪 Test", width='stretch')
    with c5:
        sync = st.button("🔄 Sync", type="primary", width='stretch')

    if sync:
        with st.spinner("Syncing from YouTube API..."):
            try:
                from youtube_connector import get_channel_info, get_channel_videos
                from mongo_client import upsert_one, upsert_many
                ch = get_channel_info()
                upsert_one("youtube_channel", ch, ["channel_id"])
                vids = get_channel_videos(max_videos=500)
                upsert_many("youtube_videos", vids, "video_id")
                st.success(f"Synced {len(vids)} videos")
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")

    if alerts:
        try:
            from rich_alerts_engine import (
                build_youtube_daily_summary,
                build_youtube_top_video_alert,
                build_youtube_dead_video_alerts,
                _send,
            )
            with st.spinner("Sending YouTube alerts to Telegram..."):
                sent = 0
                for msg in [build_youtube_daily_summary(),
                             build_youtube_top_video_alert()]:
                    if msg and _send(msg):
                        sent += 1
                for msg in build_youtube_dead_video_alerts():
                    if _send(msg):
                        sent += 1
                st.success(f"Sent {sent} YouTube alerts")
        except Exception as e:
            st.error(f"Alerts failed: {e}")

    if test:
        try:
            from reporting_engine import send_telegram
            r = send_telegram(f"🧪 YouTube test — {datetime.now().strftime('%H:%M')}")
            st.success("Test sent" if r else "Failed")
        except Exception as e:
            st.error(str(e))

    st.markdown("---")

    # ── Date range for analytics ──
    days = _period_days(period)
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=days-1)).isoformat()

    # ── Top-level metric cards ──
    videos = find_all("youtube_videos", limit=500)
    total_views = sum(int(v.get("views", 0) or 0) for v in videos)
    total_likes = sum(int(v.get("likes", 0) or 0) for v in videos)
    total_comments = sum(int(v.get("comments", 0) or 0) for v in videos)
    total_shares = sum(int(v.get("shares", 0) or 0) for v in videos)
    avg_eng = round((total_likes + total_comments) / total_views * 100, 2) if total_views else 0

    st.markdown("### Channel Overview")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("👁 Total Views",   _fmt_num(total_views))
    m2.metric("👥 Subscribers",   _fmt_num(ch_subs))
    m3.metric("👍 Total Likes",   _fmt_num(total_likes))
    m4.metric("💬 Comments",       _fmt_num(total_comments))
    m5.metric("📈 Engagement",     f"{avg_eng}%", "real calc")
    m6.metric("🔗 Shares",         _fmt_num(total_shares))

    # ── Revenue if available ──
    try:
        rev = get_revenue(start_date, end_date)
        if rev and rev.get("estimatedRevenue") is not None:
            r1, r2, r3 = st.columns(3)
            r1.metric("💰 Est Revenue",
                        f"${float(rev.get('estimatedRevenue', 0) or 0):,.2f}")
            r2.metric("📊 CPM",
                        f"${float(rev.get('cpm', 0) or 0):,.2f}")
            r3.metric("📺 Ad Impressions",
                        _fmt_num(rev.get("adImpressions", 0)))
    except Exception:
        pass

    st.markdown("---")

    # ── Best / Worst ──
    if videos:
        # Compute engagement per video
        for v in videos:
            views = int(v.get("views", 0) or 0)
            likes = int(v.get("likes", 0) or 0)
            comments = int(v.get("comments", 0) or 0)
            v["_engagement_rate"] = round((likes + comments) / views * 100, 2) if views else 0
            # Score: views/day + engagement
            try:
                pub = datetime.fromisoformat(str(v.get("published_at", ""))[:19].replace("Z",""))
                age = max((datetime.now() - pub).days, 1)
            except Exception:
                age = 1
            vpd = views / age
            v["_score"] = min(100, int(vpd * 3 + v["_engagement_rate"] * 5))

        best = max(videos, key=lambda v: v["_score"], default={})
        worst = min([v for v in videos if int(v.get("views", 0) or 0) > 0],
                    key=lambda v: v["_score"], default={})

        colB, colW = st.columns(2)
        with colB:
            st.markdown(f"""
            <div style="background:rgba(74,222,128,0.08);border:1px solid rgba(74,222,128,0.25);
                        border-radius:16px;padding:20px;">
              <div style="color:#4ADE80;font-weight:700;font-size:16px;margin-bottom:12px;">
                🏆 BEST Performing
              </div>
              <div style="color:#fff;font-weight:600;margin-bottom:12px;">
                {str(best.get('title', 'N/A'))[:80]}
              </div>
              <div style="display:flex;gap:20px;color:#9CA3AF;font-size:13px;">
                <div>Views: <b style="color:#fff;">{_fmt_num(best.get('views', 0))}</b></div>
                <div>Eng: <b style="color:#fff;">{best.get('_engagement_rate', 0)}%</b></div>
                <div>Likes: <b style="color:#fff;">{_fmt_num(best.get('likes', 0))}</b></div>
                <div>Score: <b style="color:#4ADE80;">{best.get('_score', 0)}/100</b></div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Why did this work?", key="ai_best"):
                with st.spinner("Analyzing..."):
                    ans = _ask_ai("Why did this video perform well?", best)
                    st.info(ans)

        with colW:
            st.markdown(f"""
            <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);
                        border-radius:16px;padding:20px;">
              <div style="color:#EF4444;font-weight:700;font-size:16px;margin-bottom:12px;">
                ⚠️ WORST Performing
              </div>
              <div style="color:#fff;font-weight:600;margin-bottom:12px;">
                {str(worst.get('title', 'N/A'))[:80]}
              </div>
              <div style="display:flex;gap:20px;color:#9CA3AF;font-size:13px;">
                <div>Views: <b style="color:#fff;">{_fmt_num(worst.get('views', 0))}</b></div>
                <div>Eng: <b style="color:#fff;">{worst.get('_engagement_rate', 0)}%</b></div>
                <div>Likes: <b style="color:#fff;">{_fmt_num(worst.get('likes', 0))}</b></div>
                <div>Score: <b style="color:#EF4444;">{worst.get('_score', 0)}/100</b></div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Why did this fail?", key="ai_worst"):
                with st.spinner("Analyzing..."):
                    ans = _ask_ai("Why did this video underperform?", worst)
                    st.warning(ans)

    st.markdown("---")

    # ── Sub-tabs: Analytics / Audience / Revenue / Traffic / Videos ──
    tab_labels = ["📈 Analytics", "👥 Audience", "💰 Revenue",
                   "🌍 Traffic", "🎬 All Videos"]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_analytics_tab(period, start_date, end_date, get_daily_views, get_subscriber_growth)

    with tabs[1]:
        _render_audience_tab(start_date, end_date, get_demographics)

    with tabs[2]:
        _render_revenue_tab(start_date, end_date)

    with tabs[3]:
        _render_traffic_tab(start_date, end_date, get_traffic_sources)

    with tabs[4]:
        _render_videos_tab(videos, start_date, end_date, get_batch_video_analytics)


# ─── Sub-tab renderers ────────────────────────────────────────────
def _render_analytics_tab(period, start, end, get_daily_views, get_subscriber_growth):
    try:
        daily = get_daily_views(start, end)
        if not daily:
            st.info(f"No analytics data for {period}")
            return

        df = pd.DataFrame(daily)
        df["day"] = pd.to_datetime(df["day"])
        df = df.sort_values("day")

        # Big number
        st.markdown("### Views Trend")
        total = int(df["views"].sum())
        st.metric(f"Total Views ({period})", _fmt_num(total))

        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["day"], y=df["views"], name="Views", mode="lines",
            line=dict(color="#9EFF2F", width=2.5),
            fill="tozeroy", fillcolor="rgba(158,255,47,0.10)",
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#9CA3AF"), height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
        )
        st.plotly_chart(fig, width='stretch')

        # Watch time chart
        if "estimatedMinutesWatched" in df.columns:
            st.markdown("### Watch Time")
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=df["day"], y=df["estimatedMinutesWatched"],
                marker_color="#5EF46A",
                name="Minutes watched",
            ))
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#9CA3AF"), height=280,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
            )
            st.plotly_chart(fig2, width='stretch')

        # Subscriber growth
        st.markdown("### Subscriber Growth")
        subs = get_subscriber_growth(start, end)
        if subs:
            sdf = pd.DataFrame(subs)
            sdf["day"] = pd.to_datetime(sdf["day"])
            gained = int(sdf.get("subscribersGained", pd.Series([0])).sum())
            lost = int(sdf.get("subscribersLost", pd.Series([0])).sum())
            n1, n2, n3 = st.columns(3)
            n1.metric("Gained", _fmt_num(gained))
            n2.metric("Lost", _fmt_num(lost))
            n3.metric("Net", _fmt_num(gained - lost))
    except Exception as e:
        st.info(f"Analytics unavailable: {e}")


def _render_audience_tab(start, end, get_demographics):
    try:
        demo = get_demographics(start, end)
        if not demo:
            st.info("No audience data")
            return

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 🌍 Top Countries")
            geo = demo.get("geography", [])
            if geo:
                df = pd.DataFrame(geo)
                st.dataframe(df.head(15), width='stretch', hide_index=True)
            else:
                st.info("No geo data")

        with col2:
            st.markdown("### 📱 Devices")
            dev = demo.get("devices", [])
            if dev:
                st.dataframe(pd.DataFrame(dev), width='stretch', hide_index=True)

        st.markdown("### 👥 Age & Gender")
        ag = demo.get("ageGender", [])
        if ag:
            st.dataframe(pd.DataFrame(ag), width='stretch', hide_index=True)

        st.markdown("### 💻 Operating Systems")
        os_data = demo.get("os", [])
        if os_data:
            st.dataframe(pd.DataFrame(os_data), width='stretch', hide_index=True)
    except Exception as e:
        st.info(f"Audience data unavailable: {e}")


def _render_revenue_tab(start, end):
    try:
        from youtube_analytics import get_revenue, get_revenue_daily
        rev = get_revenue(start, end)
        if not rev:
            st.info("No revenue data (channel may not be monetized)")
            return
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Est Revenue", f"${float(rev.get('estimatedRevenue', 0) or 0):,.2f}")
        c2.metric("Ad Revenue",   f"${float(rev.get('estimatedAdRevenue', 0) or 0):,.2f}")
        c3.metric("Gross",         f"${float(rev.get('grossRevenue', 0) or 0):,.2f}")
        c4.metric("CPM",           f"${float(rev.get('cpm', 0) or 0):,.2f}")

        daily = get_revenue_daily(start, end)
        if daily:
            import plotly.graph_objects as go
            df = pd.DataFrame(daily)
            df["day"] = pd.to_datetime(df["day"])
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df["day"], y=df["estimatedRevenue"],
                marker_color="#9EFF2F", name="Est Revenue",
            ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#9CA3AF"), height=320,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
            )
            st.plotly_chart(fig, width='stretch')
    except Exception as e:
        st.info(f"Revenue unavailable: {e}")


def _render_traffic_tab(start, end, get_traffic_sources):
    try:
        sources = get_traffic_sources(None, start, end)
        if not sources:
            st.info("No traffic data")
            return
        st.markdown("### 🚦 Traffic Sources")
        df = pd.DataFrame(sources)
        st.dataframe(df, width='stretch', hide_index=True)

        # Bar chart
        if "insightTrafficSourceType" in df.columns and "views" in df.columns:
            import plotly.express as px
            fig = px.bar(df.head(10), x="insightTrafficSourceType", y="views",
                          color_discrete_sequence=["#9EFF2F"])
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#9CA3AF"), height=320,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
            )
            st.plotly_chart(fig, width='stretch')

        # Search terms
        try:
            from youtube_analytics import get_search_terms
            terms = get_search_terms(None, start, end)
            if terms:
                st.markdown("### 🔍 Top Search Terms")
                st.dataframe(pd.DataFrame(terms).head(20),
                             width='stretch', hide_index=True)
        except Exception:
            pass
    except Exception as e:
        st.info(f"Traffic unavailable: {e}")


def _render_videos_tab(videos, start, end, get_batch_video_analytics):
    if not videos:
        st.info("No videos yet")
        return

    st.markdown(f"### 🎬 All Videos ({len(videos)})")

    # Sort + search
    col1, col2 = st.columns([2, 1])
    with col1:
        search = st.text_input("🔍 Search title", key="yt_video_search")
    with col2:
        sort_by = st.selectbox("Sort by",
                                ["views", "likes", "comments", "published_at"],
                                key="yt_sort")

    filtered = videos
    if search:
        filtered = [v for v in videos
                     if search.lower() in str(v.get("title", "")).lower()]

    reverse = sort_by != "published_at" or True  # newest first if date
    filtered = sorted(filtered,
                       key=lambda v: v.get(sort_by, 0) if isinstance(v.get(sort_by), (int, float)) else str(v.get(sort_by, "")),
                       reverse=True)

    st.caption(f"Showing {len(filtered)} of {len(videos)} videos")

    # Show top N with expandable details
    show_n = st.slider("Show top N", 5, 100, 20, key="yt_show_n")

    # Batch fetch analytics for the top-N shown
    top_ids = [v.get("video_id") for v in filtered[:show_n] if v.get("video_id")]
    analytics_map = {}
    if top_ids:
        try:
            analytics_map = get_batch_video_analytics(top_ids, start, end)
        except Exception:
            pass

    for i, v in enumerate(filtered[:show_n], 1):
        vid = v.get("video_id", "")
        views = int(v.get("views", 0) or 0)
        likes = int(v.get("likes", 0) or 0)
        comments = int(v.get("comments", 0) or 0)
        eng = round((likes + comments) / views * 100, 2) if views else 0
        real_analytics = analytics_map.get(vid, {})

        with st.expander(f"#{i}  {str(v.get('title',''))[:80]}  ·  "
                          f"{_fmt_num(views)} views  ·  {eng}% eng"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Views (total)", _fmt_num(views))
            c2.metric("Likes",         _fmt_num(likes))
            c3.metric("Comments",      _fmt_num(comments))
            c4.metric("Engagement",    f"{eng}%")

            if real_analytics:
                st.markdown("**Real analytics for selected period:**")
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Period views",  _fmt_num(real_analytics.get("views", 0)))
                r2.metric("Watch min",     _fmt_num(real_analytics.get("estimatedMinutesWatched", 0)))
                r3.metric("Avg view %",    f"{float(real_analytics.get('averageViewPercentage', 0) or 0):.1f}%")
                r4.metric("Subs gained",   real_analytics.get("subscribersGained", 0))

            st.caption(f"Published: {str(v.get('published_at',''))[:10]} · "
                        f"Duration: {_fmt_duration(v.get('duration_seconds', 0))}")
            st.caption(_engagement_label(eng))

            b1, b2 = st.columns(2)
            with b1:
                if st.button("🤖 Analyze this", key=f"yt_ai_{vid}"):
                    with st.spinner("AI analyzing..."):
                        ctx = {**v, "engagement_rate": eng,
                                "watch_time_minutes": real_analytics.get("estimatedMinutesWatched"),
                                "avg_view_percentage": real_analytics.get("averageViewPercentage")}
                        st.info(_ask_ai("Analyze this video's performance and suggest improvements", ctx))
            with b2:
                if vid:
                    st.markdown(f"[▶ Watch on YouTube](https://youtube.com/watch?v={vid})")
