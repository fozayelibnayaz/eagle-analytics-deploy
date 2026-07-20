"""
scrape_stripe.py — Eagle 3D Streaming Analytics Hub
=====================================================
Playwright scraper for Stripe Dashboard using saved cookies.
NO Stripe API key. NO Sheets. Writes to MongoDB → sheet_raw_stripe.

Handles Stripe's React-rendered pagination:
  - Next page is an <a> tag with aria-label="Next page"
  - Must scroll into view before clicking
  - Table re-renders on each page (need to re-extract, not append)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import (
    Page, sync_playwright, TimeoutError as PlaywrightTimeoutError,
)

from sheets_writer import write_tab_data


DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

SCRAPE_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
SCRAPE_DATE = datetime.now().strftime("%Y-%m-%d")

MAX_PAGES = int(os.environ.get("STRIPE_MAX_PAGES", "20"))
PAGE_LOAD_WAIT = int(os.environ.get("STRIPE_PAGE_LOAD_WAIT_MS", "4000"))  # ms
INITIAL_LOAD_WAIT = int(os.environ.get("STRIPE_INITIAL_LOAD_WAIT_MS", "9000"))  # ms


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Stripe] {msg}", flush=True)


def _secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default).strip()
    except Exception:
        return default


# ─────────────────────────────────────────────────────────────────
# COOKIES
# ─────────────────────────────────────────────────────────────────
def _load_cookies() -> List[Dict[str, Any]]:
    raw = _secret("STRIPE_COOKIES_JSON")
    if raw:
        try:
            cookies = json.loads(raw)
            log(f"Loaded {len(cookies)} cookies from secrets.toml")
            return cookies
        except Exception as e:
            log(f"Failed to parse STRIPE_COOKIES_JSON: {e}")

    for path in ("stripe_cookies.json", "data_output/stripe_cookies.json"):
        p = Path(path)
        if p.exists():
            try:
                cookies = json.loads(p.read_text())
                log(f"Loaded {len(cookies)} cookies from {path}")
                return cookies
            except Exception as e:
                log(f"Failed to parse {path}: {e}")

    return []


def _normalize_cookies(cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for c in cookies:
        if not c.get("name") or not c.get("domain"):
            continue
        cookie = {
            "name":     c["name"],
            "value":    str(c.get("value", "")),
            "domain":   c["domain"],
            "path":     c.get("path", "/"),
            "secure":   bool(c.get("secure", True)),
            "httpOnly": bool(c.get("httpOnly", False)),
        }
        ss = c.get("sameSite")
        if ss:
            s = str(ss).lower().replace("_", "")
            cookie["sameSite"] = "Strict" if "strict" in s else ("Lax" if "lax" in s else "None")
        if c.get("expirationDate") and not c.get("session"):
            cookie["expires"] = float(c["expirationDate"])
        out.append(cookie)
    return out


# ─────────────────────────────────────────────────────────────────
# TABLE EXTRACTION
# ─────────────────────────────────────────────────────────────────
def _extract_current_page_rows(page: Page) -> List[Dict[str, Any]]:
    """Extract every row currently visible in the table."""
    rows_data: List[Dict[str, Any]] = []
    try:
        page.wait_for_selector("table tbody tr", timeout=15000)
    except PlaywrightTimeoutError:
        log("  ⚠️  No table rows found")
        return rows_data

    # Small settle time
    page.wait_for_timeout(1500)

    headers = page.eval_on_selector_all(
        "table thead th",
        "els => els.map(e => e.innerText.trim())",
    )

    rows_cells = page.eval_on_selector_all(
        "table tbody tr",
        """rows => rows.map(r => Array.from(
             r.querySelectorAll('td')
           ).map(c => c.innerText.trim()))"""
    )

    for cells in rows_cells:
        if not cells or all(c == "" for c in cells):
            continue
        row: Dict[str, Any] = {}
        for i, val in enumerate(cells):
            h = headers[i] if i < len(headers) else f"col_{i}"
            if not h:
                h = f"col_{i}"
            row[h] = val
        row["__scraped_at__"]  = SCRAPE_TS
        row["__scrape_date__"] = SCRAPE_DATE
        row["__tab__"]         = "STRIPE"
        rows_data.append(row)

    return rows_data


# ─────────────────────────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────────────────────────
NEXT_SELECTORS = [
    'a[aria-label="Next page"]',
    'a[aria-label="Next"]',
    'button[aria-label="Next page"]',
    'button[aria-label="Next"]',
    '[data-testid*="next" i][aria-label*="next" i]',
]


def _get_first_row_signature(page: Page) -> str:
    """Get a signature of the first row so we can detect when the page has changed."""
    try:
        return page.eval_on_selector(
            "table tbody tr:first-child",
            "el => (el ? el.innerText.substring(0, 200) : '')"
        ) or ""
    except Exception:
        return ""


def _click_next_page(page: Page) -> bool:
    """Try to click Stripe's 'Next page' link. Returns True if clicked and page changed."""
    prev_sig = _get_first_row_signature(page)

    # Scroll to bottom so pagination controls are in view (Stripe lazy-renders)
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
    except Exception:
        pass

    for sel in NEXT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue

            # Check aria-disabled / disabled
            aria_dis = loc.get_attribute("aria-disabled") or ""
            dis      = loc.get_attribute("disabled") or ""
            if aria_dis.lower() == "true" or dis.lower() in ("true", "disabled", ""):
                if aria_dis.lower() == "true" or dis == "true":
                    log(f"  ⏹  Next is disabled — reached last page")
                    return False

            # Scroll into view and click
            loc.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(500)
            loc.click(timeout=8000)
            page.wait_for_timeout(PAGE_LOAD_WAIT)

            # Verify page actually changed
            new_sig = _get_first_row_signature(page)
            if new_sig and new_sig != prev_sig:
                return True
            else:
                log(f"  ⏹  Page didn't change after click — assume end of results")
                return False
        except Exception as e:
            log(f"  ⚠️  {sel} click failed: {e}")
            continue

    log("  ⏹  No 'Next page' element found — likely last page")
    return False


