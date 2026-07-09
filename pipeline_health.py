"""
pipeline_health.py — Eagle 3D Streaming Analytics Hub
======================================================
Tracks pipeline run health. Writes to MongoDB pipeline_runs collection
and also to data_output/pipeline_health.json for offline display.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from mongo_client import find_all, find_one, upsert_one

_HEALTH_FILE = Path("data_output/pipeline_health.json")


def record_run(summary: Dict[str, Any]) -> bool:
    if not summary:
        return False
    doc = dict(summary)
    doc.setdefault("run_at", datetime.utcnow().isoformat())

    # MongoDB
    ok = upsert_one("pipeline_runs", doc, ["run_at"])

    # Also save to JSON for backward compat
    try:
        _HEALTH_FILE.parent.mkdir(exist_ok=True)
        _HEALTH_FILE.write_text(json.dumps(doc, default=str, indent=2))
    except Exception:
        pass

    return ok


def get_last_run() -> Optional[Dict[str, Any]]:
    # Try MongoDB first
    rows = find_all("pipeline_runs", sort=[("run_at", -1)], limit=1)
    if rows:
        return rows[0]

    # Fallback to JSON file
    if _HEALTH_FILE.exists():
        try:
            return json.loads(_HEALTH_FILE.read_text())
        except Exception:
            pass
    return None


def get_recent_runs(limit: int = 10) -> List[Dict[str, Any]]:
    return find_all("pipeline_runs", sort=[("run_at", -1)], limit=int(limit or 10))


def is_healthy() -> bool:
    last = get_last_run()
    if not last:
        return False
    total = int(last.get("total_stages", 7))
    passed = int(last.get("stages_passed", 0))
    return passed >= total


if __name__ == "__main__":
    last = get_last_run()
    print(json.dumps(last, indent=2, default=str) if last else "No runs recorded")
