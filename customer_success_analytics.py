#!/usr/bin/env python3
"""

Customer Success Analytics - COMPLETE
Covers ALL 85 fields from the CS sheet.
"""
import streamlit as st
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





def _get_sb():
    return get_db()


def _parse_date(v):
    if not v:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "null", "-"):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m/%d/%y",
                "%d/%m/%Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S", "%B %d, %Y"):
        try:
            return datetime.strptime(s.split(".")[0].split("+")[0], fmt).date()
        except Exception:
            pass
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    return None


def _parse_int(v):
    if v is None or v == "":
        return 0
    try:
        s = str(v).replace(",", "").replace("$", "").strip()
        return int(float(s)) if s and s.lower() not in ("none", "nan", "null") else 0
    except Exception:
        return 0


def _parse_float(v):
    if v is None or v == "":
        return 0.0
    try:
        s = str(v).replace(",", "").replace("$", "").strip()
        return float(s) if s and s.lower() not in ("none", "nan", "null") else 0.0
    except Exception:
        return 0.0


def get_tab_data(tab_slug):
    sb = _get_sb()
    if sb is None:
        return []
    try:
        rows = sb.table("customer_success_master").select("row_data").eq("tab_slug", tab_slug).execute().data or []
        return [r.get("row_data", {}) for r in rows]
    except Exception:
        return []


def get_unified_customers():
    sb = _get_sb()
    if sb is None:
        return []
    try:
        rows = sb.table("customer_success_master").select("row_data,tab_name,email").execute().data or []
    except Exception:
        return []
    by_email = defaultdict(dict)
    for r in rows:
        rd = r.get("row_data", {}) or {}
        email = (rd.get("Email") or rd.get("E-mail") or r.get("email", "")).strip().lower()
        if not email or "@" not in email:
            continue
        for k, v in rd.items():
            if v not in (None, "", "—") and str(v).strip():
                by_email[email][k] = v
        by_email[email]["_source_tabs"] = by_email[email].get("_source_tabs", "") + r.get("tab_name", "") + ";"
    return list(by_email.values())


# ════════════════════════════════════════════════
# 1. CHURN
# ════════════════════════════════════════════════
def churn_by_month():
    churned = get_tab_data("churned_user")
    by_month = Counter()
    customers = []
    total_revenue_lost = 0
    for r in churned:
        d = _parse_date(r.get("Date"))
        if d:
            by_month[d.strftime("%Y-%m")] += 1
        rev = _parse_float(r.get("Total (Rev/Mon)", r.get("Revenue", 0)))
        total_revenue_lost += rev
        customers.append({
            "date":     str(d) if d else str(r.get("Date","")),
            "customer": r.get("Customer", ""),
            "revenue":  rev,
            "note":     r.get("Note", ""),
        })
    return {
        "by_month":               dict(sorted(by_month.items())),
        "total_churned":          len(churned),
        "monthly_revenue_lost":   round(total_revenue_lost, 2),
        "annual_revenue_lost":    round(total_revenue_lost * 12, 2),
        "customers":              sorted(customers, key=lambda x: str(x.get("date","")), reverse=True),
    }


# ════════════════════════════════════════════════
# 2. HEALTH INDEX
# ════════════════════════════════════════════════
def health_index_analysis():
    rows = get_tab_data("customer_health_index") or get_tab_data("sheet53")
    plans, statuses, sizes, fits = Counter(), Counter(), Counter(), Counter()
    recurring = []
    no_recurring = 0
    for r in rows:
        plans[str(r.get("Plan","Unknown")).strip() or "Unknown"] += 1
        statuses[str(r.get("Status","Unknown")).strip() or "Unknown"] += 1
        sizes[str(r.get("Company Size","Unknown")).strip() or "Unknown"] += 1
        fits[str(r.get("Perfect Fit customer","Unknown")).strip() or "Unknown"] += 1
        rc = _parse_int(r.get("Recurring Payment Count", 0))
        if rc > 0:
            recurring.append(rc)
        else:
            no_recurring += 1
    avg = sum(recurring) / len(recurring) if recurring else 0
    return {
        "total_customers":         len(rows),
        "plans":                   dict(plans.most_common()),
        "statuses":                dict(statuses.most_common()),
        "company_sizes":           dict(sizes.most_common()),
        "perfect_fit":             dict(fits.most_common()),
        "avg_recurring":           round(avg, 1),
        "max_recurring":           max(recurring) if recurring else 0,
        "no_recurring_count":      no_recurring,
        "recurring_distribution":  recurring,
    }


