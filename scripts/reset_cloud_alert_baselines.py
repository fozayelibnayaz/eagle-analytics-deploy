from pathlib import Path
from datetime import datetime
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import find_all, find_one, upsert_one

def as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

# LinkedIn baseline from transformed Mongo collections
h_rows = find_all("linkedin_highlights_daily", sort=[("snapshot_date", -1)], limit=1)
h = h_rows[0] if h_rows else {}

posts = find_all("linkedin_posts", sort=[("last_updated", -1)], limit=5000)
posts_map = {}
for p in posts:
    urn = str(p.get("urn") or p.get("post_urn") or "").strip()
    if not urn:
        continue
    posts_map[urn] = {
        "title": str(p.get("title") or "")[:60],
        "url": str(p.get("url") or ""),
        "reactions": as_int(p.get("reactions", 0)),
        "comments": as_int(p.get("comments", 0)),
        "reposts": as_int(p.get("reposts", 0)),
        "follows": as_int(p.get("follows", 0)),
        "impressions": as_int(p.get("impressions", 0)),
    }

upsert_one("engagement_snapshots", {
    "key": "linkedin_channel",
    "followers": as_int(h.get("total_followers", 0)),
    "page_views": as_int(h.get("page_views", 0)),
    "unique_visitors": as_int(h.get("unique_visitors", 0)),
    "last_sync": h.get("last_updated", ""),
    "saved_at": datetime.utcnow().isoformat(),
}, ["key"])

upsert_one("engagement_snapshots", {
    "key": "linkedin_posts_map",
    "posts": posts_map,
    "last_sync": h.get("last_updated", ""),
    "saved_at": datetime.utcnow().isoformat(),
}, ["key"])

# YouTube baseline from current collections if available
ych = find_one("youtube_channel", {}) or {}
yvids = find_all("youtube_videos", limit=5000)

upsert_one("engagement_snapshots", {
    "key": "youtube_channel",
    "subscribers": as_int(ych.get("subscribers", 0)),
    "views": as_int(ych.get("views", ych.get("view_count", 0))),
    "title": str(ych.get("title") or "YouTube Channel"),
    "saved_at": datetime.utcnow().isoformat(),
}, ["key"])

y_map = {}
for v in yvids:
    vid = str(v.get("video_id") or v.get("youtube_id") or "").strip()
    if not vid:
        continue
    y_map[vid] = {
        "title": str(v.get("title") or "")[:60],
        "likes": as_int(v.get("likes", 0)),
        "comments": as_int(v.get("comments", 0)),
        "views": as_int(v.get("views", 0)),
        "shares": as_int(v.get("shares", 0)),
        "dislikes": as_int(v.get("dislikes", 0)),
    }

upsert_one("engagement_snapshots", {
    "key": "youtube_videos_map",
    "videos": y_map,
    "saved_at": datetime.utcnow().isoformat(),
}, ["key"])

print("✅ cloud alert baselines reset to current Mongo values")
