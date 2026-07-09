"""
ai_enhanced_engine.py — Eagle 3D Streaming Analytics Hub
==========================================================
Agentic AI with:
  - Multi-turn conversation memory (per user, saved to Mongo)
  - Streaming responses (word-by-word)
  - Function calling (AI runs real MongoDB queries)
  - Chart generation from natural language
  - Period/comparison aware (uses global period_engine)

Providers:
  - Primary: Groq (llama-3.3-70b-versatile, fast + free)
  - Fallback: Gemini (gemini-1.5-flash)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, Generator, List, Optional

import streamlit as st

from mongo_client import (
    count_accepted, count_docs, find_all, find_one,
    upsert_one, get_raw_db,
)


# ═════════════════════════════════════════════════════════════════
# TOOLS — Functions the AI can call to query real data
# ═════════════════════════════════════════════════════════════════
def tool_get_kpi_counts(start: str, end: str) -> Dict[str, Any]:
    """Return signups/uploads/paid counts for a period."""
    return {
        "period": f"{start} to {end}",
        "signups":  count_accepted("signups",  "signup_date",        date_gte=start, date_lte=end),
        "uploads":  count_accepted("uploads",  "upload_date",        date_gte=start, date_lte=end),
        "payments": count_accepted("payments", "first_payment_date", date_gte=start, date_lte=end),
    }


def tool_top_signup_sources(start: str, end: str, limit: int = 10) -> Dict[str, Any]:
    """Return top lead sources by signup count for a period."""
    from attribution_tracker import signups_by_source
    return dict(list(signups_by_source(start, end).items())[:limit])


def tool_top_paying_customers(start: str, end: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Return top paying customers by revenue for a period."""
    rows = find_all("payments",
                     filters={"final_status": "ACCEPTED",
                              "first_payment_date": {"$gte": start, "$lte": end}},
                     sort=[("total_spend", -1)], limit=limit,
                     projection={"email_normalized": 1, "total_spend": 1,
                                 "first_payment_date": 1, "customer_type": 1})
    return rows


def tool_get_revenue(start: str, end: str, new_customers_only: bool = False) -> Dict[str, Any]:
    """Return revenue breakdown for a period."""
    f = {"final_status": "ACCEPTED",
         "first_payment_date": {"$gte": start, "$lte": end}}
    if new_customers_only:
        f["customer_type"] = "NEW_CUSTOMER"
    docs = find_all("payments", f, projection={"total_spend": 1})
    total = sum(float(d.get("total_spend", 0) or 0) for d in docs)
    return {"period": f"{start} to {end}", "total_revenue": round(total, 2),
             "count": len(docs), "new_only": new_customers_only}


def tool_pipeline_health() -> Dict[str, Any]:
    """Return pipeline data-coverage health."""
    from pipeline_gap_scanner import scan_gaps
    return scan_gaps()


def tool_youtube_summary() -> Dict[str, Any]:
    """Return YouTube channel snapshot."""
    ch = find_one("youtube_channel", {}) or {}
    videos = find_all("youtube_videos", limit=1000)
    total_views = sum(int(v.get("views", 0) or 0) for v in videos)
    return {
        "channel":     ch.get("title", "?"),
        "subscribers": int(ch.get("subscribers", 0) or 0),
        "total_videos": len(videos),
        "total_views":  total_views,
    }


def tool_linkedin_summary() -> Dict[str, Any]:
    """Return LinkedIn latest snapshot."""
    hl_rows = find_all("linkedin_highlights_daily",
                       sort=[("snapshot_date", -1)], limit=1)
    if not hl_rows:
        return {"error": "no LinkedIn data"}
    hl = hl_rows[0]
    return {
        "followers":       int(hl.get("total_followers", 0) or 0),
        "impressions":     int(hl.get("impressions", 0) or 0),
        "page_views":      int(hl.get("page_views", 0) or 0),
        "unique_visitors": int(hl.get("unique_visitors", 0) or 0),
        "snapshot_date":   hl.get("snapshot_date"),
    }


def tool_reject_reasons(start: str, end: str,
                         collection: str = "uploads") -> Dict[str, int]:
    """Return rejection reasons breakdown for a period."""
    date_field = {"signups": "signup_date", "uploads": "upload_date",
                   "payments": "first_payment_date"}.get(collection, "signup_date")
    rows = find_all(collection, filters={
        "final_status": "REJECTED",
        date_field: {"$gte": start, "$lte": end},
    }, projection={"rejection_reason": 1, "reason": 1})
    by: Dict[str, int] = {}
    for r in rows:
        reason = r.get("rejection_reason") or r.get("reason", "unknown")
        key = str(reason).split(":")[0].split("(")[0].strip()
        by[key] = by.get(key, 0) + 1
    return dict(sorted(by.items(), key=lambda x: -x[1]))


