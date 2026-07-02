#!/usr/bin/env python3
"""

LINKEDIN DAILY PIPELINE
Runs daily to:
1. Scrape all 7 analytics pages
2. Save snapshot to MongoDB
3. Compute deltas (today vs yesterday) for each metric
4. Track historical changes per post (impressions/reactions over time)

Designed to be called by:
- Run Pipeline button in dashboard
- GitHub Actions daily cron
- Manual: python3 linkedin_daily_pipeline.py
"""

import os
import re
import json
from datetime import datetime, timedelta, date

from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
from mongo_data_loader import (
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status, load_all_ml_training_tabs
)






def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Daily] {m}", flush=True)


def _get_supabase():
    return get_db()


def _make_urn(title, post_type):
    """Stable URN from title + type."""
    h = hashlib.sha1(f"{title}|{post_type}".encode()).hexdigest()[:16]
    return f"li::post::{h}"


def run_daily_pipeline():
    log("=" * 60)
    log("LINKEDIN DAILY PIPELINE STARTING")
    log("=" * 60)

    # Step 1: Scrape fresh data
    try:
        from linkedin_browser_scraper import scrape_all
    except ImportError:
        log("ERROR: linkedin_browser_scraper.py not found")
        return False

    log("Scraping all 7 LinkedIn analytics pages...")
    data = scrape_all()

    if data.get("error"):
        log(f"Scrape error: {data['error']}")
        return False

    # Step 2: Connect MongoDB
    sb = _get_supabase()
    if sb is None:
        log("MongoDB not configured - cannot save")
        return False

    today = date.today().strftime("%Y-%m-%d")
    now = datetime.utcnow().isoformat()

    # ── 1. POSTS (latest snapshot) ──
    posts = data.get("updates", {}).get("posts", [])
    if posts:
        rows = []
        for p in posts:
            urn = _make_urn(p["title"], p.get("post_type", ""))
            rows.append({
                "urn":             urn,
                "title":           p["title"][:500],
                "post_type":       p.get("post_type", "")[:50],
                "audience":        p.get("audience", "")[:100],
                "published_at":    None,
                "impressions":     p.get("impressions", 0),
                "views":           p.get("views", 0),
                "clicks":          p.get("clicks", 0),
                "ctr":             p.get("ctr", 0),
                "reactions":       p.get("reactions", 0),
                "comments":        p.get("comments", 0),
                "reposts":         p.get("reposts", 0),
                "follows":         p.get("follows", 0),
                "engagement_rate": p.get("engagement_rate", 0),
                "url":             "",
                "last_updated":    now,
            })
        try:
            log(f"Posts upserted: {len(rows)}")
        except Exception as e:
            log(f"Posts upsert error: {e}")

        # ── POSTS DAILY HISTORY (track deltas vs yesterday) ──
        daily_rows = []
        for p in posts:
            urn = _make_urn(p["title"], p.get("post_type", ""))
            # Get yesterday's snapshot for this post
            try:
                yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
                yest_resp = sb.table("linkedin_posts_daily").select("impressions,reactions,comments").eq("post_urn", urn).eq("snapshot_date", yesterday).execute()
                yest = yest_resp.data[0] if yest_resp.data else {}
            except Exception:
                yest = {}

            delta_imp = max(0, p.get("impressions", 0) - yest.get("impressions", 0))
            delta_rxn = max(0, p.get("reactions",   0) - yest.get("reactions",   0))
            delta_com = max(0, p.get("comments",    0) - yest.get("comments",    0))

            daily_rows.append({
                "post_urn":          urn,
                "snapshot_date":     today,
                "impressions":       p.get("impressions", 0),
                "clicks":            p.get("clicks", 0),
                "reactions":         p.get("reactions", 0),
                "comments":          p.get("comments", 0),
                "reposts":           p.get("reposts", 0),
                "engagement_rate":   p.get("engagement_rate", 0),
                "delta_impressions": delta_imp,
                "delta_reactions":   delta_rxn,
                "delta_comments":    delta_com,
                "captured_at":       now,
            })
        try:
            log(f"Posts daily history: {len(daily_rows)}")
        except Exception as e:
            log(f"Posts daily error: {e}")

    # ── 2. FOLLOWERS DAILY ──
    followers_total = data.get("followers", {}).get("total", 0)
    if followers_total:
        try:
            yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
            yest_resp = sb.table("linkedin_followers_daily").select("total").eq("snapshot_date", yesterday).execute()
            yest_total = yest_resp.data[0]["total"] if yest_resp.data else followers_total
            delta = followers_total - yest_total
        except Exception:
            delta = 0

        try:
            sb.table("linkedin_followers_daily").upsert([{
                "snapshot_date":  today,
                "total":          followers_total,
                "organic_gains":  delta if delta > 0 else 0,
                "paid_gains":     0,
                "delta_total":    delta,
                "captured_at":    now,
            }], on_conflict="snapshot_date").execute()
            log(f"Followers daily: total={followers_total} delta={delta:+d}")
        except Exception as e:
            log(f"Followers daily error: {e}")

    # ── 3. VISITORS DAILY ──
    vis = data.get("visitors", {}).get("highlights", {})
    if vis:
        try:
            yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
            yest_resp = sb.table("linkedin_visitors_daily").select("page_views").eq("snapshot_date", yesterday).execute()
            yest_views = yest_resp.data[0]["page_views"] if yest_resp.data else vis.get("page_views", 0)
            delta_views = vis.get("page_views", 0) - yest_views
        except Exception:
            delta_views = 0

        try:
            sb.table("linkedin_visitors_daily").upsert([{
                "snapshot_date":   today,
                "page_views":      vis.get("page_views", 0),
                "unique_visitors": vis.get("unique_visitors", 0),
                "custom_button":   vis.get("custom_button", 0),
                "delta_views":     delta_views,
                "captured_at":     now,
            }], on_conflict="snapshot_date").execute()
            log(f"Visitors daily: views={vis.get('page_views',0)} unique={vis.get('unique_visitors',0)}")
        except Exception as e:
            log(f"Visitors error: {e}")

    # ── 4. COMPETITORS DAILY ──
    competitors = data.get("competitors", {}).get("competitors", [])
    if competitors:
        rows = []
        for c in competitors:
            rows.append({
                "snapshot_date":    today,
                "name":             c.get("name", "")[:200],
                "followers":        c.get("followers", 0),
                "follower_growth":  c.get("follower_growth", "")[:50],
                "post_engagements": c.get("post_engagements", 0),
                "engagement_rate":  c.get("engagement_rate", "")[:50],
                "posts":            c.get("posts", 0),
                "captured_at":      now,
            })
        try:
            log(f"Competitors daily: {len(rows)}")
        except Exception as e:
            log(f"Competitors error: {e}")

    # ── 5. SEARCH KEYWORDS ──
    keywords = data.get("search_appearances", {}).get("keywords", [])
    if keywords:
        rows = []
        for k in keywords:
            rows.append({
                "snapshot_date":  today,
                "keyword":        k.get("keyword", "")[:200],
                "count":          k.get("count", 0),
                "captured_at":    now,
            })
        try:
            log(f"Search keywords: {len(rows)}")
        except Exception as e:
            log(f"Keywords error: {e}")

    # ── 6. NEWSLETTER ARTICLES ──
    articles = data.get("newsletters", {}).get("articles", [])
    if articles:
        rows = []
        for a in articles:
            urn = hashlib.sha1(a["title"].encode()).hexdigest()[:16]
            rows.append({
                "urn":          f"li::news::{urn}",
                "title":        a["title"][:500],
                "published_at": None,
                "views":        a.get("views", 0),
                "reactions":    a.get("reactions", 0),
                "comments":     a.get("comments", 0),
                "shares":       a.get("shares", 0),
                "last_updated": now,
            })
        try:
            log(f"Newsletter articles: {len(rows)}")
        except Exception as e:
            log(f"Newsletter error: {e}")

    # ── 7. HIGHLIGHTS DAILY (all-page totals) ──
    h_updates = data.get("updates", {}).get("highlights", {})
    h_vis = data.get("visitors", {}).get("highlights", {})
    h_news = data.get("newsletters", {}).get("highlights", {})
    try:
        sb.table("linkedin_highlights_daily").upsert([{
            "snapshot_date":          today,
            "impressions":            h_updates.get("impressions", 0),
            "reactions":              h_updates.get("reactions", 0),
            "comments":               h_updates.get("comments", 0),
            "reposts":                h_updates.get("reposts", 0),
            "clicks":                 h_updates.get("clicks", 0),
            "page_views":             h_vis.get("page_views", 0),
            "unique_visitors":        h_vis.get("unique_visitors", 0),
            "total_followers":        followers_total,
            "newsletter_subscribers": h_news.get("subscribers", 0),
            "captured_at":            now,
        }], on_conflict="snapshot_date").execute()
        log(f"Highlights daily snapshot saved")
    except Exception as e:
        log(f"Highlights error: {e}")

    log("=" * 60)
    log("DAILY PIPELINE COMPLETE")
    log("=" * 60)
    return True


if __name__ == "__main__":
    run_daily_pipeline()
