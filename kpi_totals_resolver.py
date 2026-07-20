from __future__ import annotations

from typing import Tuple, Dict, List
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
    return str(v or "").strip().lower()

def _pick_date(doc, keys):
    for k in keys:
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _pick_amount(doc):
    for k in ("amount", "total_spend", "paid_amount", "invoice_amount"):
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

    events = []
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
            dt = _pick_date(d, ["first_payment_date", "payment_date", "created_date", "date"])
            amt = _pick_amount(d)
            if not email or not dt or amt <= 0:
                continue

            # Exclude obvious synthetic/test data
            if email.endswith("@example.com") or "webhook-test" in email or "cloud-test" in email:
                continue

            sig = (email, dt, round(amt, 2))
            if sig in seen:
                continue
            seen.add(sig)

            events.append({
                "email": email,
                "date": dt,
                "amount": amt,
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

    events.sort(key=lambda x: (x["email"], x["date"], x["collection"]))
    return events

def _first_paid_map():
    events = _all_payment_events()
    first_paid = {}
    for e in events:
        first_paid.setdefault(e["email"], e["date"])
    return events, first_paid

def resolve_period_kpis(start_iso: str, end_iso: str) -> Tuple[int, int, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]

    rows = find_all(
        "daily_kpis",
        filters={"date": {"$gte": start_day, "$lte": end_day}},
        sort=[("date", 1)],
        limit=10000,
    )

    signups = sum(_as_int(r.get("signups", 0)) for r in rows)
    uploads = sum(_as_int(r.get("first_uploads", r.get("uploads", 0))) for r in rows)

    events, first_paid = _first_paid_map()
    new_paid = len({
        e["email"] for e in events
        if start_day <= e["date"] <= end_day and first_paid.get(e["email"]) == e["date"]
    })

    return signups, uploads, new_paid

def resolve_paid_breakdown(start_iso: str, end_iso: str) -> Dict[str, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]

    events, first_paid = _first_paid_map()
    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    new_set = set()
    recurring_set = set()
    stopped_set = set()

    for e in events:
        if not (start_day <= e["date"] <= end_day):
            continue
        if first_paid.get(e["email"]) == e["date"]:
            new_set.add(e["email"])
        else:
            recurring_set.add(e["email"])

        if e["status"] in stop_statuses and first_paid.get(e["email"], e["date"]) < e["date"]:
            stopped_set.add(e["email"])

    return {
        "new_paid_customers": len(new_set),
        "recurring_customers": len(recurring_set),
        "stopped_recurring_customers": len(stopped_set),
        "total_paying_customers": len(new_set | recurring_set),
    }
