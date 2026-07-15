from pathlib import Path
from datetime import datetime
import json
import sys

# ---------- patch engagement_alerts.py ----------
eng = Path("engagement_alerts.py")
if not eng.exists():
    print("❌ engagement_alerts.py not found")
    raise SystemExit(1)

eng_text = eng.read_text(encoding="utf-8", errors="ignore")
eng_backup = Path("backups") / f"engagement_alerts.py.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
eng_backup.write_text(eng_text, encoding="utf-8")

old_yt = '''        prev = _get_snapshot("youtube_channel")
        has_prev_channel = bool(prev)
        prev_subs = _as_int(prev.get("subscribers", prev.get("subscriber_count", 0)))
        prev_views = _as_int(prev.get("views", prev.get("view_count", 0)))
'''
new_yt = '''        prev = _get_snapshot("youtube_channel")
        prev_subs = _as_int(prev.get("subscribers", prev.get("subscriber_count", 0)))
        prev_views = _as_int(prev.get("views", prev.get("view_count", 0)))
        has_prev_channel = bool(prev) and (prev_subs > 0 or prev_views > 0)
'''

old_li = '''        prev = _get_snapshot("linkedin_channel")
        has_prev_channel = bool(prev)
        prev_followers = _as_int(prev.get("followers", 0))
'''
new_li = '''        prev = _get_snapshot("linkedin_channel")
        prev_followers = _as_int(prev.get("followers", 0))
        prev_reactions = _as_int(prev.get("reactions", 0))
        prev_comments = _as_int(prev.get("comments", 0))
        prev_reposts = _as_int(prev.get("reposts", 0))
        has_prev_channel = bool(prev) and any(x > 0 for x in (prev_followers, prev_reactions, prev_comments, prev_reposts))
'''

if old_yt in eng_text:
    eng_text = eng_text.replace(old_yt, new_yt, 1)
else:
    print("WARN: YouTube baseline block not found exactly; no YT change made")

if old_li in eng_text:
    eng_text = eng_text.replace(old_li, new_li, 1)
else:
    print("WARN: LinkedIn baseline block not found exactly; no LI change made")

eng.write_text(eng_text, encoding="utf-8")
print(f"OK: patched {eng} (backup -> {eng_backup})")

# ---------- write fixed reset script with sys.path ----------
reset_script = Path("scripts/reset_and_rerun_linkedin_export_sync.py")
reset_script.write_text(
'''from pathlib import Path
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
''',
encoding="utf-8"
)
print(f"OK: wrote {reset_script}")
