from pathlib import Path
from datetime import datetime
from fnmatch import fnmatch

ROOT = Path.cwd()
BACKUP_DIR = ROOT / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

IGNORE_PARTS = {"venv", ".venv", ".git", "__pycache__", "node_modules"}

def candidates(patterns):
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in IGNORE_PARTS for part in p.parts):
            continue
        if any(fnmatch(p.name, pat) for pat in patterns):
            out.append(p)
    return sorted(set(out), key=lambda x: (len(x.parts), str(x)))

def pick(patterns, exclude_contains=()):
    for p in candidates(patterns):
        s = str(p)
        if any(x in s for x in exclude_contains):
            continue
        return p
    return None

alert_file = pick(["engagement_alerts.py", "*engagement*alerts*.py"], exclude_contains=("/scripts/",))
wrapper_file = pick(["run_engagement_alerts.sh", "*run*engagement*alerts*.sh"])

if alert_file is None:
    print("❌ Could not find engagement alerts Python file")
    raise SystemExit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")

def backup(path):
    bk = BACKUP_DIR / (path.name + "." + ts + ".bak")
    bk.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print("BACKUP:", bk)

backup(alert_file)
if wrapper_file and wrapper_file.exists():
    backup(wrapper_file)

alert_code = r'''from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional

from mongo_client import find_all, find_one, upsert_one

try:
    from urllib3.exceptions import NotOpenSSLWarning
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass


def _now_str() -> str:
    return datetime.now().strftime("%b %d, %Y %I:%M %p")


def _as_int(v: Any) -> int:
    try:
        if v is None or v == "":
            return 0
        return int(float(v))
    except Exception:
        return 0


def _safe_text(v: Any, limit: int = 72) -> str:
    s = str(v or "").strip().replace("\n", " ")
    return s[:limit] if s else "Untitled"


def _get_snapshot(key: str) -> Dict[str, Any]:
    doc = find_one("engagement_snapshots", {"key": key})
    return doc or {}


def _save_snapshot(key: str, data: Dict[str, Any]) -> bool:
    payload = dict(data or {})
    payload["key"] = key
    payload["saved_at"] = datetime.utcnow().isoformat()
    return upsert_one("engagement_snapshots", payload, ["key"])


def _send(msg: str) -> bool:
    try:
        from reporting_engine import send_telegram
        return bool(send_telegram(msg))
    except Exception as e:
        print(f"[engagement] send failed: {e}")
        return False


def _record(alerts: List[Dict[str, Any]], atype: str, delta: int, msg: str, extra: Optional[Dict[str, Any]] = None) -> None:
    sent = _send(msg)
    item = {"type": atype, "delta": int(delta), "sent": bool(sent)}
    if extra:
        item.update(extra)
    alerts.append(item)


def _pick_first_int(sources: List[Dict[str, Any]], keys: List[str]) -> int:
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in keys:
            if key in src and src.get(key) not in (None, ""):
                try:
                    return _as_int(src.get(key))
                except Exception:
                    pass
    return 0


def _normalize_linkedin_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for p in posts or []:
        urn = str(
            p.get("urn")
            or p.get("post_urn")
            or p.get("id")
            or p.get("url")
            or ""
        ).strip()
        if not urn:
            continue

        title = _safe_text(
            p.get("title")
            or p.get("text")
            or p.get("headline")
            or p.get("url")
            or "LinkedIn post",
            72,
        )

        out.append({
            "urn": urn,
            "title": title,
            "url": str(p.get("url") or "").strip(),
            "reactions": _as_int(p.get("reactions", 0)),
            "comments": _as_int(p.get("comments", 0)),
            "reposts": _as_int(p.get("reposts", 0)),
            "follows": _as_int(p.get("follows", 0)),
            "impressions": _as_int(p.get("impressions", 0)),
        })
    return out


def _linkedin_current_state() -> Dict[str, Any]:
    try:
        from linkedin_browser_scraper import scrape_all

        raw = scrape_all() or {}
        updates = raw.get("updates") or {}
        followers_block = raw.get("followers") or {}
        highlights = raw.get("highlights") or raw.get("overview") or raw.get("company") or {}

        posts = _normalize_linkedin_posts(updates.get("posts") or raw.get("posts") or [])
        state = {
            "source": "linkedin_browser_scraper",
            "followers": _pick_first_int(
                [highlights, followers_block, raw],
                ["total_followers", "followers", "follower_count", "followers_count", "totalFollowers"],
            ),
            "reactions": _pick_first_int([highlights, raw], ["reactions", "likes", "total_post_likes"]),
            "comments": _pick_first_int([highlights, raw], ["comments", "total_post_comments"]),
            "reposts": _pick_first_int([highlights, raw], ["reposts", "shares"]),
            "impressions": _pick_first_int([highlights, raw], ["impressions", "views", "total_views"]),
            "posts": posts,
        }

        if not state["reactions"] and posts:
            state["reactions"] = sum(p["reactions"] for p in posts)
        if not state["comments"] and posts:
            state["comments"] = sum(p["comments"] for p in posts)
        if not state["reposts"] and posts:
            state["reposts"] = sum(p["reposts"] for p in posts)
        if not state["impressions"] and posts:
            state["impressions"] = sum(p["impressions"] for p in posts)

        if state["followers"] or state["posts"] or state["reactions"] or state["comments"] or state["reposts"]:
            return state
    except Exception as e:
        print(f"[engagement] LinkedIn browser scrape unavailable: {e}")

    try:
        from linkedin_connector import scrape_public_metrics

        raw = scrape_public_metrics() or {}
        posts = _normalize_linkedin_posts(raw.get("posts") or [])
        state = {
            "source": "linkedin_connector_public",
            "followers": _pick_first_int([raw], ["total_followers", "followers", "follower_count", "followers_count"]),
            "reactions": _pick_first_int([raw], ["reactions", "likes", "total_post_likes"]),
            "comments": _pick_first_int([raw], ["comments", "total_post_comments"]),
            "reposts": _pick_first_int([raw], ["reposts", "shares"]),
            "impressions": _pick_first_int([raw], ["impressions", "views", "total_views"]),
            "posts": posts,
        }

        if not state["reactions"] and posts:
            state["reactions"] = sum(p["reactions"] for p in posts)
        if not state["comments"] and posts:
            state["comments"] = sum(p["comments"] for p in posts)
        if not state["reposts"] and posts:
            state["reposts"] = sum(p["reposts"] for p in posts)
        if not state["impressions"] and posts:
            state["impressions"] = sum(p["impressions"] for p in posts)

        if state["followers"] or state["posts"] or state["reactions"] or state["comments"] or state["reposts"]:
            return state
    except Exception as e:
        print(f"[engagement] LinkedIn public scrape unavailable: {e}")

    hl_rows = find_all("linkedin_highlights_daily", sort=[("snapshot_date", -1)], limit=1)
    hl = hl_rows[0] if hl_rows else {}
    posts = _normalize_linkedin_posts(find_all("linkedin_posts", sort=[("last_updated", -1)], limit=100))

    return {
        "source": "mongo_fallback",
        "followers": _as_int(hl.get("total_followers", 0)),
        "reactions": _as_int(hl.get("reactions", 0)) or sum(p["reactions"] for p in posts),
        "comments": _as_int(hl.get("comments", 0)) or sum(p["comments"] for p in posts),
        "reposts": _as_int(hl.get("reposts", 0)) or sum(p["reposts"] for p in posts),
        "impressions": _as_int(hl.get("impressions", 0)) or sum(p["impressions"] for p in posts),
        "posts": posts,
    }


def check_youtube_engagement() -> List[Dict[str, Any]]:
    alerts = []

    try:
        from youtube_connector import get_channel_info, get_channel_videos
    except ImportError:
        print("[engagement] youtube_connector import failed")
        return alerts

    try:
        ch = get_channel_info() or {}
        current_subs = _as_int(ch.get("subscribers", 0))
        current_views = _as_int(ch.get("views", ch.get("view_count", 0)))
        channel_title = _safe_text(ch.get("title", "YouTube Channel"), 80)

        prev = _get_snapshot("youtube_channel")
        has_prev_channel = bool(prev)
        prev_subs = _as_int(prev.get("subscribers", prev.get("subscriber_count", 0)))
        prev_views = _as_int(prev.get("views", prev.get("view_count", 0)))

        if has_prev_channel and current_subs > prev_subs:
            delta = current_subs - prev_subs
            msg = (
                f"🎉 *YouTube: New Subscribers!*\\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                f"Channel: {channel_title}\\n\\n"
                f"📋 Details\\n"
                f"  • New subs:   +{delta}\\n"
                f"  • Total subs: {current_subs:,}\\n"
                f"  • Previous:   {prev_subs:,}\\n\\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "yt_new_subs", delta, msg)

        elif has_prev_channel and current_subs < prev_subs:
            delta = prev_subs - current_subs
            msg = (
                f"📉 *YouTube: Lost Subscribers*\\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                f"Channel: {channel_title}\\n\\n"
                f"📋 Details\\n"
                f"  • Lost subs:  -{delta}\\n"
                f"  • Total now:  {current_subs:,}\\n"
                f"  • Previous:   {prev_subs:,}\\n\\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "yt_lost_subs", delta, msg)

        if has_prev_channel and current_views > prev_views:
            view_delta = current_views - prev_views
            if view_delta >= 50:
                msg = (
                    f"🚀 *YouTube: View Surge*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Channel: {channel_title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New views:  +{view_delta:,}\\n"
                    f"  • Total:      {current_views:,}\\n"
                    f"  • Previous:   {prev_views:,}\\n\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_view_surge", view_delta, msg)

        _save_snapshot("youtube_channel", {
            "subscribers": current_subs,
            "views": current_views,
            "title": channel_title,
        })

        current_videos = get_channel_videos(max_videos=50) or []
        snap = _get_snapshot("youtube_videos_map")
        prev_vids_map = snap.get("videos", {}) if isinstance(snap, dict) else {}
        new_vids_map = {}

        for v in current_videos:
            vid = str(v.get("video_id") or v.get("youtube_id") or "").strip()
            if not vid:
                continue

            title = _safe_text(v.get("title", "YouTube video"), 60)
            cur_likes = _as_int(v.get("likes", 0))
            cur_comments = _as_int(v.get("comments", 0))
            cur_views = _as_int(v.get("views", 0))
            cur_shares = _as_int(v.get("shares", 0))
            cur_dislikes = _as_int(v.get("dislikes", 0))

            prev_v = prev_vids_map.get(vid, {})
            had_prev = vid in prev_vids_map

            prev_likes = _as_int(prev_v.get("likes", 0))
            prev_comments = _as_int(prev_v.get("comments", 0))
            prev_shares = _as_int(prev_v.get("shares", 0))
            prev_dislikes = _as_int(prev_v.get("dislikes", 0))

            new_vids_map[vid] = {
                "title": title,
                "likes": cur_likes,
                "comments": cur_comments,
                "views": cur_views,
                "shares": cur_shares,
                "dislikes": cur_dislikes,
            }

            if not had_prev:
                continue

            if cur_comments > prev_comments:
                delta = cur_comments - prev_comments
                msg = (
                    f"💬 *YouTube: New Comment(s)*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Video: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New comments: +{delta}\\n"
                    f"  • Total:        {cur_comments}\\n"
                    f"  • Views:        {cur_views:,}\\n"
                    f"  • Link:         youtube.com/watch?v={vid}\\n\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_comments", delta, msg, {"video_id": vid})

            elif cur_comments < prev_comments:
                delta = prev_comments - cur_comments
                msg = (
                    f"🗑️ *YouTube: Comment Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Video: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Removed comments: -{delta}\\n"
                    f"  • Total now:        {cur_comments}\\n"
                    f"  • Link:             youtube.com/watch?v={vid}\\n\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_comments_removed", delta, msg, {"video_id": vid})

            if cur_likes > prev_likes:
                delta = cur_likes - prev_likes
                msg = (
                    f"👍 *YouTube: New Like(s)*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Video: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New likes: +{delta}\\n"
                    f"  • Total:     {cur_likes}\\n"
                    f"  • Views:     {cur_views:,}\\n"
                    f"  • Link:      youtube.com/watch?v={vid}\\n\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_likes", delta, msg, {"video_id": vid})

            elif cur_likes < prev_likes:
                delta = prev_likes - cur_likes
                msg = (
                    f"👎 *YouTube: Like Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Video: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Likes removed: -{delta}\\n"
                    f"  • Total now:     {cur_likes}\\n"
                    f"  • Link:          youtube.com/watch?v={vid}\\n\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_likes_removed", delta, msg, {"video_id": vid})

            supports_shares = ("shares" in prev_v) or ("shares" in v)
            if supports_shares and cur_shares > prev_shares:
                delta = cur_shares - prev_shares
                msg = (
                    f"🔁 *YouTube: New Share(s)*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Video: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New shares: +{delta}\\n"
                    f"  • Total:      {cur_shares}\\n"
                    f"  • Link:       youtube.com/watch?v={vid}\\n\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_shares", delta, msg, {"video_id": vid})

            supports_dislikes = ("dislikes" in prev_v) or ("dislikes" in v)
            if supports_dislikes and cur_dislikes > prev_dislikes:
                delta = cur_dislikes - prev_dislikes
                msg = (
                    f"⚠️ *YouTube: New Dislike(s)*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Video: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New dislikes: +{delta}\\n"
                    f"  • Total:        {cur_dislikes}\\n"
                    f"  • Link:         youtube.com/watch?v={vid}\\n\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_dislikes", delta, msg, {"video_id": vid})

        _save_snapshot("youtube_videos_map", {"videos": new_vids_map})

    except Exception as e:
        print(f"[engagement] YouTube check failed: {e}")

    return alerts


def check_linkedin_engagement() -> List[Dict[str, Any]]:
    alerts = []

    try:
        current = _linkedin_current_state()
        posts = current.get("posts", []) or []

        cur_followers = _as_int(current.get("followers", 0))
        cur_reactions = _as_int(current.get("reactions", 0))
        cur_comments = _as_int(current.get("comments", 0))
        cur_reposts = _as_int(current.get("reposts", 0))
        cur_impressions = _as_int(current.get("impressions", 0))

        prev = _get_snapshot("linkedin_channel")
        has_prev_channel = bool(prev)
        prev_followers = _as_int(prev.get("followers", 0))

        if has_prev_channel and cur_followers > prev_followers:
            delta = cur_followers - prev_followers
            msg = (
                f"�� *LinkedIn: New Followers!*\\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                f"Eagle 3D Streaming page\\n\\n"
                f"📋 Details\\n"
                f"  • New followers: +{delta}\\n"
                f"  • Total:         {cur_followers:,}\\n"
                f"  • Source:        {current.get('source', '?')}\\n\\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "li_new_followers", delta, msg)

        elif has_prev_channel and cur_followers < prev_followers:
            delta = prev_followers - cur_followers
            msg = (
                f"📉 *LinkedIn: Lost Followers*\\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                f"Eagle 3D Streaming page\\n\\n"
                f"📋 Details\\n"
                f"  • Lost followers: -{delta}\\n"
                f"  • Total now:      {cur_followers:,}\\n"
                f"  • Source:         {current.get('source', '?')}\\n\\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "li_lost_followers", delta, msg)

        _save_snapshot("linkedin_channel", {
            "followers": cur_followers,
            "reactions": cur_reactions,
            "comments": cur_comments,
            "reposts": cur_reposts,
            "impressions": cur_impressions,
            "source": current.get("source", ""),
        })

        snap = _get_snapshot("linkedin_posts_map")
        prev_posts_map = snap.get("posts", {}) if isinstance(snap, dict) else {}
        new_posts_map = {}

        for p in posts:
            urn = str(p.get("urn") or "").strip()
            if not urn:
                continue

            title = _safe_text(p.get("title", "LinkedIn post"), 60)
            url = str(p.get("url") or "").strip()

            cur_post_reactions = _as_int(p.get("reactions", 0))
            cur_post_comments = _as_int(p.get("comments", 0))
            cur_post_reposts = _as_int(p.get("reposts", 0))
            cur_post_follows = _as_int(p.get("follows", 0))
            cur_post_impressions = _as_int(p.get("impressions", 0))

            prev_p = prev_posts_map.get(urn, {})
            had_prev = urn in prev_posts_map

            prev_post_reactions = _as_int(prev_p.get("reactions", 0))
            prev_post_comments = _as_int(prev_p.get("comments", 0))
            prev_post_reposts = _as_int(prev_p.get("reposts", 0))
            prev_post_follows = _as_int(prev_p.get("follows", 0))

            new_posts_map[urn] = {
                "title": title,
                "url": url,
                "reactions": cur_post_reactions,
                "comments": cur_post_comments,
                "reposts": cur_post_reposts,
                "follows": cur_post_follows,
                "impressions": cur_post_impressions,
            }

            if not had_prev:
                continue

            if cur_post_reactions > prev_post_reactions:
                delta = cur_post_reactions - prev_post_reactions
                msg = (
                    f"❤️ *LinkedIn: New Reactions*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New reactions: +{delta}\\n"
                    f"  • Total:         {cur_post_reactions}\\n"
                    f"  • Impressions:   {cur_post_impressions:,}\\n"
                    f"{('  • Link:          ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_reactions", delta, msg, {"post_urn": urn})

            elif cur_post_reactions < prev_post_reactions:
                delta = prev_post_reactions - cur_post_reactions
                msg = (
                    f"💔 *LinkedIn: Reaction Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Reactions removed: -{delta}\\n"
                    f"  • Total now:         {cur_post_reactions}\\n"
                    f"{('  • Link:              ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_reactions_removed", delta, msg, {"post_urn": urn})

            if cur_post_comments > prev_post_comments:
                delta = cur_post_comments - prev_post_comments
                msg = (
                    f"💬 *LinkedIn: New Comments*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New comments: +{delta}\\n"
                    f"  • Total:        {cur_post_comments}\\n"
                    f"{('  • Link:         ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_comments", delta, msg, {"post_urn": urn})

            elif cur_post_comments < prev_post_comments:
                delta = prev_post_comments - cur_post_comments
                msg = (
                    f"🗑️ *LinkedIn: Comment Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Comments removed: -{delta}\\n"
                    f"  • Total now:        {cur_post_comments}\\n"
                    f"{('  • Link:             ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_comments_removed", delta, msg, {"post_urn": urn})

            if cur_post_reposts > prev_post_reposts:
                delta = cur_post_reposts - prev_post_reposts
                msg = (
                    f"🔁 *LinkedIn: New Reposts*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New reposts: +{delta}\\n"
                    f"  • Total:       {cur_post_reposts}\\n"
                    f"{('  • Link:        ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_reposts", delta, msg, {"post_urn": urn})

            elif cur_post_reposts < prev_post_reposts:
                delta = prev_post_reposts - cur_post_reposts
                msg = (
                    f"↩️ *LinkedIn: Repost Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"�� Details\\n"
                    f"  • Reposts removed: -{delta}\\n"
                    f"  • Total now:       {cur_post_reposts}\\n"
                    f"{('  • Link:            ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_reposts_removed", delta, msg, {"post_urn": urn})

            if cur_post_follows > prev_post_follows:
                delta = cur_post_follows - prev_post_follows
                msg = (
                    f"👥 *LinkedIn: Post-driven New Follows*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New follows: +{delta}\\n"
                    f"  • Total:       {cur_post_follows}\\n"
                    f"{('  • Link:        ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_follows", delta, msg, {"post_urn": urn})

            elif cur_post_follows < prev_post_follows:
                delta = prev_post_follows - cur_post_follows
                msg = (
                    f"📉 *LinkedIn: Post-driven Follows Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Follows lost: -{delta}\\n"
                    f"  • Total now:    {cur_post_follows}\\n"
                    f"{('  • Link:         ' + url + '\\n') if url else ''}\\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "li_post_follows_removed", delta, msg, {"post_urn": urn})

        _save_snapshot("linkedin_posts_map", {"posts": new_posts_map})

    except Exception as e:
        print(f"[engagement] LinkedIn check failed: {e}")

    return alerts


def send_combined_summary(all_alerts: List[Dict[str, Any]]) -> bool:
    if len(all_alerts) < 2:
        return False

    from collections import Counter

    types = Counter(a["type"] for a in all_alerts)
    lines = [
        "📊 *Engagement Summary (latest check)*",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "*Changes detected:*",
    ]

    icons = {
        "yt_new_subs": "🎉 YouTube subscribers +",
        "yt_lost_subs": "📉 YouTube subscribers -",
        "yt_view_surge": "🚀 YouTube views +",
        "yt_new_comments": "💬 YouTube comments +",
        "yt_comments_removed": "🗑️ YouTube comments -",
        "yt_new_likes": "👍 YouTube likes +",
        "yt_likes_removed": "👎 YouTube likes -",
        "yt_new_shares": "🔁 YouTube shares +",
        "yt_new_dislikes": "⚠️ YouTube dislikes +",
        "li_new_followers": "🎉 LinkedIn followers +",
        "li_lost_followers": "📉 LinkedIn followers -",
        "li_post_new_reactions": "❤️ LinkedIn reactions +",
        "li_post_reactions_removed": "💔 LinkedIn reactions -",
        "li_post_new_comments": "💬 LinkedIn comments +",
        "li_post_comments_removed": "🗑️ LinkedIn comments -",
        "li_post_new_reposts": "🔁 LinkedIn reposts +",
        "li_post_reposts_removed": "↩️ LinkedIn reposts -",
        "li_post_new_follows": "👥 LinkedIn follows +",
        "li_post_follows_removed": "📉 LinkedIn follows -",
    }

    for atype, count in types.most_common():
        label = icons.get(atype, atype)
        total_delta = sum(_as_int(a.get("delta", 0)) for a in all_alerts if a["type"] == atype)
        lines.append(f"  {label}{total_delta} ({count} event{'s' if count != 1 else ''})")

    lines.append("")
    lines.append(f"⏰ {_now_str()}")

    return _send("\\n".join(lines))


def run_all_engagement_checks() -> Dict[str, int]:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Engagement check starting...")

    yt = check_youtube_engagement()
    li = check_linkedin_engagement()

    all_alerts = yt + li
    print(f"  YouTube alerts:  {len(yt)}")
    print(f"  LinkedIn alerts: {len(li)}")

    combined = 0
    if len(all_alerts) >= 2 and send_combined_summary(all_alerts):
        combined = 1
        print(f"  Combined summary: sent ({len(all_alerts)} events batched)")

    return {
        "youtube_alerts": len(yt),
        "linkedin_alerts": len(li),
        "combined_summary_sent": combined,
    }


if __name__ == "__main__":
    result = run_all_engagement_checks()
    import json
    print()
    print(json.dumps(result, indent=2))
'''