# ════════════════════════════════════════════════
# 3. STREAMING TIME (all bi-weekly periods)
# ════════════════════════════════════════════════
def streaming_time_breakdown():
    rows = get_tab_data("customer_health_index") or get_tab_data("sheet53")
    period_totals = defaultdict(float)
    per_customer = []
    for r in rows:
        email = (r.get("Email") or "").strip().lower()
        total = 0
        for k, v in r.items():
            if "stream time" in str(k).lower() or "tst" in str(k).lower():
                val = _parse_float(v)
                period_totals[k] += val
                total += val
        if total > 0 and email:
            per_customer.append({
                "email":         email,
                "name":          f"{r.get('First Name','')} {r.get('Last Name','')}".strip() or r.get('User Name',''),
                "total_stream":  round(total, 1),
                "plan":          r.get("Plan",""),
                "status":        r.get("Status",""),
                "company_size":  r.get("Company Size",""),
                "perfect_fit":   r.get("Perfect Fit customer",""),
                "recurring":     _parse_int(r.get("Recurring Payment Count", 0)),
            })
    per_customer.sort(key=lambda x: -x["total_stream"])
    return {
        "period_totals":       {k: round(v,1) for k,v in sorted(period_totals.items())},
        "total_stream_hours":  round(sum(period_totals.values()), 1),
        "top_50_streamers":    per_customer[:50],
        "bottom_streamers":    per_customer[-30:] if len(per_customer) > 30 else [],
        "active_streamers":    len(per_customer),
        "non_streamers":       len(rows) - len(per_customer),
    }


# ════════════════════════════════════════════════
# 4. SESSIONS (Sheet40 + Sheet54)
# ════════════════════════════════════════════════
def session_analysis():
    rows = get_tab_data("sheet40") + get_tab_data("sheet54")
    seen_clients = set()
    per_client = []
    totals = {"sessions":0,"video_min":0,"channel_min":0,
              "connected_success":0,"connected_failure":0,
              "streamed_success":0,"streamed_failure":0}
    for r in rows:
        client = r.get("Client Name") or r.get("User Name") or ""
        if not client or client in seen_clients:
            continue
        seen_clients.add(client)
        s = _parse_int(r.get("Number of Sessions",0))
        vm = _parse_float(r.get("Video Streaming Time in min(s)",0))
        cm = _parse_float(r.get("Channel Streaming Time in min(s)",0))
        cs = _parse_int(r.get("Connected Success",0))
        cf = _parse_int(r.get("Connected Failure",0))
        ss = _parse_int(r.get("Streamed Success",0))
        sf = _parse_int(r.get("Streamed Failure",0))
        totals["sessions"] += s; totals["video_min"] += vm; totals["channel_min"] += cm
        totals["connected_success"] += cs; totals["connected_failure"] += cf
        totals["streamed_success"] += ss; totals["streamed_failure"] += sf
        if s > 0 or vm > 0:
            per_client.append({
                "client":            client,
                "sessions":          s,
                "video_min":         vm,
                "channel_min":       cm,
                "connected_success": cs,
                "connected_failure": cf,
                "streamed_success":  ss,
                "streamed_failure":  sf,
                "success_rate":      round(ss/(ss+sf)*100,1) if (ss+sf) else 0,
            })
    per_client.sort(key=lambda x: -x["sessions"])
    conn = totals["connected_success"]+totals["connected_failure"]
    stream = totals["streamed_success"]+totals["streamed_failure"]
    return {
        **totals,
        "total_clients":           len(per_client),
        "total_video_hours":       round(totals["video_min"]/60,1),
        "connected_success_rate":  round(totals["connected_success"]/conn*100,2) if conn else 0,
        "streamed_success_rate":   round(totals["streamed_success"]/stream*100,2) if stream else 0,
        "top_30_clients":          per_client[:30],
        "high_failure_clients":    sorted([c for c in per_client if c["success_rate"]<80 and c["sessions"]>5],
                                          key=lambda x: x["success_rate"])[:20],
    }


