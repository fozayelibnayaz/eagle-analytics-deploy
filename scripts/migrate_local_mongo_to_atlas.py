import re
from pathlib import Path
from pymongo import MongoClient

text = Path(".streamlit/secrets.toml").read_text(encoding="utf-8", errors="ignore")
m = re.search(r'^MONGO_URI\s*=\s*"(.*)"\s*$', text, re.MULTILINE)
atlas_uri = m.group(1) if m else ""

if not atlas_uri:
    raise SystemExit("❌ Atlas MONGO_URI not found in .streamlit/secrets.toml")

local = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)
atlas = MongoClient(atlas_uri, serverSelectionTimeoutMS=10000)

src_db = local["eagle3d"]
dst_db = atlas["eagle3d"]

collections = src_db.list_collection_names()
print("Collections to migrate:", collections)

for name in collections:
    src_col = src_db[name]
    dst_col = dst_db[name]

    docs = list(src_col.find({}, {"_id": 0}))
    print(f"{name}: local docs = {len(docs)}")

    dst_col.delete_many({})
    if docs:
        dst_col.insert_many(docs)

    print(f"{name}: migrated = {len(docs)}")

print("✅ Local Mongo -> Atlas migration completed")
