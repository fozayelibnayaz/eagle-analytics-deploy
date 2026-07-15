from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any, Dict, List

from mongo_client import find_all, find_one, upsert_one

try:
    from urllib3.exceptions import NotOpenSSLWarning
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass


LINKEDIN_STALE_MINUTES = 2160  # 36 hours for export-based LinkedIn sync


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


def _link_line(url: str) -> str:
    url = str(url or "").strip()
    return f"  • Link:         {url}\n" if url else ""


def _parse_dt(value: Any):
    s = str(value or "").strip()
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        pass
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except Exception:
        return None


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


def _record(alerts: List[Dict[str, Any]], atype: str, delta: int, msg: str, extra: Dict[str, Any] = None) -> None:
    sent = _send(msg)
    item = {"type": atype, "delta": int(delta), "sent": bool(sent)}
    if extra:
        item.update(extra)
    alerts.append(item)


def _latest_linkedin_state() -> Dict[str, Any]:
    highlights = find_all("linkedin_highlights_daily", sort=[("snapshot_date", -1)], limit=1)
    hl = highlights[0] if highlights else {}

    posts_raw = find_all("linkedin_posts", sort=[("last_updated", -1)], limit=200)
    posts = []

    for p in posts_raw:
        urn = str(
            p.get("urn")
            or p.get("post_urn")
            or p.get("id")
            or p.get("url")
            or ""
        ).strip()
        if not urn:
            continue

        posts.append({
            "urn": urn,
            "title": _safe_text(
                p.get("title")
                or p.get("text")
                or p.get("headline")
                or p.get("url")
                or "LinkedIn post",
                72,
            ),
            "url": str(p.get("url") or "").strip(),
            "reactions": _as_int(p.get("reactions", 0)),
            "comments": _as_int(p.get("comments", 0)),
            "reposts": _as_int(p.get("reposts", 0)),
            "follows": _as_int(p.get("follows", 0)),
            "impressions": _as_int(p.get("impressions", 0)),
            "last_updated": str(p.get("last_updated") or ""),
        })

    last_ts = None
    if posts:
        last_ts = _parse_dt(posts[0].get("last_updated"))
    if last_ts is None:
        last_ts = _parse_dt(hl.get("last_updated") or hl.get("saved_at") or hl.get("snapshot_date"))

    stale = False
    stale_minutes = None
    if last_ts is not None:
        stale_minutes = int((datetime.utcnow() - last_ts.replace(tzinfo=None)).total_seconds() // 60)
        stale = stale_minutes > LINKEDIN_STALE_MINUTES

    return {
        "source": "mongo_only",
        "followers": _as_int(hl.get("total_followers", 0)),
        "reactions": _as_int(hl.get("reactions", 0)) or sum(p["reactions"] for p in posts),
        "comments": _as_int(hl.get("comments", 0)) or sum(p["comments"] for p in posts),
        "reposts": _as_int(hl.get("reposts", 0)) or sum(p["reposts"] for p in posts),
        "impressions": _as_int(hl.get("impressions", 0)) or sum(p["impressions"] for p in posts),
        "posts": posts,
        "stale": stale,
        "stale_minutes": stale_minutes,
        "last_timestamp": last_ts.isoformat() if last_ts else "",
    }


def check_youtube_engagement() -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []

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
        prev_subs = _as_int(prev.get("subscribers", prev.get("subscriber_count", 0)))
        prev_views = _as_int(prev.get("views", prev.get("view_count", 0)))
        has_prev_channel = bool(prev) and (prev_subs > 0 or prev_views > 0)

        if has_prev_channel and current_subs > prev_subs:
            delta = current_subs - prev_subs
            msg = (
                f"🎉 *YouTube: New Subscribers!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Channel: {channel_title}\n\n"
                f"📋 Details\n"
                f"  • New subs:   +{delta}\n"
                f"  • Total subs: {current_subs:,}\n"
                f"  • Previous:   {prev_subs:,}\n\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "yt_new_subs", delta, msg)

        elif has_prev_channel and current_subs < prev_subs:
            delta = prev_subs - current_subs
            msg = (
                f"📉 *YouTube: Lost Subscribers*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Channel: {channel_title}\n\n"
                f"📋 Details\n"
                f"  • Lost subs:  -{delta}\n"
                f"  • Total now:  {current_subs:,}\n"
                f"  • Previous:   {prev_subs:,}\n\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "yt_lost_subs", delta, msg)

        if has_prev_channel and current_views > prev_views:
            view_delta = current_views - prev_views
            if view_delta >= 50:
                msg = (
                    f"🚀 *YouTube: View Surge*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Channel: {channel_title}\n\n"
                    f"📋 Details\n"
                    f"  • New views:  +{view_delta:,}\n"
                    f"  • Total:      {current_views:,}\n"
                    f"  • Previous:   {prev_views:,}\n\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_view_surge", view_delta, msg)

        _save_snapshot("youtube_channel", {
            "subscribers": current_subs,
            "views": current_views,
            "title": channel_title,
        })

        snap = _get_snapshot("youtube_videos_map")
        prev_vids_map = snap.get("videos", {}) if isinstance(snap, dict) else {}
        new_vids_map: Dict[str, Dict[str, Any]] = {}

        current_videos = get_channel_videos(max_videos=50) or []
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
                    f"💬 *YouTube: New Comment(s)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Video: {title}\n\n"
                    f"📋 Details\n"
                    f"  • New comments: +{delta}\n"
                    f"  • Total:        {cur_comments}\n"
                    f"  • Views:        {cur_views:,}\n"
                    f"  • Link:         youtube.com/watch?v={vid}\n\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_comments", delta, msg, {"video_id": vid})

            elif cur_comments < prev_comments:
                delta = prev_comments - cur_comments
                msg = (
                    f"🗑️ *YouTube: Comment Count Decreased*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Video: {title}\n\n"
                    f"📋 Details\n"
                    f"  • Removed comments: -{delta}\n"
                    f"  • Total now:        {cur_comments}\n"
                    f"  • Link:             youtube.com/watch?v={vid}\n\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_comments_removed", delta, msg, {"video_id": vid})

            if cur_likes > prev_likes:
                delta = cur_likes - prev_likes
                msg = (
                    f"👍 *YouTube: New Like(s)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Video: {title}\n\n"
                    f"📋 Details\n"
                    f"  • New likes: +{delta}\n"
                    f"  • Total:     {cur_likes}\n"
                    f"  • Views:     {cur_views:,}\n"
                    f"  • Link:      youtube.com/watch?v={vid}\n\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_likes", delta, msg, {"video_id": vid})

            elif cur_likes < prev_likes:
                delta = prev_likes - cur_likes
                msg = (
                    f"👎 *YouTube: Like Count Decreased*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Video: {title}\n\n"
                    f"📋 Details\n"
                    f"  • Likes removed: -{delta}\n"
                    f"  • Total now:     {cur_likes}\n"
                    f"  • Link:          youtube.com/watch?v={vid}\n\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_likes_removed", delta, msg, {"video_id": vid})

            supports_shares = ("shares" in prev_v) or ("shares" in v)
            if supports_shares and cur_shares > prev_shares:
                delta = cur_shares - prev_shares
                msg = (
                    f"🔁 *YouTube: New Share(s)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Video: {title}\n\n"
                    f"📋 Details\n"
                    f"  • New shares: +{delta}\n"
                    f"  • Total:      {cur_shares}\n"
                    f"  • Link:       youtube.com/watch?v={vid}\n\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_shares", delta, msg, {"video_id": vid})

            supports_dislikes = ("dislikes" in prev_v) or ("dislikes" in v)
            if supports_dislikes and cur_dislikes > prev_dislikes:
                delta = cur_dislikes - prev_dislikes
                msg = (
                    f"⚠️ *YouTube: New Dislike(s)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Video: {title}\n\n"
                    f"📋 Details\n"
                    f"  • New dislikes: +{delta}\n"
                    f"  • Total:        {cur_dislikes}\n"
                    f"  • Link:         youtube.com/watch?v={vid}\n\n"
                    f"⏰ {_now_str()}"
                )
                _record(alerts, "yt_new_dislikes", delta, msg, {"video_id": vid})

        _save_snapshot("youtube_videos_map", {"videos": new_vids_map})

    except Exception as e:
        print(f"[engagement] YouTube check failed: {e}")

    return alerts


def check_linkedin_engagement() -> List[Dict[str, Any]]:
    """
    Final stable LinkedIn alert mode:
    - reads ONLY Mongo collections populated by export-based sync
    - no browser scraping / no live LinkedIn calls
    - follower deltas from linkedin_highlights_daily
    - post-level deltas from linkedin_posts
    """
    alerts: List[Dict[str, Any]] = []

    def _to_dt(value):
        s = str(value or "").strip()
        if not s:
            return None
        try:
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s)
        except Exception:
            pass
        try:
            return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

    try:
        h_rows = find_all("linkedin_highlights_daily", sort=[("snapshot_date", -1)], limit=1)
        if not h_rows:
            print("[engagement] LinkedIn highlights not available yet")
            return alerts

        h = h_rows[0]

        posts = find_all("linkedin_posts", sort=[("last_updated", -1)], limit=5000)

        last_sync_dt = _to_dt(h.get("last_updated"))
        if last_sync_dt is None and posts:
            last_sync_dt = _to_dt(posts[0].get("last_updated"))

        if last_sync_dt is not None:
            stale_minutes = int((datetime.utcnow() - last_sync_dt.replace(tzinfo=None)).total_seconds() // 60)
            if stale_minutes > LINKEDIN_STALE_MINUTES:
                print(
                    "[engagement] LinkedIn data is stale: "
                    f"{stale_minutes} min old. Skipping LinkedIn alerts until export sync updates Mongo."
                )
                return alerts

        cur_followers = _as_int(h.get("total_followers", 0))
        cur_page_views = _as_int(h.get("page_views", 0))
        cur_unique_visitors = _as_int(h.get("unique_visitors", 0))

        prev = _get_snapshot("linkedin_channel")
        prev_followers = _as_int(prev.get("followers", 0))
        prev_page_views = _as_int(prev.get("page_views", 0))
        prev_unique_visitors = _as_int(prev.get("unique_visitors", 0))
        has_prev_channel = bool(prev) and any(x > 0 for x in (prev_followers, prev_page_views, prev_unique_visitors))

        if has_prev_channel and cur_followers > prev_followers:
            delta = cur_followers - prev_followers
            msg = (
                f"🎉 *LinkedIn: New Followers!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Eagle 3D Streaming page\n\n"
                f"📋 Details\n"
                f"  • New followers: +{delta}\n"
                f"  • Total:         {cur_followers:,}\n\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "li_new_followers", delta, msg)

        elif has_prev_channel and cur_followers < prev_followers:
            delta = prev_followers - cur_followers
            msg = (
                f"📉 *LinkedIn: Lost Followers*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Eagle 3D Streaming page\n\n"
                f"📋 Details\n"
                f"  • Lost followers: -{delta}\n"
                f"  • Total now:      {cur_followers:,}\n\n"
                f"⏰ {_now_str()}"
            )
            _record(alerts, "li_lost_followers", delta, msg)

        _save_snapshot("linkedin_channel", {
            "followers": cur_followers,
            "page_views": cur_page_views,
            "unique_visitors": cur_unique_visitors,
            "source": "linkedin_highlights_daily",
            "last_sync": h.get("last_updated", ""),
        })

        snap = _get_snapshot("linkedin_posts_map")
        prev_posts_map = snap.get("posts", {}) if isinstance(snap, dict) else {}
        new_posts_map = {}

        for post in posts:
            urn = str(post.get("urn") or post.get("post_urn") or "").strip()
            if not urn:
                continue

            title = _safe_text(post.get("title", "LinkedIn post"), 60)
            url = str(post.get("url") or "").strip()

            cur_reactions = _as_int(post.get("reactions", 0))
            cur_comments = _as_int(post.get("comments", 0))
            cur_reposts = _as_int(post.get("reposts", 0))
            cur_follows = _as_int(post.get("follows", 0))
            cur_impressions = _as_int(post.get("impressions", 0))

            prev_post = prev_posts_map.get(urn, {})
            had_prev = urn in prev_posts_map

            prev_reactions = _as_int(prev_post.get("reactions", 0))
            prev_comments = _as_int(prev_post.get("comments", 0))
            prev_reposts = _as_int(prev_post.get("reposts", 0))
            prev_follows = _as_int(prev_post.get("follows", 0))

            new_posts_map[urn] = {
                "title": title,
                "url": url,
                "reactions": cur_reactions,
                "comments": cur_comments,
                "reposts": cur_reposts,
                "follows": cur_follows,
                "impressions": cur_impressions,
            }

            if not had_prev:
                continue

            if cur_reactions > prev_reactions:
                delta = cur_reactions - prev_reactions
                msg = (
                    f"❤️ *LinkedIn: New Reactions*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"📋 Details\n"
                    f"  • New reactions: +{delta}\n"
                    f"  • Total:         {cur_reactions}\n"
                    f"  • Impressions:   {cur_impressions:,}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_reactions", delta, msg, {"post_urn": urn})

            elif cur_reactions < prev_reactions:
                delta = prev_reactions - cur_reactions
                msg = (
                    f"💔 *LinkedIn: Reaction Count Decreased*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"📋 Details\n"
                    f"  • Reactions removed: -{delta}\n"
                    f"  • Total now:         {cur_reactions}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_reactions_removed", delta, msg, {"post_urn": urn})

            if cur_comments > prev_comments:
                delta = cur_comments - prev_comments
                msg = (
                    f"💬 *LinkedIn: New Comments*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"📋 Details\n"
                    f"  • New comments: +{delta}\n"
                    f"  • Total:        {cur_comments}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_comments", delta, msg, {"post_urn": urn})

            elif cur_comments < prev_comments:
                delta = prev_comments - cur_comments
                msg = (
                    f"��️ *LinkedIn: Comment Count Decreased*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"📋 Details\n"
                    f"  • Comments removed: -{delta}\n"
                    f"  • Total now:        {cur_comments}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_comments_removed", delta, msg, {"post_urn": urn})

            if cur_reposts > prev_reposts:
                delta = cur_reposts - prev_reposts
                msg = (
                    f"🔁 *LinkedIn: New Reposts*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"📋 Details\n"
                    f"  • New reposts: +{delta}\n"
                    f"  • Total:       {cur_reposts}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_reposts", delta, msg, {"post_urn": urn})

            elif cur_reposts < prev_reposts:
                delta = prev_reposts - cur_reposts
                msg = (
                    f"↩️ *LinkedIn: Repost Count Decreased*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"📋 Details\n"
                    f"  • Reposts removed: -{delta}\n"
                    f"  • Total now:       {cur_reposts}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_reposts_removed", delta, msg, {"post_urn": urn})

            if cur_follows > prev_follows:
                delta = cur_follows - prev_follows
                msg = (
                    f"👥 *LinkedIn: Post-driven New Follows*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"�� Details\n"
                    f"  • New follows: +{delta}\n"
                    f"  • Total:       {cur_follows}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_follows", delta, msg, {"post_urn": urn})

            elif cur_follows < prev_follows:
                delta = prev_follows - cur_follows
                msg = (
                    f"📉 *LinkedIn: Post-driven Follows Decreased*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Post: {title}\n\n"
                    f"📋 Details\n"
                    f"  • Follows lost: -{delta}\n"
                    f"  • Total now:    {cur_follows}\n"
                    + _link_line(url) +
                    f"\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_follows_removed", delta, msg, {"post_urn": urn})

        _save_snapshot("linkedin_posts_map", {
            "posts": new_posts_map,
            "source": "linkedin_posts",
            "last_sync": h.get("last_updated", ""),
        })

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

    return _send("\n".join(lines))


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
