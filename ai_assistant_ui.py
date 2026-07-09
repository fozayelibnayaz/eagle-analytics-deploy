#!/usr/bin/env python3
"""AI Assistant UI - chat interface with platform context + tools"""

import streamlit as st
from datetime import datetime


SUGGESTED_QUESTIONS = {
    "all": [
        "How is the business doing overall?",
        "What's my biggest opportunity right now?",
        "Compare this month vs last month across all platforms",
        "Where should I focus my time this week?",
        "What 3 things should I fix immediately?",
        "Give me a 30-day action plan",
    ],
    "kpi": [
        "How many signups today vs last week?",
        "What's my best lead source?",
        "Why is my conversion rate low?",
        "Predict end-of-month KPIs",
        "Which countries sign up most?",
        "Show me the funnel breakdown",
    ],
    "youtube": [
        "How is my channel doing overall?",
        "What's my best performing video and why?",
        "Which videos have the worst retention?",
        "What content should I create next?",
        "Show me engagement breakdown",
        "Compare my top 5 vs bottom 5 videos",
        "What patterns do you see in my viral videos?",
        "Why are some videos getting 0 views?",
        "Give me a 30-day action plan",
        "What times should I upload?",
    ],
    "linkedin": [
        "Which post performed best and why?",
        "Should I post more or focus on quality?",
        "Who are my top competitors and what do they do?",
        "What's the best time to post?",
        "How can I grow followers faster?",
        "What content drives the most engagement?",
    ],
    "ga4": [
        "Where is my traffic coming from?",
        "Which countries drive the most sessions?",
        "How can I improve website traffic?",
        "What pages should I optimize?",
        "Compare this month vs last month",
    ],
    "customer_success": [
        "Who are my at-risk customers?",
        "What's my average customer lifetime?",
        "Why are people canceling?",
        "Show me the customer funnel",
        "Which customers should I upsell?",
        "What's the churn rate trend?",
    ],
}


def render_ai_assistant(default_platform="all"):
    st.markdown('<div class="sec-head">🤖 AI Assistant</div>', unsafe_allow_html=True)
    st.caption("Powered by Groq + Gemini · Uses REAL data from your MongoDB · Has conversation memory")

    user_email = st.session_state.get("user_email", "anonymous")

    # Platform selector
    pc1, pc2, pc3 = st.columns([2, 1, 1])
    with pc1:
        platform = st.selectbox(
            "🎯 Focus area",
            ["all", "kpi", "youtube", "linkedin", "ga4", "customer_success"],
            index=["all","kpi","youtube","linkedin","ga4","customer_success"].index(default_platform),
            key=f"ai_platform_{default_platform}",
        )
    with pc2:
        if st.button("🗑️ Clear chat", key=f"ai_clear_{default_platform}"):
            st.session_state[f"ai_history_{platform}"] = []
            st.rerun()
    with pc3:
        if st.button("📥 Load past", key=f"ai_load_{default_platform}"):
            try:
                from ai_assistant_engine import get_history
                past = get_history(user_email, platform, limit=20)
                msgs = []
                for p in reversed(past):
                    msgs.append({"role": "user", "content": p["question"]})
                    msgs.append({"role": "assistant", "content": p["answer"]})
                st.session_state[f"ai_history_{platform}"] = msgs
                st.success(f"Loaded {len(past)} past conversations")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    # Initialize history
    hist_key = f"ai_history_{platform}"
    if hist_key not in st.session_state:
        st.session_state[hist_key] = []

    history = st.session_state[hist_key]

    # ── Show suggested questions if no history ──
    if not history:
        st.markdown("### ✨ Ask me anything")
        suggestions = SUGGESTED_QUESTIONS.get(platform, SUGGESTED_QUESTIONS["all"])
        cols = st.columns(2)
        for i, q in enumerate(suggestions):
            with cols[i % 2]:
                if st.button(q, key=f"sug_{platform}_{i}", width='stretch'):
                    st.session_state[f"_pending_q_{platform}"] = q
                    st.rerun()

    # ── Show chat history ──
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Process pending question from suggestion click ──
    pending_key = f"_pending_q_{platform}"
    if st.session_state.get(pending_key):
        q = st.session_state.pop(pending_key)
        _process(q, platform, history, user_email, hist_key)
        st.rerun()

    # ── Chat input ──
    q = st.chat_input("Ask anything about your data...", key=f"legacy_ai_input_{platform}")
    if q:
        _process(q, platform, history, user_email, hist_key)
        st.rerun()

    # ── AI Power Tools ──
    st.divider()
    with st.expander(f"⚡ AI Power Tools for {platform.upper()}", expanded=False):
        try:
            from ai_assistant_engine import TOOLS, run_tool
            # Show tools for current platform - all 30 per platform
            tools = TOOLS.get(platform, [])
            if not tools and platform == "all":
                tools = TOOLS.get("all", [])
            if not tools:
                tools = TOOLS.get("kpi", [])
            st.caption(f"⚡ {len(tools)} specialized AI tools that analyze YOUR real {platform.upper()} data")

            tool_cols = st.columns(3)
            for i, tool in enumerate(tools):
                with tool_cols[i % 3]:
                    with st.container(border=True):
                        st.markdown(f"**{tool['name']}**")
                        st.caption(tool["desc"])
                        needs_input = "input" in tool
                        user_input = ""
                        if needs_input:
                            user_input = st.text_input(
                                tool.get("input", "Input"),
                                key=f"tool_in_{platform}_{tool['id']}",
                                placeholder=tool.get("input", ""),
                            )
                        if st.button(f"▶ Run", key=f"tool_run_{platform}_{tool['id']}", width='stretch'):
                            if needs_input and not user_input:
                                st.warning(f"Please enter {tool['input']}")
                            else:
                                with st.spinner(f"Running {tool['name']}..."):
                                    result = run_tool(platform, tool["id"], user_input, user_email)
                                if result.get("error"):
                                    st.error(result["error"])
                                else:
                                    st.success(f"✅ {tool['name']} done")
                                    st.markdown(result["answer"])
                                    st.caption(f"via {result['source']}")
        except Exception as e:
            st.warning(f"Tools error: {e}")


def _process(question, platform, history, user_email, hist_key):
    from ai_assistant_engine import ask_ai
    history.append({"role": "user", "content": question})
    with st.spinner("🤖 Thinking..."):
        result = ask_ai(question, platform=platform, history=history, user_email=user_email)
    if result.get("error"):
        history.append({"role": "assistant", "content": f"⚠️ Error: {result['error']}"})
    else:
        ans = result["answer"]
        ans += f"\n\n*via {result['source']}*"
        history.append({"role": "assistant", "content": ans})
    st.session_state[hist_key] = history
