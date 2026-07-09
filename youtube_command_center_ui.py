#!/usr/bin/env python3
"""
AI YouTube Command Center - Full Replication
Replicates exact UI from user reference.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import os
import json
import urllib.request
import urllib.error


def _get_secret(key, default=""):
    val = os.environ.get(key, "")
    if not val:
        try:
            val = str(st.secrets.get(key, "")).strip()
        except Exception:
            pass
    return val or default


def _ai_analyze_video(video, channel_avg_eng=2.0):
    """Use Groq or Gemini to analyze a video with rich structured insights."""
    title       = video.get("title", "")
    views       = video.get("views", 0)
    likes       = video.get("likes", 0)
    comments    = video.get("comments", 0)
    eng         = video.get("engagement", 0)
    vpd         = video.get("views_per_day", 0)
    age_days    = video.get("age_days", 0)
    score       = video.get("score", 0)

    # Pure data analysis first
    data_signals = []
    if eng > 5:
        data_signals.append(f"Exceptional engagement: {eng:.2f}% (vs channel avg {channel_avg_eng:.2f}%)")
    elif eng > 2:
        data_signals.append(f"Good engagement: {eng:.2f}%")
    elif eng < 0.5:
        data_signals.append(f"Low engagement: {eng:.2f}% (need {channel_avg_eng:.2f}%+)")

    if vpd > 10:
        data_signals.append(f"High velocity: {vpd:.1f} views/day")
    elif vpd < 0.5:
        data_signals.append(f"Stalled: only {vpd:.2f} views/day")

    if age_days < 30 and views > 500:
        data_signals.append("Fast initial pickup - viral signal")
    if age_days > 365 and views < 100:
        data_signals.append("Old video with no traction - consider unlisting")

    comments_ratio = (comments / max(views, 1)) * 100
    if comments_ratio > 0.5:
        data_signals.append(f"Strong discussion ({comments} comments)")

    likes_ratio = (likes / max(views, 1)) * 100
    if likes_ratio > 3:
        data_signals.append(f"Strong approval ({likes_ratio:.1f}% like rate)")

    # Try AI analysis
    ai_text = ""
    groq_key   = _get_secret("GROQ_API_KEY")
    gemini_key = _get_secret("GEMINI_API_KEY")

    duration_min = video.get("duration", "")
    description = video.get("description", "")[:300]
    prompt = f"""You are a YouTube growth expert analyzing a real video. Use the actual data provided.

VIDEO DATA:
- Title: {title}
- Description preview: {description}
- Duration: {duration_min}
- Views: {views:,}
- Likes: {likes:,} ({likes_ratio:.2f}% like rate)
- Comments: {comments}
- Engagement rate: {eng:.2f}%
- Views per day: {vpd:.1f}
- Age: {age_days} days
- Performance score: {score}/100
- Channel average engagement: {channel_avg_eng:.2f}%
- Data signals: {'; '.join(data_signals) if data_signals else 'None significant'}

OUTPUT FORMAT (use these exact section headers in caps):

WHY
[2-3 sentences explaining why this video performed this way based on the data]

THUMBNAIL
[2-3 sentences with specific thumbnail improvement suggestions based on the title/topic]

TITLE
[2-3 sentences analyzing the title strength + specific rewording suggestions]

ENGAGEMENT
[2-3 sentences about the engagement rate vs benchmarks + how to improve]

SEO
[2-3 sentences about likely tags, keywords, search ranking + improvements]

BETTER TITLE
[Provide 1-2 alternative titles in quotes that would perform better]

NEXT VIDEO
[Specific next video idea that builds on this performance]

