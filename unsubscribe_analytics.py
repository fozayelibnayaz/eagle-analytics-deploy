#!/usr/bin/env python3
"""

Unsubscribe & Churn Analytics
Addresses the business problem: "Too many people are unsubscribing right now"

Provides:
1. Unsubscribe rate tracking (daily/weekly/monthly)
2. Plan downgrade detection
3. Churn reason capture (from Stripe metadata + custom field)
4. Cohort retention analysis
5. AI insights on WHY people leave
6. Alert when unsubscribe rate spikes
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter, defaultdict


import os
import re
import json
from datetime import datetime, timedelta, date

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





def _get_db():
    # Alias below for legacy code
    pass

def _get_sb():
    return get_db()


def _get_stripe_key():
    val = os.environ.get("STRIPE_SECRET_KEY", "")
    if not val:
        try:
            import streamlit as st
            val = str(st.secrets.get("STRIPE_SECRET_KEY", "")).strip()
        except Exception:
            pass
    return val


def fetch_canceled_subscriptions(days=90):
    """Fetch canceled subscriptions from Stripe API."""
    stripe_key = _get_stripe_key()
    if not stripe_key:
        return {"error": "STRIPE_SECRET_KEY not set", "subscriptions": []}

    try:
        import stripe
        stripe.api_key = stripe_key
    except ImportError:
        return {"error": "stripe library not installed", "subscriptions": []}

    cutoff_ts = int((datetime.now() - timedelta(days=days)).timestamp())
    canceled = []
    starting_after = None

    while True:
        try:
            params = {"status": "canceled", "limit": 100, "created": {"gte": cutoff_ts}}
            if starting_after:
                params["starting_after"] = starting_after
            resp = stripe.Subscription.list(**params)
            for s in resp.data:
                canceled.append({
                    "id":              s.id,
                    "customer_id":     s.customer,
                    "created":         datetime.fromtimestamp(s.created).strftime("%Y-%m-%d"),
                    "canceled_at":     datetime.fromtimestamp(s.canceled_at).strftime("%Y-%m-%d") if s.canceled_at else None,
                    "ended_at":        datetime.fromtimestamp(s.ended_at).strftime("%Y-%m-%d") if s.ended_at else None,
                    "cancel_reason":   s.cancellation_details.reason if s.cancellation_details else None,
                    "cancel_feedback": s.cancellation_details.feedback if s.cancellation_details else None,
                    "comment":         s.cancellation_details.comment if s.cancellation_details else None,
                    "plan_id":         s.items.data[0].price.id if s.items.data else None,
                    "amount":          (s.items.data[0].price.unit_amount / 100) if (s.items.data and s.items.data[0].price.unit_amount) else 0,
                    "metadata":        dict(s.metadata) if s.metadata else {},
                })
            if not resp.has_more:
                break
            starting_after = resp.data[-1].id if resp.data else None
            if not starting_after:
                break
        except Exception as e:
            return {"error": f"Stripe API error: {e}", "subscriptions": canceled}

    return {"subscriptions": canceled, "total": len(canceled)}


def fetch_active_subscriptions():
    """Get current active subscriptions count."""
    stripe_key = _get_stripe_key()
    if not stripe_key:
        return {"error": "STRIPE_SECRET_KEY not set", "count": 0}
    try:
        import stripe
        stripe.api_key = stripe_key
        active = stripe.Subscription.list(status="active", limit=1)
        # Use subscription list count
        all_active = []
        starting_after = None
        while True:
            params = {"status": "active", "limit": 100}
            if starting_after:
                params["starting_after"] = starting_after
            resp = stripe.Subscription.list(**params)
            all_active.extend(resp.data)
            if not resp.has_more:
                break
            starting_after = resp.data[-1].id
        return {"count": len(all_active), "subscriptions": all_active}
    except Exception as e:
        return {"error": str(e), "count": 0}


def compute_churn_metrics(days=90):
    """Comprehensive churn analysis."""
    canceled_data = fetch_canceled_subscriptions(days=days)
    if canceled_data.get("error"):
        return canceled_data

    active = fetch_active_subscriptions()
    canceled = canceled_data["subscriptions"]
    active_count = active.get("count", 0)

    # Compute monthly churn rate
    today = date.today()
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    canceled_this = [c for c in canceled if c.get("canceled_at", "").startswith(this_month)]
    canceled_last = [c for c in canceled if c.get("canceled_at", "").startswith(last_month)]

    # Reasons breakdown
    reasons = Counter()
    feedback = Counter()
    comments = []
    for c in canceled:
        if c.get("cancel_reason"):
            reasons[c["cancel_reason"]] += 1
        if c.get("cancel_feedback"):
            feedback[c["cancel_feedback"]] += 1
        if c.get("comment"):
            comments.append({
                "date":     c["canceled_at"],
                "feedback": c["cancel_feedback"],
                "comment":  c["comment"],
                "amount":   c["amount"],
            })

    # Subscription lifetime
    lifetimes = []
    for c in canceled:
        try:
            start = datetime.fromisoformat(c["created"])
            end = datetime.fromisoformat(c["canceled_at"])
            lifetimes.append((end - start).days)
        except Exception:
            pass
    avg_lifetime = sum(lifetimes) / len(lifetimes) if lifetimes else 0

    # Daily cancel timeline (last 30 days)
    daily_cancels = defaultdict(int)
    for c in canceled[-200:]:
        if c.get("canceled_at"):
            daily_cancels[c["canceled_at"]] += 1
    daily_timeline = sorted([{"date": d, "canceled": n} for d, n in daily_cancels.items()])

    # Churn rate calculation
    base = active_count + len(canceled_last)
    monthly_churn_rate = (len(canceled_this) / base * 100) if base > 0 else 0

    # Lost revenue
    lost_mrr_this = sum(c["amount"] for c in canceled_this)
    lost_mrr_last = sum(c["amount"] for c in canceled_last)

    # ALERT trigger
    alert = None
    if len(canceled_this) > len(canceled_last) * 1.5 and len(canceled_last) > 0:
        alert = f"⚠️ SPIKE: Cancellations up {((len(canceled_this) - len(canceled_last)) / len(canceled_last) * 100):.0f}% this month ({len(canceled_this)} vs {len(canceled_last)} last month)"
    elif monthly_churn_rate > 10:
        alert = f"⚠️ HIGH CHURN: {monthly_churn_rate:.1f}% monthly churn rate"

    return {
        "active_subscriptions":   active_count,
        "canceled_total":         len(canceled),
        "canceled_this_month":    len(canceled_this),
        "canceled_last_month":    len(canceled_last),
        "monthly_churn_rate":     round(monthly_churn_rate, 2),
        "avg_subscription_days":  round(avg_lifetime, 0),
        "lost_mrr_this_month":    round(lost_mrr_this, 2),
        "lost_mrr_last_month":    round(lost_mrr_last, 2),
        "lost_mrr_delta":         round(lost_mrr_this - lost_mrr_last, 2),
        "cancel_reasons":         dict(reasons.most_common(10)),
        "cancel_feedback":        dict(feedback.most_common(10)),
        "comments":               comments[:20],
        "daily_timeline":         daily_timeline,
        "alert":                  alert,
    }


def get_ai_churn_insight(metrics):
    """Use AI to analyze churn patterns and suggest action."""
    import urllib.request
    import urllib.error
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        try:
            import streamlit as st
            groq_key = str(st.secrets.get("GROQ_API_KEY", "")).strip()
        except Exception:
            pass
    if not groq_key:
        return "AI not configured"

    summary = {
        "active":          metrics.get("active_subscriptions", 0),
        "canceled_this":   metrics.get("canceled_this_month", 0),
        "canceled_last":   metrics.get("canceled_last_month", 0),
        "churn_rate":      metrics.get("monthly_churn_rate", 0),
        "avg_lifetime":    metrics.get("avg_subscription_days", 0),
        "lost_mrr":        metrics.get("lost_mrr_this_month", 0),
        "top_reasons":     metrics.get("cancel_reasons", {}),
        "top_feedback":    metrics.get("cancel_feedback", {}),
        "comments":        metrics.get("comments", [])[:10],
    }

    prompt = f"""You are a SaaS churn expert. Analyze Eagle3D Streaming's subscription cancellation data.

