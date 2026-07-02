#!/usr/bin/env python3
"""LinkedIn Post Scraper - targets Content engagement table specifically."""

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

import os, json, time, re, hashlib
from datetime import datetime, date, timedelta
from pathlib import Path

DATA_DIR = Path("data_output")
COMPANY_ID = "68624141"
UPDATES_URL = f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/updates/"

def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [LI] {m}", flush=True)

def _get_sb():
    return get_db()


def scrape_all_posts():
    from playwright.sync_api import sync_playwright
    session_file = DATA_DIR / "linkedin_session_state.json"
    cookies_file = DATA_DIR / "linkedin_cookies.json"
    if not session_file.exists() and not cookies_file.exists():
        log("No session/cookies"); return []

    all_posts = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
        ctx_args = {"user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "viewport":{"width":1440,"height":900}}
        if session_file.exists():
            ctx_args["storage_state"] = str(session_file)
        context = browser.new_context(**ctx_args)
        if not session_file.exists() and cookies_file.exists():
            try:
                cookies = json.loads(cookies_file.read_text())
                pw_cookies = []
                for c in cookies:
                    try:
                        domain = c.get("domain",".linkedin.com")
                        if not domain.startswith("."): domain = "." + domain
                        pw_c = {"name":c["name"],"value":c["value"],"domain":domain,
                                "path":c.get("path","/"),"secure":c.get("secure",True),
                                "httpOnly":c.get("httpOnly",False)}
                        exp = c.get("expirationDate")
                        if exp and not c.get("session"): pw_c["expires"] = int(exp)
                        pw_cookies.append(pw_c)
                    except: continue
                context.add_cookies(pw_cookies)
            except: pass

        page = context.new_page()
        page.goto(UPDATES_URL, timeout=45000, wait_until="domcontentloaded")
        time.sleep(6)
        if "login" in page.url.lower():
            log("LOGIN REQUIRED"); browser.close(); return []
        log("Page loaded")

        # STEP 1: Scroll down to "Content engagement" section
        log("Scrolling to Content engagement section...")
        for _ in range(10):
            page.evaluate("window.scrollBy(0, 500)")
            time.sleep(1)

        # STEP 2: Find and click the "Time range" dropdown in Content engagement
        # It shows text like "Time range:  Jun 25, 2025 - Jun 25, 2026"
        log("Looking for Content engagement Time range dropdown...")
        try:
            # Find the Time range button - it contains date text
            time_btns = page.query_selector_all("button")
            for btn in time_btns:
                txt = (btn.inner_text() or "").strip()
                if "Time range" in txt or ("2025" in txt and "2026" in txt):
                    log(f"  Found Time range button: {txt[:60]}")
                    btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    btn.click()
                    time.sleep(3)
                    log("  Clicked Time range dropdown")

                    # Select "Last 12 months" from the dropdown
                    for opt in ["Last 12 months", "Last 6 months", "Last 12 weeks"]:
                        el = page.query_selector(
                            f"button:has-text('{opt}'), li:has-text('{opt}'), "
                            f"[role='option']:has-text('{opt}'), [role='menuitem']:has-text('{opt}'), "
                            f"div:has-text('{opt}'):not(:has(div))")
                        if el:
                            el.click()
                            time.sleep(5)
                            log(f"  Selected: {opt}")
                            break
                    break
        except Exception as e:
            log(f"  Time range error: {e}")

        time.sleep(3)

        # STEP 3: Change "Show: 10" to maximum
        log("Changing Show dropdown to maximum...")
        try:
            show_btns = page.query_selector_all("button, select")
            for btn in show_btns:
                txt = (btn.inner_text() or "").strip()
                if txt in ("10", "Show:\n10", "Show: 10") or "Show" in txt:
                    log(f"  Found Show button: '{txt}'")
                    btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    btn.click()
                    time.sleep(2)
                    # Select highest option
                    for num in ["100", "50", "20"]:
                        opt = page.query_selector(
                            f"button:has-text('{num}'), li:has-text('{num}'), "
                            f"[role='option']:has-text('{num}'), option[value='{num}']")
                        if opt:
                            opt.click()
                            time.sleep(4)
                            log(f"  Set Show to: {num}")
                            break
                    break
        except Exception as e:
            log(f"  Show dropdown error: {e}")

        time.sleep(4)

        # STEP 4: Paginate through ALL pages
        page_num = 1
        while True:
            log(f"Scraping page {page_num}...")
            time.sleep(3)

            # Scroll to make sure table is visible
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            page.evaluate("window.scrollBy(0, -500)")
            time.sleep(1)

            posts = _extract_posts(page)
            log(f"  Page {page_num}: {len(posts)} posts")
            all_posts.extend(posts)

            # Click Next
            try:
                next_btn = None
                all_btns = page.query_selector_all("button, a")
                for btn in all_btns:
                    txt = (btn.inner_text() or "").strip()
                    aria = btn.get_attribute("aria-label") or ""
                    if txt == "Next" or "Next" in aria or txt == "›":
                        if btn.is_visible() and btn.is_enabled():
                            next_btn = btn
                            break

                if next_btn:
                    next_btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    next_btn.click()
                    time.sleep(4)
                    page_num += 1
                    log(f"  Clicked Next -> page {page_num}")
                else:
                    log("  No more pages")
                    break
            except Exception as e:
                log(f"  Next error: {e}")
                break

            if page_num > 15:
                log("  Safety limit"); break

        browser.close()

    log(f"Total: {len(all_posts)} posts from {page_num} pages")
    return all_posts

def _extract_posts(page):
    posts = []
    try:
        rows = page.query_selector_all("tr")
        for row in rows:
            try:
                cells = row.query_selector_all("td")
                if len(cells) < 4: continue
                texts = [c.inner_text().strip() for c in cells]
                if any(h in texts[0] for h in ["Post title","Impressions","Title"]): continue

                def si(s):
                    try: return int(re.sub(r"[^\d]","",str(s)) or "0")
                    except: return 0
                def sf(s):
                    try: return float(re.sub(r"[^\d.]","",str(s)) or "0")
                    except: return 0.0

                pub_date = None
                dm = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", texts[0])
                if dm:
                    try: pub_date = datetime.strptime(dm.group(1),"%m/%d/%Y").strftime("%Y-%m-%d")
                    except: pass

                post = {
                    "title": texts[0][:500],
                    "post_type": texts[1] if len(texts)>1 else "",
                    "audience": texts[2] if len(texts)>2 else "",
                    "impressions": si(texts[3]) if len(texts)>3 else 0,
                    "views": si(texts[4]) if len(texts)>4 else 0,
                    "clicks": si(texts[5]) if len(texts)>5 else 0,
                    "ctr": sf(texts[6]) if len(texts)>6 else 0,
                    "reactions": si(texts[7]) if len(texts)>7 else 0,
                    "comments": si(texts[8]) if len(texts)>8 else 0,
                    "reposts": si(texts[9]) if len(texts)>9 else 0,
                    "follows": si(texts[10]) if len(texts)>10 else 0,
                    "engagement_rate": sf(texts[11]) if len(texts)>11 else 0,
                    "published_at": pub_date,
                }
                if post["impressions"] > 0 or post["reactions"] > 0:
                    posts.append(post)
            except: continue
    except Exception as e:
        log(f"  Extract error: {e}")
    return posts

def save_to_supabase(posts):
    sb = _get_sb()
    if not sb: log("MongoDB not configured"); return 0
    rows = []
    for p in posts:
        title = p.get("title","")[:200]
        pub = p.get("published_at") or ""
        urn = "li::" + hashlib.sha1((title + pub).encode()).hexdigest()[:16]
        rows.append({
            "urn":urn, "title":p["title"][:500],
            "post_type":p.get("post_type","")[:50],
            "audience":p.get("audience","")[:100],
            "published_at":(pub+"T00:00:00+00:00") if pub else None,
            "impressions":p.get("impressions",0),
            "views":p.get("views",0), "clicks":p.get("clicks",0),
            "ctr":p.get("ctr",0), "reactions":p.get("reactions",0),
            "comments":p.get("comments",0), "reposts":p.get("reposts",0),
            "follows":p.get("follows",0),
            "engagement_rate":p.get("engagement_rate",0),
            "last_updated":datetime.utcnow().isoformat(),
        })
    errors = 0
    for i in range(0,len(rows),20):
        try: upsert_many("linkedin_posts", rows[i:i+20], "urn")
        except Exception as e:
            errors += 1
            if errors <= 3: log(f"Upsert error: {e}")
    log(f"Saved {len(rows)} posts, {errors} errors")
    return len(rows)

def run():
    log("="*60)
    log("LINKEDIN ALL POSTS SCRAPER")
    log("="*60)
    posts = scrape_all_posts()
    if posts:
        saved = save_to_supabase(posts)
        cache = {"scraped_at":datetime.utcnow().isoformat(),"posts":posts,"count":len(posts)}
        (DATA_DIR/"linkedin_all_posts.json").write_text(json.dumps(cache,indent=2,default=str))
        return saved
    return 0

if __name__ == "__main__":
    count = run()
    print(f"\nTotal: {count} posts saved")
