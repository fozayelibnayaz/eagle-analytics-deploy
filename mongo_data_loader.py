"""
mongo_data_loader.py — Eagle 3D Streaming Analytics Hub
=========================================================
100% MongoDB data-access layer for the Streamlit app.
100% MongoDB only. No Sheets. No other database.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from mongo_client import (
    count_accepted,
    count_docs,
    find_all,
    find_one,
    get_mongo_status,
    get_raw_db,
    insert_many,
    upsert_many,
    upsert_one,
)


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
_META_COLS = ("_id", "_migrated_at", "_updated_at", "_inserted_at",
              "_sheet_key", "_tab_name")


def _clean_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    drop = [c for c in _META_COLS if c in df.columns]
    if drop:
        df = df.drop(columns=drop, errors="ignore")
    return df


def _clean_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    return [
        {k: v for k, v in r.items() if k not in _META_COLS}
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────
# CORE KPI LOADERS
# ─────────────────────────────────────────────────────────────────
def load_daily_kpis() -> pd.DataFrame:
    rows = find_all("daily_kpis", sort=[("date", 1)])
    return _clean_df(rows)


def load_signups(final_status: Optional[str] = None) -> pd.DataFrame:
    filters: Dict[str, Any] = {}
    if final_status:
        filters["final_status"] = final_status
    rows = find_all("signups", filters)
    return _clean_df(rows)


def load_uploads(final_status: Optional[str] = None) -> pd.DataFrame:
    filters: Dict[str, Any] = {}
    if final_status:
        filters["final_status"] = final_status
    rows = find_all("uploads", filters)
    return _clean_df(rows)


def load_payments(final_status: Optional[str] = None) -> pd.DataFrame:
    filters: Dict[str, Any] = {}
    if final_status:
        filters["final_status"] = final_status
    rows = find_all("payments", filters)
    return _clean_df(rows)


# ─────────────────────────────────────────────────────────────────
# KPI COUNTS (period-aware)
# ─────────────────────────────────────────────────────────────────
def get_kpi_counts(
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    since_upload_start: Optional[str] = None,
) -> Dict[str, Any]:
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()

    result: Dict[str, Any] = {
        "signups_today":    count_accepted("signups",  "signup_date",        date_gte=today),
        "uploads_today":    count_accepted("uploads",  "upload_date",        date_gte=today),
        "payments_today":   count_accepted("payments", "first_payment_date", date_gte=today),
        "signups_month":    count_accepted("signups",  "signup_date",        date_gte=month_start),
        "uploads_month":    count_accepted("uploads",  "upload_date",        date_gte=month_start),
        "payments_month":   count_accepted("payments", "first_payment_date", date_gte=month_start),
        "signups_total":    count_accepted("signups",  "signup_date"),
        "uploads_total":    count_accepted("uploads",  "upload_date"),
        "payments_total":   count_accepted("payments", "first_payment_date"),
        "active_overrides": count_docs("manual_overrides", {"is_active": True}),
        "source": "mongodb",
    }

    if since_upload_start:
        result["signups_since_start"]  = count_accepted("signups",  "signup_date",        date_gte=since_upload_start)
        result["uploads_since_start"]  = count_accepted("uploads",  "upload_date",        date_gte=since_upload_start)
        result["payments_since_start"] = count_accepted("payments", "first_payment_date", date_gte=since_upload_start)

    if period_start and period_end:
        result["signups_period"]  = count_accepted("signups",  "signup_date",        date_gte=period_start, date_lte=period_end)
        result["uploads_period"]  = count_accepted("uploads",  "upload_date",        date_gte=period_start, date_lte=period_end)
        result["payments_period"] = count_accepted("payments", "first_payment_date", date_gte=period_start, date_lte=period_end)

    return result


def get_earliest_upload_date() -> Optional[str]:
    rows = find_all(
        "uploads",
        filters={"final_status": "ACCEPTED"},
        projection={"upload_date": 1},
        sort=[("upload_date", 1)],
        limit=1,
    )
    if rows and rows[0].get("upload_date"):
        return str(rows[0]["upload_date"])[:10]
    return None


# ─────────────────────────────────────────────────────────────────
# LEGACY "TAB" ACCESS (maps to sheet_* MongoDB collections)
# Kept for backward compatibility with old app code.
# ─────────────────────────────────────────────────────────────────
def _tab_to_collection(tab_name: str) -> str:
    return "sheet_" + str(tab_name).lower().replace(" ", "_").replace("-", "_")


def load_tab(tab_name: str) -> List[Dict[str, Any]]:
    return _clean_rows(find_all(_tab_to_collection(tab_name)))


def load_tab_df(tab_name: str) -> pd.DataFrame:
    return _clean_df(find_all(_tab_to_collection(tab_name)))


def read_tab_data(tab_name: str) -> List[Dict[str, Any]]:
    """Legacy alias — apps and pipeline call this."""
    return load_tab(tab_name)


def load_master_sheet_tab(tab_name: str) -> List[Dict[str, Any]]:
    """Legacy alias."""
    return load_tab(tab_name)


# ─────────────────────────────────────────────────────────────────
# ML TRAINING TABS
# ─────────────────────────────────────────────────────────────────
def load_ml_training_data(tab_name: str) -> List[Dict[str, Any]]:
    coll = "ml_training_" + str(tab_name).lower().replace(" ", "_").replace("-", "_")
    return _clean_rows(find_all(coll))


def load_all_ml_training_tabs() -> Dict[str, List[Dict[str, Any]]]:
    db = get_raw_db()
    if db is None:
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for c in db.list_collection_names():
        if c.startswith("ml_training_"):
            tab = c.replace("ml_training_", "")
            out[tab] = _clean_rows(find_all(c))
    return out


# ─────────────────────────────────────────────────────────────────
# LINKEDIN LOADERS
# ─────────────────────────────────────────────────────────────────
def load_linkedin_posts(limit: int = 0) -> List[Dict[str, Any]]:
    return find_all("linkedin_posts", sort=[("published_at", -1)], limit=limit)


def load_linkedin_followers_daily() -> List[Dict[str, Any]]:
    return find_all("linkedin_followers_daily", sort=[("snapshot_date", 1)])


def load_linkedin_posts_daily(
    post_urn: Optional[str] = None,
    date_gte: Optional[str] = None,
    date_lte: Optional[str] = None,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {}
    if post_urn:
        filters["post_urn"] = post_urn
    if date_gte or date_lte:
        rng: Dict[str, Any] = {}
        if date_gte:
            rng["$gte"] = str(date_gte)
        if date_lte:
            rng["$lte"] = str(date_lte)
        filters["snapshot_date"] = rng
    return find_all("linkedin_posts_daily", filters, sort=[("snapshot_date", 1)])


def load_linkedin_highlights(
    date_gte: Optional[str] = None,
    date_lte: Optional[str] = None,
    limit: int = 1,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {}
    if date_gte or date_lte:
        rng: Dict[str, Any] = {}
        if date_gte:
            rng["$gte"] = str(date_gte)
        if date_lte:
            rng["$lte"] = str(date_lte)
        filters["snapshot_date"] = rng
    return find_all(
        "linkedin_highlights_daily",
        filters,
        sort=[("snapshot_date", -1)],
        limit=limit,
    )


def load_linkedin_visitors_daily() -> List[Dict[str, Any]]:
    return find_all("linkedin_visitors_daily", sort=[("snapshot_date", 1)])


def load_linkedin_competitors_daily() -> List[Dict[str, Any]]:
    return find_all("linkedin_competitors_daily", sort=[("snapshot_date", 1)])


# ─────────────────────────────────────────────────────────────────
# YOUTUBE LOADERS
# ─────────────────────────────────────────────────────────────────
def load_youtube_channel() -> Optional[Dict[str, Any]]:
    return find_one("youtube_channel", {})


def load_youtube_videos(limit: int = 0) -> List[Dict[str, Any]]:
    return find_all("youtube_videos", sort=[("published_at", -1)], limit=limit)


# ─────────────────────────────────────────────────────────────────
# CUSTOMER SUCCESS LOADERS
# ─────────────────────────────────────────────────────────────────
def load_customer_success_master(limit: int = 0) -> List[Dict[str, Any]]:
    return find_all("customer_success_master", limit=limit)


def load_customer_success_enriched(limit: int = 0) -> List[Dict[str, Any]]:
    return find_all("customer_success_enriched", limit=limit)


# ─────────────────────────────────────────────────────────────────
# ACCESS LOG
# ─────────────────────────────────────────────────────────────────
def load_access_log(limit: int = 100) -> List[Dict[str, Any]]:
    return find_all("access_log", sort=[("timestamp", -1)], limit=limit)


# ─────────────────────────────────────────────────────────────────
# SYNCS (used by pipeline)
# ─────────────────────────────────────────────────────────────────
def sync_daily_kpis(rows: List[Dict[str, Any]]) -> int:
    return upsert_many("daily_kpis", rows, "date")


def sync_signups(rows: List[Dict[str, Any]]) -> int:
    return upsert_many("signups", rows, "email_normalized")


def sync_uploads(rows: List[Dict[str, Any]]) -> int:
    return upsert_many("uploads", rows, "email_normalized")


def sync_payments(rows: List[Dict[str, Any]]) -> int:
    return upsert_many("payments", rows, "email_normalized")


# ─────────────────────────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────────────────────────
def get_connection_status() -> Dict[str, Any]:
    return get_mongo_status()


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print(json.dumps(get_connection_status(), indent=2, default=str))
    print(f"Daily KPIs:   {len(load_daily_kpis())} rows")
    print(f"Signups:      {len(load_signups())} rows")
    print(f"Uploads:      {len(load_uploads())} rows")
    print(f"Payments:     {len(load_payments())} rows")
    print(f"LinkedIn posts:  {len(load_linkedin_posts())} rows")
    print(f"YouTube videos:  {len(load_youtube_videos())} rows")
    print(f"CS master:       {len(load_customer_success_master())} rows")
    print(f"ML training tabs:{len(load_all_ml_training_tabs())} tabs")
