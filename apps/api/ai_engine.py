"""
ai_engine.py — Unified AI Engine for Eagle3D KPI System v2
==========================================================
Supports: Groq (fast), Google Gemini, fallback to rule-based.
8+ AI tools for deep analytics. Chat history. Smart context.
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

# ── Provider detection ─────────────────────────────────────

def _get_provider():
    """Returns 'groq', 'gemini', or 'rule_based'. Detects from env + Streamlit secrets."""
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    try:
        import streamlit as st
        if "GROQ_API_KEY" in st.secrets:
            _gk = st.secrets["GROQ_API_KEY"]
            if _gk and str(_gk).strip() and len(str(_gk).strip()) > 10:
                return "groq"
        if "GEMINI_API_KEY" in st.secrets:
            _gmk = st.secrets["GEMINI_API_KEY"]
            if _gmk and str(_gmk).strip() and len(str(_gmk).strip()) > 10:
                return "gemini"
    except Exception:
        pass
    return "rule_based"


def _get_provider_debug():
    """Returns (provider, debug_info) for sidebar display."""
    info = {"env_groq": False, "env_gemini": False, "secret_groq": False, "secret_gemini": False,
            "groq_len": 0, "gemini_len": 0}
    info["env_groq"] = bool(os.environ.get("GROQ_API_KEY"))
    info["env_gemini"] = bool(os.environ.get("GEMINI_API_KEY"))
    try:
        import streamlit as st
        _gk = st.secrets.get("GROQ_API_KEY", "")
        _gmk = st.secrets.get("GEMINI_API_KEY", "")
        info["secret_groq"] = bool(_gk)
        info["secret_gemini"] = bool(_gmk)
        info["groq_len"] = len(str(_gk).strip())
        info["gemini_len"] = len(str(_gmk).strip())
    except Exception:
        pass
    return _get_provider(), info


def _get_api_key(provider):
    """Get API key from env or Streamlit secrets."""
    key_name = "GROQ_API_KEY" if provider == "groq" else "GEMINI_API_KEY"
    key = os.environ.get(key_name, "")
    if key:
        return key
    try:
        import streamlit as st
        if key_name in st.secrets:
            val = st.secrets[key_name]
            if val and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return ""


# ── Groq API (OpenAI-compatible) ────────────────────────────

def _call_groq(system_prompt: str, user_message: str, api_key: str) -> str:
    """Call Groq API (fast LLM inference). NO fallback to Gemini here — handled by ask_ai."""
    import urllib.request
    import json as _json

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = _json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.3,
        "max_tokens": 2500,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        raise RuntimeError(f"Groq API error: {e}")


# ── Gemini API ──────────────────────────────────────────────

def _call_gemini(system_prompt: str, user_message: str, api_key: str) -> str:
    """Call Google Gemini API."""
    import urllib.request
    import json as _json

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = _json.dumps({
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_message}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2500},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
            return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        raise RuntimeError(f"Gemini API error: {e}")


# ── Rule-based fallback ─────────────────────────────────────

def _rule_based_answer(question: str, data_context: str) -> str:
    """Intelligent rule-based analysis when no AI API is available."""
    q = question.lower()
    lines = [f"## 📊 Analysis\n"]
    
    # Extract numbers from context
    import re
    
    # Smart pattern matching
    if any(w in q for w in ["why", "reason", "cause", "dropped", "declined", "decreased"]):
        lines.append("### 🔍 Root Cause Analysis")
        lines.append("Based on the data patterns:")
        lines.append("- **Check if there were any marketing changes** in the comparison period")
        lines.append("- **Seasonal patterns** may be affecting traffic quality")
        lines.append("- **Source mix shifts** could change conversion rates")
        lines.append("- **Technical issues** may have impacted sign-up flow")
        lines.append("\n*Connect Groq or Gemini for deeper AI analysis.*")
    elif any(w in q for w in ["improve", "increase", "grow", "better", "optimize", "strategy"]):
        lines.append("### 💡 Growth Recommendations")
        lines.append("Based on current data patterns:")
        lines.append("1. **Optimize top-performing channels** — double down on what's working")
        lines.append("2. **Improve onboarding flow** — reduce friction from sign-up to first upload")
        lines.append("3. **Content marketing** — create tutorials for Unreal Engine / 3D streaming")
        lines.append("4. **AI search optimization** — ensure docs are indexed by ChatGPT, Gemini, Perplexity")
        lines.append("5. **Referral program** — incentivize word-of-mouth with credits")
        lines.append("\n*Connect Groq or Gemini for data-specific recommendations.*")
    elif any(w in q for w in ["predict", "forecast", "future", "next week", "next month", "next", "can we get", "how many more", "achieve", "goal", "expect", "will we"]):
        lines.append("### 🔮 Prediction Analysis")
        
        # Parse data context for prediction
        _signup_vals = []
        _upload_vals = []
        _paid_vals = []
        for _line in data_context.split("\n"):
            _m = re.match(r'- (\d{4}-\d{2}-\d{2}):\s*(\d+)\s*signup.*?(\d+)\s*upload.*?(\d+)\s*paid', _line)
            if _m:
                _signup_vals.append(int(_m.group(2)))
                _upload_vals.append(int(_m.group(3)))
                _paid_vals.append(int(_m.group(4)))
            _m2 = re.match(r'- Sign-ups:\s*(\d+)', _line)
            if _m2 and not _signup_vals:
                _signup_vals.append(int(_m2.group(1)))
            _m3 = re.match(r'- First Uploads:\s*(\d+)', _line)
            if _m3 and not _upload_vals:
                _upload_vals.append(int(_m3.group(1)))
            _m4 = re.match(r'- Paid Customers:\s*(\d+)', _line)
            if _m4 and not _paid_vals:
                _paid_vals.append(int(_m4.group(1)))

        # Determine days remaining in month
        from datetime import datetime as _dt
        _now = _dt.now()
        _days_in_month = 30  # approximate
        _days_passed = _now.day
        _days_remaining = max(1, _days_in_month - _days_passed)

        if _signup_vals:
            _total_signups = sum(_signup_vals)
            _daily_avg = _total_signups / max(1, len(_signup_vals)) if _signup_vals else 0
            
            # Trend: use last 7 days if available
            _recent = _signup_vals[-7:] if len(_signup_vals) >= 7 else _signup_vals
            _recent_avg = sum(_recent) / max(1, len(_recent))
            
            # Growth rate
            if len(_signup_vals) >= 4:
                _first_half = sum(_signup_vals[:len(_signup_vals)//2])
                _second_half = sum(_signup_vals[len(_signup_vals)//2:])
                _growth_rate = ((_second_half - _first_half) / max(1, _first_half)) if _first_half > 0 else 0
            else:
                _growth_rate = 0
            
            _best_daily = _recent_avg * (1 + max(0.1, _growth_rate))
            _worst_daily = _recent_avg * 0.6
            _possible_daily = _recent_avg
            
            _best_total = _total_signups + int(_best_daily * _days_remaining)
            _possible_total = _total_signups + int(_possible_daily * _days_remaining)
            _worst_total = _total_signups + int(_worst_daily * _days_remaining)
            
            _best_additional = int(_best_daily * _days_remaining)
            _possible_additional = int(_possible_daily * _days_remaining)
            _worst_additional = int(_worst_daily * _days_remaining)

            lines.append(f"**📅 Current Month Progress ({_days_passed}/{_days_in_month} days passed)**")
            lines.append(f"- Current sign-ups: **{_total_signups}**")
            lines.append(f"- Daily average: **{_daily_avg:.1f}**")
            lines.append(f"- Recent trend (7d): **{_recent_avg:.1f}/day**")
            lines.append(f"- Growth rate: **{_growth_rate:+.0%}**")
            lines.append(f"")
            lines.append(f"**📈 Sign-up Forecast for Remaining {_days_remaining} Days:**")
            lines.append(f"")
            lines.append(f"| Scenario | Additional | Month Total | Daily Rate |")
            lines.append(f"|----------|-----------|-------------|------------|")
            lines.append(f"| 🟢 **Best Case** | +{_best_additional} | **{_best_total}** | {_best_daily:.1f}/day |")
            lines.append(f"| 🟡 **Possible** | +{_possible_additional} | **{_possible_total}** | {_possible_daily:.1f}/day |")
            lines.append(f"| 🔴 **Worst Case** | +{_worst_additional} | **{_worst_total}** | {_worst_daily:.1f}/day |")
            lines.append(f"")
            
            # Date-wise breakdown
            lines.append(f"**📊 Date-wise Projection (Possible Scenario):**")
            for _d in range(1, min(_days_remaining + 1, 15)):
                _proj_date = (_now + __import__('datetime').timedelta(days=_d)).strftime("%Y-%m-%d")
                _proj_cumulative = _total_signups + int(_possible_daily * _d)
                lines.append(f"- {_proj_date}: ~{_proj_cumulative} total (+{int(_possible_daily)}/day)")
            
            if _days_remaining > 14:
                lines.append(f"- ... and {_days_remaining - 14} more days at ~{int(_possible_daily)}/day")

            # Upload and paid forecasts
            if _upload_vals:
                _total_uploads = sum(_upload_vals)
                _u_avg = _total_uploads / max(1, len(_upload_vals))
                _u_projected = _total_uploads + int(_u_avg * _days_remaining)
                lines.append(f"\n**📤 Upload Forecast:** Currently {_total_uploads}, projected **{_u_projected}** by month end")
            if _paid_vals:
                _total_paid = sum(_paid_vals)
                _p_avg = _total_paid / max(1, len(_paid_vals))
                _p_projected = _total_paid + int(_p_avg * _days_remaining)
                lines.append(f"**💳 Paid Forecast:** Currently {_total_paid}, projected **{_p_projected}** by month end")

            lines.append(f"\n💡 *Connect Groq/Gemini for AI-enhanced predictions with deeper pattern analysis.*")
        else:
            lines.append("Insufficient data for prediction. Need daily breakdown data.")
            lines.append("\n*Connect Groq or Gemini for AI-powered forecasting.*")
    else:
        lines.append(data_context)
        lines.append("\n### 💡 Summary")
        lines.append("The data above shows your current performance metrics. For specific insights and recommendations, try asking:")
        lines.append("- \"Why did signups change?\" — for root cause analysis")
        lines.append("- \"How to improve uploads?\" — for growth recommendations")
        lines.append("- \"How many sign-ups can we get more this month?\" — for 3-scenario predictions")
        lines.append("\n*Connect Groq or Gemini API for deeper AI analysis.*")
    
    lines.append("\n---")
    lines.append("*Analysis by Eagle Analytics Hub (rule-based mode)*")
    return "\n".join(lines)


# ── Data Context Builder ────────────────────────────────────

def build_data_context(
    kpi_df=None, utm_df=None, pages_df=None, events_df=None,
    geo_df=None, leads_df=None, period_label: str = "this period",
    prev_kpi_df=None, prev_utm_df=None,
) -> str:
    """Build a comprehensive data summary for AI context."""
    lines = []
    
    # KPI Data
    if kpi_df is not None and not kpi_df.empty:
        s = int(pd.to_numeric(kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
        u = int(pd.to_numeric(kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum())
        p = int(pd.to_numeric(kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum())
        
        lines.append(f"### CRM KPI Data ({period_label})")
        lines.append(f"- Sign-ups: {s}")
        lines.append(f"- First Uploads: {u}")
        lines.append(f"- Paid Customers: {p}")
        
        # Funnel rates
        s2u = (u / s * 100) if s > 0 else 0
        u2p = (p / u * 100) if u > 0 else 0
        s2p = (p / s * 100) if s > 0 else 0
        lines.append(f"- Sign-up → Upload rate: {s2u:.1f}%")
        lines.append(f"- Upload → Paid rate: {u2p:.1f}%")
        lines.append(f"- Sign-up → Paid rate: {s2p:.1f}%")
        
        if prev_kpi_df is not None and not prev_kpi_df.empty:
            ps = int(pd.to_numeric(prev_kpi_df.get("signups", 0), errors="coerce").fillna(0).sum())
            pu = int(pd.to_numeric(prev_kpi_df.get("first_uploads", 0), errors="coerce").fillna(0).sum())
            pp = int(pd.to_numeric(prev_kpi_df.get("paid_customers", 0), errors="coerce").fillna(0).sum())
            
            s_change = ((s - ps) / ps * 100) if ps > 0 else 0
            u_change = ((u - pu) / pu * 100) if pu > 0 else 0
            p_change = ((p - pp) / pp * 100) if pp > 0 else 0
            
            lines.append(f"\n### Comparison (vs Previous Period)")
            lines.append(f"- Sign-ups: {s} vs {ps} ({s_change:+.1f}%)")
            lines.append(f"- Uploads: {u} vs {pu} ({u_change:+.1f}%)")
            lines.append(f"- Paid: {p} vs {pp} ({p_change:+.1f}%)")
        
        # Daily breakdown
        if "date" in kpi_df.columns and len(kpi_df) > 1:
            lines.append(f"\n### Daily Breakdown")
            for _, row in kpi_df.head(14).iterrows():
                d = row.get("date", "")
                ds = int(pd.to_numeric(row.get("signups", 0), errors="coerce") or 0)
                du = int(pd.to_numeric(row.get("first_uploads", 0), errors="coerce") or 0)
                dp = int(pd.to_numeric(row.get("paid_customers", 0), errors="coerce") or 0)
                lines.append(f"- {d}: {ds} signups, {du} uploads, {dp} paid")
    
    # Lead Sources
    if leads_df is not None and not leads_df.empty:
        lines.append(f"\n### CRM Lead Sources ({period_label})")
        for _, row in leads_df.head(10).iterrows():
            src = row.get("Lead Source", "?")
            cnt = int(pd.to_numeric(row.get("Signups", 0), errors="coerce") or 0)
            pct = row.get("% of Total", 0)
            lines.append(f"- {src}: {cnt} signups ({pct}%)")
    
    # Traffic Sources
    if utm_df is not None and not utm_df.empty:
        lines.append(f"\n### GA4 Traffic ({period_label})")
        src_col = "source_normalized" if "source_normalized" in utm_df.columns else "sessionSource"
        sessions_col = "sessions" if "sessions" in utm_df.columns else src_col
        conv_col = "conversions" if "conversions" in utm_df.columns else None
        
        by_src = utm_df.groupby(src_col).agg(
            sessions=(sessions_col, "sum"),
        ).sort_values("sessions", ascending=False).head(10)
        
        for src, row in by_src.iterrows():
            lines.append(f"- {src}: {int(row['sessions'])} sessions")
    
    return "\n".join(lines)


# ── System Prompt ───────────────────────────────────────────

SYSTEM_PROMPT = """You are Eagle3D AI Analytics Assistant — an expert data analyst for Eagle3D Streaming (a pixel streaming / 3D cloud rendering platform).

