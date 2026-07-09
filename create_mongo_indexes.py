"""
create_mongo_indexes.py — Eagle 3D Streaming Analytics Hub
============================================================
Creates performance indexes on MongoDB collections.
Idempotent: safe to run multiple times.

Run:
    python3 create_mongo_indexes.py
"""

from __future__ import annotations

from mongo_client import get_raw_db


INDEXES = {
    "signups": [
        [("email_normalized", 1)],
        [("final_status", 1)],
        [("signup_date", 1)],
        [("final_status", 1), ("signup_date", 1)],
    ],
    "uploads": [
        [("email_normalized", 1)],
        [("final_status", 1)],
        [("upload_date", 1)],
        [("final_status", 1), ("upload_date", 1)],
    ],
    "payments": [
        [("email_normalized", 1)],
        [("final_status", 1)],
        [("first_payment_date", 1)],
        [("final_status", 1), ("first_payment_date", 1)],
    ],
    "daily_kpis": [
        [("date", 1)],
    ],
    "monthly_counts": [
        [("month", 1)],
    ],
    "upload_registry": [
        [("email_normalized", 1)],
        [("first_upload_date", 1)],
    ],
    "access_control": [
        [("email", 1)],
        [("is_active", 1)],
    ],
    "access_log": [
        [("timestamp", -1)],
        [("email", 1)],
    ],
    "linkedin_posts": [
        [("urn", 1)],
        [("published_at", -1)],
    ],
    "linkedin_posts_daily": [
        [("post_urn", 1), ("snapshot_date", 1)],
        [("snapshot_date", 1)],
    ],
    "linkedin_followers_daily": [
        [("snapshot_date", 1)],
    ],
    "linkedin_visitors_daily": [
        [("snapshot_date", 1)],
    ],
    "linkedin_highlights_daily": [
        [("snapshot_date", -1)],
    ],
    "linkedin_competitors_daily": [
        [("snapshot_date", 1), ("name", 1)],
    ],
    "linkedin_search_keywords": [
        [("snapshot_date", 1), ("keyword", 1)],
    ],
    "linkedin_newsletter_articles": [
        [("urn", 1)],
    ],
    "youtube_channel": [
        [("channel_id", 1)],
    ],
    "youtube_videos": [
        [("video_id", 1)],
        [("published_at", -1)],
    ],
    "customer_success_master": [
        [("_sheet_tab", 1)],
    ],
    "customer_success_enriched": [
        [("email_normalized", 1)],
    ],
    "pipeline_runs": [
        [("run_at", -1)],
    ],
    "domain_cache": [
        [("domain", 1)],
    ],
    "analytics_cache": [
        [("key", 1)],
    ],
    "manual_overrides": [
        [("email_normalized", 1)],
        [("is_active", 1)],
    ],
}


def main() -> None:
    db = get_raw_db()
    if db is None:
        print("❌ MongoDB not reachable")
        return

    existing_cols = set(db.list_collection_names())
    total_created = 0
    total_existing = 0

    for coll, indexes in INDEXES.items():
        col = db[coll]
        for keys in indexes:
            name = "_".join(f"{k}_{d}" for k, d in keys)
            try:
                existing = {ix["name"] for ix in col.list_indexes()}
                if name in existing:
                    total_existing += 1
                    continue
                col.create_index(keys, name=name, background=True)
                marker = "🆕" if coll in existing_cols else "🆕📂"
                print(f"  {marker} {coll:40s} {name}")
                total_created += 1
            except Exception as e:
                print(f"  ❌ {coll:40s} {name}: {e}")

    print()
    print("=" * 60)
    print(f"Indexes created:  {total_created}")
    print(f"Indexes existed:  {total_existing}")
    print(f"Total collections indexed: {len(INDEXES)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
