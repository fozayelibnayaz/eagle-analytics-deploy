"""
first_upload_logic.py — Eagle 3D Streaming Analytics Hub
==========================================================
Idempotent first-upload tracking. Ensures each email counts only
ONCE as a "first upload" even if the scraper re-imports the row.

MongoDB collections used:
  - upload_registry:  {email_normalized, first_upload_date, source, added_at}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from mongo_client import find_all, find_one, upsert_many, upsert_one


REGISTRY_COL = "upload_registry"


def _norm(email: str) -> str:
    return str(email or "").strip().lower()


def is_first_upload(email: str) -> bool:
    """True if this email has NEVER been recorded as a first upload before."""
    email = _norm(email)
    if not email:
        return False
    return find_one(REGISTRY_COL, {"email_normalized": email}) is None


def record_first_upload(email: str, upload_date: str,
                        source: str = "kpi_scraper") -> bool:
    """Record a first upload if not already recorded."""
    email = _norm(email)
    if not email:
        return False

    if find_one(REGISTRY_COL, {"email_normalized": email}) is not None:
        return False  # already recorded

    doc = {
        "email_normalized":  email,
        "first_upload_date": str(upload_date or "")[:10],
        "source":            str(source or ""),
        "added_at":          datetime.utcnow().isoformat(),
    }
    return upsert_one(REGISTRY_COL, doc, ["email_normalized"])


def bulk_register(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Registers many rows at once. Each row must have:
        - email (or email_normalized)
        - upload_date (or first_upload_date)

    Returns counts: {"total": N, "new": N, "duplicates": N}
    """
    if not rows:
        return {"total": 0, "new": 0, "duplicates": 0}

    existing = set()
    for r in find_all(REGISTRY_COL, projection={"email_normalized": 1, "_id": 0}):
        e = r.get("email_normalized")
        if e:
            existing.add(str(e).lower())

    to_insert: List[Dict[str, Any]] = []
    now = datetime.utcnow().isoformat()
    dupes = 0
    for row in rows:
        email = _norm(row.get("email_normalized") or row.get("email") or "")
        if not email:
            continue
        if email in existing:
            dupes += 1
            continue
        upload_date = str(row.get("first_upload_date")
                          or row.get("upload_date")
                          or "")[:10]
        to_insert.append({
            "email_normalized":  email,
            "first_upload_date": upload_date,
            "source":            str(row.get("source") or "kpi_scraper"),
            "added_at":          now,
        })
        existing.add(email)

    inserted = upsert_many(REGISTRY_COL, to_insert, "email_normalized") if to_insert else 0

    return {
        "total":      len(rows),
        "new":        int(inserted),
        "duplicates": int(dupes),
    }


def get_registry_size() -> int:
    from mongo_client import count_docs
    return count_docs(REGISTRY_COL)


def get_earliest_upload_date() -> Optional[str]:
    rows = find_all(
        REGISTRY_COL,
        projection={"first_upload_date": 1},
        sort=[("first_upload_date", 1)],
        limit=1,
    )
    if rows and rows[0].get("first_upload_date"):
        return str(rows[0]["first_upload_date"])[:10]
    return None


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Registry size:         {get_registry_size():,}")
    print(f"Earliest upload date:  {get_earliest_upload_date()}")
