from pathlib import Path
from datetime import datetime

p = Path("engagement_alerts.py")
if not p.exists():
    print("❌ engagement_alerts.py not found")
    raise SystemExit(1)

text = p.read_text(encoding="utf-8", errors="ignore")
backup = Path("backups") / f"engagement_alerts.py.linkedin_stable.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

start = text.find("def check_linkedin_engagement() -> List[Dict[str, Any]]:")
end = text.find("\ndef send_combined_summary(", start)

if start == -1 or end == -1:
    print("❌ Could not locate check_linkedin_engagement() block")
    raise SystemExit(1)

new_func = '''def check_linkedin_engagement() -> List[Dict[str, Any]]:
    """
    Stable LinkedIn alert mode:
    - reads ONLY transformed Mongo collections
    - uses follower/page-level analytics only
    - intentionally skips post-level reactions/comments/reposts until
      linkedin_posts_daily is populated reliably from exports
    """
    alerts: List[Dict[str, Any]] = []

    try:
        rows = find_all("linkedin_highlights_daily", sort=[("snapshot_date", -1)], limit=1)
        if not rows:
            print("[engagement] LinkedIn highlights not available yet")
            return alerts

        cur = rows[0]
        cur_followers = _as_int(cur.get("total_followers", 0))
        cur_page_views = _as_int(cur.get("page_views", 0))
        cur_unique_visitors = _as_int(cur.get("unique_visitors", 0))

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
        })

    except Exception as e:
        print(f"[engagement] LinkedIn check failed: {e}")

    return alerts
'''

new_text = text[:start] + new_func + text[end:]
p.write_text(new_text, encoding="utf-8")

print(f"OK: backup written -> {backup}")
print(f"OK: patched -> {p}")
