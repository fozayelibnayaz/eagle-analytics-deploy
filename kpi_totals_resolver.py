from __future__ import annotations

from typing import Tuple, Dict
from mongo_client import find_all

def _as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def _as_float(v):
    try:
        if v is None or str(v).strip() == "":
            return 0.0
        return float(v)
    except Exception:
        return 0.0

def _norm(v):
    import re
    s = str(v or "").strip()
    m = re.search(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', s)
    return m.group(1).lower() if m else s.lower()

def _pick_event_date(doc):
    for k in ("first_payment_date", "payment_date", "created_date", "date"):
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _pick_first_ever_date(doc):
    for k in ("first_ever_payment_date", "first_payment_date", "payment_date", "created_date", "date"):
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _pick_amount(doc):
    for k in ("amount", "total_spend", "paid_amount", "invoice_amount", "first_ever_amount"):
        v = doc.get(k)
        if v not in (None, "", 0, "0"):
            return _as_float(v)
    return 0.0

def _is_accepted(doc):
    fs = str(doc.get("final_status", "")).strip().upper()
    if fs:
        return fs == "ACCEPTED"
    return _pick_amount(doc) > 0

def _all_payment_events():
    collections = [
        "payments",
        "payment_history",
        "sheet_verified_stripe",
        "sheet_raw_stripe",
    ]

    rows = []
    seen = set()

    for col in collections:
        try:
            docs = find_all(col, {})
        except Exception:
            docs = []

        for d in docs:
            if not _is_accepted(d):
                continue

            email = _norm(d.get("email") or d.get("email_normalized"))
            event_date = _pick_event_date(d)
            first_ever_date = _pick_first_ever_date(d)
            amount = _pick_amount(d)

            if not email or not event_date or amount <= 0:
                continue

            # exclude known synthetic test emails
            if email.endswith("@example.com") or "webhook-test" in email or "cloud-test" in email:
                continue

            sig = (email, event_date, round(amount, 2))
            if sig in seen:
                continue
            seen.add(sig)

            rows.append({
                "email": email,
                "event_date": event_date,
                "first_ever_date": first_ever_date or event_date,
                "amount": amount,
                "status": str(
                    d.get("subscription_status")
                    or d.get("status")
                    or d.get("plan_status")
                    or d.get("customer_status")
                    or ""
                ).strip().lower(),
                "collection": col,
                "id": d.get("id"),
            })

    rows.sort(key=lambda x: (x["email"], x["event_date"], x["collection"]))
    return rows

def _first_ever_map(events):
    first_ever = {}
    for e in events:
        email = e["email"]
        dt = min(e["event_date"], e.get("first_ever_date") or e["event_date"])
        prev = first_ever.get(email)
        if prev is None or dt < prev:
            first_ever[email] = dt
    return first_ever

def resolve_period_kpis(start_iso: str, end_iso: str) -> Tuple[int, int, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]

    daily = find_all(
        "daily_kpis",
        filters={"date": {"$gte": start_day, "$lte": end_day}},
        sort=[("date", 1)],
        limit=10000,
    )

    signups = sum(_as_int(r.get("signups", 0)) for r in daily)
    uploads = sum(_as_int(r.get("first_uploads", r.get("uploads", 0))) for r in daily)

    events = _all_payment_events()
    first_ever = _first_ever_map(events)
    paid_in_period = {
        e["email"]
        for e in events
        if start_day <= e["event_date"] <= end_day
    }
    new_paid = sum(1 for email in paid_in_period if start_day <= first_ever.get(email, "9999-99-99") <= end_day)

    return signups, uploads, new_paid

def resolve_paid_breakdown(start_iso: str, end_iso: str) -> Dict[str, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]
    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    events = _all_payment_events()
    first_ever = _first_ever_map(events)
    in_period = {}
    stopped_set = set()

    for e in events:
        if not (start_day <= e["event_date"] <= end_day):
            continue
        email = e["email"]
        prev = in_period.get(email)
        if prev is None or e["event_date"] < prev:
            in_period[email] = e["event_date"]
        if e["status"] in stop_statuses and first_ever.get(email, e["event_date"]) < e["event_date"]:
            stopped_set.add(email)

    new_set = {email for email in in_period if start_day <= first_ever.get(email, "9999-99-99") <= end_day}
    recurring_set = {email for email in in_period if first_ever.get(email, "") < start_day}

    return {
        "new_paid_customers": len(new_set),
        "recurring_customers": len(recurring_set),
        "stopped_recurring_customers": len(stopped_set),
        "total_paying_customers": len(new_set | recurring_set),
    }
