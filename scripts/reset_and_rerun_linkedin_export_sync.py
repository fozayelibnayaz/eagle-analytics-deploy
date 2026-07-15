from pathlib import Path
from datetime import datetime
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import find_all, get_raw_db

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = ROOT / "backups" / f"linkedin_export_reset_{ts}"
backup_dir.mkdir(parents=True, exist_ok=True)

collections_to_backup_and_clear = [
    "linkedin_export_files",
    "linkedin_export_rows",
    "linkedin_followers_daily",
    "linkedin_visitors_daily",
    "linkedin_competitors_daily",
    "linkedin_highlights_daily",
    "linkedin_posts_daily",
]

db = get_raw_db()
if db is None:
    print("❌ MongoDB not available")
    raise SystemExit(1)

print(f"Backup dir: {backup_dir}")

for col in collections_to_backup_and_clear:
    try:
        docs = find_all(col, {})
        out = backup_dir / f"{col}.json"
        out.write_text(json.dumps(docs, indent=2, default=str), encoding="utf-8")
        deleted = db[col].delete_many({}).deleted_count
        print(f"{col}: backed up {len(docs)} docs -> {out} | cleared {deleted}")
    except Exception as e:
        print(f"{col}: ERROR -> {e}")

print("✅ Mongo backup + clear completed")
