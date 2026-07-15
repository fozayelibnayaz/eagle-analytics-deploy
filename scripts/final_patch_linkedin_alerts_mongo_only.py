from pathlib import Path
from datetime import datetime

p = Path("engagement_alerts.py")
if not p.exists():
    print("❌ engagement_alerts.py not found")
    raise SystemExit(1)

text = p.read_text(encoding="utf-8", errors="ignore")
backup = Path("backups") / f"engagement_alerts.py.mongo_only_final.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

# 1) raise stale threshold for export-based LinkedIn sync
text = text.replace(
    "LINKEDIN_STALE_MINUTES = 180",
    "LINKEDIN_STALE_MINUTES = 2160  # 36 hours for export-based LinkedIn sync"
)

start = text.find("def check_linkedin_engagement() -> List[Dict[str, Any]]:")
end = text.find("\ndef send_combined_summary(", start)

if start == -1 or end == -1:
    print("❌ Could not locate check_linkedin_engagement() block")
    raise SystemExit(1)

new_func = '''def check_linkedin_engagement() -> List[Dict[str, Any]]:
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
                f"🎉 *LinkedIn: New Followers!*\\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                f"Eagle 3D Streaming page\\n\\n"
                f"📋 Details\\n"
                f"  • New followers: +{delta}\\n"
                f"  • Total:         {cur_followers:,}\\n\\n"
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
                f"  • Total now:      {cur_followers:,}\\n\\n"
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
                    f"❤️ *LinkedIn: New Reactions*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New reactions: +{delta}\\n"
                    f"  • Total:         {cur_reactions}\\n"
                    f"  • Impressions:   {cur_impressions:,}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_reactions", delta, msg, {"post_urn": urn})

            elif cur_reactions < prev_reactions:
                delta = prev_reactions - cur_reactions
                msg = (
                    f"💔 *LinkedIn: Reaction Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Reactions removed: -{delta}\\n"
                    f"  • Total now:         {cur_reactions}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_reactions_removed", delta, msg, {"post_urn": urn})

            if cur_comments > prev_comments:
                delta = cur_comments - prev_comments
                msg = (
                    f"💬 *LinkedIn: New Comments*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New comments: +{delta}\\n"
                    f"  • Total:        {cur_comments}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_comments", delta, msg, {"post_urn": urn})

            elif cur_comments < prev_comments:
                delta = prev_comments - cur_comments
                msg = (
                    f"��️ *LinkedIn: Comment Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Comments removed: -{delta}\\n"
                    f"  • Total now:        {cur_comments}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_comments_removed", delta, msg, {"post_urn": urn})

            if cur_reposts > prev_reposts:
                delta = cur_reposts - prev_reposts
                msg = (
                    f"🔁 *LinkedIn: New Reposts*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • New reposts: +{delta}\\n"
                    f"  • Total:       {cur_reposts}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_reposts", delta, msg, {"post_urn": urn})

            elif cur_reposts < prev_reposts:
                delta = prev_reposts - cur_reposts
                msg = (
                    f"↩️ *LinkedIn: Repost Count Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Reposts removed: -{delta}\\n"
                    f"  • Total now:       {cur_reposts}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_reposts_removed", delta, msg, {"post_urn": urn})

            if cur_follows > prev_follows:
                delta = cur_follows - prev_follows
                msg = (
                    f"👥 *LinkedIn: Post-driven New Follows*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"�� Details\\n"
                    f"  • New follows: +{delta}\\n"
                    f"  • Total:       {cur_follows}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
                )
                _record(alerts, "li_post_new_follows", delta, msg, {"post_urn": urn})

            elif cur_follows < prev_follows:
                delta = prev_follows - cur_follows
                msg = (
                    f"📉 *LinkedIn: Post-driven Follows Decreased*\\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\\n"
                    f"Post: {title}\\n\\n"
                    f"📋 Details\\n"
                    f"  • Follows lost: -{delta}\\n"
                    f"  • Total now:    {cur_follows}\\n"
                    + _link_line(url) +
                    f"\\n⏰ {_now_str()}"
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
'''

new_text = text[:start] + new_func + text[end:]
p.write_text(new_text, encoding="utf-8")

print(f"OK: backup written -> {backup}")
print(f"OK: patched -> {p}")
