#!/usr/bin/env python3
"""
COMMON PERIOD ENGINE — Priority 4
All-Time = Common Available Data Period, NOT entire database history.
Prevents comparing mismatched coverage periods.
"""
import json
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Tuple

DATA_DIR = Path("data_output")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [CommonPeriod] {msg}", flush=True)


def get_metric_coverage(daily_data: list) -> dict:
    """Get first/last date for each metric in daily_counts."""
    signup_dates  = sorted([r["Date"] for r in daily_data if r.get("Date") and r.get("SignUps_Accepted", 0) > 0])
    upload_dates  = sorted([r["Date"] for r in daily_data if r.get("Date") and r.get("FirstUploads_Accepted", 0) > 0])
    paid_dates    = sorted([r["Date"] for r in daily_data if r.get("Date") and r.get("PaidSubscribers_Accepted", 0) > 0])

    return {
        "signups": {
            "start": signup_dates[0]  if signup_dates  else None,
            "end":   signup_dates[-1] if signup_dates  else None,
            "days":  len(signup_dates),
        },
        "uploads": {
            "start": upload_dates[0]  if upload_dates  else None,
            "end":   upload_dates[-1] if upload_dates  else None,
            "days":  len(upload_dates),
        },
        "paid": {
            "start": paid_dates[0]    if paid_dates    else None,
            "end":   paid_dates[-1]   if paid_dates    else None,
            "days":  len(paid_dates),
        },
    }


def get_common_period(daily_data: list = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (common_start, common_end) where ALL metrics have coverage.
    This is the only valid period for cross-metric conversion rate calculations.
    """
    if daily_data is None:
        try:
            daily_data = json.loads(Path("data_output/daily_counts.json").read_text())
        except Exception:
            return None, None

    coverage = get_metric_coverage(daily_data)

    starts = [v["start"] for v in coverage.values() if v["start"]]
    ends   = [v["end"]   for v in coverage.values() if v["end"]]

    if not starts or not ends:
        return None, None

    # Common start = latest start (all metrics must have started)
    # Common end   = earliest end (all metrics must still have data)
    common_start = max(starts)
    common_end   = min(ends)

    # Validate the period makes sense
    try:
        cs = datetime.fromisoformat(common_start)
        ce = datetime.fromisoformat(common_end)
        if cs > ce:
            log(f"WARNING: Common period invalid ({common_start} > {common_end})")
            return common_start, common_end
    except Exception:
        pass

    return common_start, common_end


def filter_to_common_period(daily_data: list) -> list:
    """Filter daily_counts records to common coverage period only."""
    common_start, common_end = get_common_period(daily_data)
    if not common_start or not common_end:
        return daily_data

    filtered = [r for r in daily_data if r.get("Date") and common_start <= r["Date"] <= common_end]
    log(f"Common period: {common_start} → {common_end} ({len(filtered)} of {len(daily_data)} records)")
    return filtered


def compute_alltime_metrics(use_common_period: bool = True) -> dict:
    """
    Compute All-Time metrics.
    If use_common_period=True: uses only the valid common coverage period.
    If use_common_period=False: uses entire database (MISLEADING for conversion rates).
    """
    try:
        daily = json.loads(Path("data_output/daily_counts.json").read_text())
    except Exception as e:
        log(f"Cannot load daily_counts: {e}")
        return {}

    coverage = get_metric_coverage(daily)
    common_start, common_end = get_common_period(daily)

    if use_common_period and common_start and common_end:
        data = filter_to_common_period(daily)
        period_label = f"{common_start} to {common_end}"
        period_type  = "common_period"
    else:
        data = daily
        period_label = f"{min(r['Date'] for r in daily if r.get('Date'))} to {max(r['Date'] for r in daily if r.get('Date'))}"
        period_type  = "full_database"

    signups = sum(r.get("SignUps_Accepted", 0) for r in data)
    uploads = sum(r.get("FirstUploads_Accepted", 0) for r in data)
    paid    = sum(r.get("PaidSubscribers_Accepted", 0) for r in data)

    s2u = (uploads / signups * 100) if signups > 0 else 0
    s2p = (paid    / signups * 100) if signups > 0 else 0
    u2p = (paid    / uploads * 100) if uploads > 0 else 0

    return {
        "period_type":      period_type,
        "period_label":     period_label,
        "common_start":     common_start,
        "common_end":       common_end,
        "signups":          signups,
        "uploads":          uploads,
        "paid":             paid,
        "signup_to_upload": round(s2u, 2),
        "signup_to_paid":   round(s2p, 2),
        "upload_to_paid":   round(u2p, 2),
        "full_db_signups":  sum(r.get("SignUps_Accepted", 0) for r in daily),
        "full_db_uploads":  sum(r.get("FirstUploads_Accepted", 0) for r in daily),
        "full_db_paid":     sum(r.get("PaidSubscribers_Accepted", 0) for r in daily),
        "coverage":         coverage,
        "note":             (
            "All-Time computed using common coverage period (when ALL metrics have data). "
            "Full database totals available in full_db_* fields."
        ) if use_common_period else "WARNING: Full database used — conversion rates may be misleading due to coverage gaps",
    }


def get_alltime_label() -> str:
    """Get the correct All-Time label for display."""
    common_start, common_end = get_common_period()
    if common_start and common_end:
        return f"Common Period ({common_start[:7]} to {common_end[:7]})"
    return "All Time"


if __name__ == "__main__":
    result = compute_alltime_metrics(use_common_period=True)
    print(json.dumps(result, indent=2))
