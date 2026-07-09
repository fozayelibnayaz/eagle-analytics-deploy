"""
pipeline_gap_scanner.py — Eagle 3D Streaming Analytics Hub
=============================================================
Scans daily_kpis for missing/incomplete days in the last 180 days.
Missing = day has no row OR row has all zeros for signups+uploads+payments.

Used by:
  - daily_pipeline.py runs this AFTER main scrape to fill any gaps
  - dashboard shows "N missing days" widget with 'refill' button
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from mongo_client import find_all, get_raw_db

LOOKBACK_DAYS = 180  # threshold: 6 months


def _all_expected_dates() -> List[str]:
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(LOOKBACK_DAYS)]


def scan_gaps() -> Dict[str, Any]:
    """Returns detailed report of missing / zero-only days."""
    expected = set(_all_expected_dates())
    rows = find_all("daily_kpis",
                    filters={"date": {"$gte": min(expected)}},
                    projection={"date": 1, "signups_accepted": 1,
                                 "uploads_accepted": 1, "paid_accepted": 1,
                                 "signups": 1, "uploads": 1, "payments": 1})
    have = {r["date"] for r in rows if r.get("date")}
    missing_dates = sorted(expected - have)

    # Also find zero-only days (row exists but no metrics)
    zero_days = []
    for r in rows:
        d = r.get("date")
        if not d or d not in expected:
            continue
        s = int(r.get("signups_accepted") or r.get("signups") or 0)
        u = int(r.get("uploads_accepted") or r.get("uploads") or 0)
        p = int(r.get("paid_accepted")    or r.get("payments") or 0)
        if s == 0 and u == 0 and p == 0:
            zero_days.append(d)
    zero_days.sort()

    return {
        "lookback_days":    LOOKBACK_DAYS,
        "expected_days":    len(expected),
        "have_rows":        len(have),
        "missing_dates":    missing_dates,
        "zero_only_dates":  zero_days,
        "missing_count":    len(missing_dates),
        "zero_count":       len(zero_days),
        "health_pct":       round((len(have) - len(zero_days)) / len(expected) * 100, 1)
                             if expected else 0,
    }


def fill_missing_stubs() -> int:
    """
    For each missing date, insert a stub row so daily_kpis has 100% coverage.
    Stub = date + zero counts + _source='gap_stub'.
    Returns count of stubs inserted.
    """
    db = get_raw_db()
    if db is None:
        return 0
    report = scan_gaps()
    inserted = 0
    from datetime import datetime as _dt
    now = _dt.utcnow().isoformat()
    for d in report["missing_dates"]:
        try:
            db["daily_kpis"].update_one(
                {"date": d},
                {"$setOnInsert": {
                    "date": d,
                    "signups": 0, "uploads": 0, "payments": 0,
                    "signups_accepted": 0, "uploads_accepted": 0, "paid_accepted": 0,
                    "_source": "gap_stub",
                    "_filled_at": now,
                }},
                upsert=True,
            )
            inserted += 1
        except Exception:
            pass
    return inserted


def rebuild_from_raw() -> Dict[str, Any]:
    """
    Rebuild ALL daily_kpis rows for last LOOKBACK_DAYS from raw collections.
    Reads: signups, uploads, payments (ACCEPTED only) grouped by date.
    Writes: signups_accepted, uploads_accepted, paid_accepted in daily_kpis.
    """
    from collections import defaultdict
    from mongo_client import find_all as fa
    db = get_raw_db()
    if db is None:
        return {"error": "MongoDB offline"}

    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()

    # Aggregate raw ACCEPTED counts by date
    signups_by_date  = defaultdict(int)
    uploads_by_date  = defaultdict(int)
    payments_by_date = defaultdict(int)

    for r in fa("signups", filters={"final_status": "ACCEPTED",
                                     "signup_date": {"$gte": cutoff}},
                 projection={"signup_date": 1}):
        d = str(r.get("signup_date") or "")[:10]
        if d: signups_by_date[d] += 1

    for r in fa("uploads", filters={"final_status": "ACCEPTED",
                                     "upload_date": {"$gte": cutoff}},
                 projection={"upload_date": 1}):
        d = str(r.get("upload_date") or "")[:10]
        if d: uploads_by_date[d] += 1

    for r in fa("payments", filters={"final_status": "ACCEPTED",
                                      "first_payment_date": {"$gte": cutoff}},
                 projection={"first_payment_date": 1}):
        d = str(r.get("first_payment_date") or "")[:10]
        if d: payments_by_date[d] += 1

    # Union of all dates
    all_dates = set(signups_by_date) | set(uploads_by_date) | set(payments_by_date)
    # Also add missing days
    today = date.today()
    for i in range(LOOKBACK_DAYS):
        all_dates.add((today - timedelta(days=i)).isoformat())

    from datetime import datetime as _dt
    now = _dt.utcnow().isoformat()
    updated = 0
    for d in sorted(all_dates):
        try:
            db["daily_kpis"].update_one(
                {"date": d},
                {"$set": {
                    "date": d,
                    "signups_accepted": int(signups_by_date.get(d, 0)),
                    "uploads_accepted": int(uploads_by_date.get(d, 0)),
                    "paid_accepted":    int(payments_by_date.get(d, 0)),
                    "_rebuilt_at":      now,
                    "_source":          "rebuild_from_raw",
                }},
                upsert=True,
            )
            updated += 1
        except Exception:
            pass

    return {
        "rebuilt_days":  updated,
        "signups_total": sum(signups_by_date.values()),
        "uploads_total": sum(uploads_by_date.values()),
        "paid_total":    sum(payments_by_date.values()),
    }


if __name__ == "__main__":
    import json
    print("Scanning for gaps...")
    print(json.dumps(scan_gaps(), indent=2, default=str))
    print("\nRebuilding daily_kpis from raw...")
    print(json.dumps(rebuild_from_raw(), indent=2))
    print("\nAfter rebuild:")
    print(json.dumps(scan_gaps(), indent=2, default=str))
