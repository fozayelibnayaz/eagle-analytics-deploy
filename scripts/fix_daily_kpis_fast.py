from __future__ import annotations

from datetime import date, datetime, timedelta
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import get_raw_db

LOOKBACK_DAYS = int(os.environ.get("KPI_REBUILD_LOOKBACK_DAYS", "120"))
TODAY = date.today()
START = TODAY - timedelta(days=LOOKBACK_DAYS)
START_DAY = START.isoformat()
END_DAY = TODAY.isoformat()

TEST_SOURCES = {"test-postman", "cloud-test", "manual-test", "debug"}
TEST_EMAIL_MARKERS = ("@example.com", "webhook-test", "cloud-test", "newuser@example.com")

def norm_email(v):
    s = str(v or "").strip()
    m = re.search(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', s)
    return m.group(1).lower() if m else s.lower()

def is_test_email(email: str) -> bool:
    e = norm_email(email)
    return any(x in e for x in TEST_EMAIL_MARKERS)

def pick_date(doc, keys):
    for k in keys:
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def is_real_webhook_doc(doc):
    source = str(doc.get("source", "") or "").strip().lower()
    email = norm_email(doc.get("email") or doc.get("email_normalized"))
    if not source or source in TEST_SOURCES:
        return False
    if is_test_email(email):
        return False
    return True

def get_cutover_date(db):
    # cheap source-of-truth: earliest real webhook log event
    rows = list(db["webhook_log"].find({}, {"_id": 0, "source": 1, "received_at": 1}).sort("received_at", 1))
    dates = []
    for r in rows:
        src = str(r.get("source", "") or "").strip().lower()
        if not src or src in TEST_SOURCES:
            continue
        dt = str(r.get("received_at", "") or "").strip()[:10]
        if dt:
            dates.append(dt)
    return min(dates) if dates else None

def include_legacy_vs_webhook(doc, day, cutover):
    source = str(doc.get("source", "") or "").strip().lower()
    if not cutover:
        return True
    if day < cutover:
        return source != "webhook"
    return is_real_webhook_doc(doc)

def ensure_indexes(db):
    try:
        db["signups"].create_index([("final_status", 1), ("signup_date", 1)])
    except Exception:
        pass
    try:
        db["uploads"].create_index([("final_status", 1), ("upload_date", 1)])
    except Exception:
        pass
    try:
        db["payments"].create_index([("final_status", 1), ("first_payment_date", 1)])
    except Exception:
        pass
    try:
        db["payment_history"].create_index([("email_normalized", 1)])
    except Exception:
        pass
    try:
        db["daily_kpis"].create_index([("date", 1)])
    except Exception:
        pass

def main():
    db = get_raw_db()
    if db is None:
        raise SystemExit("❌ MongoDB/Atlas not available")

    ensure_indexes(db)

    cutover = get_cutover_date(db)
    print(f"Cutover date = {cutover}")
    print(f"Rebuilding window = {START_DAY} .. {END_DAY}")

    # payment history map (canonical first-ever date)
    first_paid = {}
    for d in db["payment_history"].find({}, {"_id": 0, "email_normalized": 1, "first_ever_payment_date": 1}):
        email = norm_email(d.get("email_normalized"))
        dt = pick_date(d, ["first_ever_payment_date"])
        if email and dt:
            first_paid[email] = dt

    daymap = {}

    def ensure_day(day):
        if day not in daymap:
            daymap[day] = {
                "date": day,
                "_s": set(),
                "_u": set(),
                "_new": set(),
                "_rec": set(),
                "_stop": set(),
            }
        return daymap[day]

    # signups
    for d in db["signups"].find(
        {"final_status": "ACCEPTED", "signup_date": {"$gte": START_DAY, "$lte": END_DAY}},
        {"_id": 0, "email": 1, "email_normalized": 1, "signup_date": 1, "source": 1}
    ):
        day = pick_date(d, ["signup_date"])
        email = norm_email(d.get("email") or d.get("email_normalized"))
        if day and email and include_legacy_vs_webhook(d, day, cutover):
            ensure_day(day)["_s"].add(email)

    # uploads
    for d in db["uploads"].find(
        {"final_status": "ACCEPTED", "upload_date": {"$gte": START_DAY, "$lte": END_DAY}},
        {"_id": 0, "email": 1, "email_normalized": 1, "upload_date": 1, "source": 1}
    ):
        day = pick_date(d, ["upload_date"])
        email = norm_email(d.get("email") or d.get("email_normalized"))
        if day and email and include_legacy_vs_webhook(d, day, cutover):
            ensure_day(day)["_u"].add(email)

    # payments
    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}
    for d in db["payments"].find(
        {"final_status": "ACCEPTED", "first_payment_date": {"$gte": START_DAY, "$lte": END_DAY}},
        {"_id": 0, "email": 1, "email_normalized": 1, "first_payment_date": 1, "first_ever_payment_date": 1,
         "source": 1, "subscription_status": 1, "status": 1, "plan_status": 1, "customer_status": 1}
    ):
        day = pick_date(d, ["first_payment_date"])
        email = norm_email(d.get("email") or d.get("email_normalized"))
        if not (day and email):
            continue
        if not include_legacy_vs_webhook(d, day, cutover):
            continue

        first_ever = pick_date(d, ["first_ever_payment_date"]) or first_paid.get(email, day)
        status = str(d.get("subscription_status") or d.get("status") or d.get("plan_status") or d.get("customer_status") or "").strip().lower()

        bucket = ensure_day(day)
        if first_ever == day:
            bucket["_new"].add(email)
        else:
            bucket["_rec"].add(email)

        if status in stop_statuses and first_ever < day:
            bucket["_stop"].add(email)

    rows = []
    for day in sorted(daymap.keys()):
        b = daymap[day]
        rows.append({
            "date": day,
            "signups": len(b["_s"]),
            "uploads": len(b["_u"]),
            "first_uploads": len(b["_u"]),
            "paid_customers": len(b["_new"]),
            "new_paid_customers": len(b["_new"]),
            "recurring_customers": len(b["_rec"]),
            "stopped_recurring_customers": len(b["_stop"]),
            "total_paying_customers": len(b["_new"] | b["_rec"]),
            "payments": len(b["_new"]),
            "source": "daily_kpis_fast_cutover_fix",
            "rebuilt_at": datetime.utcnow().isoformat(),
        })

    # replace only the rolling window
    db["daily_kpis"].delete_many({"date": {"$gte": START_DAY, "$lte": END_DAY}})
    if rows:
        db["daily_kpis"].insert_many(rows)

    month_rows = [r for r in rows if str(r["date"]).startswith("2026-07")]
    print({
        "month_signups": sum(as_int(r["signups"]) for r in month_rows),
        "month_first_uploads": sum(as_int(r["first_uploads"]) for r in month_rows),
        "month_new_paid_customers": sum(as_int(r["new_paid_customers"]) for r in month_rows),
        "month_recurring_customers": sum(as_int(r["recurring_customers"]) for r in month_rows),
        "month_stopped_recurring_customers": sum(as_int(r["stopped_recurring_customers"]) for r in month_rows),
        "month_total_paying_customers": sum(as_int(r["total_paying_customers"]) for r in month_rows),
    })

if __name__ == "__main__":
    main()
