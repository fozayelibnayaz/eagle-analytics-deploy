#!/usr/bin/env python3
"""

KPI Pattern Analyzer
Analyzes signups, first uploads, and paid customers by:
- Region (from email domain TLD + LinkedIn country + GA4 geo)
- Time patterns (day of week, month of year, hour)
- Seasonal trends
- Year-over-year comparison
- Growth velocity
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

# Legacy compatibility: old code calls _get_supabase(), backend is MongoDB only.
def _get_supabase():
    return get_db()


def extract_country_from_email(email):
    """Extract likely country from email address."""
    if not email or "@" not in email:
        return "Unknown"
    domain = email.split("@")[-1].lower().strip()
    # Check exact domain match
    if domain in DOMAIN_COUNTRY:
        return DOMAIN_COUNTRY[domain]
    # Check TLD
    tld = domain.split(".")[-1] if "." in domain else ""
    if tld in TLD_COUNTRY:
        return TLD_COUNTRY[tld]
    # Check second-level TLD (co.uk, com.br, etc)
    parts = domain.split(".")
    if len(parts) >= 3:
        sld = parts[-2] + "." + parts[-1]
        if sld == "co.uk":
            return "United Kingdom"
        if sld == "com.br":
            return "Brazil"
        if sld == "com.au":
            return "Australia"
        if sld == "com.tr":
            return "Turkey"
        if sld == "co.jp":
            return "Japan"
        if sld == "co.in":
            return "India"
        if sld == "com.mx":
            return "Mexico"
        if parts[-2] in TLD_COUNTRY:
            return TLD_COUNTRY[parts[-2]]
    if tld == "com" or tld == "org" or tld == "net":
        return "Global / Generic"
    return "Other"


def analyze_signups_by_region(metric_type="signups"):
    """Analyze accepted records by region from email domain."""
    sb = _get_supabase()
    if sb is None:
        return {"error": "MongoDB not configured", "by_country": {}}

    table_map = {
        "signups":  ("signups",  "signup_date",        "email"),
        "uploads":  ("uploads",  "upload_date",        "email"),
        "paid":     ("payments", "first_payment_date", "email"),
    }
    if metric_type not in table_map:
        return {"error": f"Unknown metric: {metric_type}"}

    tbl, date_col, email_col = table_map[metric_type]

    try:
        resp = sb.table(tbl).select(f"{email_col},{date_col}").eq("final_status", "ACCEPTED").limit(10000).execute()
        rows = resp.data or []
    except Exception as e:
        return {"error": str(e), "by_country": {}}

    by_country = Counter()
    by_country_date = defaultdict(lambda: defaultdict(int))

    for r in rows:
        email = r.get(email_col, "")
        if not email:
            continue
        country = extract_country_from_email(email)
        by_country[country] += 1

        date_val = r.get(date_col, "")
        if date_val:
            year_month = str(date_val)[:7]
            by_country_date[country][year_month] += 1

    # Sort by count
    top_countries = by_country.most_common(20)
    total = sum(by_country.values())

    result = {
        "metric":      metric_type,
        "total":       total,
        "unique_countries": len(by_country),
        "top_countries":    [
            {
                "country": c,
                "count":   n,
                "percentage": round(n / total * 100, 2) if total > 0 else 0,
            } for c, n in top_countries
        ],
        "by_country_month": {
            c: dict(by_country_date[c])
            for c, _ in top_countries[:10]
        },
    }
    return result


def analyze_time_patterns(metric_type="signups"):
    """Analyze time patterns: month-of-year, day-of-week, year-over-year."""
    sb = _get_supabase()
    if sb is None:
        return {"error": "MongoDB not configured"}

    table_map = {
        "signups":  ("signups",  "signup_date"),
        "uploads":  ("uploads",  "upload_date"),
        "paid":     ("payments", "first_payment_date"),
    }
    if metric_type not in table_map:
        return {"error": f"Unknown metric: {metric_type}"}

    tbl, date_col = table_map[metric_type]

    try:
        resp = sb.table(tbl).select(date_col).eq("final_status", "ACCEPTED").limit(20000).execute()
        rows = resp.data or []
    except Exception as e:
        return {"error": str(e)}

    dates = []
    for r in rows:
        v = r.get(date_col)
        if v:
            try:
                dt = datetime.fromisoformat(str(v)[:10])
                dates.append(dt)
            except Exception:
                pass

    if not dates:
        return {"error": "No valid dates found"}

    by_month_of_year   = Counter(d.strftime("%B") for d in dates)
    by_month_num       = Counter(d.month for d in dates)
    by_day_of_week     = Counter(d.strftime("%A") for d in dates)
    by_year            = Counter(d.year for d in dates)
    by_year_month      = Counter(d.strftime("%Y-%m") for d in dates)
    by_quarter         = Counter(f"Q{((d.month-1)//3)+1}" for d in dates)
    by_quarter_year    = Counter(f"{d.year}-Q{((d.month-1)//3)+1}" for d in dates)

    # Order months and days properly
    month_order = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    day_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

    months_ordered = [(m, by_month_of_year.get(m, 0)) for m in month_order]
    days_ordered   = [(d, by_day_of_week.get(d, 0))   for d in day_order]

    # Find peak month overall
    peak_month_name, peak_month_count = max(months_ordered, key=lambda x: x[1])
    peak_day_name,   peak_day_count   = max(days_ordered,   key=lambda x: x[1])

    # YoY growth
    years_sorted = sorted(by_year.keys())
    yoy = {}
    for i, y in enumerate(years_sorted):
        if i > 0:
            prev = by_year.get(years_sorted[i-1], 0)
            curr = by_year.get(y, 0)
            growth = ((curr - prev) / prev * 100) if prev > 0 else 0
            yoy[y] = {
                "count":      curr,
                "prev_count": prev,
                "growth_pct": round(growth, 1),
            }
        else:
            yoy[y] = {"count": by_year[y], "prev_count": None, "growth_pct": None}

    return {
        "metric":            metric_type,
        "total_records":     len(dates),
        "date_range":        {
            "first": min(dates).strftime("%Y-%m-%d"),
            "last":  max(dates).strftime("%Y-%m-%d"),
        },
        "by_month_of_year":  months_ordered,
        "by_day_of_week":    days_ordered,
        "by_year":           dict(sorted(by_year.items())),
        "by_year_month":     dict(sorted(by_year_month.items())),
        "by_quarter":        dict(sorted(by_quarter.items())),
        "by_quarter_year":   dict(sorted(by_quarter_year.items())),
        "peak_month":        {"name": peak_month_name, "count": peak_month_count},
        "peak_day":          {"name": peak_day_name,   "count": peak_day_count},
        "year_over_year":    yoy,
    }


def detect_fluctuation_patterns(metric_type="signups"):
    """Detect anomalies, spikes, drops in time-series data."""
    sb = _get_supabase()
    if sb is None:
        return {"error": "MongoDB not configured"}

    table_map = {
        "signups":  ("signups",  "signup_date"),
        "uploads":  ("uploads",  "upload_date"),
        "paid":     ("payments", "first_payment_date"),
    }
    tbl, date_col = table_map.get(metric_type, table_map["signups"])

    try:
        resp = sb.table(tbl).select(date_col).eq("final_status", "ACCEPTED").limit(20000).execute()
        rows = resp.data or []
    except Exception as e:
        return {"error": str(e)}

    daily = Counter()
    for r in rows:
        v = r.get(date_col)
        if v:
            daily[str(v)[:10]] += 1

    if not daily:
        return {"error": "No data"}

    sorted_dates = sorted(daily.keys())
    values = [daily[d] for d in sorted_dates]

    # Compute mean + std
    n = len(values)
    mean = sum(values) / n if n > 0 else 0
    variance = sum((v - mean) ** 2 for v in values) / n if n > 0 else 0
    std = variance ** 0.5

    # Find spikes (>2 std above mean) and drops (>2 std below)
    threshold_high = mean + 2 * std
    threshold_low  = max(0, mean - 2 * std)

    spikes = [{"date": d, "count": daily[d]} for d in sorted_dates if daily[d] > threshold_high]
    drops  = [{"date": d, "count": daily[d]} for d in sorted_dates if daily[d] < threshold_low]

    # Best 10 days and worst 10 days
    sorted_by_count = sorted(daily.items(), key=lambda x: -x[1])
    best_days  = [{"date": d, "count": c} for d, c in sorted_by_count[:10]]
    worst_days = [{"date": d, "count": c} for d, c in sorted_by_count[-10:] if c > 0]

    return {
        "metric":           metric_type,
        "total_days":       n,
        "mean_per_day":     round(mean, 2),
        "std":              round(std, 2),
        "spike_threshold":  round(threshold_high, 2),
        "drop_threshold":   round(threshold_low, 2),
        "spike_count":      len(spikes),
        "drop_count":       len(drops),
        "spikes":           spikes[:20],
        "drops":            drops[:20],
        "best_days":        best_days,
        "worst_days":       worst_days,
    }


def get_full_analysis(metric_type="signups"):
    """Get all three analyses in one call."""
    return {
        "metric":      metric_type,
        "region":      analyze_signups_by_region(metric_type),
        "time":        analyze_time_patterns(metric_type),
        "fluctuation": detect_fluctuation_patterns(metric_type),
        "generated":   datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    for metric in ("signups", "uploads", "paid"):
        print("=" * 60)
        print(f"ANALYSIS: {metric.upper()}")
        print("=" * 60)
        r = analyze_signups_by_region(metric)
        print(f"\nTop 5 countries:")
        for c in r.get("top_countries", [])[:5]:
            print(f"  {c['country']:<30} {c['count']:>5} ({c['percentage']}%)")
        t = analyze_time_patterns(metric)
        print(f"\nPeak month: {t.get('peak_month', {}).get('name')} ({t.get('peak_month', {}).get('count')} records)")
        print(f"Peak day:   {t.get('peak_day', {}).get('name')} ({t.get('peak_day', {}).get('count')} records)")
        print(f"\nYear-over-year:")
        for year, data in t.get("year_over_year", {}).items():
            growth = data.get("growth_pct")
            growth_str = f" ({growth:+.1f}%)" if growth is not None else ""
            print(f"  {year}: {data['count']}{growth_str}")
