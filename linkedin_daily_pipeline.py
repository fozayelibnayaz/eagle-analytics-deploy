"""
linkedin_daily_pipeline.py — Eagle 3D Streaming Analytics Hub
===============================================================
100% MongoDB. Runs daily:
  1. Scrape all LinkedIn analytics pages (via linkedin_browser_scraper)
  2. Save snapshot to MongoDB collections
  3. Compute deltas (today vs yesterday)
  4. Track historical changes per post
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from mongo_client import find_one, upsert_many


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [LI-daily] {msg}", flush=True)


def _make_urn(title: str, post_type: str) -> str:
    h = hashlib.sha1(f"{title}|{post_type}".encode()).hexdigest()[:16]
    return f"li::post::{h}"


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def run_daily_pipeline() -> bool:
    log("=" * 60)
    log("LINKEDIN DAILY PIPELINE STARTING (MongoDB)")
    log("=" * 60)

    # ── Import scraper ──
    try:
        from linkedin_browser_scraper import scrape_all
    except ImportError:
        log("ERROR: linkedin_browser_scraper.py not found — skipping")
        return False

    log("Scraping all LinkedIn analytics pages...")
    try:
        data = scrape_all()
    except Exception as e:
        log(f"Scrape failed: {e}")
        return False

    if isinstance(data, dict) and data.get("error"):
        log(f"Scrape error: {data['error']}")
        return False

    today = _today()
    yesterday = _yesterday()
    now = _now_iso()

    # ── 1. POSTS (latest snapshot) ──
    posts = (data.get("updates", {}) or {}).get("posts", []) or []
    if posts:
        rows: List[Dict[str, Any]] = []
        for p in posts:
            urn = _make_urn(p.get("title", ""), p.get("post_type", ""))
            rows.append({
                "urn":             urn,
                "title":           str(p.get("title", ""))[:500],
                "post_type":       str(p.get("post_type", ""))[:50],
                "audience":        str(p.get("audience", ""))[:100],
                "published_at":    p.get("published_at"),
                "impressions":     int(p.get("impressions", 0) or 0),
                "views":           int(p.get("views", 0) or 0),
                "clicks":          int(p.get("clicks", 0) or 0),
                "ctr":             float(p.get("ctr", 0) or 0),
                "reactions":       int(p.get("reactions", 0) or 0),
                "comments":        int(p.get("comments", 0) or 0),
                "reposts":         int(p.get("reposts", 0) or 0),
                "follows":         int(p.get("follows", 0) or 0),
                "engagement_rate": float(p.get("engagement_rate", 0) or 0),
                "url":             str(p.get("url", "")),
                "last_updated":    now,
            })
        n = upsert_many("linkedin_posts", rows, "urn")
        log(f"Posts upserted: {n}")

        # POSTS DAILY HISTORY
        daily_rows: List[Dict[str, Any]] = []
        for p in posts:
            urn = _make_urn(p.get("title", ""), p.get("post_type", ""))
            yest = find_one("linkedin_posts_daily",
                            {"post_urn": urn, "snapshot_date": yesterday}) or {}
            imp_now = int(p.get("impressions", 0) or 0)
            rxn_now = int(p.get("reactions", 0) or 0)
            com_now = int(p.get("comments", 0) or 0)

            daily_rows.append({
                "post_urn":          urn,
                "snapshot_date":     today,
                "impressions":       imp_now,
                "clicks":            int(p.get("clicks", 0) or 0),
                "reactions":         rxn_now,
                "comments":          com_now,
                "reposts":           int(p.get("reposts", 0) or 0),
                "engagement_rate":   float(p.get("engagement_rate", 0) or 0),
                "delta_impressions": max(0, imp_now - int(yest.get("impressions", 0) or 0)),
                "delta_reactions":   max(0, rxn_now - int(yest.get("reactions", 0) or 0)),
                "delta_comments":    max(0, com_now - int(yest.get("comments", 0) or 0)),
                "captured_at":       now,
            })
        n = upsert_many("linkedin_posts_daily", daily_rows, ["post_urn", "snapshot_date"])
        log(f"Posts daily history: {n}")

    # ── 2. FOLLOWERS DAILY ──
    followers_total = int((data.get("followers", {}) or {}).get("total", 0) or 0)
    if followers_total:
        yest_f = find_one("linkedin_followers_daily", {"snapshot_date": yesterday}) or {}
        yest_total = int(yest_f.get("total", followers_total) or followers_total)
        delta = followers_total - yest_total

        upsert_many("linkedin_followers_daily", [{
            "snapshot_date":  today,
            "total":          followers_total,
            "organic_gains":  delta if delta > 0 else 0,
            "paid_gains":     0,
            "delta_total":    delta,
            "captured_at":    now,
        }], "snapshot_date")
        log(f"Followers daily: total={followers_total} delta={delta:+d}")

    # ── 3. VISITORS DAILY ──
    vis = (data.get("visitors", {}) or {}).get("highlights", {}) or {}
    if vis:
        yest_v = find_one("linkedin_visitors_daily", {"snapshot_date": yesterday}) or {}
        views_now = int(vis.get("page_views", 0) or 0)
        yest_views = int(yest_v.get("page_views", views_now) or views_now)

        upsert_many("linkedin_visitors_daily", [{
            "snapshot_date":   today,
            "page_views":      views_now,
            "unique_visitors": int(vis.get("unique_visitors", 0) or 0),
            "custom_button":   int(vis.get("custom_button", 0) or 0),
            "delta_views":     views_now - yest_views,
            "captured_at":     now,
        }], "snapshot_date")
        log(f"Visitors daily: views={views_now}")

    # ── 4. COMPETITORS DAILY ──
    competitors = (data.get("competitors", {}) or {}).get("competitors", []) or []
    if competitors:
        rows = [{
            "snapshot_date":    today,
            "name":             str(c.get("name", ""))[:200],
            "followers":        int(c.get("followers", 0) or 0),
            "follower_growth":  str(c.get("follower_growth", ""))[:50],
            "post_engagements": int(c.get("post_engagements", 0) or 0),
            "engagement_rate":  str(c.get("engagement_rate", ""))[:50],
            "posts":            int(c.get("posts", 0) or 0),
            "captured_at":      now,
        } for c in competitors]
        n = upsert_many("linkedin_competitors_daily", rows, ["snapshot_date", "name"])
        log(f"Competitors daily: {n}")

    # ── 5. SEARCH KEYWORDS ──
    keywords = (data.get("search_appearances", {}) or {}).get("keywords", []) or []
    if keywords:
        rows = [{
            "snapshot_date": today,
            "keyword":       str(k.get("keyword", ""))[:200],
            "count":         int(k.get("count", 0) or 0),
            "captured_at":   now,
        } for k in keywords]
        n = upsert_many("linkedin_search_keywords", rows, ["snapshot_date", "keyword"])
        log(f"Search keywords: {n}")

    # ── 6. NEWSLETTER ARTICLES ──
    articles = (data.get("newsletters", {}) or {}).get("articles", []) or []
    if articles:
        rows = []
        for a in articles:
            aid = hashlib.sha1(str(a.get("title", "")).encode()).hexdigest()[:16]
            rows.append({
                "urn":          f"li::news::{aid}",
                "title":        str(a.get("title", ""))[:500],
                "published_at": a.get("published_at"),
                "views":        int(a.get("views", 0) or 0),
                "reactions":    int(a.get("reactions", 0) or 0),
                "comments":     int(a.get("comments", 0) or 0),
                "shares":       int(a.get("shares", 0) or 0),
                "last_updated": now,
            })
        n = upsert_many("linkedin_newsletter_articles", rows, "urn")
        log(f"Newsletter articles: {n}")

    # ── 7. HIGHLIGHTS DAILY (all-page totals) ──
    h_updates = (data.get("updates", {}) or {}).get("highlights", {}) or {}
    h_vis     = (data.get("visitors", {}) or {}).get("highlights", {}) or {}
    h_news    = (data.get("newsletters", {}) or {}).get("highlights", {}) or {}

    upsert_many("linkedin_highlights_daily", [{
        "snapshot_date":          today,
        "impressions":            int(h_updates.get("impressions", 0) or 0),
        "reactions":              int(h_updates.get("reactions", 0) or 0),
        "comments":               int(h_updates.get("comments", 0) or 0),
        "reposts":                int(h_updates.get("reposts", 0) or 0),
        "clicks":                 int(h_updates.get("clicks", 0) or 0),
        "page_views":             int(h_vis.get("page_views", 0) or 0),
        "unique_visitors":        int(h_vis.get("unique_visitors", 0) or 0),
        "total_followers":        followers_total,
        "newsletter_subscribers": int(h_news.get("subscribers", 0) or 0),
        "captured_at":            now,
    }], "snapshot_date")
    log("Highlights daily snapshot saved")

    log("=" * 60)
    log("LINKEDIN DAILY PIPELINE COMPLETE")
    log("=" * 60)
    return True


if __name__ == "__main__":
    run_daily_pipeline()