TOOL_REGISTRY = {
    "get_kpi_counts":         tool_get_kpi_counts,
    "top_signup_sources":     tool_top_signup_sources,
    "top_paying_customers":   tool_top_paying_customers,
    "get_revenue":            tool_get_revenue,
    "pipeline_health":        tool_pipeline_health,
    "youtube_summary":        tool_youtube_summary,
    "linkedin_summary":       tool_linkedin_summary,
    "reject_reasons":         tool_reject_reasons,
}


TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_kpi_counts",
        "description": "Get sign-ups, uploads, and paying customer counts for a date range",
        "parameters": {"type": "object", "properties": {
            "start": {"type": "string", "description": "Start date YYYY-MM-DD"},
            "end":   {"type": "string", "description": "End date YYYY-MM-DD"},
        }, "required": ["start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "top_signup_sources",
        "description": "Get top traffic/lead sources by signup count for a period",
        "parameters": {"type": "object", "properties": {
            "start": {"type": "string"}, "end": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "top_paying_customers",
        "description": "Get top paying customers by revenue for a period",
        "parameters": {"type": "object", "properties": {
            "start": {"type": "string"}, "end": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "get_revenue",
        "description": "Get total revenue for a period, optionally filtered to new customers only",
        "parameters": {"type": "object", "properties": {
            "start": {"type": "string"}, "end": {"type": "string"},
            "new_customers_only": {"type": "boolean", "default": False},
        }, "required": ["start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "pipeline_health",
        "description": "Get data pipeline health (missing/zero days)",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "youtube_summary",
        "description": "Get YouTube channel snapshot (subs, videos, views)",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "linkedin_summary",
        "description": "Get LinkedIn latest snapshot (followers, impressions)",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "reject_reasons",
        "description": "Get rejection reasons breakdown for signups/uploads/payments for a period",
        "parameters": {"type": "object", "properties": {
            "start": {"type": "string"}, "end": {"type": "string"},
            "collection": {"type": "string",
                            "enum": ["signups", "uploads", "payments"],
                            "default": "uploads"},
        }, "required": ["start", "end"]},
    }},
]


# ═════════════════════════════════════════════════════════════════
# CONVERSATION MEMORY
# ═════════════════════════════════════════════════════════════════
def save_conversation(user_email: str, thread_id: str,
                       messages: List[Dict[str, Any]]) -> bool:
    if not user_email:
        return False
    try:
        return upsert_one("ai_conversations", {
            "user_email":  user_email,
            "thread_id":   thread_id,
            "messages":    messages,
            "updated_at":  datetime.utcnow().isoformat(),
        }, ["user_email", "thread_id"])
    except Exception:
        return False


def load_conversation(user_email: str,
                       thread_id: str) -> List[Dict[str, Any]]:
    if not user_email:
        return []
    doc = find_one("ai_conversations", {
        "user_email": user_email, "thread_id": thread_id,
    })
    return doc.get("messages", []) if doc else []


def list_threads(user_email: str, limit: int = 20) -> List[Dict[str, Any]]:
    if not user_email:
        return []
    # Explicit projection — always include thread_id
    return find_all("ai_conversations", {"user_email": user_email},
                     sort=[("updated_at", -1)], limit=limit,
                     projection={"_id": 0, "thread_id": 1,
                                 "updated_at": 1, "messages": 1})


# ═════════════════════════════════════════════════════════════════
# SYSTEM PROMPT (period-aware)
# ═════════════════════════════════════════════════════════════════
def _build_system_prompt() -> str:
    try:
        from period_engine import get_period
        p = get_period()
        period_str = (f"Current selected period: {p.label} "
                       f"({p.start_iso()} to {p.end_iso()}, {p.days} days)")
        if p.compare_enabled:
            period_str += f"\nComparison: {p.compare_label}"
    except Exception:
        period_str = f"Today is {date.today().isoformat()}"

    return f"""You are the AI analytics assistant for Eagle 3D Streaming.

{period_str}

Data available:
  - signups, uploads, payments collections (with final_status = ACCEPTED)
  - daily_kpis aggregated table (post-dedup)
  - YouTube: 262 videos, 1010 subs
  - LinkedIn: 91 posts, 2552 followers
  - GA4 traffic, Customer Success data

Guidelines:
  - ALWAYS call tools to get REAL numbers. Never guess.
  - When user asks about a period, use the current selected period unless they specify otherwise.
  - Use bullet points. Cite specific numbers.
  - If you need multiple pieces of data, call multiple tools in parallel.
  - Be concise (max ~200 words unless user asks for detail).
  - End with 2-3 actionable recommendations when relevant.
"""


# ═════════════════════════════════════════════════════════════════
# CHAT with tool-calling
# ═════════════════════════════════════════════════════════════════
# Cache API keys once at module load (avoids Streamlit-context issues in generators)
def _get_key(name: str) -> str:
    import os
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        return str(st.secrets.get(name, "") or "").strip()
    except Exception:
        return ""


def chat(messages: List[Dict[str, Any]],
         stream: bool = True) -> Generator[str, None, str]:
    """
    Multi-turn chat with automatic tool-calling.
    Yields text chunks. Returns full assistant response at end.
    """
    # PRE-LOAD keys OUTSIDE any nested try/except so generator doesn't lose context
    groq_key   = _get_key("GROQ_API_KEY")
    gemini_key = _get_key("GEMINI_API_KEY")

    system_msg = {"role": "system", "content": _build_system_prompt()}
    full_messages = [system_msg] + messages

    # Try Groq first (supports function calling + streaming)
    try:
        from openai import OpenAI
        if not groq_key:
            raise RuntimeError("No GROQ_API_KEY")
        api_key = groq_key

        client = OpenAI(api_key=api_key,
                        base_url="https://api.groq.com/openai/v1")

        # First call: let model decide if it needs tools
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=full_messages,
            tools=TOOL_SPECS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=1500,
        )
        msg = r.choices[0].message

        # If model called tools, execute them and feed back
        if msg.tool_calls:
            full_messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                   "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                fname = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}

                yield f"\n_🔧 Querying: {fname}({', '.join(f'{k}={v}' for k,v in args.items())})..._\n\n"

                fn = TOOL_REGISTRY.get(fname)
                if fn:
                    try:
                        result = fn(**args)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    result = {"error": f"unknown tool: {fname}"}

                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                })

            # Second call: model summarizes tool results
            if stream:
                r2 = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=full_messages,
                    temperature=0.3,
                    max_tokens=1500,
                    stream=True,
                )
                full_text = ""
                for chunk in r2:
                    delta = chunk.choices[0].delta.content or ""
                    full_text += delta
                    yield delta
                return full_text
            else:
                r2 = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=full_messages,
                    temperature=0.3,
                    max_tokens=1500,
                )
                text = r2.choices[0].message.content or ""
                yield text
                return text

        # No tool calls — just return the response
        if stream:
            r2 = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=full_messages,
                temperature=0.3,
                max_tokens=1500,
                stream=True,
            )
            full_text = ""
            for chunk in r2:
                delta = chunk.choices[0].delta.content or ""
                full_text += delta
                yield delta
            return full_text
        else:
            text = msg.content or ""
            yield text
            return text

    except Exception as e:
        print(f"[ai_enhanced] Groq failed: {e}")

    # Gemini fallback (no tool calling / streaming)
    try:
        import google.generativeai as genai
        api_key = gemini_key
        if api_key:
            genai.configure(api_key=api_key)
            m = genai.GenerativeModel("gemini-1.5-flash")
            prompt = system_msg["content"] + "\n\n"
            for msg in messages:
                prompt += f"{msg['role']}: {msg['content']}\n"
            r = m.generate_content(prompt)
            text = r.text or ""
            yield text
            return text
    except Exception as e:
        print(f"[ai_enhanced] Gemini failed: {e}")

    err = "❌ AI unavailable — check GROQ_API_KEY / GEMINI_API_KEY"
    yield err
    return err