# ════════════════════════════════════════════════
# 5. SHEET1 - LAST STREAMED + CHI
# ════════════════════════════════════════════════
def sheet1_analysis():
    rows = get_tab_data("sheet1")
    customers, color_dist, chi_dist, plan_dist = [], Counter(), Counter(), Counter()
    today = date.today()
    for r in rows:
        email = (r.get("Email") or "").strip().lower()
        if not email: continue
        ls = _parse_date(r.get("Last Streamed"))
        days = (today - ls).days if ls else None
        chi = str(r.get("CHI","")).strip()
        color = str(r.get("Color","")).strip()
        plan = str(r.get("Plan","")).strip() or "Unknown"
        chi_dist[chi] += 1
        color_dist[color] += 1
        plan_dist[plan] += 1
        customers.append({
            "email":         email,
            "name":          r.get("User Name",""),
            "plan":          plan,
            "status":        r.get("Status",""),
            "last_streamed": str(ls) if ls else str(r.get("Last Streamed","")),
            "days_since":    days,
            "tst_april":     _parse_float(r.get("Total Streaming Time (April)",0)),
            "tst_march":     _parse_float(r.get("TST : March",0)),
            "tst_feb":       _parse_float(r.get("TST : February",0)),
            "tst_jan":       _parse_float(r.get("TST: January",0)),
            "tst_2025":      _parse_float(r.get("TST (2025)",0)),
            "total_sessions": _parse_int(r.get("Total Session",0)),
            "last_month_sessions": _parse_int(r.get("Last Month Sessions",0)),
            "chi": chi, "color": color,
        })
    customers.sort(key=lambda x: -x.get("tst_2025",0))
    danger = [c for c in customers if c["days_since"] and c["days_since"]>30 and c.get("tst_2025",0)>0]
    return {
        "total_customers":     len(customers),
        "color_dist":          dict(color_dist.most_common()),
        "chi_dist":            dict(chi_dist.most_common()),
        "plan_dist":           dict(plan_dist.most_common()),
        "top_2025_streamers":  customers[:30],
        "dormant_paying":      sorted(danger, key=lambda x: -x.get("tst_2025",0))[:30],
        "never_streamed":      [c for c in customers if not c["days_since"]][:30],
    }


# ════════════════════════════════════════════════
# 6. SUBSCRIPTIONS
# ════════════════════════════════════════════════
def subscription_lifecycle():
    rows = get_tab_data("customer_health_index") or get_tab_data("sheet53")
    today = date.today()
    month_start = today.replace(day=1)
    new_, ending, expired, long_term = [], [], [], []
    for r in rows:
        email = (r.get("Email") or "").strip().lower()
        if not email: continue
        start = _parse_date(r.get("Subscription Create Date"))
        cur_end = _parse_date(r.get("Current Period End Date"))
        recurring = _parse_int(r.get("Recurring Payment Count",0))
        rec = {
            "email": email,
            "name": f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
            "plan": r.get("Plan",""), "status": r.get("Status",""),
            "subscription_start": str(start) if start else "",
            "current_end": str(cur_end) if cur_end else "",
            "recurring": recurring,
            "company_size": r.get("Company Size",""),
            "perfect_fit": r.get("Perfect Fit customer",""),
        }
        if start and start >= month_start:
            new_.append(rec)
        if cur_end:
            d_left = (cur_end - today).days
            if 0 <= d_left <= 30:
                ending.append({**rec, "days_left": d_left})
            elif d_left < 0:
                expired.append({**rec, "days_ago": abs(d_left)})
        if recurring >= 12:
            long_term.append(rec)
    return {
        "new_this_month": new_,
        "ending_in_30d": sorted(ending, key=lambda x: x["days_left"]),
        "expired": sorted(expired, key=lambda x: x["days_ago"])[:50],
        "long_term_customers": sorted(long_term, key=lambda x: -x["recurring"]),
        "count_new": len(new_), "count_ending": len(ending),
        "count_expired": len(expired), "count_long_term": len(long_term),
    }


