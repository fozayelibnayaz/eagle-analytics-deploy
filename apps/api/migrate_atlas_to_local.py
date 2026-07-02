"""
migrate_atlas_to_local.py
Copy all data from MongoDB Atlas → Local MongoDB
"""
import os
import sys
import certifi
from pymongo import MongoClient
from datetime import datetime

print("\n" + "="*60)
print("ATLAS → LOCAL MONGODB MIGRATION")
print("="*60)

ATLAS_URI = os.environ.get("MONGO_URI", "").strip()
LOCAL_URI  = "mongodb://localhost:27017"
DB_NAME    = "eagle3d"

if not ATLAS_URI or "localhost" in ATLAS_URI:
    print("ERROR: ATLAS_URI not found in environment.")
    print("Run: source migration_env.sh first")
    sys.exit(1)

print(f"Source (Atlas): {ATLAS_URI[:50]}...")
print(f"Target (Local): {LOCAL_URI}")
print(f"Database:       {DB_NAME}")

# Connect Atlas
print("\nConnecting to Atlas...")
atlas_client = None
try:
    atlas_client = MongoClient(
        ATLAS_URI,
        serverSelectionTimeoutMS=15000,
        tls=True,
        tlsCAFile=certifi.where(),
    )
    atlas_client.admin.command("ping")
    atlas_db = atlas_client[DB_NAME]
    print("Atlas connected")
except Exception as e:
    print(f"certifi attempt failed: {str(e)[:80]}")
    try:
        atlas_client = MongoClient(
            ATLAS_URI,
            serverSelectionTimeoutMS=15000,
            tls=True,
            tlsAllowInvalidCertificates=True,
        )
        atlas_client.admin.command("ping")
        atlas_db = atlas_client[DB_NAME]
        print("Atlas connected (tlsAllowInvalidCertificates)")
    except Exception as e2:
        print(f"Atlas connection failed: {e2}")
        sys.exit(1)

# Connect Local
print("Connecting to local MongoDB...")
try:
    local_client = MongoClient(LOCAL_URI, serverSelectionTimeoutMS=5000)
    local_client.admin.command("ping")
    local_db = local_client[DB_NAME]
    print("Local MongoDB connected")
except Exception as e:
    print(f"Local MongoDB failed: {e}")
    print("Fix: brew services start mongodb-community@7.0")
    sys.exit(1)

# Copy all collections
collections = sorted(atlas_db.list_collection_names())
print(f"\nCollections to copy: {len(collections)}")
print("="*60)

total = 0
for col_name in collections:
    try:
        docs = list(atlas_db[col_name].find({}))
        if not docs:
            print(f"  [EMPTY]  {col_name}")
            continue
        local_db[col_name].drop()
        local_db[col_name].insert_many(docs, ordered=False)
        total += len(docs)
        print(f"  [OK]     {col_name:<45} {len(docs):>8,} docs")
    except Exception as e:
        print(f"  [ERR]    {col_name}: {e}")

print("="*60)
print(f"\nTotal documents copied to local: {total:,}")

local_cols = local_db.list_collection_names()
local_total = sum(local_db[c].count_documents({}) for c in local_cols)
print(f"Local MongoDB verified: {local_total:,} docs in {len(local_cols)} collections")
print("\nATLAS_TO_LOCAL_MIGRATION_COMPLETE")