# ═════════════════════════════════════════════════════════════════
# CHART GENERATION FROM NATURAL LANGUAGE
# ═════════════════════════════════════════════════════════════════
def generate_chart_from_prompt(prompt: str) -> Optional[Any]:
    """
    Ask AI what chart to make + data to fetch, then generate Plotly figure.
    Returns fig or None.
    """
    try:
        from openai import OpenAI
        import plotly.express as px
        import pandas as pd

        api_key = _get_key("GROQ_API_KEY")
        if not api_key:
            return None

        client = OpenAI(api_key=api_key,
                        base_url="https://api.groq.com/openai/v1")

        # Ask AI to output a strict JSON chart plan
        planner_sys = """You output ONLY strict JSON (no markdown fences).
Given a chart request, return:
{
  "chart_type": "line" | "bar" | "pie",
  "data_source": "signups_by_source" | "kpi_daily" | "top_paying" | "reject_reasons",
  "start": "YYYY-MM-DD",
  "end":   "YYYY-MM-DD",
  "title": "chart title"
}
Choose the best data_source. Use current period if not specified."""

        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": planner_sys},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        plan_raw = r.choices[0].message.content.strip()
        # Strip fences if present
        if plan_raw.startswith("```"):
            plan_raw = plan_raw.strip("`").split("\n", 1)[-1].rsplit("\n", 1)[0]
            if plan_raw.startswith("json"):
                plan_raw = plan_raw[4:].strip()
        plan = json.loads(plan_raw)

        # Fetch data
        src = plan.get("data_source", "signups_by_source")
        start = plan.get("start", (date.today() - timedelta(days=30)).isoformat())
        end   = plan.get("end", date.today().isoformat())

        if src == "signups_by_source":
            from attribution_tracker import signups_by_source
            data = signups_by_source(start, end)
            df = pd.DataFrame([{"source": k, "count": v} for k, v in data.items()])
            x, y = "source", "count"
        elif src == "kpi_daily":
            rows = find_all("daily_kpis",
                            filters={"date": {"$gte": start, "$lte": end}},
                            sort=[("date", 1)])
            df = pd.DataFrame(rows)
            x, y = "date", "signups_accepted"
        elif src == "top_paying":
            rows = find_all("payments",
                            filters={"final_status": "ACCEPTED",
                                     "first_payment_date": {"$gte": start, "$lte": end}},
                            sort=[("total_spend", -1)], limit=15)
            df = pd.DataFrame(rows)
            x, y = "email_normalized", "total_spend"
        elif src == "reject_reasons":
            data = tool_reject_reasons(start, end, "uploads")
            df = pd.DataFrame([{"reason": k, "count": v} for k, v in data.items()])
            x, y = "reason", "count"
        else:
            return None

        if df.empty:
            return None

        chart_type = plan.get("chart_type", "bar")
        title = plan.get("title", "Chart")

        if chart_type == "line":
            fig = px.line(df, x=x, y=y, title=title, markers=True,
                           color_discrete_sequence=["#9EFF2F"])
        elif chart_type == "pie":
            fig = px.pie(df, names=x, values=y, title=title,
                          color_discrete_sequence=px.colors.sequential.Greens)
        else:
            fig = px.bar(df, x=x, y=y, title=title,
                          color_discrete_sequence=["#9EFF2F"])

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#9CA3AF"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            height=380,
        )
        return fig
    except Exception as e:
        print(f"[chart_gen] failed: {e}")
        return None



