"""
ai_enhanced_ui.py — Enhanced AI chat UI with memory, streaming, tools, charts
"""
from __future__ import annotations

import uuid
from datetime import datetime

import streamlit as st

from ai_enhanced_engine import (
    chat, load_conversation, save_conversation, list_threads,
    generate_chart_from_prompt,
)


def render_ai_enhanced_page(user_email: str = "") -> None:
    st.markdown("### ✦ AI Insights — Enhanced")
    st.caption("Multi-turn memory · streaming · live MongoDB queries · chart generation")

    # ── Thread management ──
    if "ai_thread_id" not in st.session_state:
        st.session_state["ai_thread_id"] = str(uuid.uuid4())[:8]

    threads = list_threads(user_email, limit=20)

    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        thread_options = {"🆕 New conversation": None}
        for t in threads:
            tid = t.get("thread_id")
            if not tid:
                continue
            preview = ""
            msgs = t.get("messages") or []
            if msgs:
                preview = str(msgs[0].get("content", ""))[:40]
            label = f"{str(t.get('updated_at',''))[:16]} · {preview}"
            thread_options[label] = tid

        selected = st.selectbox("Conversation",
                                  list(thread_options.keys()),
                                  key="ai_thread_selector")
    with c2:
        if st.button("🆕 New", width='stretch'):
            st.session_state["ai_thread_id"] = str(uuid.uuid4())[:8]
            st.session_state["ai_messages"] = []
            st.rerun()
    with c3:
        if st.button("🗑 Clear", width='stretch'):
            st.session_state["ai_messages"] = []
            st.rerun()

    # Switch thread if selected
    chosen_id = thread_options.get(selected)
    if chosen_id and chosen_id != st.session_state["ai_thread_id"]:
        st.session_state["ai_thread_id"] = chosen_id
        st.session_state["ai_messages"] = load_conversation(user_email, chosen_id)
        st.rerun()

    # Load messages
    if "ai_messages" not in st.session_state:
        st.session_state["ai_messages"] = load_conversation(
            user_email, st.session_state["ai_thread_id"])

    messages = st.session_state["ai_messages"]

    # ── Quick prompts (only if new conversation) ──
    if not messages:
        st.markdown("**Try these:**")
        q1, q2, q3, q4 = st.columns(4)
        quick = None
        prompts = [
            ("📊 This month", "How's business this month? Give me the numbers."),
            ("💰 Revenue", "Show me revenue breakdown by traffic source for the last 30 days."),
            ("🔍 Why reject", "Why are uploads being rejected? Show the breakdown."),
            ("�� Chart signups", "Chart signups by source for the last 30 days."),
        ]
        for i, (col, (label, q)) in enumerate(zip([q1, q2, q3, q4], prompts)):
            with col:
                if st.button(label, key=f"ai_qp_{i}", width='stretch'):
                    quick = q
        if quick:
            st.session_state["_pending_query"] = quick
            st.rerun()

    # ── Display history ──
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg.get("content", ""))
            # Show any chart attached
            if msg.get("chart_prompt"):
                fig = generate_chart_from_prompt(msg["chart_prompt"])
                if fig:
                    st.plotly_chart(fig, width='stretch')

    # ── Input ──
    pending = st.session_state.pop("_pending_query", None)
    prompt = pending or st.chat_input("Ask anything about your data...", key="ai_enhanced_chat_input")

    if prompt:
        # Add user message
        messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Check if chart request
        chart_keywords = ["chart", "graph", "plot", "visualize", "visualise"]
        is_chart_request = any(kw in prompt.lower() for kw in chart_keywords)

        # Generate response with streaming
        with st.chat_message("assistant"):
            placeholder = st.empty()
            full_response = ""

            # Stream text
            try:
                for chunk in chat(messages, stream=True):
                    full_response += chunk
                    placeholder.markdown(full_response + "▌")
                placeholder.markdown(full_response)
            except Exception as e:
                full_response = f"❌ Error: {e}"
                placeholder.error(full_response)

            # Generate chart if requested
            chart_prompt = None
            if is_chart_request:
                with st.spinner("Generating chart..."):
                    fig = generate_chart_from_prompt(prompt)
                    if fig:
                        st.plotly_chart(fig, width='stretch')
                        chart_prompt = prompt

        # Save to memory
        msg_to_save = {"role": "assistant", "content": full_response,
                        "at": datetime.utcnow().isoformat()}
        if chart_prompt:
            msg_to_save["chart_prompt"] = chart_prompt
        messages.append(msg_to_save)
        st.session_state["ai_messages"] = messages

        # Persist to Mongo
        save_conversation(user_email,
                           st.session_state["ai_thread_id"], messages)
