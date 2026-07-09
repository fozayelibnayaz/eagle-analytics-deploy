"""
daily_counts.py — Eagle 3D Streaming Analytics Hub
====================================================
Builds daily_kpis + monthly_counts collections from ACCEPTED
signups / uploads / payments in MongoDB.

Reads directly from processed collections; falls back to raw_data
if the top-level date field is empty.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from mongo_client import find_all, upsert_many


DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def _parse_date_string(s: Any) -> str:
    """Return YYYY-MM-DD or empty string."""
    if s is None:
        return ""
    s = str(s).strip()
    if not s or s.lower() in ("nan", "none", "—", "-", "null", "n/a", "na"):
        return ""

    import re
    # ISO first
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)

    # US MM/DD/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{yy:04d}-{mm:02d}-{dd:02d}"
        except Exception:
            pass

    # "Sun May 31 2026" style
    for fmt in ("%a %b %d %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(s[:len(fmt) + 10], fmt)
            return d.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue

    return ""


def _row_date(row: Dict[str, Any], primary_fields: Tuple[str, ...],
              raw_fields: Tuple[str, ...] = ()) -> str:
    """
    Try top-level fields first, then dip into raw_data.
    Returns YYYY-MM-DD or empty string.
    """
    for k in primary_fields:
        d = _parse_date_string(row.get(k))
        if d:
            return d

    raw = row.get("raw_data") or {}
    for k in raw_fields or primary_fields:
        d = _parse_date_string(raw.get(k))
        if d:
            return d

    return ""


# ─────────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────────
def _load_accepted_dates(
    collection: str,
    primary_fields: Tuple[str, ...],
    raw_fields: Tuple[str, ...] = (),
) -> List[str]:
    rows = find_all(collection, {"final_status": "ACCEPTED"})
    out = []
    for r in rows:
        d = _row_date(r, primary_fields, raw_fields)
        if d:
            out.append(d)
    return out


# ─────────────────────────────────────────────────────────────────
# MAIN BUILDER
# ─────────────────────────────────────────────────────────────────
def build_daily_counts_table() -> Dict[str, Any]:
    signup_dates = _load_accepted_dates(
        "signups",
        primary_fields=("signup_date",),
        raw_fields=("Account Created On", "Account_Created_On",
                    "Signup Date", "Signup_Date", "Created", "Date"),
    )
    upload_dates = _load_accepted_dates(
        "uploads",
        primary_fields=("upload_date",),
        raw_fields=("First_Upload_Date", "First Upload Date",
                    "Upload Date", "Upload_Date", "Date"),
    )
    payment_dates = _load_accepted_dates(
        "payments",
        primary_fields=("first_payment_date", "created_date"),
        raw_fields=("Payment_Date", "Payment Date",
                    "First payment", "First Payment",
                    "Created", "Created On"),
    )

    all_dates = sorted(set(signup_dates + upload_dates + payment_dates))
    if not all_dates:
        return {"daily_rows": 0, "free_accepted": 0,
                "upload_accepted": 0, "stripe_accepted": 0}

    signup_by  = defaultdict(int)
    upload_by  = defaultdict(int)
    payment_by = defaultdict(int)

    for d in signup_dates:  signup_by[d]  += 1
    for d in upload_dates:  upload_by[d]  += 1
    for d in payment_dates: payment_by[d] += 1

    now = datetime.utcnow().isoformat()

    daily_rows = [{
        "date":       d,
        "signups":    signup_by[d],
        "uploads":    upload_by[d],
        "payments":   payment_by[d],
        "_source":    "daily_counts",
        "_built_at":  now,
    } for d in all_dates]

    upsert_many("daily_kpis", daily_rows, "date")

    # Monthly rollup
    monthly = defaultdict(lambda: {"signups": 0, "uploads": 0, "payments": 0})
    for row in daily_rows:
        m = row["date"][:7]
        monthly[m]["signups"]  += row["signups"]
        monthly[m]["uploads"]  += row["uploads"]
        monthly[m]["payments"] += row["payments"]

    monthly_rows = [{
        "month":     m,
        "signups":   vals["signups"],
        "uploads":   vals["uploads"],
        "payments":  vals["payments"],
        "_built_at": now,
    } for m, vals in sorted(monthly.items())]
    upsert_many("monthly_counts", monthly_rows, "month")

    # Snapshot JSON for legacy compat
    try:
        (DATA_DIR / "daily_counts.json").write_text(
            json.dumps({r["date"]: {"signups": r["signups"],
                                    "uploads": r["uploads"],
                                    "payments": r["payments"]}
                       for r in daily_rows}, indent=2)
        )
    except Exception:
        pass

    return {
        "daily_rows":       len(daily_rows),
        "monthly_rows":     len(monthly_rows),
        "free_accepted":    sum(signup_by.values()),
        "upload_accepted":  sum(upload_by.values()),
        "stripe_accepted":  sum(payment_by.values()),
    }


if __name__ == "__main__":
    result = build_daily_counts_table()
    print(json.dumps(result, indent=2))
