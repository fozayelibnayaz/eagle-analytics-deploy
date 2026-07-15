from __future__ import annotations

from typing import Tuple
from mongo_client import find_all

def _as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def _norm_day(v: str) -> str:
    return str(v or "").strip()[:10]

def _raw_fallback(start_day: str, end_day: str) -> Tuple[int, int, int, int, int]:
    signups = uploads = new_paid = recurring = stopped = 0

    s_rows = find_all("signups", {})
    u_rows = find_all("uploads", {})
    p_rows = find_all("payments", {})

    signups = sum(
        1 for r in s_rows
        if str(r.get("final_status", "")).upper() == "ACCEPTED"
        and start_day <= _norm_day(r.get("signup_date", "")) <= end_day
    )

    uploads = sum(
        1 for r in u_rows
        if str(r.get("final_status", "")).upper() == "ACCEPTED"
        and start_day <= _norm_day(r.get("upload_date", "")) <= end_day
    )

    for r in p_rows:
        if str(r.get("final_status", "")).upper() != "ACCEPTED":
            continue
        d = _norm_day(r.get("first_payment_date") or r.get("payment_date") or r.get("date"))
        if not d or not (start_day <= d <= end_day):
            continue

        ctype = str(r.get("customer_type", "")).upper()
        status = str(
            r.get("subscription_status")
            or r.get("status")
            or r.get("plan_status")
            or ""
        ).lower()

        if ctype == "NEW_CUSTOMER" or _as_int(r.get("payment_count", 0)) == 1:
            new_paid += 1
        else:
            recurring += 1

        if status in {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}:
            if _as_int(r.get("payment_count", 0)) > 1:
                stopped += 1

    return signups, uploads, new_paid, recurring, stopped

def resolve_period_kpis(start_iso: str, end_iso: str) -> Tuple[int, int, int, int, int]:
    start_day = _norm_day(start_iso)
    end_day = _norm_day(end_iso)

    rows = find_all(
        "daily_kpis",
        {"date": {"$gte": start_day, "$lte": end_day}},
        sort=[("date", 1)],
        limit=10000,
    )

    signups = sum(_as_int(r.get("signups", 0)) for r in rows)
    uploads = sum(_as_int(r.get("first_uploads", r.get("uploads", 0))) for r in rows)
    new_paid = sum(_as_int(r.get("new_paid_customers", r.get("paid_customers", 0))) for r in rows)
    recurring = sum(_as_int(r.get("recurring_customers", 0)) for r in rows)
    stopped = sum(_as_int(r.get("stopped_recurring_customers", 0)) for r in rows)

    if signups == 0 and uploads == 0 and new_paid == 0 and rows:
        # rows exist but counts zero -> suspicious, try raw fallback
        return _raw_fallback(start_day, end_day)

    if not rows:
        return _raw_fallback(start_day, end_day)

    return signups, uploads, new_paid, recurring, stopped
