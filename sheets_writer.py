"""
sheets_writer.py — Eagle 3D Streaming Analytics Hub
====================================================
COMPATIBILITY SHIM — routes all "sheet writer" calls to MongoDB.
No Google Sheets. No gspread. MongoDB only.

Kept for backward compatibility with legacy code that imports:
    read_tab_data, write_tab_data, upsert_to_collection, get_connection_status,
    ensure_tabs_exist, write_run_summary
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from mongo_client import (
    delete_many,
    find_all,
    get_mongo_status,
    get_raw_db,
    insert_many,
    upsert_many,
    upsert_one,
)


# Nothing google here — kept purely as constants for compat
SHEETS_AVAILABLE = True   # Historically checked; MongoDB is always "available"
MASTER_SHEET_URL = ""     # Deprecated


def _tab_to_collection(tab_name: str) -> str:
    return "sheet_" + str(tab_name).lower().replace(" ", "_").replace("-", "_")


# ─────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────
def read_tab_data(tab_name: str) -> List[Dict[str, Any]]:
    rows = find_all(_tab_to_collection(tab_name))
    meta = ("_id", "_updated_at", "_inserted_at", "_migrated_at",
            "_sheet_key", "_tab_name")
    return [{k: v for k, v in r.items() if k not in meta} for r in rows]


def fetch_all(collection_name: str,
              filters: Optional[Dict[str, Any]] = None,
              limit: int = 0) -> List[Dict[str, Any]]:
    return find_all(collection_name, filters, limit=limit)


# ─────────────────────────────────────────────────────────────────
# WRITE
# ─────────────────────────────────────────────────────────────────
def write_tab_data(tab_name: str, rows: Iterable[Dict[str, Any]],
                   conflict_field: Optional[str] = None,
                   replace: bool = False) -> int:
    """
    Writes rows to sheet_<tab_name> collection in MongoDB.
    - If conflict_field is given: upsert by that field.
    - If replace=True and no conflict_field: drop collection + insert all.
    - Else: append.
    """
    coll = _tab_to_collection(tab_name)
    rows = list(rows or [])
    if not rows:
        return 0

    if conflict_field:
        return upsert_many(coll, rows, conflict_field)

    if replace:
        db = get_raw_db()
        if db is not None:
            db[coll].drop()

    return insert_many(coll, rows)


def write_tab(tab_name: str, rows: Iterable[Dict[str, Any]],
              conflict_field: Optional[str] = None) -> int:
    """Legacy alias."""
    return write_tab_data(tab_name, rows, conflict_field=conflict_field,
                          replace=(conflict_field is None))


def upsert_to_collection(collection: str, rows: Iterable[Dict[str, Any]],
                         on_conflict: str) -> int:
    """Direct MongoDB upsert (non-sheet). Used by pipeline."""
    return upsert_many(collection, list(rows or []), on_conflict)


# ─────────────────────────────────────────────────────────────────
# TAB LIFECYCLE (no-op for MongoDB - collections created on demand)
# ─────────────────────────────────────────────────────────────────
def ensure_tabs_exist(tab_names: Optional[List[str]] = None) -> List[str]:
    """
    MongoDB creates collections implicitly. Returns empty list (no-op).
    Kept for backward compatibility with old pipeline code.
    """
    return []


def clear_tab(tab_name: str) -> int:
    db = get_raw_db()
    if db is None:
        return 0
    try:
        return int(db[_tab_to_collection(tab_name)].delete_many({}).deleted_count or 0)
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────
# RUN SUMMARY (pipeline health)
# ─────────────────────────────────────────────────────────────────
def write_run_summary(summary: Dict[str, Any]) -> bool:
    """Write pipeline run summary to MongoDB pipeline_runs collection."""
    if not summary:
        return False
    doc = dict(summary)
    doc.setdefault("run_at", datetime.utcnow().isoformat())
    return upsert_one("pipeline_runs", doc, ["run_at"])


# ─────────────────────────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────────────────────────
def get_connection_status() -> Dict[str, Any]:
    return get_mongo_status()


# ─────────────────────────────────────────────────────────────────
# LEGACY NO-OPS (some old modules import these)
# ─────────────────────────────────────────────────────────────────
def _get_sb():
    """Returns MongoDB DB - legacy name."""
    return get_raw_db()


def _get_client():
    """Legacy Google Sheets client factory — returns (None, None)."""
    return None, None


if __name__ == "__main__":
    import json
    print(json.dumps(get_connection_status(), indent=2, default=str))
    print(f"sheet_daily_counts: {len(read_tab_data('Daily_Counts'))} rows")
    print(f"sheet_raw_free:     {len(read_tab_data('Raw_FREE'))} rows")