# ════════════════════════════════════════════════
# 7. REVENUE
# ════════════════════════════════════════════════
def revenue_analysis():
    net_loss = get_tab_data("net_loss_due_to_conversion")
    losses = []
    tot_prev = tot_curr = tot_dev = 0
    for r in net_loss:
        prev = _parse_float(r.get("previous spent",0))
        curr = _parse_float(r.get("current",0))
        dev = _parse_float(r.get("Deviation in USD", curr - prev))
        tot_prev += prev; tot_curr += curr; tot_dev += dev
        losses.append({"email": r.get("E-mail",""), "previous": prev, "current": curr, "deviation": dev})
    return {
        "conversion_losses": sorted(losses, key=lambda x: x["deviation"]),
        "total_previous": round(tot_prev,2),
        "total_current":  round(tot_curr,2),
        "total_deviation": round(tot_dev,2),
        "loss_customers": len([l for l in losses if l["deviation"]<0]),
        "gain_customers": len([l for l in losses if l["deviation"]>0]),
    }


def stream_time_trend():
    rows = get_tab_data("stream_time_graph")
    return [{"period": r.get("Period",""), "stream_time": _parse_float(r.get("Stream Time",0))} for r in rows]


# ════════════════════════════════════════════════
# 8. NO SUB USERS
# ════════════════════════════════════════════════
def no_sub_users_analysis():
    rows = get_tab_data("no_sub_users")
    plans, sizes, fits = Counter(), Counter(), Counter()
    users = []
    for r in rows:
        plans[str(r.get("Plan","Unknown")).strip() or "Unknown"] += 1
        sizes[str(r.get("Company Size","Unknown")).strip() or "Unknown"] += 1
        fits[str(r.get("Perfect Fit customer","Unknown")).strip() or "Unknown"] += 1
        users.append({
            "email": (r.get("Email") or "").strip().lower(),
            "name": f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
            "plan": r.get("Plan",""),
            "company_size": r.get("Company Size",""),
            "perfect_fit": r.get("Perfect Fit customer",""),
        })
    return {
        "total": len(rows),
        "by_plan": dict(plans.most_common()),
        "by_size": dict(sizes.most_common()),
        "by_fit":  dict(fits.most_common()),
        "users": users[:50],
    }


# ════════════════════════════════════════════════
# 9. CORRELATIONS
# ════════════════════════════════════════════════
def cross_correlations():
    rows_health = get_tab_data("customer_health_index") or get_tab_data("sheet53")
    rows_churn = get_tab_data("churned_user")
    churned_customers = set()
    for r in rows_churn:
        c = str(r.get("Customer","")).lower().strip()
        if c: churned_customers.add(c)
    size_t, size_c = Counter(), Counter()
    plan_t, plan_c = Counter(), Counter()
    fit_t, fit_c = Counter(), Counter()
    for r in rows_health:
        size = str(r.get("Company Size","Unknown")).strip() or "Unknown"
        plan = str(r.get("Plan","Unknown")).strip() or "Unknown"
        fit  = str(r.get("Perfect Fit customer","Unknown")).strip() or "Unknown"
        email = (r.get("Email") or "").strip().lower()
        status = str(r.get("Status","")).lower()
        size_t[size] += 1; plan_t[plan] += 1; fit_t[fit] += 1
        if "cancel" in status or "ended" in status or email in churned_customers:
            size_c[size] += 1; plan_c[plan] += 1; fit_c[fit] += 1
    def _rate(t, c):
        return {k: round(c.get(k,0)/v*100,1) for k,v in t.items() if v>0}
    return {
        "company_size_churn_rate": _rate(size_t, size_c),
        "plan_churn_rate":         _rate(plan_t, plan_c),
        "perfect_fit_churn_rate":  _rate(fit_t, fit_c),
        "size_totals": dict(size_t), "plan_totals": dict(plan_t), "fit_totals": dict(fit_t),
    }