DATA:
{json.dumps(summary, indent=2, default=str)}

Provide insights in these sections (use exact headers):

CHURN DIAGNOSIS
[Is churn high/normal/low? What does the rate mean for a B2B SaaS?]

ROOT CAUSE
[Based on cancel reasons + feedback + comments, what is killing retention?]

REVENUE IMPACT
[Lost MRR analysis + projected annual loss if pace continues]

URGENT ACTIONS
[3 specific things to do THIS WEEK to reduce churn]

LONG TERM FIXES
[3 strategic changes to lower churn permanently]

CUSTOMER VOICE
[What are users actually saying? Quote a comment + explain]

Be specific, actionable, brutal honesty."""

    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You are a brutal, honest SaaS churn expert."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens":  1500,
                "temperature": 0.3,
            }).encode(),
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type":  "application/json",
                "User-Agent":    "Mozilla/5.0",
                "Accept":        "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"AI HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return f"AI error: {e}"


def save_to_db(metrics):
    """Save churn snapshot to MongoDB."""
    sb = _get_db()
    if sb is None:
        return False
    try:
        upsert_one("analytics_cache", {"source": "churn_metrics"}, {
            "source": "churn_metrics",
            "metric_date":  date.today().strftime("%Y-%m-%d"),
            "period_type":  "monthly",
            "data":         metrics,
            "fetched_at":   datetime.utcnow().isoformat(),
            "is_valid":     True,
        })
        return True
    except Exception as e:
        print(f"Save error: {e}")
        return False


if __name__ == "__main__":
    print("Computing churn metrics...")
    m = compute_churn_metrics(days=90)
    if m.get("error"):
        print(f"ERROR: {m['error']}")
    else:
        print(json.dumps(m, indent=2, default=str)[:3000])
        if m.get("alert"):
            print(f"\n{m['alert']}")

# Backward-compat: DB is MongoDB now, function name kept for UI compat
save_to_supabase = save_to_db  # backward-compat alias



# Backward-compat alias
_get_db = _get_sb
