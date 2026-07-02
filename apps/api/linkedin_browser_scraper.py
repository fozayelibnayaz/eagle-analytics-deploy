#!/usr/bin/env python3
"""


LinkedIn Full Browser Scraper - All Admin Analytics Pages
Scrapes 7 LinkedIn admin pages using Playwright + cookies:
  1. /admin/analytics/updates/        - posts performance
  2. /admin/analytics/visitors/       - visitor demographics
  3. /admin/analytics/followers/      - follower growth + demographics
  4. /admin/analytics/search-appearances/ - search visibility
  5. /admin/analytics/competitors/    - competitor comparison
  6. /admin/analytics/leads/          - lead gen analytics
  7. /admin/analytics/newsletters/    - newsletter performance
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






COOKIES_FILE = DATA_DIR / "linkedin_cookies.json"
CACHE_FILE   = DATA_DIR / "linkedin_full_analytics.json"
COMPANY_ID   = "68624141"
NEWSLETTER_URN = "urn:li:fsd_contentSeries:7332986018540728320"

URLS = {
    "updates":            f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/updates/",
    "visitors":           f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/visitors/",
    "followers":          f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/followers/",
    "search_appearances": f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/search-appearances/",
    "competitors":        f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/competitors/",
    "leads":              f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/leads/",
    "newsletters":        f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/newsletters/{NEWSLETTER_URN}/",
}


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [LinkedIn] {m}", flush=True)


def _load_cookies():
    if COOKIES_FILE.exists():
        try:
            c = json.loads(COOKIES_FILE.read_text())
            return c if isinstance(c, list) else json.loads(c)
        except Exception as e:
            log(f"Cookie load error: {e}")
    return []


def _get_supabase():
    return get_db()


def _setup_browser(headless=False):
    """If session_state.json exists, use headless. Otherwise show browser."""
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    session_file = DATA_DIR / "linkedin_session_state.json"
    use_headless = headless if session_file.exists() else False
    browser = p.chromium.launch(
        headless=use_headless,
        args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--disable-gpu",'--disable-blink-features=AutomationControlled'],
    )
    # Prefer saved session state (more reliable than cookies alone)
    session_file = DATA_DIR / "linkedin_session_state.json"
    context_args = {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport":   {"width": 1440, "height": 900},
    }
    if session_file.exists():
        log(f"Using saved session state: {session_file}")
        context_args["storage_state"] = str(session_file)
    context = browser.new_context(**context_args)

    # Load cookies (additional - in case session state missing or stale)
    cookies = _load_cookies()
    pw_cookies = []
    for c in cookies:
        try:
            domain = c.get("domain", ".linkedin.com")
            if not domain.startswith("."):
                domain = "." + domain.lstrip(".")
            pw_c = {
                "name":     c["name"],
                "value":    c["value"],
                "domain":   domain,
                "path":     c.get("path", "/"),
                "secure":   c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
            }
            exp = c.get("expirationDate")
            if exp and not c.get("session"):
                pw_c["expires"] = int(exp)
            pw_cookies.append(pw_c)
        except Exception:
            continue
    context.add_cookies(pw_cookies)
    page = context.new_page()
    return p, browser, page


def _safe_int(s):
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0


def _safe_float(s):
    try:
        return float(re.sub(r"[^\d.]", "", str(s)) or "0")
    except Exception:
        return 0.0


def _wait_load(page, timeout=20000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    time.sleep(3)


def _set_max_date_range(page):
    """Force date range to Last 365 days by finding date filter button next to Export."""
    try:
        # LinkedIn analytics pages have a date picker button.
        # It usually displays a date range like "May 22, 2026 - Jun 20, 2026"
        # Strategy: find any button containing month names or year numbers
        time.sleep(2)

        # Try clicking date picker by multiple strategies
        clicked = False
        # Strategy 1: button with date range text
        for pattern in [
            "button:has-text('Jun ')",
            "button:has-text('May ')",
            "button:has-text('Apr ')",
            "button:has-text('Mar ')",
            "button:has-text('Last ')",
            "button:has-text('Past ')",
            "[aria-label*='Date range' i]",
            "[aria-label*='time range' i]",
            "button[id*='date']",
            "button[class*='date']",
            "[data-test-id*='time-range']",
            ".artdeco-dropdown__trigger",
        ]:
            try:
                btns = page.query_selector_all(pattern)
                for btn in btns:
                    txt = (btn.inner_text() or "").strip()
                    # Only click if it looks like a date range
                    if any(m in txt for m in ["2025", "2026", "days", "Last", "Past", "year", "month"]):
                        btn.click()
                        time.sleep(2)
                        log(f"  Clicked date picker: '{txt[:60]}'")
                        clicked = True
                        break
                if clicked:
                    break
            except Exception:
                continue

        if not clicked:
            log("  WARN: Could not find date picker button")
            return False

        time.sleep(2)

        # Now find "Last 365 days" option in dropdown
        for opt_text in [
            "Last 365 days", "Last year", "Past year",
            "Past 365 days", "365 days", "1 year", "Past 1 year",
        ]:
            try:
                # Try multiple element types
                for sel in [
                    f"button:has-text('{opt_text}')",
                    f"li:has-text('{opt_text}')",
                    f"[role='option']:has-text('{opt_text}')",
                    f"[role='menuitem']:has-text('{opt_text}')",
                    f"div:has-text('{opt_text}'):not(:has(*))",
                    f"span:has-text('{opt_text}'):not(:has(*))",
                ]:
                    opt = page.query_selector(sel)
                    if opt:
                        try:
                            opt.click()
                            time.sleep(3)
                            log(f"  Selected: {opt_text}")
                            # Wait for data to reload
                            try:
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception:
                                pass
                            time.sleep(3)
                            return True
                        except Exception:
                            continue
            except Exception:
                continue

        # If "Last 365 days" not in dropdown, try clicking "Custom" and entering dates
        log("  Last 365 days not in dropdown - trying alternative")
        return False
    except Exception as e:
        log(f"  Date range error: {e}")
        return False


def _extract_highlights(page, patterns):
    """Extract highlight metrics from page text using regex patterns."""
    out = {}
    try:
        body = page.inner_text("body")
        for key, pat in patterns.items():
            m = re.search(pat, body, re.I)
            if m:
                try:
                    out[key] = _safe_int(m.group(1))
                except Exception:
                    pass
    except Exception as e:
        log(f"  Highlights error: {e}")
    return out


def _scroll_full(page, max_scrolls=80):
    """Scroll to load all dynamic content (LinkedIn lazy loads)."""
    last_height = 0
    same_count = 0
    for i in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        try:
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                same_count += 1
                if same_count >= 3:
                    break
            else:
                same_count = 0
            last_height = new_height
        except Exception:
            time.sleep(1)

    # Try clicking "Show more" or "Load more" buttons
    for _ in range(20):
        try:
            btn = page.query_selector("button:has-text('Show more'), button:has-text('Load more'), button:has-text('See more')")
            if btn:
                btn.click()
                time.sleep(2)
            else:
                break
        except Exception:
            break


def _extract_table_rows(page):
    """Extract data from any tables/grids on page - handles divs and tables."""
    rows_data = []
    try:
        # Try table rows first
        rows = page.query_selector_all("tr, [role='row'], .artdeco-table tr, [data-test-id*='row'], [data-test-id*='card']")
        for row in rows:
            try:
                cells = row.query_selector_all("td, [role='cell'], [role='gridcell'], th, [data-test-id*='cell']")
                if len(cells) < 2:
                    # Try grabbing all text as single field
                    txt = row.inner_text().strip()
                    if txt and len(txt) > 5:
                        lines = [l.strip() for l in txt.split("\n") if l.strip()]
                        if len(lines) >= 2:
                            rows_data.append(lines)
                    continue
                texts = []
                for c in cells:
                    try:
                        texts.append(c.inner_text().strip())
                    except Exception:
                        texts.append("")
                if any(texts):
                    rows_data.append(texts)
            except Exception:
                continue

        # Fallback: extract from analytics card divs
        if len(rows_data) < 3:
            cards = page.query_selector_all("[class*='analytics-update'], [class*='post-card'], [class*='content-engagement'], li[class*='post']")
            for card in cards:
                try:
                    txt = card.inner_text().strip()
                    if txt and len(txt) > 10:
                        lines = [l.strip() for l in txt.split("\n") if l.strip()]
                        if lines:
                            rows_data.append(lines)
                except Exception:
                    continue
    except Exception as e:
        log(f"  Table extract: {e}")
    return rows_data


def _save_debug(page, name):
    debug_path = DATA_DIR / f"linkedin_debug_{name}.html"
    try:
        debug_path.write_text(page.content())
        log(f"  Debug HTML: {debug_path}")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# PAGE-SPECIFIC SCRAPERS
# ─────────────────────────────────────────────────────────────

def scrape_updates(page):
    """Scrape posts by intercepting LinkedIn XHR responses (loads ALL data)."""
    log("=" * 50)
    log("UPDATES (Posts Analytics) - XHR INTERCEPT MODE")
    log("=" * 50)
    out = {"highlights": {}, "posts": []}

    captured_responses = []

    def _on_response(resp):
        try:
            url = resp.url
            if any(k in url for k in [
                "organizationShareStatistics",
                "organizationalEntityShareStatistics",
                "organizationPageStatistics",
                "feed/updates",
                "analytics/updates",
                "organization/companies",
                "shareUpdates",
            ]):
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        body = resp.json()
                        captured_responses.append({"url": url, "body": body})
                    except Exception:
                        pass
        except Exception:
            pass

    page.on("response", _on_response)

    page.goto(URLS["updates"], timeout=60000, wait_until="domcontentloaded")
    _wait_load(page)

    if "authwall" in page.url or "login" in page.url:
        log("LOGIN REDIRECT - cookies expired")
        return out

    _set_max_date_range(page)
    time.sleep(5)

    # Aggressive load with multiple scrolls + Show more
    log("  Loading all posts via scroll + show more...")
    for i in range(40):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)
        for sel in ["button:has-text('Show more')", "button:has-text('Load more')",
                    "button:has-text('See more')", "[aria-label*='Show more' i]"]:
            try:
                btns = page.query_selector_all(sel)
                for btn in btns:
                    if btn.is_visible():
                        btn.click()
                        time.sleep(2)
            except Exception:
                pass

    time.sleep(4)
    log(f"  Captured {len(captured_responses)} XHR responses")

    # Parse captured responses for post data
    seen_urns = set()
    for cap in captured_responses:
        body = cap.get("body", {})
        elements = body.get("elements", []) or body.get("results", [])
        if not isinstance(elements, list):
            continue
        for el in elements:
            if not isinstance(el, dict):
                continue
            ts = el.get("totalShareStatistics") or el.get("statistics", {})
            share = el.get("share", "") or el.get("shareUrn", "") or el.get("urn", "") or el.get("entity", "")
            if not share or share in seen_urns:
                continue
            seen_urns.add(share)
            imps = int(ts.get("impressionCount", 0) or ts.get("impressions", 0) or 0)
            clicks = int(ts.get("clickCount", 0) or ts.get("clicks", 0) or 0)
            likes = int(ts.get("likeCount", 0) or ts.get("likes", 0) or 0)
            comments = int(ts.get("commentCount", 0) or ts.get("comments", 0) or 0)
            shares_ct = int(ts.get("shareCount", 0) or ts.get("shares", 0) or 0)
            engagement = int(ts.get("engagement", 0)) if ts.get("engagement") else (likes + comments + shares_ct)
            ctr = (clicks / imps * 100) if imps else 0
            er = (engagement / imps * 100) if imps else 0
            if imps > 0 or likes > 0:
                out["posts"].append({
                    "urn":             share[:200],
                    "title":           "",
                    "post_type":       "",
                    "audience":        "",
                    "impressions":     imps,
                    "views":           imps,
                    "clicks":          clicks,
                    "ctr":             round(ctr, 2),
                    "reactions":       likes,
                    "comments":        comments,
                    "reposts":         shares_ct,
                    "follows":         0,
                    "engagement_rate": round(er, 2),
                    "scraped_at":      datetime.utcnow().isoformat(),
                })

    log(f"  XHR posts extracted: {len(out['posts'])}")

    # Also try DOM scraping for titles
    rows = _extract_table_rows(page)
    log(f"  DOM rows found: {len(rows)}")
    dom_posts = []
    for r in rows:
        if not r or len(r) < 4:
            continue
        if any(h in r[0] for h in ["Post title", "Impressions", "Reactions"]):
            continue
        dom_posts.append({
            "title":           r[0][:300],
            "post_type":       r[1] if len(r) > 1 else "",
            "audience":        r[2] if len(r) > 2 else "",
            "impressions":     _safe_int(r[3]) if len(r) > 3 else 0,
            "views":           _safe_int(r[4]) if len(r) > 4 else 0,
            "clicks":          _safe_int(r[5]) if len(r) > 5 else 0,
            "ctr":             _safe_float(r[6]) if len(r) > 6 else 0.0,
            "reactions":       _safe_int(r[7]) if len(r) > 7 else 0,
            "comments":        _safe_int(r[8]) if len(r) > 8 else 0,
            "reposts":         _safe_int(r[9]) if len(r) > 9 else 0,
            "follows":         _safe_int(r[10]) if len(r) > 10 else 0,
            "engagement_rate": _safe_float(r[11]) if len(r) > 11 else 0.0,
            "scraped_at":      datetime.utcnow().isoformat(),
            "urn":             f"dom::{abs(hash(r[0]))}",
        })

    # Merge: use DOM titles to enrich XHR posts, OR if no XHR data, use DOM
    if dom_posts:
        if not out["posts"]:
            out["posts"] = dom_posts
        else:
            # Match by impression count + likes (rough heuristic)
            for dp in dom_posts:
                matched = False
                for xp in out["posts"]:
                    if abs(xp["impressions"] - dp["impressions"]) < 5 and abs(xp["reactions"] - dp["reactions"]) < 2:
                        xp["title"] = dp["title"]
                        xp["post_type"] = dp.get("post_type", "")
                        xp["audience"] = dp.get("audience", "")
                        matched = True
                        break
                if not matched:
                    out["posts"].append(dp)

    log(f"  Final posts: {len(out['posts'])}")

    # Highlights
    body_text = page.inner_text("body")
    import re as _re
    patterns = {
        "impressions": r"([\d,]+)\s*(?:\n|\s)+Impressions",
        "reactions":   r"([\d,]+)\s*(?:\n|\s)+Reactions",
        "comments":    r"([\d,]+)\s*(?:\n|\s)+Comments",
        "reposts":     r"([\d,]+)\s*(?:\n|\s)+Reposts",
        "clicks":      r"([\d,]+)\s*(?:\n|\s)+Clicks",
    }
    for key, pat in patterns.items():
        m = _re.search(pat, body_text, _re.I)
        if m:
            try:
                out["highlights"][key] = _safe_int(m.group(1))
            except Exception:
                pass
    log(f"Highlights: {out['highlights']}")

    page.remove_listener("response", _on_response)
    return out



def scrape_visitors(page):
    log("=" * 50)
    log("VISITORS")
    log("=" * 50)
    out = {"highlights": {}, "demographics": {}, "by_date": []}

    page.goto(URLS["visitors"], timeout=45000, wait_until="domcontentloaded")
    _wait_load(page)
    _set_max_date_range(page)
    _scroll_full(page)

    out["highlights"] = _extract_highlights(page, {
        "page_views":       r"([\d,]+)\s*(?:Page views|page views)",
        "unique_visitors":  r"([\d,]+)\s*(?:Unique visitors|unique visitors)",
        "custom_button":    r"([\d,]+)\s*(?:Custom button)",
    })
    log(f"Visitor highlights: {out['highlights']}")

    rows = _extract_table_rows(page)
    for r in rows:
        if len(r) >= 2 and r[0]:
            out["by_date"].append({"category": r[0], "values": r[1:]})

    if not out["highlights"]:
        _save_debug(page, "visitors")
    return out


def scrape_followers(page):
    log("=" * 50)
    log("FOLLOWERS")
    log("=" * 50)
    out = {"total": 0, "highlights": {}, "demographics": {}, "by_date": []}

    page.goto(URLS["followers"], timeout=45000, wait_until="domcontentloaded")
    _wait_load(page)
    _set_max_date_range(page)
    _scroll_full(page)

    body = page.inner_text("body")
    m = re.search(r"([\d,]+)\s*(?:total\s+)?followers", body, re.I)
    if m:
        out["total"] = _safe_int(m.group(1))
    log(f"Total followers: {out['total']}")

    out["highlights"] = _extract_highlights(page, {
        "new_followers":  r"([\d,]+)\s*(?:New followers|new followers)",
        "organic":        r"([\d,]+)\s*(?:Organic|organic)",
        "sponsored":      r"([\d,]+)\s*(?:Sponsored|sponsored)",
    })

    # Try to extract chart data
    try:
        chart_data = page.evaluate("""() => {
            const scripts = document.querySelectorAll('script, code');
            for (const s of scripts) {
                const t = s.textContent || '';
                if (t.includes('followerGains') || t.includes('organicFollowerCounts')) {
                    return t.substring(0, 100000);
                }
            }
            return null;
        }""")
        if chart_data:
            pairs = re.findall(r'"start":(\d+).*?"organicFollowerGains":(\d+)', chart_data)
            for ts, count in pairs[:400]:
                try:
                    d = datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
                    out["by_date"].append({
                        "date":          d,
                        "organic_gains": _safe_int(count),
                        "paid_gains":    0,
                        "total":         _safe_int(count),
                    })
                except Exception:
                    continue
            log(f"Daily followers extracted: {len(out['by_date'])}")
    except Exception as e:
        log(f"Chart extract: {e}")

    if not out["total"] and not out["by_date"]:
        _save_debug(page, "followers")
    return out


def scrape_search_appearances(page):
    log("=" * 50)
    log("SEARCH APPEARANCES")
    log("=" * 50)
    out = {"highlights": {}, "keywords": [], "companies": []}

    page.goto(URLS["search_appearances"], timeout=45000, wait_until="domcontentloaded")
    _wait_load(page)
    _set_max_date_range(page)
    _scroll_full(page)

    out["highlights"] = _extract_highlights(page, {
        "appearances":     r"([\d,]+)\s*(?:Appearances|appearances)",
        "search_keywords": r"([\d,]+)\s*(?:keywords|Keywords)",
    })
    log(f"Search appearances: {out['highlights']}")

    rows = _extract_table_rows(page)
    for r in rows:
        if len(r) >= 2 and r[0]:
            out["keywords"].append({
                "keyword":     r[0],
                "count":       _safe_int(r[1]) if len(r) > 1 else 0,
                "extra":       r[2:] if len(r) > 2 else [],
            })

    if not out["highlights"] and not out["keywords"]:
        _save_debug(page, "search_appearances")
    return out


def scrape_competitors(page):
    log("=" * 50)
    log("COMPETITORS")
    log("=" * 50)
    out = {"competitors": []}

    page.goto(URLS["competitors"], timeout=45000, wait_until="domcontentloaded")
    _wait_load(page)
    _scroll_full(page)

    rows = _extract_table_rows(page)
    for r in rows:
        if len(r) >= 2 and r[0]:
            out["competitors"].append({
                "name":              r[0],
                "followers":         _safe_int(r[1]) if len(r) > 1 else 0,
                "follower_growth":   r[2] if len(r) > 2 else "",
                "post_engagements":  _safe_int(r[3]) if len(r) > 3 else 0,
                "engagement_rate":   r[4] if len(r) > 4 else "",
                "posts":             _safe_int(r[5]) if len(r) > 5 else 0,
                "extra":             r[6:] if len(r) > 6 else [],
            })

    log(f"Competitors extracted: {len(out['competitors'])}")
    if not out["competitors"]:
        _save_debug(page, "competitors")
    return out


def scrape_leads(page):
    log("=" * 50)
    log("LEADS")
    log("=" * 50)
    out = {"highlights": {}, "forms": [], "leads_list": []}

    page.goto(URLS["leads"], timeout=45000, wait_until="domcontentloaded")
    _wait_load(page)
    _set_max_date_range(page)
    _scroll_full(page)

    out["highlights"] = _extract_highlights(page, {
        "leads":         r"([\d,]+)\s*(?:Leads|leads)\b",
        "form_views":    r"([\d,]+)\s*(?:Form views|form views)",
        "conversion":    r"([\d.]+%)\s*(?:Conversion|conversion)",
    })
    log(f"Leads highlights: {out['highlights']}")

    rows = _extract_table_rows(page)
    for r in rows:
        if len(r) >= 2 and r[0]:
            out["forms"].append({"form": r[0], "values": r[1:]})

    if not out["highlights"] and not out["forms"]:
        _save_debug(page, "leads")
    return out


def scrape_newsletters(page):
    log("=" * 50)
    log("NEWSLETTERS")
    log("=" * 50)
    out = {"highlights": {}, "articles": []}

    page.goto(URLS["newsletters"], timeout=45000, wait_until="domcontentloaded")
    _wait_load(page)
    _scroll_full(page)

    out["highlights"] = _extract_highlights(page, {
        "subscribers":   r"([\d,]+)\s*(?:Subscribers|subscribers)",
        "open_rate":     r"([\d.]+%)\s*(?:Open rate|open rate)",
        "articles_count":r"([\d,]+)\s*(?:Articles|articles)",
    })
    log(f"Newsletter highlights: {out['highlights']}")

    rows = _extract_table_rows(page)
    for r in rows:
        if len(r) >= 2 and r[0]:
            out["articles"].append({
                "title":      r[0][:300],
                "views":      _safe_int(r[1]) if len(r) > 1 else 0,
                "reactions":  _safe_int(r[2]) if len(r) > 2 else 0,
                "comments":   _safe_int(r[3]) if len(r) > 3 else 0,
                "shares":     _safe_int(r[4]) if len(r) > 4 else 0,
            })

    log(f"Articles: {len(out['articles'])}")
    if not out["highlights"] and not out["articles"]:
        _save_debug(page, "newsletters")
    return out


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def scrape_all():
    result = {
        "scraped_at":         datetime.utcnow().isoformat(),
        "updates":            {},
        "visitors":           {},
        "followers":          {},
        "search_appearances": {},
        "competitors":        {},
        "leads":              {},
        "newsletters":        {},
        "error":              None,
    }

    cookies = _load_cookies()
    if not cookies:
        result["error"] = "No cookies found at data_output/linkedin_cookies.json"
        return result

    try:
        p, browser, page = _setup_browser()
    except Exception as e:
        result["error"] = f"Browser setup failed: {e}"
        return result

    try:
        # Test login first
        page.goto("https://www.linkedin.com/feed/", timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)
        if "login" in page.url.lower() or "authwall" in page.url.lower():
            result["error"] = f"Login redirect: {page.url}"
            log(result["error"])
            browser.close()
            p.stop()
            return result
        log(f"Logged in: {page.url}")

        # Run all scrapers
        result["updates"]            = scrape_updates(page)
        result["visitors"]           = scrape_visitors(page)
        result["followers"]          = scrape_followers(page)
        result["search_appearances"] = scrape_search_appearances(page)
        result["competitors"]        = scrape_competitors(page)
        result["leads"]              = scrape_leads(page)
        result["newsletters"]        = scrape_newsletters(page)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass

    DATA_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(result, indent=2, default=str))
    log(f"Saved: {CACHE_FILE}")

    _save_to_supabase(result)

    return result


def _save_to_supabase(data):
    sb = _get_supabase()
    if sb is None:
        log("MongoDB not configured - skipped")
        return False

    # Posts
    posts = data.get("updates", {}).get("posts", [])
    if posts:
        rows = []
        for p in posts:
            urn = f"scraped::{abs(hash(p['title']))}"
            rows.append({
                "urn":              urn,
                "text":             p["title"][:500],
                "published_at":     None,
                "impressions":      p.get("impressions", 0),
                "clicks":           p.get("clicks", 0),
                "ctr":              p.get("ctr", 0),
                "reactions":        p.get("reactions", 0),
                "comments":         p.get("comments", 0),
                "shares":           p.get("reposts", 0),
                "engagement_rate":  p.get("engagement_rate", 0),
                "url":              "",
                "updated_at":       datetime.utcnow().isoformat(),
            })
        try:
            log(f"Posts upserted: {len(rows)}")
        except Exception as e:
            log(f"Posts upsert error: {e}")

    # Daily followers
    fd = data.get("followers", {}).get("by_date", [])
    if fd:
        rows = [{
            "date":          f["date"],
            "organic_gains": f.get("organic_gains", 0),
            "paid_gains":    f.get("paid_gains", 0),
            "total":         f.get("total", 0),
        } for f in fd if f.get("date")]
        try:
            log(f"Follower days upserted: {len(rows)}")
        except Exception as e:
            log(f"Followers upsert error: {e}")

    # Full snapshot in analytics_cache
    try:
        upsert_one(
            "analytics_cache",
            {
                "source": "linkedin_full",
                "metric_date": datetime.now().strftime("%Y-%m-%d"),
            },
            {
                "source": "linkedin_full",
                "metric_date": datetime.now().strftime("%Y-%m-%d"),
                "period_type": "365days",
                "data": data,
                "fetched_at": datetime.utcnow().isoformat(),
                "is_valid": True,
            },
        )
        log("analytics_cache upserted")
    except Exception as e:
        log(f"analytics_cache error: {e}")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("LINKEDIN FULL SCRAPER - 7 ANALYTICS PAGES")
    print("=" * 60)
    print("\nBrowser will open. Wait for it to finish.\n")
    result = scrape_all()

    print("\n" + "=" * 60)
    print("RESULT SUMMARY")
    print("=" * 60)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
    else:
        print(f"Updates posts:         {len(result['updates'].get('posts', []))}")
        print(f"Updates highlights:    {result['updates'].get('highlights', {})}")
        print(f"Visitors highlights:   {result['visitors'].get('highlights', {})}")
        print(f"Followers total:       {result['followers'].get('total')}")
        print(f"Follower days:         {len(result['followers'].get('by_date', []))}")
        print(f"Search appearances:    {result['search_appearances'].get('highlights', {})}")
        print(f"Search keywords:       {len(result['search_appearances'].get('keywords', []))}")
        print(f"Competitors:           {len(result['competitors'].get('competitors', []))}")
        print(f"Leads highlights:      {result['leads'].get('highlights', {})}")
        print(f"Newsletter articles:   {len(result['newsletters'].get('articles', []))}")