# ════════════════════════════════════════════════
# 10. CONTACT INFO COMPLETENESS (NEW)
# ════════════════════════════════════════════════
def contact_completeness():
    customers = get_unified_customers()
    fields = ["Corporate Phone Number", "Other Phone", "Phone Numer", "LinkedIn", "Website", "Location", "Time zone"]
    counts = {f: 0 for f in fields}
    missing_all = 0
    fully_complete = 0
    for c in customers:
        present = sum(1 for f in fields if c.get(f) and str(c[f]).strip() not in ("", "-", "N/A"))
        if present == 0:
            missing_all += 1
        if present == len(fields):
            fully_complete += 1
        for f in fields:
            if c.get(f) and str(c[f]).strip() not in ("", "-", "N/A"):
                counts[f] += 1
    return {
        "total_customers":    len(customers),
        "field_completeness": counts,
        "missing_all_contact": missing_all,
        "fully_complete":     fully_complete,
        "completeness_pct":   {f: round(counts[f]/len(customers)*100, 1) if customers else 0 for f in fields},
    }


# ════════════════════════════════════════════════
# 11. PHONE CALL CAMPAIGN TRACKING (NEW)
# ════════════════════════════════════════════════
def phone_call_analytics():
    customers = get_unified_customers()
    call_statuses = Counter()
    person_calling = Counter()
    customers_with_calls = 0
    total_calls = 0
    no_answer = 0
    answered = 0
    callbacks = []
    for c in customers:
        any_call = False
        for n in range(1, 6):
            status = c.get(f"Phone Call 0{n} - Status") or c.get(f"Phone Call {n} - Status")
            if status:
                any_call = True
                total_calls += 1
                s = str(status).lower().strip()
                call_statuses[str(status).strip()] += 1
                if "answer" in s and "no" not in s:
                    answered += 1
                elif "no answer" in s or "voicemail" in s:
                    no_answer += 1
            person = c.get("Person Calling")
            if person:
                person_calling[str(person).strip()] += 1
        if any_call:
            customers_with_calls += 1
    return {
        "total_customers":       len(customers),
        "customers_called":      customers_with_calls,
        "total_calls_made":      total_calls,
        "call_statuses":         dict(call_statuses.most_common()),
        "person_calling":        dict(person_calling.most_common()),
        "answered_calls":        answered,
        "no_answer_calls":       no_answer,
        "answer_rate":           round(answered/total_calls*100,1) if total_calls else 0,
    }


# ════════════════════════════════════════════════
# 12. GEOGRAPHIC ANALYSIS (NEW)
# ════════════════════════════════════════════════
def geographic_analysis():
    customers = get_unified_customers()
    locations = Counter()
    timezones = Counter()
    for c in customers:
        loc = str(c.get("Location","")).strip()
        tz = str(c.get("Time zone","")).strip()
        if loc and loc != "-": locations[loc] += 1
        if tz and tz != "-":   timezones[tz] += 1
    return {
        "top_locations": dict(locations.most_common(30)),
        "top_timezones": dict(timezones.most_common(20)),
        "unique_locations": len(locations),
        "unique_timezones": len(timezones),
    }


# ════════════════════════════════════════════════
# 13. PARENT ACCOUNT ANALYSIS (NEW)
# ════════════════════════════════════════════════
def parent_account_analysis():
    customers = get_unified_customers()
    parents = Counter()
    with_parent = 0
    for c in customers:
        p = str(c.get("Parent Account","")).strip()
        if p and p != "-":
            parents[p] += 1
            with_parent += 1
    return {
        "customers_with_parent": with_parent,
        "unique_parent_accounts": len(parents),
        "top_parent_accounts":   dict(parents.most_common(30)),
    }


