from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List

from mongo_client import find_all, upsert_many, upsert_one, count_docs

NOW_ISO = datetime.utcnow().isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [LI-transform] {msg}", flush=True)


def as_int(v: Any) -> int:
    if v is None:
        return 0
    s = str(v).strip().replace(",", "")
    m = re.sub(r"[^0-9.\-]", "", s)
    if m in ("", "-", ".", "-."):
        return 0
    try:
        return int(float(m))
    except Exception:
        return 0


def as_float(v: Any) -> float:
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", "")
    m = re.sub(r"[^0-9.\-]", "", s)
    if m in ("", "-", ".", "-."):
        return 0.0
    try:
        return float(m)
    except Exception:
        return 0.0


def parse_date_any(v: Any, default_iso: str) -> str:
    s = str(v or "").strip()
    if not s:
        return default_iso

    fmts = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%Y/%m/%d",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass

    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", s)
    if m:
        return m.group(1)

    return default_iso


def extract_url(text: Any) -> str:
    s = str(text or "").strip()
    m = re.search(r"https?://[^\s)\]]+", s)
    return m.group(0) if m else s


def make_post_urn(title: str, url: str, published_at: str) -> str:
    seed = f"{title}|{url}|{published_at}"
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]
    return f"li::post::{h}"


def latest_imported_files() -> Dict[str, Dict[str, Any]]:
    docs = find_all(
        "linkedin_export_files",
        {"status": "imported"},
        sort=[("imported_at", -1)],
        limit=200,
    )
    by_dataset: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        key = str(d.get("dataset_key") or "").strip()
        if key and key not in by_dataset:
            by_dataset[key] = d
    return by_dataset


def raw_rows_for_file(file_name: str) -> List[Dict[str, Any]]:
    return find_all(
        "linkedin_export_rows",
        {"file_name": file_name},
        sort=[("row_index", 1)],
        limit=100000,
    )


def group_rows_by_sheet(file_name: str) -> Dict[str, List[Dict[str, Any]]]:
    docs = raw_rows_for_file(file_name)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for doc in docs:
        sheet = str(doc.get("sheet_name") or "").strip()
        row = doc.get("row_data") or {}
        out.setdefault(sheet, []).append(row)
    return out


def row_values(row: Dict[str, Any]) -> List[Any]:
    return list(row.values())


def parse_embedded_header_sheet(rows: List[Dict[str, Any]], header_first_value: str) -> List[Dict[str, Any]]:
    header = None
    result = []

    for row in rows:
        vals = row_values(row)
        vals_str = [str(v).strip() if v is not None else "" for v in vals]

        if not any(vals_str):
            continue

        if header is None:
            if header_first_value in vals_str:
                header = [x if x else f"col_{i}" for i, x in enumerate(vals_str)]
            continue

        obj = {}
        for i, h in enumerate(header):
            obj[h] = vals[i] if i < len(vals) else None

        # skip duplicate header rows
        if str(obj.get(header[0], "")).strip() == header_first_value:
            continue

        result.append(obj)

    return result


def normalize_updates(file_doc: Dict[str, Any]) -> Dict[str, int]:
    file_name = file_doc["file_name"]
    default_date = str(file_doc.get("imported_at", NOW_ISO))[:10]
    sheets = group_rows_by_sheet(file_name)

    all_posts_rows = parse_embedded_header_sheet(sheets.get("All posts", []), "Post title")
    metrics_rows = parse_embedded_header_sheet(sheets.get("Metrics", []), "Date")

    latest_rows = []
    daily_rows = []
    metric_daily_rows = []

    for row in all_posts_rows:
        title = str(row.get("Post title") or "").strip()
        url = extract_url(row.get("Post link"))
        created = str(row.get("Created date") or "").strip()

        if not title and not url:
            continue

        snapshot_date = parse_date_any(created, default_date)
        urn = make_post_urn(title, url, created or snapshot_date)

        base = {
            "urn": urn,
            "post_urn": urn,
            "title": title[:1000],
            "url": url,
            "post_type": str(row.get("Post type") or "").strip(),
            "posted_by": str(row.get("Posted by") or "").strip(),
            "published_at": created,
            "snapshot_date": snapshot_date,
            "audience": str(row.get("Audience") or "").strip(),
            "impressions": as_int(row.get("Impressions")),
            "views": as_int(row.get("Views")),
            "offsite_views": as_int(row.get("Offsite Views")),
            "clicks": as_int(row.get("Clicks")),
            "ctr": as_float(row.get("Click through rate (CTR)")),
            "reactions": as_int(row.get("Likes")),
            "comments": as_int(row.get("Comments")),
            "reposts": as_int(row.get("Reposts")),
            "follows": as_int(row.get("Follows")),
            "engagement_rate": as_float(row.get("Engagement rate")),
            "content_type": str(row.get("Content Type") or "").strip(),
            "source_file": file_name,
            "last_updated": NOW_ISO,
        }

        latest_rows.append(dict(base))
        daily_rows.append(dict(base))

    for row in metrics_rows:
        snapshot_date = parse_date_any(row.get("Date"), default_date)
        metric_daily_rows.append({
            "snapshot_date": snapshot_date,
            "impressions_total": as_int(row.get("Impressions (total)")),
            "unique_impressions_organic": as_int(row.get("Unique impressions (organic)")),
            "clicks_total": as_int(row.get("Clicks (total)")),
            "reactions_total": as_int(row.get("Reactions (total)")),
            "comments_total": as_int(row.get("Comments (total)")),
            "reposts_total": as_int(row.get("Reposts (total)")),
            "engagement_rate_total": as_float(row.get("Engagement rate (total)")),
            "source_file": file_name,
            "last_updated": NOW_ISO,
        })

    if latest_rows:
        upsert_many("linkedin_posts", latest_rows, "urn")
    if daily_rows:
        upsert_many("linkedin_posts_daily", daily_rows, "post_urn,snapshot_date")
    if metric_daily_rows:
        upsert_many("linkedin_updates_metrics_daily", metric_daily_rows, "snapshot_date")

    return {
        "posts_latest": len(latest_rows),
        "posts_daily": len(daily_rows),
        "updates_metrics_daily": len(metric_daily_rows),
    }