# ═════════════════════════════════════════════════════════════════
# ADDITIONAL TOOLS: comparisons, cohorts, forecasts
# ═════════════════════════════════════════════════════════════════
def tool_compare_periods(period1_start: str, period1_end: str,
                          period2_start: str, period2_end: str) -> Dict[str, Any]:
    """Compare KPIs between two arbitrary periods (e.g. this month vs last month)."""
    p1 = tool_get_kpi_counts(period1_start, period1_end)
    p2 = tool_get_kpi_counts(period2_start, period2_end)
    def _pct(a, b):
        if b == 0: return None
        return round((a - b) / b * 100, 1)
    return {
        "period1": p1, "period2": p2,
        "changes": {
            "signups_pct":  _pct(p1["signups"],  p2["signups"]),
            "uploads_pct":  _pct(p1["uploads"],  p2["uploads"]),
            "payments_pct": _pct(p1["payments"], p2["payments"]),
        },
    }


def tool_cohort_analysis(cohort_month: str) -> Dict[str, Any]:
    """Track a signup cohort's behavior: how many uploaded, how many paid."""
    from datetime import date as _d, timedelta as _td
    y, m = cohort_month.split("-")
    start = f"{y}-{m}-01"
    if int(m) == 12:
        end = f"{int(y)+1}-01-01"
    else:
        end = f"{y}-{int(m)+1:02d}-01"

    signups = find_all("signups", filters={
        "final_status": "ACCEPTED",
        "signup_date": {"$gte": start, "$lt": end},
    }, projection={"email_normalized": 1})
    emails = {r.get("email_normalized") for r in signups}

    uploaded = count_docs("uploads", {
        "final_status": "ACCEPTED",
        "email_normalized": {"$in": list(emails)},
    })
    paid = count_docs("payments", {
        "final_status": "ACCEPTED",
        "email_normalized": {"$in": list(emails)},
    })

    return {
        "cohort_month":  cohort_month,
        "signups":       len(emails),
        "uploaded":      uploaded,
        "paid":          paid,
        "upload_rate":   round(uploaded / len(emails) * 100, 1) if emails else 0,
        "paid_rate":     round(paid / len(emails) * 100, 1) if emails else 0,
    }