# ════════════════════════════════════════════════
# 14. RECENT STREAMING ACTIVITY (NEW)
# ════════════════════════════════════════════════
def recent_activity_analysis():
    """Last 3 bi-weekly periods vs prior period - growth or decline."""
    rows = get_tab_data("customer_health_index") or get_tab_data("sheet53")
    # Most recent periods
    recent_keys = ["Total Stream Time June 01 - June 15, 2026",
                   "Total Stream Time May 15 - May 31, 2026",
                   "Total Stream Time May 01 - May 15, 2026"]
    prior_keys  = ["Total Stream Time Apr 16 - Apr 30, 2026",
                   "Total Stream Time Apr 01 - Apr 15, 2026",
                   "Total Stream Time Mar 16 - Mar 31, 2026"]
    growing, declining, steady = [], [], []
    for r in rows:
        email = (r.get("Email") or "").strip().lower()
        if not email: continue
        recent = sum(_parse_float(r.get(k,0)) for k in recent_keys)
        prior  = sum(_parse_float(r.get(k,0)) for k in prior_keys)
        if recent == 0 and prior == 0: continue
        delta = recent - prior
        pct = ((recent - prior) / prior * 100) if prior > 0 else None
        rec = {
            "email": email,
            "name":  f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
            "recent_hours": round(recent, 1),
            "prior_hours":  round(prior, 1),
            "delta": round(delta, 1),
            "growth_pct": round(pct, 1) if pct is not None else None,
            "plan": r.get("Plan",""),
            "status": r.get("Status",""),
        }
        if pct is not None:
            if pct > 20: growing.append(rec)
            elif pct < -20: declining.append(rec)
            else: steady.append(rec)
        elif recent > 0: growing.append(rec)
    growing.sort(key=lambda x: -(x.get("growth_pct") or 0))
    declining.sort(key=lambda x: (x.get("growth_pct") or 0))
    return {
        "growing":    growing[:30],
        "declining":  declining[:30],
        "steady":     steady[:30],
        "count_growing":   len(growing),
        "count_declining": len(declining),
        "count_steady":    len(steady),
    }


# ════════════════════════════════════════════════
# 15. CUSTOMER VALUE TIERS (NEW)
# ════════════════════════════════════════════════
def customer_value_tiers():
    customers = get_unified_customers()
    tiers = {"vip": [], "high": [], "mid": [], "low": []}
    for c in customers:
        recurring = _parse_int(c.get("Recurring Payment Count",0))
        if recurring >= 18:
            tiers["vip"].append({"email": c.get("Email", c.get("E-mail","")),
                                 "name": f"{c.get('First Name','')} {c.get('Last Name','')}".strip(),
                                 "recurring": recurring, "plan": c.get("Plan","")})
        elif recurring >= 12:
            tiers["high"].append({"email": c.get("Email", c.get("E-mail","")),
                                  "recurring": recurring, "plan": c.get("Plan","")})
        elif recurring >= 6:
            tiers["mid"].append({"email": c.get("Email", c.get("E-mail","")),
                                 "recurring": recurring, "plan": c.get("Plan","")})
        elif recurring >= 1:
            tiers["low"].append({"email": c.get("Email", c.get("E-mail","")),
                                 "recurring": recurring, "plan": c.get("Plan","")})
    return {
        "vip_count": len(tiers["vip"]),
        "high_count": len(tiers["high"]),
        "mid_count": len(tiers["mid"]),
        "low_count": len(tiers["low"]),
        "vip_customers": sorted(tiers["vip"], key=lambda x: -x["recurring"])[:50],
        "high_customers": tiers["high"][:50],
        "mid_customers": tiers["mid"][:30],
        "low_customers": tiers["low"][:30],
    }


def get_all_insights():
    return {
        "churn":              churn_by_month(),
        "health":             health_index_analysis(),
        "streaming":          streaming_time_breakdown(),
        "sessions":           session_analysis(),
        "sheet1":             sheet1_analysis(),
        "subscriptions":      subscription_lifecycle(),
        "revenue":            revenue_analysis(),
        "stream_trend":       stream_time_trend(),
        "no_sub":             no_sub_users_analysis(),
        "correlations":       cross_correlations(),
        "contact":            contact_completeness(),
        "phone_calls":        phone_call_analytics(),
        "geography":          geographic_analysis(),
        "parent_accounts":    parent_account_analysis(),
        "recent_activity":    recent_activity_analysis(),
        "value_tiers":        customer_value_tiers(),
        "generated_at":       datetime.utcnow().isoformat(),
    }
