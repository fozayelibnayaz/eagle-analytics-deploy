from pathlib import Path
from datetime import datetime

p = Path("linkedin_transform_exports.py")
if not p.exists():
    print("❌ linkedin_transform_exports.py not found")
    raise SystemExit(1)

text = p.read_text(encoding="utf-8", errors="ignore")
backup = Path("backups") / f"linkedin_transform_exports.py.competitors_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

old = '''def normalize_competitors(file_doc: Dict[str, Any]) -> Dict[str, int]:
    file_name = file_doc["file_name"]
    default_date = str(file_doc.get("imported_at", NOW_ISO))[:10]
    docs = raw_rows_for_file(file_name)

    out = []
    for doc in docs:
        row = doc.get("row_data") or {}
        if not row:
            continue

        keys = list(row.keys())
        if not keys:
            continue

        competitor_name = None
        for k in keys:
            if "competitor" in k.lower() or "company" in k.lower() or "name" in k.lower():
                competitor_name = row.get(k)
                if competitor_name:
                    break

        if not competitor_name:
            continue

        out.append({
            "snapshot_date": default_date,
            "competitor_name": str(competitor_name).strip()[:300],
            "followers": max(as_int(v) for k, v in row.items() if "follower" in str(k).lower()) if row else 0,
            "posts": max(as_int(v) for k, v in row.items() if "post" in str(k).lower() or "update" in str(k).lower()) if row else 0,
            "engagement": max(as_float(v) for k, v in row.items() if "engagement" in str(k).lower()) if row else 0.0,
            "source_file": file_name,
            "row_data": row,
            "last_updated": NOW_ISO,
        })

    if out:
        upsert_many("linkedin_competitors_daily", out, "snapshot_date,competitor_name")

    return {"competitors_daily": len(out)}
'''

new = '''def normalize_competitors(file_doc: Dict[str, Any]) -> Dict[str, int]:
    file_name = file_doc["file_name"]
    default_date = str(file_doc.get("imported_at", NOW_ISO))[:10]
    docs = raw_rows_for_file(file_name)

    def max_int_match(row: Dict[str, Any], needles: List[str]) -> int:
        vals = []
        for k, v in row.items():
            kk = str(k).lower()
            if any(n in kk for n in needles):
                vals.append(as_int(v))
        return max(vals) if vals else 0

    def max_float_match(row: Dict[str, Any], needles: List[str]) -> float:
        vals = []
        for k, v in row.items():
            kk = str(k).lower()
            if any(n in kk for n in needles):
                vals.append(as_float(v))
        return max(vals) if vals else 0.0

    out = []
    for doc in docs:
        row = doc.get("row_data") or {}
        if not row:
            continue

        keys = list(row.keys())
        if not keys:
            continue

        competitor_name = None
        for k in keys:
            lk = k.lower()
            if "competitor" in lk or "company" in lk or "organization" in lk or "name" in lk:
                competitor_name = row.get(k)
                if competitor_name:
                    break

        if not competitor_name:
            continue

        out.append({
            "snapshot_date": default_date,
            "competitor_name": str(competitor_name).strip()[:300],
            "followers": max_int_match(row, ["follower", "followers"]),
            "posts": max_int_match(row, ["post", "posts", "update", "updates"]),
            "engagement": max_float_match(row, ["engagement", "engagement rate"]),
            "source_file": file_name,
            "row_data": row,
            "last_updated": NOW_ISO,
        })

    if out:
        upsert_many("linkedin_competitors_daily", out, "snapshot_date,competitor_name")

    return {"competitors_daily": len(out)}
'''

if old not in text:
    print("❌ Could not find normalize_competitors() block exactly")
    raise SystemExit(1)

text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

print(f"OK: backup written -> {backup}")
print(f"OK: patched -> {p}")
