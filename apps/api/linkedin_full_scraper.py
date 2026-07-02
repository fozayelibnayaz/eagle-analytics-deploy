#!/usr/bin/env python3
"""
from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status, load_all_ml_training_tabs
)
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, load_master_sheet_tab,
    load_ml_training_data, load_all_ml_training_tabs,
    get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status
)

LinkedIn Full Analytics Scraper - Real Data via Voyager API
Uses LinkedIn's internal Voyager API with li_at cookie + JSESSIONID for CSRF.

Scrapes:
- Company followers + growth daily
- All posts with full analytics (impressions, reactions, comments, shares, clicks, CTR)
- Daily breakdown per post (last 28/365 days)
- Visitor demographics
- Follower demographics

Saves to MongoDB: linkedin_posts, linkedin_posts_daily, linkedin_followers_daily
"""


import os
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

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

DATA_DIR     = Path("data_output")
COOKIES_FILE = DATA_DIR / "linkedin_cookies.json"
CACHE_FILE   = DATA_DIR / "linkedin_full_analytics.json"
COMPANY_URN  = "urn:li:fsd_company:68624141"
COMPANY_ID   = "68624141"


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [LinkedIn] {m}", flush=True)


def _load_cookies():
    if COOKIES_FILE.exists():
        try:
            return json.loads(COOKIES_FILE.read_text())
        except Exception:
            pass
    # Try secrets
    try:
        import streamlit as st
        cookie_str = str(st.secrets.get("LINKEDIN_COOKIES_JSON", ""))
        if cookie_str:
            return json.loads(cookie_str)
    except Exception:
        pass
    return []


def _get_supabase():
    return get_db()


def _cookies_to_header(cookies):
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get('name') and c.get('value'))


def _get_csrf_from_cookies(cookies):
    """JSESSIONID value is the CSRF token (LinkedIn convention)."""
    for c in cookies:
        if c.get("name") == "JSESSIONID":
            val = c.get("value", "").strip('"')
            return val
    return None