wrapper_code = r'''#!/bin/bash
set -euo pipefail

ROOT="$HOME/eagle3d-kpi-automation"
LOGDIR="$ROOT/logs"
LOCKDIR="$ROOT/.engagement_alerts.lock"

mkdir -p "$LOGDIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] SKIP: engagement alerts already running" >> "$LOGDIR/engagement_alerts.out.log"
  exit 0
fi

cleanup() {
  rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT

cd "$ROOT"
source venv/bin/activate

SCRIPT="$(find "$ROOT" -maxdepth 2 -type f \( -name 'engagement_alerts.py' -o -name '*engagement*alerts*.py' \) | grep -v '/scripts/' | sort | head -n 1)"
if [ -z "${SCRIPT:-}" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: engagement alerts Python script not found" >> "$LOGDIR/engagement_alerts.err.log"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START $SCRIPT" >> "$LOGDIR/engagement_alerts.out.log"
python3 "$SCRIPT" >> "$LOGDIR/engagement_alerts.out.log" 2>> "$LOGDIR/engagement_alerts.err.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] END" >> "$LOGDIR/engagement_alerts.out.log"
'''

alert_file.write_text(alert_code, encoding="utf-8")
print("OK: patched", alert_file)

if wrapper_file:
    wrapper_file.write_text(wrapper_code, encoding="utf-8")
    print("OK: patched", wrapper_file)