Your role:
- Answer questions about sign-ups, uploads, paid customers, traffic, lead sources, conversions
- Provide data-driven insights and business recommendations
- Identify trends, anomalies, and opportunities
- Suggest actionable next steps
- Compare periods and explain changes

Rules:
- Always use the provided data to answer — never make up numbers
- If data is missing or insufficient, say so clearly
- Be concise but thorough
- Use markdown formatting (headers, bullet points, bold)
- When suggesting actions, be specific and actionable
- Consider the business context: Eagle3D is a B2B SaaS for 3D streaming
- Conversion funnel: Traffic → Sign-up → First Upload → Paid Customer

Key business context:
- Sign-ups come from Google, LinkedIn, YouTube, AI tools, referrals
- "First Upload" = user's first project upload (key activation metric)
- The company serves architects, game devs, 3D artists, real estate
- Competitors: Vagon, Parsec, Furioos
- Pricing: Free tier + paid plans
- When reporting numbers, always clarify what is REAL data vs prediction/forecast"""


# ── Main Ask Function ───────────────────────────────────────

def ask_ai(
    question: str,
    kpi_df=None, utm_df=None, pages_df=None, events_df=None,
    geo_df=None, leads_df=None, period_label: str = "this period",
    prev_kpi_df=None, prev_utm_df=None,
) -> dict:
    if not question or len(question.strip()) < 3:
        return {"answer": "Please ask a question.", "provider": "none", "status": "error"}

    provider = _get_provider()
    data_context = build_data_context(
        kpi_df, utm_df, pages_df, events_df, geo_df, leads_df,
        period_label, prev_kpi_df, prev_utm_df,
    )

    user_message = f"""Here is the current data for Eagle3D:

{data_context}

---
User Question: {question}

Please analyze the data above and answer the question thoroughly. Include specific numbers, percentages, and actionable recommendations. Clearly distinguish between REAL data and any forecasts."""

    if provider == "groq":
        api_key = _get_api_key("groq")
        try:
            answer = _call_groq(SYSTEM_PROMPT, user_message, api_key)
        except Exception as e:
            # Try Gemini once, no recursion
            gemini_key = _get_api_key("gemini")
            if gemini_key and len(str(gemini_key).strip()) > 10:
                try:
                    answer = _call_gemini(SYSTEM_PROMPT, user_message, gemini_key)
                    answer = f"*(Groq unavailable, used Gemini)*\n\n{answer}"
                except Exception:
                    answer = _rule_based_answer(question, data_context)
            else:
                answer = _rule_based_answer(question, data_context)
    elif provider == "gemini":
        api_key = _get_api_key("gemini")
        try:
            answer = _call_gemini(SYSTEM_PROMPT, user_message, api_key)
        except Exception as e:
            # Try Groq once, no recursion
            groq_key = _get_api_key("groq")
            if groq_key and len(str(groq_key).strip()) > 10:
                try:
                    answer = _call_groq(SYSTEM_PROMPT, user_message, groq_key)
                    answer = f"*(Gemini unavailable, used Groq)*\n\n{answer}"
                except Exception:
                    answer = _rule_based_answer(question, data_context)
            else:
                answer = _rule_based_answer(question, data_context)
    else:
        answer = _rule_based_answer(question, data_context)

    return {
        "answer": answer,
        "provider": provider,
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
    }


def get_available_tools() -> list:
    """Return list of available AI tools."""
    return [
        {
            "id": "funnel_analysis",
            "name": "📊 Funnel",
            "description": "Analyze the full conversion funnel",
            "prompt": "Analyze the conversion funnel in detail. Where is the biggest drop-off? What specific actions should we take to improve each stage? Include real numbers.",
        },
        {
            "id": "source_attribution",
            "name": "🎯 Sources",
            "description": "Which traffic sources bring the best users?",
            "prompt": "Analyze all traffic and lead sources. Which sources have the highest conversion rates? Which should we invest more in? Which should we stop?",
        },
        {
            "id": "anomaly_detection",
            "name": "🚨 Anomalies",
            "description": "Find unusual patterns or spikes",
            "prompt": "Look for anomalies, unusual patterns, sudden spikes or drops in the data. Compare current period to previous. Flag anything abnormal and explain possible causes.",
        },
        {
            "id": "weekly_brief",
            "name": "📋 Briefing",
            "description": "Comprehensive weekly status report",
            "prompt": "Generate a comprehensive weekly briefing. Include: executive summary, key metrics with real numbers, trends, wins, concerns, and recommended actions.",
        },
        {
            "id": "business_decisions",
            "name": "💡 Decisions",
            "description": "Data-driven business recommendations",
            "prompt": "Based on all the data, what are the top 5 business decisions we should make this week? Be specific, tie each to real data points.",
        },
        {
            "id": "competitor_strategy",
            "name": "🥊 Compete",
            "description": "Competitive analysis and positioning",
            "prompt": "Based on our traffic and conversion data, how should we position Eagle3D against Vagon, Parsec, Furioos? What SEO, content, and partnership strategies?",
        },
        {
            "id": "cohort_analysis",
            "name": "👥 Cohort",
            "description": "Analyze user behavior by signup cohort",
            "prompt": "Analyze the signup-to-upload conversion patterns. Are newer cohorts converting better or worse? What does the data tell us about user activation?",
        },
        {
            "id": "revenue_forecast",
            "name": "💰 Revenue",
            "description": "Revenue prediction based on current pipeline",
            "prompt": "Based on current sign-up and conversion trends, project revenue for next 30/60/90 days. What is the expected customer acquisition? What would improve the forecast?",
        },
        {
            "id": "churn_risk",
            "name": "⚠️ Churn",
            "description": "Identify churn risk signals",
            "prompt": "Analyze the data for churn risk signals. Are there patterns suggesting users are dropping off? What activation metrics should we monitor? Suggest retention strategies.",
        },
        {
            "id": "team_report",
            "name": "📄 Report",
            "description": "Shareable stakeholder report",
            "prompt": "Create a professional stakeholder report with: key metrics summary, period-over-period comparison, top insights, concerns, and next steps. Use tables and clear sections.",
        },
        {
            "id": "growth_hacking",
            "name": "🚀 Growth",
            "description": "Growth hacking strategies based on data",
            "prompt": "Based on our current data, suggest 5 creative growth hacking strategies. Consider our funnel metrics, traffic sources, and conversion rates. Be specific and unconventional.",
        },
        {
            "id": "ai_seo",
            "name": "🤖 AI SEO",
            "description": "Optimize for AI search (ChatGPT, Gemini, Perplexity)",
            "prompt": "How can Eagle3D optimize its online presence for AI-powered search engines? Consider our traffic from AI tools and suggest a comprehensive AI SEO strategy.",
        },
    ]


def run_tool(tool_id: str, kpi_df=None, utm_df=None, pages_df=None,
             events_df=None, geo_df=None, leads_df=None,
             period_label: str = "this period",
             prev_kpi_df=None, prev_utm_df=None) -> dict:
    """Run a predefined AI tool."""
    tools = {t["id"]: t for t in get_available_tools()}
    tool = tools.get(tool_id)
    if not tool:
        return {"answer": f"Tool '{tool_id}' not found.", "provider": "none", "status": "error"}
    
    return ask_ai(
        tool["prompt"],
        kpi_df=kpi_df, utm_df=utm_df, pages_df=pages_df,
        events_df=events_df, geo_df=geo_df, leads_df=leads_df,
        period_label=period_label,
        prev_kpi_df=prev_kpi_df, prev_utm_df=prev_utm_df,
    )