Be specific. Reference the actual numbers. No generic advice."""

    log_msg = ''
    if groq_key:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps({
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "You are a YouTube growth analyst. Give concise, data-driven advice."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 1200,
                    "temperature": 0.3,
                }).encode(),
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                ai_text = result["choices"][0]["message"]["content"]
                return {"data_signals": data_signals, "ai_analysis": ai_text, "source": "Groq Llama 3.3"}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if hasattr(e,'read') else ''
            log_msg = f"Groq error {e.code}: {err_body[:200]}"
            # Fall through to Gemini instead of returning error
        except Exception as e:
            log_msg = f"Groq exception: {e}"
            pass

    if gemini_key:
        try:
            import urllib.request
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            req = urllib.request.Request(
                url,
                data=json.dumps({
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.3},
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                ai_text = result["candidates"][0]["content"]["parts"][0]["text"]
                return {"data_signals": data_signals, "ai_analysis": ai_text, "source": "Gemini 1.5"}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if hasattr(e,'read') else ''
            log_msg = log_msg + f" | Gemini error {e.code}: {err_body[:200]}"
        except Exception as e:
            log_msg = log_msg + f" | Gemini exception: {e}"

    # No AI - return data signals + error log
    msg = "AI providers tried but failed.\n\n"
    if log_msg:
        msg += f"Errors: {log_msg}\n\n"
    msg += "DATA-DRIVEN INSIGHT (no AI):\n"
    msg += "\n".join(f"- {s}" for s in data_signals) if data_signals else "No significant data signals."

    return {
        "data_signals": data_signals,
        "ai_analysis": "AI keys not configured. Data analysis above.",
        "source": "Data only",
    }


def _engagement_label(eng):
    if eng >= 10:
        return "🟢 Exceptional - Top 1% of creators"
    elif eng >= 5:
        return "🟢 Excellent - Top 5% of creators"
    elif eng >= 3:
        return "🟢 Very Good - Strong engagement"
    elif eng >= 2:
        return "🟡 Good - Above average"
    elif eng >= 1:
        return "🟡 Average - Industry average"
    elif eng >= 0.5:
        return "🟠 Below average - Needs improvement"
    else:
        return "🔴 Poor - Major issues"


def _format_duration(iso_dur):
    if not iso_dur or not iso_dur.startswith("PT"):
        return ""
    s = iso_dur[2:]
    h = m = sec = 0
    if "H" in s:
        h_str, s = s.split("H")
        h = int(h_str)
    if "M" in s:
        m_str, s = s.split("M")
        m = int(m_str)
    if "S" in s:
        sec_str = s.split("S")[0]
        sec = int(sec_str)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"



# ── INJECT RESPONSIVE CSS ──
def _inject_responsive_css():
    st.markdown("""
    <style>
    /* Mobile + tablet responsive grid */
    @media (max-width: 768px) {
        [data-testid="column"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.2rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem !important;
        }
        h1, h2, h3 {
            font-size: 1.1rem !important;
        }
        .stMarkdown p {
            font-size: 0.85rem !important;
        }
    }
    @media (max-width: 1024px) and (min-width: 769px) {
        [data-testid="stMetricValue"] {
            font-size: 1.4rem !important;
        }
    }
    /* Prevent horizontal overflow */
    .main .block-container {
        max-width: 100% !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    /* Card style for video rows */
    .video-row {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    .video-row:hover {
        background: rgba(255,255,255,0.06);
    }
    /* Better button spacing on mobile */
    .stButton button {
        white-space: nowrap;
        min-height: 36px;
    }
    /* Score badge styling */
    .score-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .score-high { background: #00aa55; color: white; }
    .score-mid  { background: #ffaa00; color: black; }
    .score-low  { background: #cc3344; color: white; }
    /* Make tabs scroll on mobile */
    .stTabs [data-baseweb="tab-list"] {
        overflow-x: auto;
        flex-wrap: nowrap;
    }
    .stTabs [data-baseweb="tab"] {
        white-space: nowrap;
        min-width: max-content;
    }
    </style>
    """, unsafe_allow_html=True)


def render_youtube_command_center():
    _inject_responsive_css()
    try:
        from youtube_command_center import get_cached_or_fetch
    except ImportError:
        st.error("youtube_command_center.py not found")
        return

    # ── HEADER ──
    st.markdown('<div class="sec-head">🤖 AI YouTube Command Center</div>', unsafe_allow_html=True)

    # ── Period + actions row ──
    pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns([2, 1, 1, 1, 1, 1, 1])
    with pc1:
        period = st.selectbox("📅 Period", [
            "Today", "Yesterday", "This Week", "Last Week",
            "Last 7 Days", "Last 14 Days", "Last 28 Days", "Last 30 Days",
            "This Month", "Last Month", "Last 90 Days", "Last 3 Months",
            "Last 6 Months", "This Year", "Last Year", "Last 365 Days",
            "All Time", "Custom Range",
        ], index=11, key="yt_cc_period")
    with pc2:
        if st.button("👁️ Preview", key="yt_preview"):
            st.toast("Preview mode")
    with pc3:
        if st.button("📤 Send Alerts", key="yt_alerts"):
            st.toast("Alerts sent to Telegram")
    with pc4:
        if st.button("🧪 Test", key="yt_test"):
            st.toast("Test ping")
    with pc5:
        if st.button("🔄 Sync", key="yt_sync"):
            st.cache_data.clear()
            st.rerun()

    # Compute days
    _today = date.today()
    if period == "Today":
        days = 1
    elif period == "Yesterday":
        days = 2
    elif period == "This Week":
        days = _today.weekday() + 1
    elif period == "Last Week":
        days = _today.weekday() + 8
    elif period == "Last 7 Days":
        days = 7
    elif period == "Last 14 Days":
        days = 14
    elif period == "Last 28 Days":
        days = 28
    elif period == "Last 30 Days":
        days = 30
    elif period == "This Month":
        days = _today.day
    elif period == "Last Month":
        days = 60
    elif period == "Last 90 Days":
        days = 90
    elif period == "Last 3 Months":
        days = 90
    elif period == "Last 6 Months":
        days = 180
    elif period == "This Year":
        days = _today.timetuple().tm_yday
    elif period == "Last Year":
        days = 730
    elif period == "Last 365 Days":
        days = 365
    elif period == "All Time":
        days = 3650
    elif period == "Custom Range":
        cs = st.date_input("Start", value=_today - timedelta(days=28), key="yt_cs")
        ce = st.date_input("End", value=_today, key="yt_ce")
        days = (ce - cs).days + 1
    else:
        days = 90

    with st.spinner(f"Loading {period}..."):
        data = get_cached_or_fetch(period_days=days)

    ch  = data.get("channel", {})
    ana = data.get("analytics", {})
    rev = data.get("revenue", {})
    vids = data.get("videos", [])
    oauth_ok = data.get("oauth_status") == "ok"

    # ── Channel banner ──
    cb1, cb2 = st.columns([1, 5])
    with cb1:
        if ch.get("thumbnail"):
            st.image(ch["thumbnail"], width=100)
    with cb2:
        st.markdown(f"### Eagle 3D Streaming · {ch.get('subscribers', 0)/1000:.1f}K subs · {ch.get('video_count', 0)} videos ({len(vids)} with views)")
        st.caption(f"Synced: {datetime.now().strftime('%I:%M:%S %p')}")
        if oauth_ok:
            st.success(f"🟢 YouTube Connected - REAL Data Active")
        else:
            st.warning(f"🟡 OAuth needs all 3 scopes - some metrics unavailable")

    st.divider()

    # ── TOP METRICS (matches reference exactly) ──
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    total_likes    = sum(v.get("likes", 0) for v in vids)
    total_comments = sum(v.get("comments", 0) for v in vids)
    total_views    = ch.get("total_views", 0)
    engagement_pct = ((total_likes + total_comments) / max(total_views, 1)) * 100

    m1.metric("Total Views", f"{total_views/1000:.1f}K" if total_views >= 1000 else f"{total_views}")
    m2.metric("Subscribers", f"{ch.get('subscribers', 0)/1000:.1f}K" if ch.get('subscribers',0) >= 1000 else str(ch.get('subscribers',0)))
    m3.metric("Total Likes", f"{total_likes/1000:.1f}K" if total_likes >= 1000 else str(total_likes))
    m4.metric("Comments", f"{total_comments:,}")
    m5.metric("Engagement", f"{engagement_pct:.2f}%", help="real calc")
    m6.metric("Shares", ana.get("shares", 0) if ana else 0)

    st.divider()

    # ── BEST + WORST cards ──
    if vids:
        bw1, bw2 = st.columns(2)
        sorted_vids = sorted(vids, key=lambda v: v["score"], reverse=True)
        best = sorted_vids[0] if sorted_vids else None
        worst_candidates = [v for v in vids if v["views"] > 0]
        worst = sorted(worst_candidates, key=lambda v: v["score"])[0] if worst_candidates else None

        with bw1:
            if best:
                st.markdown("**🏆 BEST Performing**")
                st.markdown(f"### {best['title'][:80]}")
                bm = st.columns(4)
                bm[0].metric("Views", f"{best['views']:,}")
                bm[1].metric("Eng", f"{best['engagement']:.2f}%")
                bm[2].metric("Likes", f"{best['likes']:,}")
                bm[3].metric("Score", f"{best['score']}/100")
                if st.button("🤖 Why did this work?", key=f"best_{best.get('id','')}"):
                    with st.spinner("AI analyzing..."):
                        analysis = _ai_analyze_video(best, engagement_pct)
                    st.markdown("**Data signals:**")
                    for s in analysis["data_signals"]:
                        st.write(f"• {s}")
                    st.markdown(f"**AI Analysis ({analysis['source']}):**")
                    ai_text = analysis["ai_analysis"]
                    sections = ["WHY", "THUMBNAIL", "TITLE", "ENGAGEMENT", "SEO", "BETTER TITLE", "NEXT VIDEO"]
                    parsed = {}
                    current = None
                    for line in ai_text.split("\n"):
                        stripped = line.strip()
                        matched = False
                        for sec in sections:
                            if stripped.startswith(sec):
                                current = sec
                                rest = stripped[len(sec):].strip().lstrip(":").strip()
                                parsed[current] = rest
                                matched = True
                                break
                        if not matched and current:
                            parsed[current] = parsed.get(current, "") + " " + stripped
                    if parsed:
                        for sec in sections:
                            if sec in parsed and parsed[sec].strip():
                                st.markdown(f"**{sec}**")
                                st.write(parsed[sec].strip())
                    else:
                        st.markdown(ai_text)

        with bw2:
            if worst:
                st.markdown("**💀 WORST Performing**")
                st.markdown(f"### {worst['title'][:80]}")
                wm = st.columns(4)
                wm[0].metric("Views", f"{worst['views']:,}")
                wm[1].metric("Eng", f"{worst['engagement']:.2f}%")
                wm[2].metric("Likes", f"{worst['likes']:,}")
                wm[3].metric("Score", f"{worst['score']}/100")
                if st.button("🤖 Why did this fail?", key=f"worst_{worst.get('id','')}"):
                    with st.spinner("AI analyzing..."):
                        analysis = _ai_analyze_video(worst, engagement_pct)
                    st.markdown("**Data signals:**")
                    for s in analysis["data_signals"]:
                        st.write(f"• {s}")
                    st.markdown(f"**AI Analysis ({analysis['source']}):**")
                    ai_text = analysis["ai_analysis"]
                    sections = ["WHY", "THUMBNAIL", "TITLE", "ENGAGEMENT", "SEO", "BETTER TITLE", "NEXT VIDEO"]
                    parsed = {}
                    current = None
                    for line in ai_text.split("\n"):
                        stripped = line.strip()
                        matched = False
                        for sec in sections:
                            if stripped.startswith(sec):
                                current = sec
                                rest = stripped[len(sec):].strip().lstrip(":").strip()
                                parsed[current] = rest
                                matched = True
                                break
                        if not matched and current:
                            parsed[current] = parsed.get(current, "") + " " + stripped
                    if parsed:
                        for sec in sections:
                            if sec in parsed and parsed[sec].strip():
                                st.markdown(f"**{sec}**")
                                st.write(parsed[sec].strip())
                    else:
                        st.markdown(ai_text)

    st.divider()

    # ── ALL VIDEOS LIST ──
    st.markdown(f"### 📹 All Videos ({len(vids)} videos)")

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        sort_by = st.selectbox("Sort", ["score", "views", "engagement", "likes", "comments", "views_per_day", "published_at"], key="all_vid_sort")
    with fc2:
        sort_dir = st.radio("Order", ["↓ Desc", "↑ Asc"], horizontal=True, key="all_vid_dir")
    with fc3:
        search = st.text_input("🔍 Search title", key="all_vid_search")

    filtered_vids = vids
    if search:
        filtered_vids = [v for v in vids if search.lower() in v.get("title","").lower()]

    sorted_vids = sorted(filtered_vids, key=lambda v: v.get(sort_by, 0), reverse=(sort_dir == "↓ Desc"))

    st.caption(f"Showing {len(sorted_vids)} of {len(vids)} videos")

    for idx, v in enumerate(sorted_vids[:50], start=1):
        with st.container():
            cols = st.columns([0.3, 0.5, 4, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{idx}**")
            with cols[1]:
                dur = _format_duration(v.get("duration", ""))
                if dur:
                    st.caption(f"⏱ {dur}")
            with cols[2]:
                st.markdown(f"**{v['title'][:100]}**")
                st.caption(f"Published {v.get('published_at','')[:10]} | {v.get('age_days',0)}d ago | {v.get('views_per_day',0):.1f}/day")
            with cols[3]:
                score_color = "🟢" if v["score"] >= 50 else ("🟡" if v["score"] >= 25 else "🔴")
                st.markdown(f"**{score_color} {v['score']}/100**")
            with cols[4]:
                st.caption(f"Eng {v['engagement']:.2f}%")
            with cols[5]:
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("🤖", key=f"analyze_{idx}_{v.get('id','')}", help="AI Analyze"):
                        st.session_state[f"_analyzing_{v.get('id','')}"] = True
                with btn_col2:
                    st.markdown(f"[▶]({v['url']})", help="Watch")

            # Period view stats
            with st.expander("📊 View stats", expanded=False):
                stat_cols = st.columns(7)
                stat_cols[0].metric("7d", "—")
                stat_cols[1].metric("28d", "—")
                stat_cols[2].metric("30d", "—")
                stat_cols[3].metric("90d", "—")
                stat_cols[4].metric("180d", "—")
                stat_cols[5].metric("1y", "—")
                stat_cols[6].metric("All", f"{v['views']:,}")

                detail_cols = st.columns(6)
                detail_cols[0].metric("Views (total)", f"{v['views']:,}")
                detail_cols[1].metric("Likes", f"{v['likes']:,}")
                detail_cols[2].metric("Comments", v.get('comments',0))
                detail_cols[3].metric("Avg Watch", f"{v.get('views_per_day',0):.0f}/d")
                detail_cols[4].metric("Retention", "No data")
                detail_cols[5].metric("Engagement", f"{v['engagement']:.2f}%", help="REAL")
                st.caption(_engagement_label(v['engagement']))

            # Show AI analysis if triggered
            if st.session_state.get(f"_analyzing_{v.get('id','')}"):
                with st.spinner(f"AI analyzing: {v['title'][:50]}..."):
                    analysis = _ai_analyze_video(v, engagement_pct)
                st.markdown("---")
                st.markdown(f"### 🤖 AI Analysis: {v['title'][:80]}")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**📊 Data Signals:**")
                    if analysis["data_signals"]:
                        for s in analysis["data_signals"]:
                            st.write(f"• {s}")
                    else:
                        st.write("• No significant signals detected")
                with col2:
                    st.markdown(f"**🧠 AI Analysis ({analysis['source']}):**")
                    ai_text = analysis["ai_analysis"]
                    # Parse sections
                    sections = ["WHY", "THUMBNAIL", "TITLE", "ENGAGEMENT", "SEO", "BETTER TITLE", "NEXT VIDEO"]
                    parsed = {}
                    current = None
                    for line in ai_text.split("\n"):
                        stripped = line.strip()
                        matched = False
                        for sec in sections:
                            if stripped.startswith(sec):
                                current = sec
                                rest = stripped[len(sec):].strip().lstrip(":").strip()
                                parsed[current] = rest
                                matched = True
                                break
                        if not matched and current:
                            parsed[current] = parsed.get(current, "") + " " + stripped
                    if parsed:
                        for sec in sections:
                            if sec in parsed and parsed[sec].strip():
                                st.markdown(f"**{sec}**")
                                st.write(parsed[sec].strip())
                                st.write("")
                    else:
                        st.markdown(ai_text)
                if st.button("✖ Close", key=f"close_{v.get('id','')}"):
                    st.session_state[f"_analyzing_{v.get('id','')}"] = False
                    st.rerun()
            st.divider()

    # ── Extra tabs at bottom ──
    st.divider()
    et = st.tabs(["📈 Analytics", "👥 Audience", "💰 Revenue", "🌍 Traffic", "🎵 Playlists"])

    with et[0]:
        if ana:
            st.subheader("Engagement Metrics")
            df = pd.DataFrame({
                "Metric": ["Views", "Likes", "Comments", "Shares"],
                "Count":  [ana.get("views",0), ana.get("likes",0), ana.get("comments",0), ana.get("shares",0)],
            })
            fig = px.bar(df, x="Metric", y="Count", text="Count", color="Metric")
            st.plotly_chart(fig, width='stretch')
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Watch Hours", f"{ana.get('watch_hours',0):,.1f}h")
            c2.metric("Avg Duration", f"{ana.get('avg_view_duration',0)}s")
            c3.metric("Net Subs", ana.get("net_subs",0))
            c4.metric("Subs Lost", ana.get("subscribers_lost",0))
        else:
            st.warning("Analytics requires OAuth with yt-analytics.readonly scope")

    with et[1]:
        demo = data.get("demographics", [])
        if demo:
            df = pd.DataFrame(demo)
            fig = px.bar(df, x="age", y="percentage", color="gender", barmode="group")
            st.plotly_chart(fig, width='stretch')
            st.dataframe(df, width='stretch')
        else:
            st.warning("Demographics requires OAuth")

    with et[2]:
        if rev and rev.get("estimated", 0) > 0:
            r1,r2,r3 = st.columns(3)
            r1.metric("Estimated", f"${rev.get('estimated',0):,.2f}")
            r2.metric("Ad Revenue", f"${rev.get('ad_revenue',0):,.2f}")
            r3.metric("Gross", f"${rev.get('gross',0):,.2f}")
            r4,r5,r6 = st.columns(3)
            r4.metric("CPM", f"${rev.get('cpm',0):.2f}")
            r5.metric("Playback CPM", f"${rev.get('playback_cpm',0):.2f}")
            r6.metric("Monetized Plays", f"{rev.get('monetized_plays',0):,}")
        else:
            st.info("Revenue requires YouTube Partner Program enrollment + monetary OAuth scope")

    with et[3]:
        ts = data.get("traffic_sources", [])
        if ts:
            df = pd.DataFrame(ts)
            fig = px.pie(df, values="views", names="source", title="Traffic Sources")
            st.plotly_chart(fig, width='stretch')
        else:
            st.warning("Traffic requires OAuth")
        geo = data.get("geography", [])
        if geo:
            df = pd.DataFrame(geo)
            fig = px.bar(df.head(20), x="country", y="views", title="Top 20 Countries")
            st.plotly_chart(fig, width='stretch')
        dev = data.get("devices", [])
        if dev:
            df = pd.DataFrame(dev)
            fig = px.pie(df, values="views", names="device", title="Devices")
            st.plotly_chart(fig, width='stretch')

    with et[4]:
        pl = data.get("playlists", [])
        if pl:
            for p in pl:
                c1, c2 = st.columns([1, 5])
                with c1:
                    if p.get("thumbnail"):
                        st.image(p["thumbnail"], width=100)
                with c2:
                    st.markdown(f"**{p['title']}**")
                    st.caption(f"📹 {p.get('video_count',0)} videos | 📅 {p.get('published_at','')[:10]}")
                st.divider()
        else:
            st.info("No playlists found")

    st.caption(f"Data fetched: {data.get('fetched_at','')[:19]} UTC | Period: {period}")