def tool_forecast_signups(days_ahead: int = 30) -> Dict[str, Any]:
    """Simple linear forecast based on last 30-day trend."""
    from datetime import date as _d, timedelta as _td
    end = _d.today()
    start = end - _td(days=30)
    rows = find_all("daily_kpis", filters={
        "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }, sort=[("date", 1)])

    if len(rows) < 7:
        return {"error": "not enough data"}

    signups = [int(r.get("signups_accepted", 0) or 0) for r in rows]
    avg = sum(signups) / len(signups)
    # Simple: last 7 days trend
    recent = signups[-7:]
    trend = (recent[-1] - recent[0]) / len(recent) if len(recent) > 1 else 0
    forecast = avg * days_ahead + (trend * days_ahead * days_ahead / 2)
    return {
        "days_ahead":       days_ahead,
        "avg_daily_signups": round(avg, 1),
        "recent_trend":      round(trend, 2),
        "projected_signups": round(max(0, forecast)),
        "confidence":        "low (linear model — for indication only)",
    }


def tool_data_quality_check() -> Dict[str, Any]:
    """Health check: missing dates, high rejection rates, source diversity."""
    from datetime import date as _d, timedelta as _td
    from pipeline_gap_scanner import scan_gaps

    gap = scan_gaps()
    end = _d.today()
    week_ago = (end - _td(days=7)).isoformat()

    # Rejection rate this week
    signup_rej = count_docs("signups", {
        "final_status": "REJECTED",
        "signup_date":  {"$gte": week_ago, "$lte": end.isoformat()},
    })
    signup_acc = count_accepted("signups", "signup_date",
                                 date_gte=week_ago, date_lte=end.isoformat())
    rej_rate = signup_rej / (signup_rej + signup_acc) * 100 if (signup_rej + signup_acc) else 0

    return {
        "data_coverage_pct": gap.get("health_pct", 0),
        "missing_days":       gap.get("missing_count", 0),
        "zero_only_days":     gap.get("zero_count", 0),
        "week_signup_rejection_pct": round(rej_rate, 1),
        "verdict": ("healthy" if gap.get("health_pct", 0) >= 90 and rej_rate < 20
                     else "needs attention"),
    }


# Register new tools
TOOL_REGISTRY.update({
    "compare_periods":     tool_compare_periods,
    "cohort_analysis":     tool_cohort_analysis,
    "forecast_signups":    tool_forecast_signups,
    "data_quality_check":  tool_data_quality_check,
})

TOOL_SPECS.extend([
    {"type": "function", "function": {
        "name": "compare_periods",
        "description": "Compare KPI counts between any two date ranges (e.g. this month vs last month, this week vs last week)",
        "parameters": {"type": "object", "properties": {
            "period1_start": {"type": "string"}, "period1_end": {"type": "string"},
            "period2_start": {"type": "string"}, "period2_end": {"type": "string"},
        }, "required": ["period1_start", "period1_end", "period2_start", "period2_end"]},
    }},
    {"type": "function", "function": {
        "name": "cohort_analysis",
        "description": "Analyze a signup-month cohort: how many uploaded, how many paid",
        "parameters": {"type": "object", "properties": {
            "cohort_month": {"type": "string", "description": "YYYY-MM (e.g. 2026-06)"},
        }, "required": ["cohort_month"]},
    }},
    {"type": "function", "function": {
        "name": "forecast_signups",
        "description": "Simple linear forecast of signups for the next N days based on recent trend",
        "parameters": {"type": "object", "properties": {
            "days_ahead": {"type": "integer", "default": 30},
        }},
    }},
    {"type": "function", "function": {
        "name": "data_quality_check",
        "description": "Assess overall data pipeline health + rejection rates",
        "parameters": {"type": "object", "properties": {}},
    }},
])