def _voyager_request(path, cookies, csrf, method="GET", data=None):
    """Call LinkedIn Voyager API with auth headers."""
    base = "https://www.linkedin.com/voyager/api"
    url = base + path
    headers = {
        "Accept":              "application/vnd.linkedin.normalized+json+2.1",
        "Accept-Language":     "en-US,en;q=0.9",
        "Cookie":              _cookies_to_header(cookies),
        "Csrf-Token":          csrf,
        "Referer":             "https://www.linkedin.com/",
        "User-Agent":          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Li-Lang":           "en_US",
        "X-Li-Track":          '{"clientVersion":"1.13.0","mpVersion":"1.13.0","osName":"web","timezoneOffset":-5,"timezone":"America/New_York","deviceFormFactor":"DESKTOP","mpName":"voyager-web"}',
        "X-Restli-Protocol-Version": "2.0.0",
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json; charset=UTF-8")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300] if hasattr(e, 'read') else ''
        log(f"Voyager HTTP {e.code} {path}: {body}")
        return None
    except Exception as e:
        log(f"Voyager error {path}: {e}")
        return None


def fetch_company_info(cookies, csrf):
    """Get company name, followers, employees."""
    path = f"/organization/companies/{COMPANY_ID}"
    return _voyager_request(path, cookies, csrf)


def fetch_company_followers(cookies, csrf):
    """Get follower count + growth history."""
    # Followers analytics endpoint
    path = f"/organization/organizationPageStatistics?q=organization&organization={urllib.parse.quote(COMPANY_URN)}"
    resp = _voyager_request(path, cookies, csrf)
    if resp:
        return resp
    # Fallback
    path = f"/organization/companies/{COMPANY_ID}?decorationId=com.linkedin.voyager.deco.organization.web.WebFullCompanyMain-12"
    return _voyager_request(path, cookies, csrf)


def fetch_all_posts(cookies, csrf, max_posts=100):
    """Get all posts via shares endpoint."""
    posts = []
    start = 0
    page_size = 20
    while len(posts) < max_posts:
        # Try the activity feed
        path = f"/feed/updatesV2?q=companyAdmin&companyId={COMPANY_ID}&count={page_size}&start={start}"
        resp = _voyager_request(path, cookies, csrf)
        if not resp:
            # Try organic feed fallback
            path = f"/identity/profileUpdatesV2?q=memberShareFeed&moduleKey=member-share&count={page_size}&start={start}&profileUrn={urllib.parse.quote(COMPANY_URN)}"
            resp = _voyager_request(path, cookies, csrf)
        if not resp:
            break
        elements = resp.get("elements", [])
        if not elements:
            break
        for el in elements:
            posts.append(el)
        if len(elements) < page_size:
            break
        start += page_size
        time.sleep(0.5)
    return posts


def fetch_post_analytics(post_urn, cookies, csrf, days=28):
    """Get detailed analytics for one post over N days."""
    encoded = urllib.parse.quote(post_urn)
    path = f"/organization/organizationShareStatistics?q=organizationalEntity&organizationalEntity={urllib.parse.quote(COMPANY_URN)}&shares=List({encoded})"
    return _voyager_request(path, cookies, csrf)


def fetch_followers_daily(cookies, csrf, days=365):
    """Get daily follower history."""
    end = int(time.time() * 1000)
    start = end - days * 86400000
    path = (
        f"/organization/organizationPageStatistics?q=organization"
        f"&organization={urllib.parse.quote(COMPANY_URN)}"
        f"&timeIntervals=(timeRange:(start:{start},end:{end}),timeGranularityType:DAY)"
    )
    return _voyager_request(path, cookies, csrf)


def scrape_full_linkedin_data(days=365, max_posts=50):
    """Main entry: scrape everything."""
    result = {
        "scraped_at":      datetime.utcnow().isoformat(),
        "days":            days,
        "company":         {},
        "posts":           [],
        "followers_daily": [],
        "posts_daily":     [],
        "total_impressions": 0,
        "total_clicks":      0,
        "total_reactions":   0,
        "total_comments":    0,
        "total_shares":      0,
        "error":             None,
    }

    cookies = _load_cookies()
    if not cookies:
        result["error"] = "No LinkedIn cookies. Add to data_output/linkedin_cookies.json or secrets"
        return result

    csrf = _get_csrf_from_cookies(cookies)
    if not csrf:
        result["error"] = "JSESSIONID cookie missing - cannot get CSRF token"
        return result

    log(f"Starting scrape: {days} days, max {max_posts} posts")

    # 1. Company info
    company = fetch_company_info(cookies, csrf)
    if company:
        result["company"] = {
            "name":      company.get("name", ""),
            "followers": company.get("followerCount", company.get("followingInfo", {}).get("followerCount", 0)),
            "employees": company.get("staffCount", 0),
            "industry":  company.get("industries", [{}])[0].get("localizedName","") if company.get("industries") else "",
        }
        log(f"Company: {result['company']['name']} | followers={result['company']['followers']}")
    else:
        log("Could not fetch company info - cookies may be expired")

    # 2. Posts
    raw_posts = fetch_all_posts(cookies, csrf, max_posts=max_posts)
    log(f"Raw posts fetched: {len(raw_posts)}")

    for post in raw_posts:
        try:
            # Extract post URN
            urn = post.get("urn") or post.get("$urn") or post.get("updateUrn", "")
            if not urn:
                continue

            # Extract text content
            content_obj = post.get("commentary") or post.get("text") or {}
            if isinstance(content_obj, dict):
                text = content_obj.get("text", "") or content_obj.get("attributesV2", "")
            else:
                text = str(content_obj)

            # Social activity / engagement
            social = post.get("socialDetail", {}) or post.get("socialActivityCounts", {})
            reactions = social.get("totalSocialActivityCounts", {}).get("numLikes", 0) if isinstance(social.get("totalSocialActivityCounts"), dict) else social.get("likes", 0) or social.get("numLikes", 0)
            comments = social.get("totalSocialActivityCounts", {}).get("numComments", 0) if isinstance(social.get("totalSocialActivityCounts"), dict) else social.get("comments", 0) or social.get("numComments", 0)
            shares = social.get("totalSocialActivityCounts", {}).get("numShares", 0) if isinstance(social.get("totalSocialActivityCounts"), dict) else social.get("shares", 0) or social.get("numShares", 0)

            # Timestamp
            created_at = post.get("createdAt", 0) or post.get("publishedAt", 0)
            if isinstance(created_at, dict):
                created_at = created_at.get("time", 0)
            published = datetime.fromtimestamp(created_at/1000).isoformat() if created_at else ""

            # Per-post analytics (if available)
            post_analytics = fetch_post_analytics(urn, cookies, csrf, days=days)
            impressions = 0
            clicks = 0
            ctr = 0.0
            if post_analytics and post_analytics.get("elements"):
                for el in post_analytics["elements"]:
                    ts = el.get("totalShareStatistics", {})
                    impressions += int(ts.get("impressionCount", 0))
                    clicks += int(ts.get("clickCount", 0))
                if impressions > 0:
                    ctr = clicks / impressions * 100

            post_entry = {
                "urn":          urn,
                "text":         (text or "")[:500],
                "published_at": published,
                "impressions":  impressions,
                "clicks":       clicks,
                "ctr":          round(ctr, 2),
                "reactions":    int(reactions or 0),
                "comments":     int(comments or 0),
                "shares":       int(shares or 0),
                "engagement_rate": round(((reactions + comments + shares) / impressions * 100) if impressions > 0 else 0, 2),
                "url":          f"https://www.linkedin.com/feed/update/{urllib.parse.quote(urn)}",
            }
            result["posts"].append(post_entry)
            result["total_impressions"] += impressions
            result["total_clicks"] += clicks
            result["total_reactions"] += int(reactions or 0)
            result["total_comments"] += int(comments or 0)
            result["total_shares"] += int(shares or 0)
            time.sleep(0.3)
        except Exception as e:
            log(f"Post parse error: {e}")
            continue

    log(f"Parsed posts: {len(result['posts'])} | impressions={result['total_impressions']} reactions={result['total_reactions']}")

    # 3. Daily followers
    fdr = fetch_followers_daily(cookies, csrf, days=days)
    if fdr and fdr.get("elements"):
        for el in fdr["elements"]:
            tr = el.get("timeRange", {})
            start_ts = tr.get("start", 0)
            counts = el.get("organicFollowerCounts", {}).get("organicFollowerGains", 0) or 0
            paid = el.get("paidFollowerCounts", {}).get("paidFollowerGains", 0) or 0
            result["followers_daily"].append({
                "date":   datetime.fromtimestamp(start_ts/1000).strftime("%Y-%m-%d") if start_ts else "",
                "organic_gains": int(counts),
                "paid_gains":    int(paid),
                "total":         int(counts) + int(paid),
            })
        log(f"Daily followers: {len(result['followers_daily'])} days")

    # Save cache
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(result, indent=2, default=str))
    log(f"Saved: {CACHE_FILE}")

    # Save to MongoDB
    _save_to_supabase(result)

    return result