def _get_result_count(page: Page) -> Optional[int]:
    """Try to read '21-40 of 111 results' from footer to know how many total."""
    try:
        text = page.evaluate("document.body.innerText")
        m = re.search(r"of\s+(\d+)\s+result", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main() -> int:
    log("=" * 60)
    log("SCRAPE_STRIPE STARTING")
    log("=" * 60)

    cookies_raw = _load_cookies()
    if not cookies_raw:
        log("❌ No Stripe cookies")
        return 1

    cookies = _normalize_cookies(cookies_raw)
    log(f"Normalized {len(cookies)} cookies")

    stripe_url = _secret(
        "STRIPE_CUSTOMERS_URL",
        "https://dashboard.stripe.com/customers",
    )
    log(f"Target: {stripe_url[:80]}...")

    all_rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
        )
        try:
            ctx.add_cookies(cookies)
            log("✓ Cookies injected")
        except Exception as e:
            log(f"❌ Cookie injection failed: {e}")
            browser.close()
            return 1

        page = ctx.new_page()
        try:
            page.goto(stripe_url, wait_until="domcontentloaded", timeout=60000)
            log(f"Waiting {INITIAL_LOAD_WAIT}ms for React app to hydrate...")
            page.wait_for_timeout(INITIAL_LOAD_WAIT)
        except Exception as e:
            log(f"❌ Navigation failed: {e}")
            try:
                page.screenshot(path=str(DATA_DIR / "debug_stripe_nav.png"))
            except Exception:
                pass
            browser.close()
            return 1

        if "login" in page.url.lower() or page.locator('input[type="password"]').count() > 0:
            log("❌ Stripe redirected to login — cookies are stale")
            try:
                page.screenshot(path=str(DATA_DIR / "debug_stripe_stale.png"))
            except Exception:
                pass
            browser.close()
            return 1

        log(f"✓ Landed at Stripe (URL: {page.url[:80]}...)")

        # Try to read total result count from footer
        total_expected = _get_result_count(page)
        if total_expected:
            log(f"📊 Total results according to Stripe: {total_expected}")

        # Paginate
        for page_num in range(1, MAX_PAGES + 1):
            rows = _extract_current_page_rows(page)
            log(f"  📄 Page {page_num}: {len(rows)} rows scraped")

            if not rows:
                log(f"  ⚠️  Empty page — stopping")
                break

            all_rows.extend(rows)

            # Stop early if we reached the expected count
            if total_expected and len(all_rows) >= total_expected:
                log(f"  ✓ Reached expected total ({len(all_rows)}/{total_expected})")
                break

            if not _click_next_page(page):
                break

        # Take a final screenshot for reference
        try:
            page.screenshot(path=str(DATA_DIR / "debug_stripe_last.png"))
        except Exception:
            pass

        browser.close()

    log(f"Total rows scraped: {len(all_rows)}")
    if total_expected:
        log(f"Expected from Stripe: {total_expected} — captured {len(all_rows)}")

    if all_rows:
        # Dedupe on Email
        seen = set()
        unique: List[Dict[str, Any]] = []
        for r in all_rows:
            email = str(r.get("Email", "") or r.get("email", "")).strip().lower()
            key = email or json.dumps(r, sort_keys=True)[:200]
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        log(f"After dedup: {len(unique)} unique rows")

        # Write to MongoDB
        from mongo_client import get_raw_db
        db = get_raw_db()
        if db is not None:
            try:
                db["sheet_raw_stripe"].delete_many({})
                log("Cleared sheet_raw_stripe")
            except Exception:
                pass

        n = write_tab_data("Raw_STRIPE", unique, conflict_field=None, replace=True)
        log(f"✓ Wrote {n} rows to sheet_raw_stripe")

    log("=" * 60)
    log(f"SCRAPE_STRIPE COMPLETE — {len(all_rows)} rows")
    log("=" * 60)
    return 0 if all_rows else 1


if __name__ == "__main__":
    sys.exit(main())
