"""
LinkedIn Connector — Eagle Analytics Hub v7.2
==============================================
Scrapes LinkedIn company page data including:
- Company metrics (followers, employees, industry)
- Individual posts with impressions, likes, comments, engagement
- Daily time-series auto-accumulation
- Historical data for trends

3 methods:
1. Public page scrape (urllib, no auth) — limited
2. Authenticated Playwright scrape (pipeline) — full data
3. Manual entry + CSV import (dashboard UI)
"""

import os
import json
import re
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

LI_METRICS_CACHE = DATA_DIR / "linkedin_metrics.json"
LI_POSTS_CACHE = DATA_DIR / "linkedin_posts.json"
LI_DAILY_CACHE = DATA_DIR / "linkedin_daily.json"
LI_FOLLOWERS_CACHE = DATA_DIR / "linkedin_followers.json"
LI_COOKIES_PATH = DATA_DIR / "linkedin_cookies.json"


def _get_secret(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        if key in st.secrets:
            val = st.secrets[key]
            if val is not None and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return default


def _load_json(path: Path, max_age_hours: int = 6) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        ts = data.get("_cached_at", "")
        if ts:
            cached_time = datetime.fromisoformat(ts)
            if datetime.now() - cached_time < timedelta(hours=max_age_hours):
                return data
    except Exception:
        pass
    return None


def _save_json(path: Path, data: dict):
    data["_cached_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(data, default=str, indent=2))


def _get_cookies() -> str:
    val = _get_secret("LINKEDIN_COOKIES_JSON", "")
    if val:
        return val
    if LI_COOKIES_PATH.exists():
        return LI_COOKIES_PATH.read_text()
    return ""


def _get_company_page() -> str:
    url = _get_secret("LINKEDIN_COMPANY_PAGE", "")
    if not url:
        url = "https://www.linkedin.com/company/eagle-3d-streaming/"
    return url


# ═══════════════════════════════════════════════════════════════
# METHOD 1: Public Page Scraping (Works everywhere, no Playwright)
# ═══════════════════════════════════════════════════════════════

def scrape_public_metrics() -> Dict[str, Any]:
    """Scrape public metrics from LinkedIn company page using urllib.
    BULLETPROOF: Extracts data from JSON-LD structured data + HTML patterns.
    No cookies or authentication required."""
    import urllib.request
    import urllib.error

    company_page = _get_company_page()
    if not company_page:
        return {"error": "LINKEDIN_COMPANY_PAGE not configured", "demo": True}

    if not company_page.startswith("http"):
        company_page = f"https://www.linkedin.com/company/{company_page.strip('/')}/"

    try:
        req = urllib.request.Request(
            company_page,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        result = _extract_public_data(html, company_page)
        
        # Also extract posts from JSON-LD
        posts = _extract_posts_from_jsonld(html)
        if posts:
            result["posts"] = posts
            result["post_count"] = len(posts)
            result["total_post_likes"] = sum(p.get("likes", 0) for p in posts)
            result["total_post_comments"] = sum(p.get("comments", 0) for p in posts)
        
        _save_json(LI_METRICS_CACHE, result)
        return result

    except Exception as e:
        print(f"[LinkedIn] Public scrape error: {e}")
        return {"error": str(e), "demo": True}


def _extract_posts_from_jsonld(html: str) -> List[Dict]:
    """Extract recent posts from LinkedIn's structured data + HTML engagement metrics.
    Uses JSON-LD for post content, then enriches with aria-label reactions from HTML.
    This is 100% free and requires no authentication."""
    posts = []
    
    # Step 1: Parse JSON-LD for post content (text, date, URL)
    jsonld_posts = []
    try:
        m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            ld_data = json.loads(m.group(1))
            graph = ld_data.get("@graph", [])
            if not graph and isinstance(ld_data, list):
                graph = ld_data
            if not graph and ld_data.get("@type") == "DiscussionForumPosting":
                graph = [ld_data]
            
            for item in graph:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") != "DiscussionForumPosting":
                    continue
                
                post = {
                    "title": item.get("name", ""),
                    "text": item.get("text", "")[:500],
                    "url": item.get("mainEntityOfPage", item.get("url", "")),
                    "published_at": item.get("datePublished", ""),
                    "author": item.get("author", {}).get("name", ""),
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "source": "linkedin_jsonld",
                }
                
                # Extract engagement from interactionStatistic
                stats = item.get("interactionStatistic", [])
                if isinstance(stats, dict):
                    stats = [stats]
                for stat in stats:
                    if not isinstance(stat, dict):
                        continue
                    stat_type = stat.get("interactionType", "")
                    count = 0
                    try:
                        count = int(stat.get("userInteractionCount", 0))
                    except (ValueError, TypeError):
                        pass
                    if "Like" in str(stat_type) or "like" in str(stat_type).lower():
                        post["likes"] = count
                    elif "Comment" in str(stat_type) or "comment" in str(stat_type).lower():
                        post["comments"] = count
                    elif "Share" in str(stat_type) or "share" in str(stat_type).lower():
                        post["shares"] = count
                
                jsonld_posts.append(post)
    except Exception as e:
        print(f"[LinkedIn] JSON-LD extraction error: {e}")
    
    # Step 2: Extract engagement from HTML post cards (aria-label reactions)
    # LinkedIn embeds "5 Reactions", "2 comments" in aria-label attributes
    _html_engagement = {}
    try:
        post_cards = re.findall(
            r'data-id="main-feed-card"(.*?)(?=data-id="main-feed-card"|<div class="org-feed|$)',
            html, re.DOTALL
        )
        for card in post_cards:
            urn_match = re.search(r'urn:li:activity:(\d+)', card)
            if not urn_match:
                continue
            urn = urn_match.group(1)
            
            # Reactions (likes)
            reactions = re.findall(r'aria-label="(\d+)\s+Reaction', card)
            likes = int(reactions[0]) if reactions else 0
            
            # Comments
            comments = re.findall(r'(\d+)\s*comment', card, re.IGNORECASE)
            comment_count = int(comments[0]) if comments else 0
            
            # Reposts
            reposts = re.findall(r'(\d+)\s*repost', card, re.IGNORECASE)
            repost_count = int(reposts[0]) if reposts else 0
            
            _html_engagement[urn] = {
                "likes": likes,
                "comments": comment_count,
                "reposts": repost_count,
            }
    except Exception as e:
        print(f"[LinkedIn] HTML engagement extraction error: {e}")
    
    # Step 3: Merge JSON-LD posts with HTML engagement
    if jsonld_posts:
        for post in jsonld_posts:
            # Try to match by activity URN in the post URL
            url = post.get("url", "")
            urn_match = re.search(r'activity-(\d+)', url)
            if urn_match and urn_match.group(1) in _html_engagement:
                eng = _html_engagement[urn_match.group(1)]
                if eng["likes"] > 0:
                    post["likes"] = eng["likes"]
                if eng["comments"] > 0:
                    post["comments"] = eng["comments"]
                if eng["reposts"] > 0:
                    post["shares"] = eng["reposts"]
            posts.append(post)
    
    # Step 4: Add any HTML-only posts not in JSON-LD
    _used_urns = set()
    for p in posts:
        url = p.get("url", "")
        m = re.search(r'activity-(\d+)', url)
        if m:
            _used_urns.add(m.group(1))
    
    for urn, eng in _html_engagement.items():
        if urn not in _used_urns:
            posts.append({
                "title": "",
                "text": "",
                "url": f"https://www.linkedin.com/posts/eagle-3d-streaming_activity-{urn}",
                "published_at": "",
                "likes": eng["likes"],
                "comments": eng["comments"],
                "shares": eng["reposts"],
                "source": "linkedin_html",
            })
    
    # Step 5: If no JSON-LD or HTML posts, try regex fallback
    if not posts:
        try:
            activity_urls = re.findall(
                r'https://www\.linkedin\.com/posts/eagle-3d-streaming_[\w-]+-activity-(\d+)-[\w]+',
                html
            )
            if activity_urls:
                seen = set()
                for act_id in activity_urls[:10]:
                    if act_id not in seen:
                        seen.add(act_id)
                        posts.append({
                            "title": "",
                            "text": "",
                            "url": f"https://www.linkedin.com/posts/eagle-3d-streaming_activity-{act_id}",
                            "published_at": "",
                            "likes": 0,
                            "comments": 0,
                            "shares": 0,
                            "source": "linkedin_regex",
                        })
        except Exception:
            pass
    
    return posts


def _extract_public_data(html: str, url: str) -> Dict[str, Any]:
    """Extract metrics from LinkedIn public page HTML.
    BULLETPROOF: Uses multiple extraction methods — JSON-LD, meta tags, regex patterns."""
    result = {"company_page": url, "scraped_at": datetime.now().isoformat(), "demo": False}

    # ── Method 1: Extract from JSON-LD @graph (most reliable) ──
    try:
        m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            ld_data = json.loads(m.group(1))
            graph = ld_data.get("@graph", [])
            if isinstance(ld_data, list):
                graph = ld_data
            for item in graph:
                if not isinstance(item, dict):
                    continue
                author = item.get("author", {})
                if isinstance(author, dict) and author.get("name"):
                    if not result.get("company_name"):
                        result["company_name"] = author["name"]
                    if not result.get("company_url"):
                        result["company_url"] = author.get("url", "")
                # Extract follower count from interactionStatistic
                for stat in item.get("interactionStatistic", []):
                    if not isinstance(stat, dict):
                        continue
                    if "Follow" in str(stat.get("interactionType", "")):
                        try:
                            result["followers"] = int(stat.get("userInteractionCount", 0))
                        except (ValueError, TypeError):
                            pass
    except Exception:
        pass

    # ── Method 2: Regex patterns (fallback) ──
    # Follower count
    if not result.get("followers"):
        for pattern in [
            r'"followers":(\d+)', r'(\d[\d,]+)\s*followers',
            r'followerCount["\s:]+(\d+)', r'"totalFollowers":(\d+)',
            r'"standardizedFollowerCount":(\d+)',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                result["followers"] = int(m.group(1).replace(",", ""))
                break

    # Company name
    if not result.get("company_name"):
        for pattern in [
            r'<title>([^<]+?)(?:\s*\|\s*LinkedIn|\s*-\s*LinkedIn)',
            r'"name"\s*:\s*"([^"]+)"', r'"companyName"\s*:\s*"([^"]+)"',
        ]:
            m = re.search(pattern, html)
            if m:
                name = m.group(1).strip()
                if name.lower() not in ("sign up", "sign in", "linkedin", "login"):
                    result["company_name"] = name
                    break

    # Employee count
    if not result.get("employees"):
        for pattern in [
            r'(\d[\d,+]+)\s*(?:employees|associates|members)',
            r'"employeeCountRange"[^}]*?"end"\s*:\s*(\d+)',
            r'"staffCount"\s*:\s*(\d+)',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                result["employees"] = m.group(1).replace(",", "").replace("+", "")
                break

    # Industry
    if not result.get("industry"):
        for pattern in [r'"industry"\s*:\s*"([^"]+)"', r'"industryName"\s*:\s*"([^"]+)"']:
            m = re.search(pattern, html)
            if m:
                result["industry"] = m.group(1)
                break

    # Description
    if not result.get("description"):
        for pattern in [r'"description"\s*:\s*"([^"]{10,500})"', r'"tagline"\s*:\s*"([^"]{10,500})"']:
            m = re.search(pattern, html)
            if m:
                result["description"] = m.group(1)
                break

    # Website URL
    if not result.get("website"):
        for pattern in [r'"website"\s*:\s*"([^"]+)"', r'"companyPageUrl"\s*:\s*"([^"]+)"']:
            m = re.search(pattern, html)
            if m:
                result["website"] = m.group(1)
                break

    # Company type / size
    if not result.get("company_size"):
        m = re.search(r'"companySize"\s*:\s*"([^"]+)"', html)
        if m:
            result["company_size"] = m.group(1)

    # Headquarters
    if not result.get("headquarters"):
        m = re.search(r'"headquarters"[^}]*?"city"\s*:\s*"([^"]*)"[^}]*?"country"\s*:\s*"([^"]*)"', html)
        if m:
            result["headquarters"] = f"{m.group(1)}, {m.group(2)}"

    return result


# ═══════════════════════════════════════════════════════════════
# METHOD 2: Authenticated Playwright Scrape (Pipeline only)
# ═══════════════════════════════════════════════════════════════

def scrape_with_playwright(historical: bool = False) -> Dict[str, Any]:
    """Scrape LinkedIn analytics using Playwright. Pipeline only.
    Gets: company metrics + individual posts with engagement data."""
    cookies_json = _get_cookies()
    if not cookies_json:
        return scrape_public_metrics()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return scrape_public_metrics()

    company_page = _get_company_page()
    if not company_page:
        return {"error": "LINKEDIN_COMPANY_PAGE not configured", "demo": True}

    try:
        cookies = json.loads(cookies_json) if isinstance(cookies_json, str) else cookies_json
    except json.JSONDecodeError:
        return scrape_public_metrics()

    result = {"scraped_at": datetime.now().isoformat(), "demo": False}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1920, "height": 1080}
            )

            if isinstance(cookies, list):
                import html as _html
                formatted = [{
                    "name": c.get("name", ""),
                    "value": _html.unescape(str(c.get("value", ""))),
                    "domain": c.get("domain", ".linkedin.com"),
                    "path": c.get("path", "/"),
                } for c in cookies]
                context.add_cookies(formatted)

            page = context.new_page()

            # ── Scrape company metrics ──
            try:
                analytics_url = company_page.rstrip("/") + "/admin/analytics/"
                page.goto(analytics_url, wait_until="networkidle", timeout=30000)
                time.sleep(3)
                analytics = _extract_analytics_from_page(page.content())
                result.update(analytics)
            except Exception as e:
                print(f"[LinkedIn] Analytics scrape failed: {e}")

            # ── Scrape followers ──
            try:
                follower_url = company_page.rstrip("/") + "/admin/followers/"
                page.goto(follower_url, wait_until="networkidle", timeout=30000)
                time.sleep(2)
                followers = _extract_followers_from_page(page.content())
                result.update(followers)
            except Exception as e:
                print(f"[LinkedIn] Follower scrape failed: {e}")

            # ── Scrape posts with engagement ──
            try:
                posts_url = company_page.rstrip("/") + "/admin/posts/"
                page.goto(posts_url, wait_until="networkidle", timeout=30000)
                time.sleep(3)
                # Scroll to load more posts
                for _ in range(5):
                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(1)
                posts = _extract_posts_from_page(page)
                result["posts"] = posts
                result["post_count"] = len(posts)
                print(f"[LinkedIn] Scraped {len(posts)} posts")
            except Exception as e:
                print(f"[LinkedIn] Posts scrape failed: {e}")

            browser.close()
    except Exception as e:
        result["error"] = str(e)

    # Also try public scrape for basic info if Playwright missed some
    if "followers" not in result:
        pub = scrape_public_metrics()
        if "followers" in pub:
            result["followers"] = pub["followers"]
        if "company_name" not in result and "company_name" in pub:
            result["company_name"] = pub["company_name"]

    _save_json(LI_METRICS_CACHE, result)
    return result


def _extract_analytics_from_page(html: str) -> Dict[str, Any]:
    result = {}
    for pattern in [
        r'"impressionCount"\s*:\s*(\d+)',
        r'"uniqueVisitors"\s*:\s*(\d+)',
        r'"totalPageViews"\s*:\s*(\d+)',
        r'"likeCount"\s*:\s*(\d+)',
        r'"commentCount"\s*:\s*(\d+)',
        r'"shareCount"\s*:\s*(\d+)',
        r'"clickCount"\s*:\s*(\d+)',
    ]:
        m = re.search(pattern, html)
        if m:
            key = pattern.split('"')[1]
            result[key] = int(m.group(1))
    return result


def _extract_followers_from_page(html: str) -> Dict[str, Any]:
    result = {}
    for pattern in [
        r'"totalFollowers"\s*:\s*(\d+)',
        r'"followerCount"\s*:\s*(\d+)',
        r'"organicFollowers"\s*:\s*(\d+)',
    ]:
        m = re.search(pattern, html)
        if m:
            key = pattern.split('"')[1]
            result[key] = int(m.group(1))
    return result


def _extract_posts_from_page(page) -> List[Dict[str, Any]]:
    """Extract post data from LinkedIn admin posts page.
    Enhanced to capture full engagement: impressions, views, clicks, CTR,
    reactions, comments, reposts, follows, engagement rate per post.
    """
    posts = page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();
            
            // Method 1: Look for structured post cards/rows
            // LinkedIn admin posts page has cards with engagement data
            document.querySelectorAll('article, [class*="update"], [class*="post"], [class*="feed-shared"]').forEach(el => {
                const text = el.innerText || '';
                if (text.length < 10) return;
                
                const urn = el.getAttribute('data-urn') || el.getAttribute('data-id') || '';
                if (seen.has(urn) && urn) return;
                if (urn) seen.add(urn);
                
                // Extract all numeric engagement data
                const likeMatch = text.match(/(\\\\d[\\\\d,]*)\\\\s*(?:likes?|reactions?)/i) || text.match(/(?:likes?|reactions?).*?(\\\\d[\\\\d,]*)/i);
                const commentMatch = text.match(/(\\\\d[\\\\d,]*)\\\\s*comments?/i) || text.match(/comments?.*?(\\\\d[\\\\d,]*)/i);
                const repostMatch = text.match(/(\\\\d[\\\\d,]*)\\\\s*reposts?/i) || text.match(/reposts?.*?(\\\\d[\\\\d,]*)/i);
                const impressionMatch = text.match(/(\\\\d[\\\\d,]*)\\\\s*impressions?/i);
                const viewMatch = text.match(/(\\\\d[\\\\d,]*)\\\\s*views?/i);
                const clickMatch = text.match(/(\\\\d[\\\\d,]*)\\\\s*clicks?/i);
                const followMatch = text.match(/(\\\\d[\\\\d,]*)\\\\s*follows?/i);
                const ctrMatch = text.match(/([\\\\d.]+)%\\\\s*(?:CTR|click-through)/i);
                const engMatch = text.match(/([\\\\d.]+)%\\\\s*engagement/i);
                
                // Get first meaningful lines as title
                const lines = text.split('\\\\n').filter(l => l.trim().length > 3);
                const title = lines.slice(0, 2).join(' ').substring(0, 300);
                
                const post = {
                    urn: urn,
                    title: title,
                    impressions: impressionMatch ? parseInt(impressionMatch[1].replace(/,/g, '')) : 0,
                    views: viewMatch ? parseInt(viewMatch[1].replace(/,/g, '')) : 0,
                    clicks: clickMatch ? parseInt(clickMatch[1].replace(/,/g, '')) : 0,
                    ctr: ctrMatch ? parseFloat(ctrMatch[1]) : 0,
                    likes: likeMatch ? parseInt(likeMatch[1].replace(/,/g, '')) : 0,
                    comments: commentMatch ? parseInt(commentMatch[1].replace(/,/g, '')) : 0,
                    reposts: repostMatch ? parseInt(repostMatch[1].replace(/,/g, '')) : 0,
                    follows: followMatch ? parseInt(followMatch[1].replace(/,/g, '')) : 0,
                    engagement_rate: engMatch ? parseFloat(engMatch[1]) : 0,
                };
                
                if (post.title || post.urn || post.impressions > 0 || post.likes > 0) {
                    results.push(post);
                }
            });
            
            // Method 2: If no structured cards found, parse from page text
            if (results.length === 0) {
                const allText = document.body.innerText;
                const blocks = allText.split(/\\\\n{3,}/);
                blocks.forEach(block => {
                    if (block.length < 20) return;
                    const likeMatch = block.match(/(\\\\d[\\\\d,]*)\\\\s*(?:likes?|reactions?)/i);
                    const commentMatch = block.match(/(\\\\d[\\\\d,]*)\\\\s*comments?/i);
                    const impressionMatch = block.match(/(\\\\d[\\\\d,]*)\\\\s*impressions?/i);
                    const engMatch = block.match(/([\\\\d.]+)%\\\\s*engagement/i);
                    
                    if (likeMatch || commentMatch || impressionMatch) {
                        const lines = block.split('\\\\n').filter(l => l.trim().length > 3);
                        results.push({
                            urn: '',
                            title: lines.slice(0, 2).join(' ').substring(0, 300),
                            impressions: impressionMatch ? parseInt(impressionMatch[1].replace(/,/g, '')) : 0,
                            views: 0, clicks: 0, ctr: 0,
                            likes: likeMatch ? parseInt(likeMatch[1].replace(/,/g, '')) : 0,
                            comments: commentMatch ? parseInt(commentMatch[1].replace(/,/g, '')) : 0,
                            reposts: 0, follows: 0,
                            engagement_rate: engMatch ? parseFloat(engMatch[1]) : 0,
                        });
                    }
                });
            }
            
            return results.slice(0, 50);
        }
    """)
    return posts if posts else []


# ═══════════════════════════════════════════════════════════════
# METHOD 2b: API (if access token available)
# ═══════════════════════════════════════════════════════════════

def scrape_via_api() -> Dict[str, Any]:
    """Use LinkedIn API with OAuth token if configured."""
    import urllib.request
    token = _get_secret("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        return {"error": "No LinkedIn access token", "demo": True}

    result = {"scraped_at": datetime.now().isoformat(), "demo": False}

    try:
        req = urllib.request.Request(
            "https://api.linkedin.com/rest/organizations?q=vanityName&vanityName=eagle-3d-streaming",
            headers={"Authorization": f"Bearer {token}", "LinkedIn-Version": "202401", "X-Restli-Protocol-Version": "2.0.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("elements"):
                org = data["elements"][0]
                result["followers"] = org.get("followerCount", 0)
                result["company_name"] = org.get("localizedName", "")
                result["company_id"] = org.get("id", "")
    except Exception as e:
        result["api_error"] = str(e)

    _save_json(LI_METRICS_CACHE, result)
    return result


def _extract_numeric(val):
    """Extract numeric value from a string, returning 0 if not parseable."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip().replace(",", "").replace("%", "").replace("--", "0").replace("-", "0")
    try:
        return float(s) if "." in s else int(s)
    except (ValueError, TypeError):
        return 0


def _parse_voyager_analytics(data: dict) -> dict:
    """Parse LinkedIn Voyager API analytics response into flat dict."""
    result = {}
    try:
        elements = data.get("included", []) if isinstance(data, dict) else []
        if not elements and isinstance(data, list):
            elements = data
        for item in elements:
            if not isinstance(item, dict):
                continue
            template = item.get("$linkedInSchema", "")
            if "shareStatistics" in template or "shareStatistic" in template:
                impressions = _extract_numeric(item.get("impressionCount", item.get("impressionCounts", {}).get("total", 0)))
                likes = _extract_numeric(item.get("likeCount", item.get("reactionCounts", {}).get("total", 0)))
                comments = _extract_numeric(item.get("commentCount", 0))
                reposts = _extract_numeric(item.get("shareCount", item.get("repostCount", 0)))
                result["impressionCount"] = max(result.get("impressionCount", 0), impressions)
                result["likeCount"] = max(result.get("likeCount", 0), likes)
                result["commentCount"] = max(result.get("commentCount", 0), comments)
                result["shareCount"] = max(result.get("shareCount", 0), reposts)
            if "analyticsMetricValue" in template or "timeSeries" in template:
                for key in ("impressionCount", "uniqueImpressions", "totalPageViews",
                            "uniqueVisitors", "likeCount", "commentCount", "shareCount", "clickCount"):
                    if key in item:
                        result[key] = _extract_numeric(item[key])
    except Exception:
        pass
    return result


def _parse_voyager_posts(data: dict) -> list:
    """Parse LinkedIn Voyager API content engagement response into post list."""
    posts = []
    try:
        elements = data.get("included", []) if isinstance(data, dict) else []
        for item in elements:
            if not isinstance(item, dict):
                continue
            template = item.get("$linkedInSchema", "")
            if "shareStatistics" not in template and "contentEngagement" not in template:
                continue
            post = {
                "title": (item.get("title", item.get("headline", "")) or "")[:300],
                "text": (item.get("commentary", item.get("text", "")) or "")[:500],
                "published_at": item.get("createdAt", item.get("firstPublishedAt", "")),
                "impressions": _extract_numeric(item.get("impressionCount", item.get("impressionCounts", {}).get("total", 0))),
                "views": _extract_numeric(item.get("viewCount", 0)),
                "clicks": _extract_numeric(item.get("clickCount", 0)),
                "ctr": _extract_numeric(item.get("clickThroughRate", item.get("ctr", 0))),
                "likes": _extract_numeric(item.get("likeCount", item.get("reactionCounts", {}).get("total", 0))),
                "comments": _extract_numeric(item.get("commentCount", 0)),
                "reposts": _extract_numeric(item.get("shareCount", item.get("repostCount", 0))),
                "follows": _extract_numeric(item.get("followCount", item.get("followerGains", 0))),
                "engagement_rate": _extract_numeric(item.get("engagementRate", 0)),
                "post_type": (item.get("postType", item.get("type", "")) or ""),
                "audience": (item.get("audience", item.get("visibility", "")) or ""),
                "url": (item.get("url", item.get("landingUrl", "")) or ""),
                "source": "voyager_api",
            }
            # Try to extract URN
            urn = item.get("entityUrn", item.get("urn", item.get("$id", "")))
            if urn:
                post["urn"] = urn
            # Parse milliseconds timestamp to date string
            if isinstance(post["published_at"], (int, float)) and post["published_at"] > 1e10:
                try:
                    post["published_at"] = datetime.fromtimestamp(post["published_at"] / 1000).strftime("%Y-%m-%d")
                except Exception:
                    pass
            if post["impressions"] > 0 or post["likes"] > 0 or post["title"]:
                posts.append(post)
    except Exception:
        pass
    return posts


def scrape_analytics_playwright() -> Dict[str, Any]:
    """Scrape FULL LinkedIn analytics using Playwright with authenticated session.
    Gets: Highlights (Impressions, Reactions, Comments, Reposts with % change),
          Content Engagement table per post (Impressions, Views, Clicks, CTR,
          Reactions, Comments, Reposts, Follows, Engagement Rate),
          daily visitor metrics, follower trends, historical data.
    Uses Voyager API network interception for reliable data extraction.
    Stores results in Google Sheets for dashboard display.
    Called by daily pipeline when LINKEDIN_COOKIES_JSON is configured.
    """
    cookies_json = _get_cookies()
    if not cookies_json:
        return {"error": "No cookies", "demo": True}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "Playwright not installed", "demo": True}

    company_page = _get_company_page()
    if not company_page:
        return {"error": "LINKEDIN_COMPANY_PAGE not configured", "demo": True}

    try:
        cookies = json.loads(cookies_json) if isinstance(cookies_json, str) else cookies_json
    except json.JSONDecodeError:
        return {"error": "Invalid cookies JSON", "demo": True}

    result = {"scraped_at": datetime.now().isoformat(), "demo": False, "source": "playwright_authenticated"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )

            if isinstance(cookies, list):
                import html as _html
                formatted = [{
                    "name": c.get("name", ""),
                    "value": _html.unescape(str(c.get("value", ""))),
                    "domain": c.get("domain", ".linkedin.com"),
                    "path": c.get("path", "/"),
                } for c in cookies]
                context.add_cookies(formatted)

            page = context.new_page()

            # ── NETWORK INTERCEPT: Capture Voyager API responses ──
            _voyager_responses = []
            def _on_response(response):
                url = response.url
                if "voyager/api" in url or "graphql" in url:
                    try:
                        ct = response.headers.get("content-type", "")
                        if "json" in ct:
                            data = response.json()
                            _voyager_responses.append({"url": url, "data": data})
                    except Exception:
                        pass
            page.on("response", _on_response)

            # ── 1. Analytics Overview — Highlights ──
            try:
                analytics_url = company_page.rstrip("/") + "/admin/analytics/"
                page.goto(analytics_url, wait_until="networkidle", timeout=30000)
                time.sleep(5)
                # Parse captured API responses
                for vr in _voyager_responses:
                    parsed = _parse_voyager_analytics(vr["data"])
                    if parsed:
                        result.update(parsed)
                # Also extract highlights from the overview page
                highlights = _extract_highlights_from_page(page)
                if highlights:
                    result.update(highlights)
                    print(f"[LinkedIn] Analytics Highlights: {highlights}")
                # Extract from page text for any missed metrics
                page_text = page.inner_text("body")
                _vis = _extract_metrics_from_text(page_text)
                for k, v in _vis.items():
                    if v and (k not in result or result.get(k, 0) == 0):
                        result[k] = v
                visitor_html = page.content()
                visitor_data = _extract_analytics_from_page(visitor_html)
                result.update(visitor_data)
            except Exception as e:
                print(f"[LinkedIn] Analytics overview failed: {e}")

            # ── 2. Visitor Analytics ──
            try:
                visitor_url = company_page.rstrip("/") + "/admin/analytics/visitors/"
                page.goto(visitor_url, wait_until="networkidle", timeout=30000)
                time.sleep(4)
                # Parse captured Voyager responses
                for vr in _voyager_responses:
                    parsed = _parse_voyager_analytics(vr["data"])
                    if parsed:
                        result.update(parsed)
                visitor_html = page.content()
                visitor_data = _extract_analytics_from_page(visitor_html)
                for k, v in visitor_data.items():
                    if v and (k not in result or result.get(k, 0) == 0):
                        result[k] = v
                page_text = page.inner_text("body")
                _vis = _extract_metrics_from_text(page_text)
                for k, v in _vis.items():
                    if v and (k not in result or result.get(k, 0) == 0):
                        result[k] = v
                # Extract visitor chart data
                visitor_chart = _extract_daily_chart_from_page(page)
                if visitor_chart:
                    result["daily_visitor_chart"] = visitor_chart
                    print(f"[LinkedIn] Visitor chart: {len(visitor_chart)} days")
                print(f"[LinkedIn] Visitor analytics: {visitor_data}")
            except Exception as e:
                print(f"[LinkedIn] Visitor analytics failed: {e}")

            # ── 3. Follower Data ──
            try:
                follower_url = company_page.rstrip("/") + "/admin/analytics/followers/"
                page.goto(follower_url, wait_until="networkidle", timeout=30000)
                time.sleep(3)
                follower_html = page.content()
                followers = _extract_followers_from_page(follower_html)
                for k, v in followers.items():
                    if v and (k not in result or result.get(k, 0) == 0):
                        result[k] = v
                page_text = page.inner_text("body")
                f_text = _extract_metrics_from_text(page_text)
                for k, v in f_text.items():
                    if v and (k not in result or result.get(k, 0) == 0):
                        result[k] = v
                # Save follower snapshot
                _save_json(LI_FOLLOWERS_CACHE, {"followers": result.get("followers", 0),
                                                 "organicFollowers": result.get("organicFollowers", 0),
                                                 "totalFollowers": result.get("totalFollowers", 0),
                                                 "scraped_at": datetime.now().isoformat()})
                print(f"[LinkedIn] Followers: {followers}")
            except Exception as e:
                print(f"[LinkedIn] Follower scrape failed: {e}")

            # ── 4. Posts with FULL Content Engagement Table ──
            # Uses Voyager API interception + DOM fallback for reliable extraction.
            # Gets: Post title, Post type, Audience, Impressions, Views, Clicks,
            # CTR, Reactions, Comments, Reposts, Follows, Engagement rate
            try:
                posts_url = company_page.rstrip("/") + "/admin/posts/"
                page.goto(posts_url, wait_until="networkidle", timeout=30000)
                time.sleep(4)
                # Scroll to load more posts
                for _ in range(10):
                    page.evaluate("window.scrollBy(0, 2000)")
                    time.sleep(1.5)

                # PRIMARY: Parse Voyager API responses from network interception
                posts = []
                for vr in _voyager_responses:
                    parsed = _parse_voyager_posts(vr["data"])
                    if parsed:
                        posts.extend(parsed)
                # Dedup posts by URN or title
                if posts:
                    _seen = set()
                    _uniq = []
                    for p in posts:
                        _key = p.get("urn") or p.get("title", "")[:80]
                        if _key not in _seen:
                            _seen.add(_key)
                            _uniq.append(p)
                    posts = _uniq
                    print(f"[LinkedIn] Voyager API gave {len(posts)} posts with full engagement data")

                # SECONDARY: Extract Content Engagement table (DOM)
                if not posts:
                    posts = _extract_content_engagement_table(page)

                # TERTIARY: If no table found, try extracting from page text
                if not posts:
                    posts = _extract_posts_from_page(page)

                # QUATERNARY: If still no posts, try HTML extraction
                if not posts:
                    posts = _extract_posts_from_html(page.content())

                # Enrich with public scrape data for text/dates/URLs
                try:
                    pub = scrape_public_metrics()
                    pub_posts = pub.get("posts", [])
                    if pub_posts and posts:
                        _pub_by_url = {}
                        for pp in pub_posts:
                            url = pp.get("url", "")
                            if url:
                                _pub_by_url[url] = pp
                        for post in posts:
                            p_url = post.get("url", "")
                            if p_url and p_url in _pub_by_url:
                                pp = _pub_by_url[p_url]
                                if not post.get("text") and pp.get("text"):
                                    post["text"] = pp["text"]
                                if not post.get("published_at") and pp.get("published_at"):
                                    post["published_at"] = pp["published_at"]
                    if not posts and pub_posts:
                        posts = pub_posts
                except Exception as e:
                    print(f"[LinkedIn] Public enrichment failed (non-fatal): {e}")

                result["posts"] = posts
                result["post_count"] = len(posts)
                result["total_likes"] = sum(p.get("likes", 0) for p in posts)
                result["total_comments"] = sum(p.get("comments", 0) for p in posts)
                result["total_reposts"] = sum(p.get("reposts", 0) for p in posts)
                total_imp = sum(p.get("impressions", 0) for p in posts)
                if total_imp > 0:
                    result["total_impressions"] = max(result.get("total_impressions", 0), total_imp)
                    total_eng = result["total_likes"] + result["total_comments"] + result["total_reposts"]
                    result["engagement_rate"] = round(total_eng / total_imp * 100, 2)
                print(f"[LinkedIn] Scraped {len(posts)} posts with full engagement data")
            except Exception as e:
                print(f"[LinkedIn] Posts scrape failed: {e}")

            # ── 5. Page overview (fallback for company info) ──
            try:
                page.goto(company_page, wait_until="networkidle", timeout=30000)
                time.sleep(2)
                page_text = page.inner_text("body")
                overview = _extract_metrics_from_text(page_text)
                for k, v in overview.items():
                    if v and (k not in result or not result.get(k)):
                        result[k] = v
                html = page.content()
                html_data = _extract_public_data(html, company_page)
                for k, v in html_data.items():
                    if v and (k not in result or not result.get(k)):
                        result[k] = v
            except Exception as e:
                print(f"[LinkedIn] Overview scrape failed: {e}")

            browser.close()
    except Exception as e:
        result["error"] = str(e)

    if not result.get("followers"):
        pub = scrape_public_metrics()
        if "followers" in pub:
            result["followers"] = pub["followers"]
        if "company_name" not in result and "company_name" in pub:
            result["company_name"] = pub["company_name"]

    _save_json(LI_METRICS_CACHE, result)

    # ── Write to Google Sheets ──
    try:
        from sheets_writer import write_tab_data
        _today = datetime.now().strftime("%Y-%m-%d")
        _li_row = {
            "Date": _today,
            "Followers": result.get("followers", 0),
            "Employees": result.get("employees", ""),
            "Company Name": result.get("company_name", ""),
            "Industry": result.get("industry", ""),
            "Impressions": result.get("total_impressions", 0) or result.get("impressionCount", 0),
            "Unique Visitors": result.get("uniqueVisitors", 0),
            "Likes": result.get("total_likes", 0) or result.get("likeCount", 0),
            "Comments": result.get("total_comments", 0) or result.get("commentCount", 0),
            "Shares": result.get("shareCount", 0),
            "Reposts": result.get("total_reposts", 0),
            "Posts": result.get("post_count", 0),
            "Engagement Rate": result.get("engagement_rate", 0),
            "Impressions Change": result.get("impressions_change_pct", ""),
            "Reactions Change": result.get("reactions_change_pct", ""),
            "Comments Change": result.get("comments_change_pct", ""),
            "Reposts Change": result.get("reposts_change_pct", ""),
            "Source": result.get("source", "playwright"),
            "Last Updated": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        }
        _written = write_tab_data("LinkedIn", [_li_row])
        if _written:
            print("[LinkedIn] Data written to Google Sheets")
    except Exception as e:
        print(f"[LinkedIn] Sheets write error (non-fatal): {e}")

    # ── Write posts to Sheets (with FULL engagement data) ──
    posts = result.get("posts", [])
    if posts:
        try:
            from sheets_writer import write_tab_data as _wtd
            _post_rows = []
            for p in posts[:25]:
                _post_rows.append({
                    "Date": p.get("published_at", "")[:10] if p.get("published_at") else "",
                    "Title": (p.get("title", "") or p.get("text", ""))[:200],
                    "Post Type": p.get("post_type", ""),
                    "Audience": p.get("audience", ""),
                    "Impressions": p.get("impressions", 0),
                    "Views": p.get("views", 0),
                    "Clicks": p.get("clicks", 0),
                    "CTR": p.get("ctr", 0),
                    "Likes": p.get("likes", 0),
                    "Comments": p.get("comments", 0),
                    "Reposts": p.get("reposts", 0),
                    "Follows": p.get("follows", 0),
                    "Engagement Rate": p.get("engagement_rate", 0),
                    "URL": p.get("url", ""),
                    "Source": p.get("source", "playwright"),
                })
            if _post_rows:
                _pw = _wtd("LinkedIn_Posts", _post_rows)
                if _pw:
                    print(f"[LinkedIn] {len(_post_rows)} posts written to LinkedIn_Posts sheet")
        except Exception as e:
            print(f"[LinkedIn] Posts sheet write error (non-fatal): {e}")

    return result


def _extract_highlights_from_page(page) -> Dict[str, Any]:
    """Extract Highlights section from LinkedIn admin/analytics/ page.
    Gets: Impressions, Reactions, Comments, Reposts with % change.
    The highlights section shows cards like:
      2,910  Impressions
      56.1%
    where 56.1% is the period-over-period change.
    """
    result = {}
    try:
        highlights = page.evaluate("""
            () => {
                const result = {};
                const bodyText = document.body.innerText;
                
                // Method 1: Find highlight cards with metric name + value + change %
                // LinkedIn shows cards like: "2,910\\nImpressions\\n56.1%"
                const metricPatterns = [
                    { name: 'impressions', label: 'Impressions' },
                    { name: 'reactions', label: 'Reactions' },
                    { name: 'comments', label: 'Comments' },
                    { name: 'reposts', label: 'Reposts' },
                    { name: 'followers', label: 'Followers' },
                    { name: 'clicks', label: 'Clicks' },
                    { name: 'likes', label: 'Likes' },
                    { name: 'views', label: 'Views' },
                    { name: 'engagement', label: 'Engagement' },
                ];
                
                for (const mp of metricPatterns) {
                    // Look for pattern like "2,910\nImpressions\n56.1%"
                    const regex = new RegExp(
                        '(\\\\d[\\\\d,]*)\\\\s*\\\\n\\\\s*' + mp.label + '\\\\s*\\\\n\\\\s*([\\\\d.]+%|—)',
                        'gi'
                    );
                    const match = regex.exec(bodyText);
                    if (match) {
                        result[mp.name] = parseInt(match[1].replace(/,/g, ''), 10);
                        const changeStr = match[2].trim();
                        result[mp.name + '_change_pct'] = changeStr;
                    }
                    
                    // Also try: "Impressions\n2,910\n56.1%"
                    const regex2 = new RegExp(
                        mp.label + '\\\\s*\\\\n\\\\s*(\\\\d[\\\\d,]*)\\\\s*\\\\n\\\\s*([\\\\d.]+%|—)',
                        'gi'
                    );
                    const match2 = regex2.exec(bodyText);
                    if (match2 && !result[mp.name]) {
                        result[mp.name] = parseInt(match2[1].replace(/,/g, ''), 10);
                        result[mp.name + '_change_pct'] = match2[2].trim();
                    }
                }
                
                // Method 2: Look for structured data in the page HTML
                // LinkedIn often stores data in data-attributes or embedded JSON
                const allElements = document.querySelectorAll('[class*="highlight"], [class*="metric"], [class*="statistic"], [class*="overview"]');
                allElements.forEach(el => {
                    const text = el.innerText || '';
                    for (const mp of metricPatterns) {
                        const valMatch = text.match(new RegExp('(\\\\d[\\\\d,]+)\\\\s*' + mp.label, 'i'));
                        if (valMatch && !result[mp.name]) {
                            result[mp.name] = parseInt(valMatch[1].replace(/,/g, ''), 10);
                            const changeMatch = text.match(/([\\d.]+%)/);
                            if (changeMatch) {
                                result[mp.name + '_change_pct'] = changeMatch[1];
                            }
                        }
                    }
                });
                
                return result;
            }
        """)
        if highlights:
            result.update(highlights)
    except Exception as e:
        print(f"[LinkedIn] Highlights extraction error: {e}")

    # Also try from page text directly
    try:
        page_text = page.inner_text("body")
        # Find blocks like: "2,910\nImpressions\n56.1%"
        for metric_name, label in [("impressions", "Impressions"), ("reactions", "Reactions"),
                                     ("comments", "Comments"), ("reposts", "Reposts"),
                                     ("likes", "Likes"), ("clicks", "Clicks")]:
            # Pattern: number \n label \n percentage
            pat = rf'(\d[\d,]*)\s*\n\s*{label}\s*\n\s*([\d.]+%)'
            m = re.search(pat, page_text, re.IGNORECASE)
            if m and not result.get(metric_name):
                result[metric_name] = int(m.group(1).replace(",", ""))
                result[f"{metric_name}_change_pct"] = m.group(2)
            # Reverse pattern: label \n number \n percentage
            pat2 = rf'{label}\s*\n\s*(\d[\d,]*)\s*\n\s*([\d.]+%)'
            m2 = re.search(pat2, page_text, re.IGNORECASE)
            if m2 and not result.get(metric_name):
                result[metric_name] = int(m2.group(1).replace(",", ""))
                result[f"{metric_name}_change_pct"] = m2.group(2)
    except Exception:
        pass

    # Map to result keys
    if "impressions" in result:
        result["total_impressions"] = result["impressions"]
        result["impressionCount"] = result["impressions"]
    if "reactions" in result:
        result["likeCount"] = result["reactions"]
        result["total_likes"] = result["reactions"]
    if "comments" in result:
        result["commentCount"] = result["comments"]
        result["total_comments"] = result["comments"]
    if "reposts" in result:
        result["shareCount"] = result["reposts"]
        result["total_reposts"] = result["reposts"]

    return result


def _extract_content_engagement_table(page) -> List[Dict[str, Any]]:
    """Extract the Content Engagement table from LinkedIn /admin/posts/ page.
    
    The table looks like:
    Post title | Post type | Audience | Impressions | Views | Clicks | CTR | Reactions | Comments | Reposts | Follows | Engagement rate
    
    Example row from user's data:
    Image | All followers | 396 | - | 12 | 3.03% | 5 | 0 | 0 | - | 4.29%
    """
    posts = []
    try:
        # PRIMARY METHOD: JavaScript extraction of the table
        posts = page.evaluate("""
            () => {
                const results = [];
                const seen = new Set();
                
                // Method 1: Find the Content Engagement table
                // LinkedIn uses various table structures — try all of them
                const tables = document.querySelectorAll('table');
                for (const table of tables) {
                    const rows = table.querySelectorAll('tr');
                    if (rows.length < 2) continue;
                    
                    // Get header columns to understand column positions
                    const headerCells = rows[0].querySelectorAll('th, td');
                    const headers = Array.from(headerCells).map(c => (c.innerText || '').trim().toLowerCase());
                    
                    // Only process if it looks like an engagement table
                    if (!headers.some(h => h.includes('impressions') || h.includes('engagement') || h.includes('reactions'))) continue;
                    
                    for (let i = 1; i < rows.length; i++) {
                        const cells = rows[i].querySelectorAll('td');
                        if (cells.length < 4) continue;
                        
                        const cellTexts = Array.from(cells).map(c => (c.innerText || '').trim());
                        
                        // Find the post title (usually first cell with substantial text)
                        let title = '';
                        let titleIdx = 0;
                        for (let j = 0; j < cellTexts.length; j++) {
                            if (cellTexts[j].length > 15) {
                                title = cellTexts[j].substring(0, 300);
                                titleIdx = j;
                                break;
                            }
                        }
                        
                        if (!title && cellTexts.length > 0) {
                            title = cellTexts[0].substring(0, 300);
                            titleIdx = 0;
                        }
                        
                        // Parse numeric values from remaining cells
                        const post = {
                            title: title.replace(/\\n/g, ' ').substring(0, 300),
                            impressions: 0, views: 0, clicks: 0, ctr: 0,
                            likes: 0, comments: 0, reposts: 0, follows: 0,
                            engagement_rate: 0, post_type: '', audience: '',
                        };
                        
                        // Map by header names
                        for (let j = 0; j < headers.length && j < cellTexts.length; j++) {
                            const h = headers[j];
                            const val = cellTexts[j];
                            const numVal = parseFloat(val.replace(/,/g, '')) || 0;
                            
                            if (h.includes('impression')) post.impressions = numVal;
                            else if (h.includes('view') && !h.includes('unique')) post.views = numVal;
                            else if (h.includes('click') && !h.includes('unique')) post.clicks = numVal;
                            else if (h.includes('ctr') || h.includes('click through')) post.ctr = parseFloat(val) || 0;
                            else if (h.includes('reaction') || h.includes('like')) post.likes = numVal;
                            else if (h.includes('comment')) post.comments = numVal;
                            else if (h.includes('repost') || h.includes('share')) post.reposts = numVal;
                            else if (h.includes('follow')) post.follows = numVal;
                            else if (h.includes('engagement') && (h.includes('rate') || h.includes('%'))) post.engagement_rate = parseFloat(val) || 0;
                            else if (h.includes('type') || h.includes('post type')) post.post_type = val;
                            else if (h.includes('audience')) post.audience = val;
                        }
                        
                        // Dedup by title
                        const dedupKey = post.title.substring(0, 50);
                        if (seen.has(dedupKey)) continue;
                        seen.add(dedupKey);
                        
                        if (post.title || post.impressions > 0 || post.likes > 0) {
                            results.push(post);
                        }
                    }
                }
                
                // Method 2: If no table found, parse from the page text
                // LinkedIn sometimes uses div-based tables
                if (results.length === 0) {
                    const bodyText = document.body.innerText;
                    // Split into blocks — each post in the admin page has its own section
                    const blocks = bodyText.split(/\\n{3,}/);
                    
                    let currentPost = null;
                    for (const block of blocks) {
                        const lines = block.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                        if (lines.length < 3) continue;
                        
                        // Look for blocks that contain post-like data
                        // Pattern: Title text, followed by date, then engagement numbers
                        const hasImpressions = lines.some(l => /^\\d[\\d,]*$/.test(l) && parseInt(l.replace(/,/g, '')) > 10);
                        const hasEngagementWord = lines.some(l => /impressions?|reactions?|comments?|reposts?|engagement/i.test(l));
                        const hasPct = lines.some(l => /^[\d.]+%$/.test(l));
                        
                        if (hasImpressions || hasEngagementWord || hasPct) {
                            const post = {
                                title: '', impressions: 0, views: 0, clicks: 0,
                                ctr: 0, likes: 0, comments: 0, reposts: 0,
                                follows: 0, engagement_rate: 0, post_type: '',
                                audience: '',
                            };
                            
                            // Extract values by looking for patterns
                            for (let i = 0; i < lines.length; i++) {
                                const line = lines[i];
                                const nextLine = lines[i + 1] || '';
                                
                                // Title is typically the first long text line
                                if (!post.title && line.length > 30 && !/^\\d/.test(line)) {
                                    post.title = line.substring(0, 300);
                                    continue;
                                }
                                
                                // Pattern: number followed by label
                                if (/^\\d[\\d,]*$/.test(line) && nextLine) {
                                    const num = parseInt(line.replace(/,/g, ''), 10);
                                    const nl = nextLine.toLowerCase();
                                    if (nl.includes('impression')) post.impressions = num;
                                    else if (nl.includes('view')) post.views = num;
                                    else if (nl.includes('click')) post.clicks = num;
                                    else if (nl.includes('reaction') || nl.includes('like')) post.likes = num;
                                    else if (nl.includes('comment')) post.comments = num;
                                    else if (nl.includes('repost') || nl.includes('share')) post.reposts = num;
                                    else if (nl.includes('follow')) post.follows = num;
                                }
                                
                                // CTR and engagement rate
                                if (/^[\\d.]+%$/.test(line) && nextLine) {
                                    const pct = parseFloat(line);
                                    const nl = nextLine.toLowerCase();
                                    if (nl.includes('ctr') || nl.includes('click')) post.ctr = pct;
                                    else if (nl.includes('engagement')) post.engagement_rate = pct;
                                }
                                
                                // Post type
                                if (/image|video|article|document|carousel|poll|text/i.test(line) && line.length < 20) {
                                    post.post_type = line;
                                }
                                // Audience
                                if (line.toLowerCase().includes('follower') && line.length < 30) {
                                    post.audience = line;
                                }
                                // Date
                                if (/\\d{1,2}\\/\\d{1,2}\\/\\d{4}/.test(line) || /\\w+ \\d{1,2}, \\d{4}/.test(line)) {
                                    post.published_at = line;
                                }
                            }
                            
                            if (post.title || post.impressions > 0 || post.likes > 0) {
                                const dedupKey = (post.title || '').substring(0, 50) + '_' + post.impressions;
                                if (!seen.has(dedupKey)) {
                                    seen.add(dedupKey);
                                    results.push(post);
                                }
                            }
                        }
                    }
                }
                
                // Method 3: Parse structured div rows (LinkedIn often uses these)
                if (results.length === 0) {
                    // Find all row-like containers
                    const rowContainers = document.querySelectorAll(
                        '[class*="feed"], [class*="post"], [class*="update"], [class*="content-engagement"]'
                    );
                    rowContainers.forEach(el => {
                        const text = el.innerText || '';
                        if (text.length < 20) return;
                        
                        const post = {
                            title: '', impressions: 0, views: 0, clicks: 0,
                            ctr: 0, likes: 0, comments: 0, reposts: 0,
                            follows: 0, engagement_rate: 0, post_type: '',
                            audience: '',
                        };
                        
                        // Extract impression-like numbers
                        const impMatch = text.match(/(\\d[\\d,]*)\\s*(?:\\n|\\s)Impressions/i);
                        if (impMatch) post.impressions = parseInt(impMatch[1].replace(/,/g, ''), 10);
                        
                        const reactMatch = text.match(/(\\d[\\d,]*)\\s*(?:\\n|\\s)Reactions/i);
                        if (reactMatch) post.likes = parseInt(reactMatch[1].replace(/,/g, ''), 10);
                        
                        const commMatch = text.match(/(\\d[\\d,]*)\\s*(?:\\n|\\s)Comments/i);
                        if (commMatch) post.comments = parseInt(commMatch[1].replace(/,/g, ''), 10);
                        
                        const repMatch = text.match(/(\\d[\\d,]*)\\s*(?:\\n|\\s)Reposts/i);
                        if (repMatch) post.reposts = parseInt(repMatch[1].replace(/,/g, ''), 10);
                        
                        const engMatch = text.match(/([\\d.]+)%\\s*(?:\\n|\\s)Engagement/i);
                        if (engMatch) post.engagement_rate = parseFloat(engMatch[1]);
                        
                        // First meaningful text as title
                        const lines = text.split('\\n').filter(l => l.trim().length > 10);
                        if (lines.length > 0) post.title = lines[0].substring(0, 300);
                        
                        if (post.impressions > 0 || post.likes > 0) {
                            const dedupKey = (post.title || '').substring(0, 50);
                            if (!seen.has(dedupKey)) {
                                seen.add(dedupKey);
                                results.push(post);
                            }
                        }
                    });
                }
                
                return results.slice(0, 50);
            }
        """)
    except Exception as e:
        print(f"[LinkedIn] Content Engagement table JS error: {e}")

    # FALLBACK: Parse from page text if JS didn't find anything
    if not posts:
        try:
            posts = _parse_content_engagement_from_text(page.inner_text("body"))
        except Exception as e:
            print(f"[LinkedIn] Content Engagement text parse error: {e}")

    return posts if posts else []


def _parse_content_engagement_from_text(page_text: str) -> List[Dict[str, Any]]:
    """Parse the Content Engagement table from page text output.
    LinkedIn's /admin/posts/ page has text like:
    
    Content engagement
    Time range: Jun 2, 2026 - Jun 16, 2026
    Show: 10
    
    Post title text...
    Posted by ...
    6/12/2026
    Image    All followers    396    -    12    3.03%    5    0    0    -    4.29%
    
    Where the tab-separated row is:
    Post_type  Audience  Impressions  Views  Clicks  CTR  Reactions  Comments  Reposts  Follows  Engagement_rate
    """
    posts = []
    lines = page_text.split("\n")
    seen = set()

    # Find the "Content engagement" section
    ce_start = -1
    for i, line in enumerate(lines):
        if "content engagement" in line.lower():
            ce_start = i
            break

    if ce_start < 0:
        return []

    # After finding "Content engagement", parse post blocks
    # Each post block has: title lines, date line, then a tab/space-delimited metrics row
    current_title_lines = []
    current_date = ""
    i = ce_start + 1

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Check if this line looks like a metrics row
        # Pattern: Image/Video/Article   All followers   NUMBER   -/NUMBER   NUMBER   X.XX%   NUMBER   NUMBER   NUMBER   -/NUMBER   X.XX%
        metrics_match = re.match(
            r'^(Image|Video|Article|Document|Carousel|Poll|Text|Event|Live)\s+(All followers|Followers|Targeted)\s+(\d[\d,]*)\s+([\d,—-]+)\s+([\d,—-]+)\s+([\d.]+%|—)\s+(\d[\d,]*)\s+(\d[\d,]*)\s+(\d[\d,]*)\s+([\d,—-]+)\s+([\d.]+%|—)',
            line, re.IGNORECASE
        )

        if metrics_match:
            post = {
                "title": " ".join(current_title_lines).strip()[:300],
                "published_at": current_date,
                "post_type": metrics_match.group(1),
                "audience": metrics_match.group(2),
                "impressions": int(metrics_match.group(3).replace(",", "")) if metrics_match.group(3) not in ("—", "-") else 0,
                "views": int(metrics_match.group(4).replace(",", "")) if metrics_match.group(4) not in ("—", "-") else 0,
                "clicks": int(metrics_match.group(5).replace(",", "")) if metrics_match.group(5) not in ("—", "-") else 0,
                "ctr": float(metrics_match.group(6).rstrip("%")) if metrics_match.group(6) not in ("—", "-") else 0,
                "likes": int(metrics_match.group(7).replace(",", "")) if metrics_match.group(7) not in ("—", "-") else 0,
                "comments": int(metrics_match.group(8).replace(",", "")) if metrics_match.group(8) not in ("—", "-") else 0,
                "reposts": int(metrics_match.group(9).replace(",", "")) if metrics_match.group(9) not in ("—", "-") else 0,
                "follows": int(metrics_match.group(10).replace(",", "")) if metrics_match.group(10) not in ("—", "-") else 0,
                "engagement_rate": float(metrics_match.group(11).rstrip("%")) if metrics_match.group(11) not in ("—", "-") else 0,
            }
            dedup_key = post["title"][:50]
            if dedup_key not in seen:
                seen.add(dedup_key)
                posts.append(post)
            current_title_lines = []
            current_date = ""
        elif re.match(r"\d{1,2}/\d{1,2}/\d{4}", line):
            # Date line like "6/12/2026"
            current_date = line
        elif "Posted by" in line or "Boost" in line or "Get up to" in line:
            # Skip these lines
            pass
        elif line.startswith("Time range:") or line.startswith("Show:"):
            # Skip header lines
            pass
        elif line.lower().startswith(("image", "video", "article")):
            # Might be a metrics line with different format — try flexible parsing
            parts = line.split()
            if len(parts) >= 8:
                # Try to extract numbers from the parts
                post = {
                    "title": " ".join(current_title_lines).strip()[:300],
                    "published_at": current_date,
                    "post_type": parts[0],
                    "audience": parts[1] if len(parts) > 1 else "",
                }
                # Find numbers in the remaining parts
                num_idx = 2
                metrics_keys = ["impressions", "views", "clicks", "ctr", "likes", "comments", "reposts", "follows", "engagement_rate"]
                for mk in metrics_keys:
                    if num_idx < len(parts):
                        val = parts[num_idx].rstrip("%").replace(",", "").replace("—", "0").replace("-", "0")
                        try:
                            post[mk] = float(val) if mk in ("ctr", "engagement_rate") else int(float(val))
                        except (ValueError, TypeError):
                            post[mk] = 0
                        num_idx += 1
                    else:
                        post[mk] = 0
                dedup_key = post["title"][:50]
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    posts.append(post)
                current_title_lines = []
                current_date = ""
        elif len(line) > 15 and not line.startswith("Post") and not line.startswith("Content"):
            # Likely a post title
            current_title_lines.append(line)
        i += 1

    return posts


def _extract_daily_chart_from_page(page) -> List[Dict[str, Any]]:
    """Extract daily chart data from LinkedIn analytics page.
    LinkedIn shows line charts with daily data (Organic vs Sponsored impressions).
    The data is often in embedded JSON or can be extracted from SVG/canvas elements.
    """
    daily_data = []
    try:
        chart_data = page.evaluate("""
            () => {
                const results = [];
                // Try to find chart data in embedded JSON
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const text = script.textContent || '';
                    // Look for time series data patterns
                    const matches = text.match(/"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"[^}]*"value"\s*:\s*(\d+)/g);
                    if (matches) {
                        for (const m of matches) {
                            const dateMatch = m.match(/"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"/);
                            const valueMatch = m.match(/"value"\s*:\s*(\d+)/);
                            if (dateMatch && valueMatch) {
                                results.push({
                                    date: dateMatch[1],
                                    impressions: parseInt(valueMatch[1], 10)
                                });
                            }
                        }
                    }
                }
                
                // Also try to find data in __NEXT_DATA__ or similar hydration
                const nextData = document.getElementById('__NEXT_DATA__');
                if (nextData) {
                    try {
                        const parsed = JSON.parse(nextData.textContent);
                        const jsonStr = JSON.stringify(parsed);
                        const dateValues = jsonStr.match(/"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"[^}]*"organicImpressions"\s*:\s*(\d+)/g);
                        if (dateValues) {
                            for (const dv of dateValues) {
                                const dm = dv.match(/"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"/);
                                const im = dv.match(/"organicImpressions"\s*:\s*(\d+)/);
                                if (dm && im) {
                                    results.push({ date: dm[1], impressions: parseInt(im[1], 10), type: 'organic' });
                                }
                            }
                        }
                    } catch(e) {}
                }
                
                return results;
            }
        """)
        if chart_data:
            daily_data = chart_data
    except Exception as e:
        print(f"[LinkedIn] Daily chart extraction error: {e}")

    return daily_data


def _extract_metrics_from_text(text: str) -> Dict[str, Any]:
    """Extract numeric metrics from LinkedIn page text content."""
    result = {}
    patterns = [
        (r'(\d[\d,]+)\s*(?:total\s+)?(?:followers?|following)', 'followers'),
        (r'(\d[\d,]+)\s*(?:total\s+)?(?:impressions?|page views)', 'total_impressions'),
        (r'(\d[\d,]+)\s*(?:unique\s+)?(?:visitors?|views)', 'uniqueVisitors'),
        (r'(\d[\d,]+)\s*(?:total\s+)?(?:likes?|reactions?)', 'likeCount'),
        (r'(\d[\d,]+)\s*(?:total\s+)?comments?', 'commentCount'),
        (r'(\d[\d,]+)\s*(?:total\s+)?(?:shares?|reposts?)', 'shareCount'),
        (r'(\d[\d,]+)\s*employees?', 'employees'),
    ]
    for pattern, key in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                result[key] = int(m.group(1).replace(",", ""))
            except (ValueError, TypeError):
                pass
    return result


# ═══════════════════════════════════════════════════════════════
# METHOD 3: Cookie-based authenticated urllib scrape (no Playwright)
# Works on Streamlit Cloud where Playwright is not available
# ═══════════════════════════════════════════════════════════════

def scrape_with_cookies() -> Dict[str, Any]:
    """Scrape LinkedIn using cookies via urllib (no Playwright needed).
    Gets company page data, follower count, and basic analytics.
    Works on Streamlit Cloud and in GitHub Actions."""
    cookies_json = _get_cookies()
    company_page = _get_company_page()
    if not company_page:
        return {"error": "LINKEDIN_COMPANY_PAGE not configured", "demo": True}

    result = {"scraped_at": datetime.now().isoformat(), "demo": False}

    # Parse cookies into a cookie string
    cookie_str = ""
    if cookies_json:
        try:
            import html as _html
            cookies = json.loads(cookies_json) if isinstance(cookies_json, str) else cookies_json
            cookie_str = "; ".join(f"{c['name']}={_html.unescape(str(c['value']))}" for c in cookies if c.get("name") and c.get("value"))
        except Exception:
            pass

    # First try public scrape for basics
    pub = scrape_public_metrics()
    if not pub.get("error"):
        result.update(pub)

    # If we have cookies, try to get authenticated data
    if cookie_str:
        import urllib.request
        import urllib.error

        # Extract CSRF token from cookies (JSESSIONID after "ajax:")
        _csrf_token = ""
        for _ck in cookie_str.split(";"):
            _ck = _ck.strip()
            if _ck.startswith("JSESSIONID="):
                _csrf_token = _ck.split("=", 1)[1].strip('"').strip("'")
                if _csrf_token.startswith("ajax:"):
                    _csrf_token = _csrf_token[5:]
                break

        # ── PRIMARY: Try Voyager REST API (cleanest data) ──
        _voyager_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": cookie_str,
            "Accept": "application/vnd.linkedin.normalized+json+2.1",
            "x-restli-protocol-version": "2.0.0",
            "x-li-lang": "en_US",
            "x-li-page-instance": "urn:li:page:d_organization_admin_analytics;",
        }
        if _csrf_token:
            _voyager_headers["csrf-token"] = _csrf_token

        # Try Voyager Analytics API
        try:
            _now = datetime.now()
            _start_d = (_now - timedelta(days=365)).strftime("%Y%m%d")
            _end_d = _now.strftime("%Y%m%d")
            _voyager_url = f"https://www.linkedin.com/voyager/api/organization/analytics?q=company&startDate=(year:{_now.year},month:{_now.month},day:{_now.day})&endDate=(year:{_now.year},month:{_now.month},day:{_now.day})"
            _req = urllib.request.Request(_voyager_url, headers=_voyager_headers)
            with urllib.request.urlopen(_req, timeout=30) as _resp:
                _raw = _resp.read().decode("utf-8", errors="replace")
                _voyager_data = json.loads(_raw)
                _aparsed = _parse_voyager_analytics(_voyager_data)
                if _aparsed:
                    result.update(_aparsed)
                    print(f"[LinkedIn] Voyager API analytics: {list(_aparsed.keys())}")
        except Exception as e:
            print(f"[LinkedIn] Voyager API analytics call: {e}")

        # Try to get posts via Voyager API
        try:
            _voyager_url2 = f"https://www.linkedin.com/voyager/api/feed/shareStatistics?q=organization&startDate=(year:2024,month:1,day:1)&endDate=(year:{_now.year},month:{_now.month},day:{_now.day})"
            _req2 = urllib.request.Request(_voyager_url2, headers=_voyager_headers)
            with urllib.request.urlopen(_req2, timeout=30) as _resp2:
                _raw2 = _resp2.read().decode("utf-8", errors="replace")
                _voyager_data2 = json.loads(_raw2)
                _pparsed = _parse_voyager_posts(_voyager_data2)
                if _pparsed:
                    result["posts"] = _pparsed
                    result["post_count"] = len(_pparsed)
                    result["total_likes"] = sum(p.get("likes", 0) for p in _pparsed)
                    result["total_comments"] = sum(p.get("comments", 0) for p in _pparsed)
                    result["total_reposts"] = sum(p.get("reposts", 0) for p in _pparsed)
                    _timps = sum(p.get("impressions", 0) for p in _pparsed)
                    if _timps > 0:
                        result["total_impressions"] = max(result.get("total_impressions", 0), _timps)
                    print(f"[LinkedIn] Voyager API posts: {len(_pparsed)} posts with engagement data")
        except Exception as e:
            print(f"[LinkedIn] Voyager API posts: {e}")

        # ── SECONDARY: HTML-based fallback for any missed data ──
        _html_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": cookie_str,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": company_page,
        }

        # Try the company admin analytics page
        try:
            analytics_url = company_page.rstrip("/") + "/admin/analytics/visitors/"
            req = urllib.request.Request(analytics_url, headers=_html_headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                analytics = _extract_analytics_from_page(html)
                if analytics:
                    result.update(analytics)
        except Exception as e:
            print(f"[LinkedIn] Cookie-based analytics scrape: {e}")

        # Try followers page
        try:
            _html_headers["Referer"] = company_page.rstrip("/") + "/admin/analytics/"
            follower_url = company_page.rstrip("/") + "/admin/followers/"
            req = urllib.request.Request(follower_url, headers=_html_headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                followers = _extract_followers_from_page(html)
                if followers:
                    result.update(followers)
                    if "totalFollowers" in followers:
                        result["followers"] = followers["totalFollowers"]
                    elif "followerCount" in followers:
                        result["followers"] = followers["followerCount"]
        except Exception as e:
            print(f"[LinkedIn] Cookie-based followers scrape: {e}")

        # Try posts page (only if Voyager API didn't get posts)
        if not result.get("posts"):
            try:
                _html_headers["Referer"] = company_page.rstrip("/") + "/admin/posts/"
                posts_url = company_page.rstrip("/") + "/admin/posts/"
                req = urllib.request.Request(posts_url, headers=_html_headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
                    posts = _extract_posts_from_html(html)
                    if posts:
                        result["posts"] = posts
                        result["post_count"] = len(posts)
                        print(f"[LinkedIn] Cookie scrape: got {len(posts)} posts")
            except Exception as e:
                print(f"[LinkedIn] Cookie-based posts scrape: {e}")

        result["authenticated"] = True

    _save_json(LI_METRICS_CACHE, result)
    return result


def _extract_posts_from_html(html: str) -> List[Dict[str, Any]]:
    """Extract post data from LinkedIn HTML (non-JS, server-rendered content)."""
    posts = []
    try:
        # LinkedIn embeds post data in JSON inside script tags
        # Look for post URN patterns
        urn_pattern = re.compile(r'urn:li:activity:(\d+)')
        urns = urn_pattern.findall(html)
        
        # Look for engagement data patterns
        like_patterns = re.findall(r'(\d[\d,]*)\s*likes?', html, re.IGNORECASE)
        comment_patterns = re.findall(r'(\d[\d,]*)\s*comments?', html, re.IGNORECASE)
        repost_patterns = re.findall(r'(\d[\d,]*)\s*reposts?', html, re.IGNORECASE)
        impression_patterns = re.findall(r'(\d[\d,]*)\s*impressions?', html, re.IGNORECASE)
        
        # If we found URNs, create posts from them
        for i, urn in enumerate(urns[:50]):
            post = {
                "urn": f"urn:li:activity:{urn}",
                "title": f"Post {i+1}",
                "likes": int(like_patterns[i].replace(",", "")) if i < len(like_patterns) else 0,
                "comments": int(comment_patterns[i].replace(",", "")) if i < len(comment_patterns) else 0,
                "reposts": int(repost_patterns[i].replace(",", "")) if i < len(repost_patterns) else 0,
                "impressions": int(impression_patterns[i].replace(",", "")) if i < len(impression_patterns) else 0,
            }
            posts.append(post)
    except Exception as e:
        print(f"[LinkedIn] HTML post extraction error: {e}")
    return posts


# ═══════════════════════════════════════════════════════════════
# POST-LEVEL DATA
# ═══════════════════════════════════════════════════════════════

def get_posts() -> List[Dict[str, Any]]:
    """Get cached post data. Returns list of posts with metrics.
    Tries linkedin_posts.json first, then falls back to posts embedded in linkedin_metrics.json.
    """
    # Try dedicated posts cache first
    if LI_POSTS_CACHE.exists():
        try:
            data = json.loads(LI_POSTS_CACHE.read_text())
            if isinstance(data, list):
                return data
            posts = data.get("posts", [])
            if posts:
                return posts
        except Exception:
            pass

    # Fallback: read posts from linkedin_metrics.json (which contains posts from public scrape)
    try:
        if LI_METRICS_CACHE.exists():
            metrics = json.loads(LI_METRICS_CACHE.read_text())
            posts = metrics.get("posts", [])
            if posts:
                return posts
    except Exception:
        pass

    return []


def save_posts(posts: List[Dict[str, Any]]) -> bool:
    """Save posts data to cache."""
    try:
        data = {
            "posts": posts,
            "_saved_at": datetime.now().isoformat(),
        }
        LI_POSTS_CACHE.write_text(json.dumps(data, default=str, indent=2))
        return True
    except Exception as e:
        print(f"[LinkedIn] Save posts failed: {e}")
        return False


def calculate_post_score(post: Dict[str, Any]) -> int:
    """Calculate engagement score 0-100 for a LinkedIn post.
    When impressions are available: uses engagement rate benchmarks.
    When only likes/comments available: uses follower ratio + absolute engagement.
    Also factors in clicks, CTR, follows, and engagement_rate when available.
    """
    impressions = post.get("impressions", 0) or 0
    likes = post.get("likes", 0) or 0
    comments = post.get("comments", 0) or 0
    reposts = post.get("reposts", 0) or 0
    shares = post.get("shares", 0) or 0
    total_reposts = reposts + shares
    clicks = post.get("clicks", 0) or 0
    follows = post.get("follows", 0) or 0
    ctr = post.get("ctr", 0) or 0
    eng_rate_raw = post.get("engagement_rate", 0) or 0

    if likes == 0 and comments == 0 and total_reposts == 0 and clicks == 0 and follows == 0:
        return 0

    # If the post already has a computed engagement_rate from LinkedIn, use it directly
    if eng_rate_raw > 0:
        # LinkedIn's own engagement rate is authoritative
        if eng_rate_raw >= 8: score = 90 + min(10, int(eng_rate_raw))
        elif eng_rate_raw >= 5: score = 75 + int((eng_rate_raw - 5) / 3 * 15)
        elif eng_rate_raw >= 3: score = 55 + int((eng_rate_raw - 3) / 2 * 20)
        elif eng_rate_raw >= 2: score = 40 + int((eng_rate_raw - 2) * 15)
        elif eng_rate_raw >= 1: score = 25 + int((eng_rate_raw - 1) * 15)
        else: score = int(eng_rate_raw * 25)
        # Bonus for clicks and follows
        if clicks > 0 and impressions > 0:
            click_bonus = min(5, int(clicks / impressions * 100))
            score += click_bonus
        if follows > 0:
            score += min(5, follows)
        return min(100, max(0, score))

    if impressions > 0:
        # Full data: engagement rate based scoring
        eng_rate = (likes + comments * 3 + total_reposts * 2 + clicks) / impressions * 100
        if eng_rate >= 6: score = 80 + min(20, int(eng_rate))
        elif eng_rate >= 4: score = 60 + int((eng_rate - 4) / 2 * 20)
        elif eng_rate >= 2: score = 40 + int((eng_rate - 2) / 2 * 20)
        elif eng_rate >= 1: score = 20 + int((eng_rate - 1) * 20)
        else: score = int(eng_rate * 20)
        # CTR bonus
        if ctr > 0:
            score += min(10, int(ctr * 2))
        # Follows bonus
        if follows > 0:
            score += min(5, follows)
    else:
        # No impressions — score from likes/comments relative to followers
        score = 0
        # Likes component (0-50 points)
        if likes >= 50: score += 50
        elif likes >= 20: score += 35 + int((likes - 20) / 30 * 15)
        elif likes >= 10: score += 25 + int((likes - 10) / 10 * 10)
        elif likes >= 5: score += 15 + int((likes - 5) / 5 * 10)
        elif likes >= 1: score += 5 + int((likes - 1) / 4 * 10)
        # Comments component (0-25 points)
        if comments >= 10: score += 25
        elif comments >= 5: score += 18 + int((comments - 5) / 5 * 7)
        elif comments >= 2: score += 8 + int((comments - 2) / 3 * 10)
        elif comments >= 1: score += 5
        # Reposts component (0-15 points)
        if total_reposts >= 5: score += 15
        elif total_reposts >= 2: score += 8 + int((total_reposts - 2) / 3 * 7)
        elif total_reposts >= 1: score += 4
        # Clicks component (0-10 points)
        if clicks >= 20: score += 10
        elif clicks >= 5: score += 5 + int((clicks - 5) / 15 * 5)
        elif clicks >= 1: score += 2

    return min(100, max(0, score))


def get_score_label(score: int) -> tuple:
    """Get label and color for a score."""
    if score >= 80:
        return "🟢 Excellent", "#2ecc71"
    elif score >= 60:
        return "🟣 Strong", "#9b59b6"
    elif score >= 40:
        return "🔵 Good", "#3498db"
    elif score >= 20:
        return "🟡 Moderate", "#f39c12"
    elif score > 0:
        return "🟠 Low", "#e67e22"
    else:
        return "⚪ No Data", "#95a5a6"


# ═══════════════════════════════════════════════════════════════
# DAILY TIME-SERIES AUTO-ACCUMULATION
# ═══════════════════════════════════════════════════════════════

def save_manual_entry(data: Dict[str, Any]) -> bool:
    """Save a daily entry to the time-series. Called by pipeline and manual entry."""
    try:
        existing = {}
        if LI_DAILY_CACHE.exists():
            existing = json.loads(LI_DAILY_CACHE.read_text())

        entries = existing.get("entries", [])

        today_str = datetime.now().strftime("%Y-%m-%d")

        # Check if today already has an entry — update it instead of appending
        today_idx = None
        for i, e in enumerate(entries):
            if e.get("date") == today_str:
                today_idx = i
                break

        entry = {"date": today_str, "scraped_at": datetime.now().isoformat(), **data}

        if today_idx is not None:
            # Merge: update existing fields, keep any that new data doesn't have
            for k, v in entry.items():
                if v is not None and v != 0 and v != "":
                    entries[today_idx][k] = v
        else:
            entries.append(entry)

        # Keep last 365 days
        entries = sorted(entries, key=lambda x: x.get("date", ""))
        existing["entries"] = entries[-365:]
        _save_json(LI_DAILY_CACHE, existing)
        return True
    except Exception as e:
        print(f"[LinkedIn] Save failed: {e}")
        return False


def get_manual_history() -> pd.DataFrame:
    """Get daily time-series data as DataFrame."""
    if not LI_DAILY_CACHE.exists():
        return pd.DataFrame()
    try:
        data = json.loads(LI_DAILY_CACHE.read_text())
        entries = data.get("entries", [])
        if not entries:
            return pd.DataFrame()
        df = pd.DataFrame(entries)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.sort_values("date")
        return df
    except Exception:
        return pd.DataFrame()


def import_csv_data(csv_content: str) -> bool:
    """Import CSV data into the daily time-series."""
    import io
    try:
        df = pd.read_csv(io.StringIO(csv_content))
        if df.empty:
            return False
        existing = {}
        if LI_DAILY_CACHE.exists():
            existing = json.loads(LI_DAILY_CACHE.read_text())
        entries = existing.get("entries", [])
        for _, row in df.iterrows():
            entry = row.to_dict()
            for k, v in entry.items():
                if pd.isna(v):
                    entry[k] = None
            entries.append(entry)
        existing["entries"] = entries[-365:]
        _save_json(LI_DAILY_CACHE, existing)
        return True
    except Exception as e:
        print(f"[LinkedIn] CSV import failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# COMBINED / STATUS
# ═══════════════════════════════════════════════════════════════

def get_cached_metrics() -> Dict[str, Any]:
    cache = _load_json(LI_METRICS_CACHE, max_age_hours=24)
    if cache:
        return {k: v for k, v in cache.items() if k != "_cached_at"}
    return {}


def is_configured() -> bool:
    return bool(_get_company_page())


def has_cookies() -> bool:
    return bool(_get_cookies())


def get_status() -> Dict[str, Any]:
    _has_posts = LI_POSTS_CACHE.exists()
    # Also check linkedin_metrics.json for embedded posts
    if not _has_posts and LI_METRICS_CACHE.exists():
        try:
            _m = json.loads(LI_METRICS_CACHE.read_text())
            if _m.get("posts"):
                _has_posts = True
        except Exception:
            pass
    return {
        "company_page": bool(_get_company_page()),
        "cookies": bool(_get_cookies()),
        "public_scrape": bool(_get_company_page()),
        "authenticated_scrape": bool(_get_cookies() and _get_company_page()),
        "configured": bool(_get_company_page()),
        "cached_data": LI_METRICS_CACHE.exists(),
        "has_posts": _has_posts,
        "has_daily": LI_DAILY_CACHE.exists(),
    }


def get_aggregate_stats() -> Dict[str, Any]:
    """Get aggregate LinkedIn stats from all sources.
    Includes: followers, impressions, likes, comments, reposts, clicks, CTR,
    follows, engagement rate, change percentages from Highlights.
    """
    stats = {
        "followers": 0,
        "company_name": "",
        "industry": "",
        "employees": "",
        "total_impressions": 0,
        "total_likes": 0,
        "total_comments": 0,
        "total_reposts": 0,
        "total_clicks": 0,
        "total_follows": 0,
        "total_views": 0,
        "avg_engagement_rate": 0.0,
        "avg_ctr": 0.0,
        "post_count": 0,
        "connected": False,
        "impressions_change_pct": "",
        "reactions_change_pct": "",
        "comments_change_pct": "",
        "reposts_change_pct": "",
    }

    # From cached metrics
    cached = get_cached_metrics()
    if cached and not cached.get("error"):
        stats["followers"] = cached.get("followers", 0)
        stats["company_name"] = cached.get("company_name", "")
        stats["industry"] = cached.get("industry", "")
        stats["employees"] = cached.get("employees", "")
        stats["total_impressions"] = cached.get("impressionCount", 0) or cached.get("total_impressions", 0)
        stats["connected"] = True
        # Highlights change percentages
        for _ck in ("impressions_change_pct", "reactions_change_pct",
                     "comments_change_pct", "reposts_change_pct"):
            if cached.get(_ck):
                stats[_ck] = cached[_ck]

    # From posts
    posts = get_posts()
    if posts:
        stats["post_count"] = len(posts)
        stats["total_likes"] = sum(p.get("likes", 0) for p in posts)
        stats["total_comments"] = sum(p.get("comments", 0) for p in posts)
        stats["total_reposts"] = sum(p.get("reposts", 0) for p in posts)
        stats["total_clicks"] = sum(p.get("clicks", 0) for p in posts)
        stats["total_follows"] = sum(p.get("follows", 0) for p in posts)
        stats["total_views"] = sum(p.get("views", 0) for p in posts)
        total_imp = sum(p.get("impressions", 0) for p in posts)
        if total_imp > 0:
            stats["total_impressions"] = max(stats["total_impressions"], total_imp)
            total_eng = stats["total_likes"] + stats["total_comments"] + stats["total_reposts"]
            stats["avg_engagement_rate"] = round(total_eng / total_imp * 100, 2) if total_imp > 0 else 0.0
            stats["avg_ctr"] = round(stats["total_clicks"] / total_imp * 100, 2) if total_imp > 0 else 0.0
        # If posts have engagement_rate field, use average of those
        _er_vals = [p.get("engagement_rate", 0) for p in posts if p.get("engagement_rate", 0) > 0]
        if _er_vals:
            stats["avg_engagement_rate"] = round(sum(_er_vals) / len(_er_vals), 2)
        _ctr_vals = [p.get("ctr", 0) for p in posts if p.get("ctr", 0) > 0]
        if _ctr_vals:
            stats["avg_ctr"] = round(sum(_ctr_vals) / len(_ctr_vals), 2)
        stats["connected"] = True

    # From daily history
    hist = get_manual_history()
    if not hist.empty:
        stats["connected"] = True
        if "followers" in hist.columns and not hist["followers"].empty:
            latest_f = hist["followers"].dropna()
            if not latest_f.empty:
                stats["followers"] = max(stats["followers"], int(latest_f.iloc[-1]))

    return stats