def normalize_followers(file_doc: Dict[str, Any]) -> Dict[str, int]:
    file_name = file_doc["file_name"]
    default_date = str(file_doc.get("imported_at", NOW_ISO))[:10]
    sheets = group_rows_by_sheet(file_name)

    summary_total = 0

    # demographic sheets contain current total follower count slices
    for sheet_name, rows in sheets.items():
        if sheet_name == "New followers":
            continue
        for row in rows:
            if "Total followers" in row:
                summary_total = max(summary_total, as_int(row.get("Total followers")))

    grouped: Dict[str, Dict[str, Any]] = {}

    # historical daily rows
    for row in sheets.get("New followers", []):
        d = parse_date_any(row.get("Date"), default_date)
        grouped[d] = {
            "snapshot_date": d,
            "sponsored_followers": as_int(row.get("Sponsored followers")),
            "organic_followers": as_int(row.get("Organic followers")),
            "auto_invited_followers": as_int(row.get("Auto-invited followers")),
            "new_followers": as_int(row.get("Total followers")),
            "total_followers": 0,
            "source_file": file_name,
            "last_updated": NOW_ISO,
        }

    # current snapshot row
    if summary_total > 0:
        cur = grouped.get(default_date, {
            "snapshot_date": default_date,
            "sponsored_followers": 0,
            "organic_followers": 0,
            "auto_invited_followers": 0,
            "new_followers": 0,
            "total_followers": 0,
            "source_file": file_name,
            "last_updated": NOW_ISO,
        })
        cur["total_followers"] = max(cur["total_followers"], summary_total)
        grouped[default_date] = cur

    out = list(grouped.values())
    if out:
        upsert_many("linkedin_followers_daily", out, "snapshot_date")

    return {"followers_daily": len(out)}


def normalize_visitors(file_doc: Dict[str, Any]) -> Dict[str, int]:
    file_name = file_doc["file_name"]
    default_date = str(file_doc.get("imported_at", NOW_ISO))[:10]
    sheets = group_rows_by_sheet(file_name)

    grouped: Dict[str, Dict[str, Any]] = {}

    for row in sheets.get("Visitor metrics", []):
        d = parse_date_any(row.get("Date"), default_date)
        grouped[d] = {
            "snapshot_date": d,
            "page_views": as_int(row.get("Total page views (total)")),
            "unique_visitors": as_int(row.get("Total unique visitors (total)")),
            "overview_page_views": as_int(row.get("Overview page views (total)")),
            "overview_unique_visitors": as_int(row.get("Overview unique visitors (total)")),
            "jobs_page_views": as_int(row.get("Jobs page views (total)")),
            "jobs_unique_visitors": as_int(row.get("Jobs unique visitors (total)")),
            "life_page_views": as_int(row.get("Life page views (total)")),
            "life_unique_visitors": as_int(row.get("Life unique visitors (total)")),
            "source_file": file_name,
            "last_updated": NOW_ISO,
        }

    out = list(grouped.values())
    if out:
        upsert_many("linkedin_visitors_daily", out, "snapshot_date")

    return {"visitors_daily": len(out)}


def normalize_competitors(file_doc: Dict[str, Any]) -> Dict[str, int]:
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


def rebuild_highlights() -> Dict[str, int]:
    followers = find_all("linkedin_followers_daily", sort=[("snapshot_date", -1)], limit=1)
    visitors = find_all("linkedin_visitors_daily", sort=[("snapshot_date", -1)], limit=1)
    updates_metrics = find_all("linkedin_updates_metrics_daily", sort=[("snapshot_date", -1)], limit=1)

    latest_date = str(datetime.utcnow().date())

    f_doc = followers[0] if followers else {}
    v_doc = visitors[0] if visitors else {}
    u_doc = updates_metrics[0] if updates_metrics else {}

    doc = {
        "snapshot_date": latest_date,
        "total_followers": as_int(f_doc.get("total_followers", 0)),
        "page_views": as_int(v_doc.get("page_views", 0)),
        "unique_visitors": as_int(v_doc.get("unique_visitors", 0)),
        "impressions": as_int(u_doc.get("impressions_total", 0)),
        "reactions": as_int(u_doc.get("reactions_total", 0)),
        "comments": as_int(u_doc.get("comments_total", 0)),
        "reposts": as_int(u_doc.get("reposts_total", 0)),
        "post_count": count_docs("linkedin_posts"),
        "last_updated": NOW_ISO,
        "source": "linkedin_transform_exports",
    }

    ok = upsert_one("linkedin_highlights_daily", doc, ["snapshot_date"])
    return {"highlights_daily": 1 if ok else 0}


def main():
    latest = latest_imported_files()
    if not latest:
        print("No imported LinkedIn export files found.")
        return

    summary: Dict[str, int] = {}

    if "updates" in latest:
        summary.update(normalize_updates(latest["updates"]))
    if "followers" in latest:
        summary.update(normalize_followers(latest["followers"]))
    if "visitors" in latest:
        summary.update(normalize_visitors(latest["visitors"]))
    if "competitors" in latest:
        summary.update(normalize_competitors(latest["competitors"]))

    summary.update(rebuild_highlights())

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
