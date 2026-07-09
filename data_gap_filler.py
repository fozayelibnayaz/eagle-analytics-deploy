"""
data_gap_filler.py — Eagle 3D Streaming Analytics Hub
=======================================================
Fills daily_kpis gaps by carrying forward last known values with 0 counts.
Prevents chart holes when the pipeline was skipped for a day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from mongo_client import find_all, upsert_many


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def find_gaps() -> List[str]:
    """Returns list of missing dates in daily_kpis between min and today."""
    rows = find_all("daily_kpis", projection={"date": 1, "_id": 0})
    if not rows:
        return []

    dates = set()
    for r in rows:
        d = str(r.get("date", ""))[:10]
        if d and len(d) == 10:
            dates.add(d)

    if not dates:
        return []

    try:
        min_d = min(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
    except Exception:
        return []
    max_d = date.today()

    gaps = []
    for d in _daterange(min_d, max_d):
        if d.isoformat() not in dates:
            gaps.append(d.isoformat())
    return gaps


def fill_gaps() -> Dict[str, Any]:
    """Insert zero-count rows for any missing dates."""
    gaps = find_gaps()
    initial = len(gaps)
    if not gaps:
        return {"initial_gaps": 0, "final_gaps": 0, "filled": 0}

    rows = [
        {
            "date":            d,
            "signups":         0,
            "uploads":         0,
            "payments":        0,
            "_source":         "gap_filler",
            "_filled_at":      datetime.utcnow().isoformat(),
        }
        for d in gaps
    ]
    filled = upsert_many("daily_kpis", rows, "date")

    final_gaps = find_gaps()
    return {
        "initial_gaps": initial,
        "final_gaps":   len(final_gaps),
        "filled":       filled,
    }


def run() -> Dict[str, Any]:
    """Compat alias used by daily_pipeline."""
    return fill_gaps()


if __name__ == "__main__":
    import json
    result = fill_gaps()
    print(json.dumps(result, indent=2))
