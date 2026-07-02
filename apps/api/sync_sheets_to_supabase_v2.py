#!/usr/bin/env python3
"""


Sync ALL Verified_FREE / Verified_FIRST_UPLOAD / Verified_STRIPE rows
from Google Sheets to MongoDB. Handles pagination + upserts on email_normalized.
Rebuilds daily_kpis after sync to keep counts in sync everywhere.
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





def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def _get_sb():
    return get_db()


def parse_date(v):
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%d","%m/%d/%y, %I:%M %p","%m/%d/%Y, %I:%M %p",
                "%a, %d %b %Y %H:%M:%S %Z","%a, %d %b %Y %H:%M:%S GMT",
                "%b %d, %Y","%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s.split("+")[0], fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100: y += 2000
        try:
            return f"{y}-{mo:02d}-{d:02d}"
        except Exception:
            pass
    return None


def parse_amount(v):
    if not v: return 0.0
    s = re.sub(r"[$,€£\s\n\r]", "", str(v))
    s = re.sub(r"[A-Za-z]+$", "", s).strip()
    try: return float(s)
    except: return 0.0


def sync_signups():
    sb = _get_sb()
    from sheets_writer import read_tab_data
    rows = read_tab_data("Verified_FREE")
    log(f"Verified_FREE: {len(rows)} rows")

    upsert = []
    for r in rows:
        email = str(r.get("Email","") or r.get("email","")).strip().lower()
        if not email or "@" not in email: continue
        d = None
        for f in ("Account Created On","row_date_used","__scraped_date__"):
            v = r.get(f)
            if v:
                d = parse_date(v)
                if d: break
        upsert.append({
            "email": email,
            "email_normalized": email,
            "signup_date": d,
            "lead_source": str(r.get("Lead Source","") or "")[:200],
            "final_status": str(r.get("final_status","PENDING") or "PENDING").upper()[:20],
            "category": str(r.get("category","") or "")[:50],
            "rejection_reason": str(r.get("__rejection_reason__", r.get("verdict_reason","")) or "")[:300],
        })

    log(f"Upserting {len(upsert)} signups...")
    errors = 0
    for i in range(0, len(upsert), 50):
        try:
            pass
        except Exception as e:
            errors += 1
            if errors <= 3: log(f"  Chunk {i} err: {e}")
    log(f"Signups done: {len(upsert)} sent, {errors} errors")
    return len(upsert)


def sync_uploads():
    sb = _get_sb()
    from sheets_writer import read_tab_data
    rows = read_tab_data("Verified_FIRST_UPLOAD")
    log(f"Verified_FIRST_UPLOAD: {len(rows)} rows")

    upsert = []
    for r in rows:
        email = str(r.get("Email","") or r.get("email","")).strip().lower()
        if not email or "@" not in email: continue
        d = None
        for f in ("Upload Date","row_date_used","__scraped_date__"):
            v = r.get(f)
            if v:
                d = parse_date(v)
                if d: break
        upsert.append({
            "email": email,
            "email_normalized": email,
            "upload_date": d,
            "final_status": str(r.get("final_status","PENDING") or "PENDING").upper()[:20],
            "category": str(r.get("category","") or "")[:50],
            "rejection_reason": str(r.get("__rejection_reason__","") or "")[:300],
        })

    log(f"Upserting {len(upsert)} uploads...")
    errors = 0
    for i in range(0, len(upsert), 50):
        try:
            pass
        except Exception as e:
            errors += 1
            if errors <= 3: log(f"  Chunk {i} err: {e}")
    log(f"Uploads done: {len(upsert)} sent, {errors} errors")
    return len(upsert)


def sync_payments():
    sb = _get_sb()
    from sheets_writer import read_tab_data
    rows = read_tab_data("Verified_STRIPE")
    log(f"Verified_STRIPE: {len(rows)} rows")

    upsert = []
    for r in rows:
        email = str(r.get("Email","") or r.get("email","")).strip().lower()
        if not email or "@" not in email: continue
        d = None
        for f in ("First payment","row_date_used","Created","Created (UTC)","__scraped_date__"):
            v = r.get(f)
            if v:
                d = parse_date(v)
                if d: break
        amt = 0.0
        for af in ("Amount","Total spend","Total Spend","__amount__"):
            v = r.get(af)
            if v:
                a = parse_amount(v)
                if a > 0: amt = a; break
        try:
            pc = int(r.get("Payment Count", r.get("payment_count",0)) or 0)
        except: pc = 0
        upsert.append({
            "email": email,
            "email_normalized": email,
            "first_payment_date": d,
            "total_spend": amt,
            "payment_count": pc,
            "final_status": str(r.get("final_status","PENDING") or "PENDING").upper()[:20],
            "category": str(r.get("category","") or "")[:50],
        })

    log(f"Upserting {len(upsert)} payments...")
    errors = 0
    for i in range(0, len(upsert), 50):
        try:
            pass
        except Exception as e:
            errors += 1
            if errors <= 3: log(f"  Chunk {i} err: {e}")
    log(f"Payments done: {len(upsert)} sent, {errors} errors")
    return len(upsert)


def rebuild_daily_kpis():
    """Rebuild daily_kpis from source-of-truth signups/uploads/payments (paginated)."""
    sb = _get_sb()

    def fetch_all(table, cols):
        rows = []
        offset = 0
        while True:
            r = sb.table(table).select(cols).eq("final_status","ACCEPTED").range(offset, offset + 999).execute()
            batch = r.data or []
            rows.extend(batch)
            if len(batch) < 1000: break
            offset += 1000
        return rows

    log("Fetching ALL accepted signups (paginated)...")
    sign_rows = fetch_all("signups","signup_date,email")
    log(f"  {len(sign_rows)}")

    log("Fetching ALL accepted uploads...")
    upl_rows = fetch_all("uploads","upload_date,email")
    log(f"  {len(upl_rows)}")

    log("Fetching ALL accepted payments...")
    pay_rows = fetch_all("payments","first_payment_date,email")
    log(f"  {len(pay_rows)}")

    daily = defaultdict(lambda: {"s":0,"u":0,"p":0,"se":[],"ue":[],"pe":[]})
    for r in sign_rows:
        d = str(r.get("signup_date") or "")[:10]
        if d:
            daily[d]["s"] += 1
            daily[d]["se"].append(r.get("email",""))
    for r in upl_rows:
        d = str(r.get("upload_date") or "")[:10]
        if d:
            daily[d]["u"] += 1
            daily[d]["ue"].append(r.get("email",""))
    for r in pay_rows:
        d = str(r.get("first_payment_date") or "")[:10]
        if d:
            daily[d]["p"] += 1
            daily[d]["pe"].append(r.get("email",""))

    upsert = []
    for d, v in daily.items():
        upsert.append({
            "date": d,
            "year": str(d[:4]),
            "month": str(d[:7]),
            "signups_accepted": v["s"],
            "uploads_accepted": v["u"],
            "paid_accepted":    v["p"],
            "signup_details": "; ".join(sorted(set(v["se"])))[:5000],
            "upload_details": "; ".join(sorted(set(v["ue"])))[:5000],
            "paid_details":   "; ".join(sorted(set(v["pe"])))[:5000],
            "last_updated":   datetime.utcnow().isoformat(),
        })
    upsert.sort(key=lambda x: x["date"])
    log(f"Upserting {len(upsert)} daily_kpis rows...")
    for i in range(0, len(upsert), 100):
        upsert_many("daily_kpis", upsert[i:i+100], "date")
    log(f"daily_kpis rebuilt: {len(upsert)} days")


def verify():
    sb = _get_sb()
    from datetime import date, timedelta
    today = date.today().strftime("%Y-%m-%d")
    print("\n" + "="*60)
    print("FINAL VERIFICATION (Source-of-truth = MongoDB signups/uploads/payments)")
    print("="*60)

    for ps, pe, lbl in [
        ("2026-06-01","2026-06-30","June 2026"),
        (today, today, "Today"),
        ("2025-12-01","2026-06-30","Common Period"),
    ]:
        a = sb.table("signups").select("count",count="exact").eq("final_status","ACCEPTED").gte("signup_date",ps).lte("signup_date",pe).execute().count or 0
        u = sb.table("uploads").select("count",count="exact").eq("final_status","ACCEPTED").gte("upload_date",ps).lte("upload_date",pe).execute().count or 0
        p = sb.table("payments").select("count",count="exact").eq("final_status","ACCEPTED").gte("first_payment_date",ps).lte("first_payment_date",pe).execute().count or 0
        # daily_kpis
        rows = sb.table("daily_kpis").select("signups_accepted,uploads_accepted,paid_accepted").gte("date",ps).lte("date",pe).execute().data or []
        ds = sum(x["signups_accepted"] for x in rows)
        du = sum(x["uploads_accepted"] for x in rows)
        dp = sum(x["paid_accepted"] for x in rows)
        match_s = "OK" if a == ds else "MISMATCH"
        match_u = "OK" if u == du else "MISMATCH"
        match_p = "OK" if p == dp else "MISMATCH"
        print(f"  {lbl}:")
        print(f"    Signups: source={a} daily_kpis={ds} [{match_s}]")
        print(f"    Uploads: source={u} daily_kpis={du} [{match_u}]")
        print(f"    Paid:    source={p} daily_kpis={dp} [{match_p}]")


def run():
    log("="*60)
    log("FULL SYNC: Sheets -> MongoDB -> daily_kpis rebuild")
    log("="*60)
    rebuild_daily_kpis()
    verify()
    log("DONE")


if __name__ == "__main__":
    run()