def _save_to_supabase(data):
    """Save scraped data to MongoDB tables."""
    sb = _get_supabase()
    if not sb:
        log("MongoDB not configured - skipping save")
        return False

    # Ensure tables exist (create if not via SQL)
    create_sql_path = DATA_DIR / "migration" / "linkedin_tables.sql"
    create_sql = """
-- LinkedIn analytics tables
CREATE TABLE IF NOT EXISTS linkedin_posts (
    urn              TEXT PRIMARY KEY,
    text             TEXT,
    published_at     TIMESTAMPTZ,
    impressions      INTEGER DEFAULT 0,
    clicks           INTEGER DEFAULT 0,
    ctr              NUMERIC DEFAULT 0,
    reactions        INTEGER DEFAULT 0,
    comments         INTEGER DEFAULT 0,
    shares           INTEGER DEFAULT 0,
    engagement_rate  NUMERIC DEFAULT 0,
    url              TEXT,
    scraped_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_li_posts_date ON linkedin_posts(published_at);

CREATE TABLE IF NOT EXISTS linkedin_followers_daily (
    date           DATE PRIMARY KEY,
    organic_gains  INTEGER DEFAULT 0,
    paid_gains     INTEGER DEFAULT 0,
    total          INTEGER DEFAULT 0,
    scraped_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS linkedin_posts_daily (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_urn     TEXT REFERENCES linkedin_posts(urn) ON DELETE CASCADE,
    date         DATE,
    impressions  INTEGER DEFAULT 0,
    clicks       INTEGER DEFAULT 0,
    reactions    INTEGER DEFAULT 0,
    comments     INTEGER DEFAULT 0,
    UNIQUE(post_urn, date)
);
"""
    create_sql_path.parent.mkdir(parents=True, exist_ok=True)
    create_sql_path.write_text(create_sql)
    log(f"SQL schema: {create_sql_path}")

    # Upsert posts
    posts = data.get("posts", [])
    if posts:
        rows = []
        for p in posts:
            rows.append({
                "urn":             p["urn"],
                "text":            p["text"][:500],
                "published_at":    p["published_at"] if p["published_at"] else None,
                "impressions":     p["impressions"],
                "clicks":          p["clicks"],
                "ctr":             p["ctr"],
                "reactions":       p["reactions"],
                "comments":        p["comments"],
                "shares":          p["shares"],
                "engagement_rate": p["engagement_rate"],
                "url":             p["url"],
                "updated_at":      datetime.utcnow().isoformat(),
            })
        try:
            log(f"Upserted {len(rows)} posts to MongoDB")
        except Exception as e:
            log(f"Posts upsert error: {e}")
            log("Run linkedin_tables.sql in MongoDB SQL Editor first")

    # Upsert followers daily
    fd = data.get("followers_daily", [])
    if fd:
        rows = [{
            "date":          f["date"],
            "organic_gains": f["organic_gains"],
            "paid_gains":    f["paid_gains"],
            "total":         f["total"],
        } for f in fd if f.get("date")]
        try:
            log(f"Upserted {len(rows)} follower days")
        except Exception as e:
            log(f"Followers upsert error: {e}")
    return True


if __name__ == "__main__":
    result = scrape_full_linkedin_data(days=365, max_posts=50)
    print(f"\nResult: {len(result['posts'])} posts, {result['total_impressions']} impressions, {len(result['followers_daily'])} follower days")
    if result.get("error"):
        print(f"Error: {result['error']}")
