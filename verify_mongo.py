#!/usr/bin/env python3
"""
verify_mongo.py — Eagle 3D Streaming
Verifies MongoDB local connection + reports collection stats.

Run:  python3 verify_mongo.py
"""

import sys
from mongo_client import get_mongo_status, get_raw_db


def main():
    print("=" * 60)
    print("Eagle 3D Streaming — MongoDB Health Check")
    print("=" * 60)

    status = get_mongo_status()
    print(f"URI:        {status.get('uri')}")
    print(f"Database:   {status.get('db')}")
    print(f"Connected:  {status.get('connected')}")
    print(f"Message:    {status.get('message')}")

    if not status.get("connected"):
        print("\n❌ MongoDB is NOT reachable.")
        print("Fix:")
        print("  1. brew services list | grep mongodb")
        print("  2. brew services start mongodb-community@7.0")
        print("  3. Verify MONGO_URI in .streamlit/secrets.toml")
        return 1

    db = get_raw_db()
    if db is None:
        print("\n❌ Could not access database.")
        return 1

    print("\n" + "=" * 60)
    print("COLLECTIONS")
    print("=" * 60)

    cols = sorted(db.list_collection_names())
    total_docs = 0
    for c in cols:
        n = db[c].count_documents({})
        total_docs += n
        print(f"  {c:40s} {n:>10,} docs")

    print("=" * 60)
    print(f"  TOTAL: {len(cols)} collections, {total_docs:,} documents")
    print("=" * 60)

    # Quick sanity checks
    print("\nSANITY CHECKS")
    print("-" * 60)
    checks = [
        ("daily_kpis",   "date"),
        ("signups",      "email_normalized"),
        ("uploads",      "email_normalized"),
        ("payments",     "email_normalized"),
        ("access_control", "email"),
    ]
    for col, key_field in checks:
        if col not in cols:
            print(f"  ⚠️  {col:30s} — collection missing")
            continue
        n = db[col].count_documents({})
        sample = db[col].find_one({}, {"_id": 0})
        has_key = bool(sample and key_field in (sample or {}))
        marker = "✅" if (n > 0 and has_key) else "⚠️ "
        print(f"  {marker} {col:30s} {n:>7,} docs, {key_field}={'yes' if has_key else 'MISSING'}")

    print("\n✅ MongoDB verification complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
