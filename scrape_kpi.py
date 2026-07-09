"""
scrape_kpi.py — Eagle 3D Streaming Analytics Hub
==================================================
Playwright scraper for the KPI dashboard (MUI React SPA).

Flow (proven to work):
  1. Fresh Firebase login (single-session, no storage_state)
  2. Wait for dashboard to fully load — MUI Select becomes ENABLED
  3. Change period to desired (Current Month / Last 6 Month)
  4. Wait for DataGrid to re-populate after period change
  5. For each tab (FREE, FIRST UPLOAD):
       - Click tab
       - Wait for DataGrid ready
       - Extract all rows (with virtualized-list scroll if needed)
       - Paginate to next page, repeat
  6. Write to MongoDB
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from playwright.sync_api import (
    Page, sync_playwright, TimeoutError as PlaywrightTimeoutError
)

from sheets_writer import write_tab_data


KPI_URL = "https://kpidashboard.eagle3dstreaming.com/"
DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)
DEBUG_DIR = DATA_DIR / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

HISTORICAL_MARKER = DATA_DIR / ".historical_done"
FORCE_HISTORICAL = os.environ.get("FORCE_HISTORICAL", "0") == "1"

SCRAPE_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
SCRAPE_DATE = datetime.now().strftime("%Y-%m-%d")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [KPI] {msg}", flush=True)


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
# LOGIN
# ─────────────────────────────────────────────────────────────────
def _login_in_page(page: Page) -> bool:
    email = _secret("KPI_EMAIL")
    password = _secret("KPI_PASSWORD")
    if not email or not password:
        log("KPI_EMAIL / KPI_PASSWORD missing")
        return False

    log(f"Logging in as {email}...")

    for sel in ['input[type="email"]', 'input[type="text"]']:
        if page.locator(sel).count() > 0:
            page.locator(sel).first.fill(email)
            break
    else:
        return False

    if page.locator('input[type="password"]').count() > 0:
        page.locator('input[type="password"]').first.fill(password)
    else:
        return False

    for sel in ['button:has-text("SIGN IN")', 'button:has-text("Sign in")',
                'button[type="submit"]']:
        if page.locator(sel).count() > 0:
            page.locator(sel).first.click()
            break

    log("  Waiting for auth...")
    for i in range(90):
        if page.locator('input[type="password"]').count() == 0:
            log(f"  Auth OK after {i+1}s")
            page.wait_for_timeout(6000)
            return True
        page.wait_for_timeout(1000)

    log("  Auth failed")
    return False


def _launch_browser(p):
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
    return browser, ctx


# ─────────────────────────────────────────────────────────────────
# WAIT FOR APP READY (period selector becomes ENABLED)
# ─────────────────────────────────────────────────────────────────
def _wait_for_app_ready(page: Page, max_wait_sec: int = 120) -> bool:
    """
    The MUI Select for period is `aria-disabled="true"` while data loads.
    We wait for it to become enabled — that means the app is fully hydrated.
    """
    log("Waiting for app to fully load (period select becomes enabled)...")
    for i in range(max_wait_sec):
        try:
            aria = page.locator('[role="combobox"]').first.get_attribute(
                "aria-disabled", timeout=2000
            )
            if aria != "true":
                log(f"  App ready after {i+1}s (period select enabled)")
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    log(f"  App did not become ready in {max_wait_sec}s")
    return False


# ─────────────────────────────────────────────────────────────────
# PERIOD (MUI SELECT)
# ─────────────────────────────────────────────────────────────────
def _select_mui_period(page: Page, period_label: str) -> bool:
    log(f"Setting period to '{period_label}'...")

    # Try multiple selectors for the trigger
    trigger = page.locator('[role="combobox"]').first
    if trigger.count() == 0:
        log("  No combobox found")
        return False

    # Verify it's enabled
    aria = trigger.get_attribute("aria-disabled")
    if aria == "true":
        log("  Period select is DISABLED — waiting more...")
        for _ in range(30):
            page.wait_for_timeout(1000)
            aria = trigger.get_attribute("aria-disabled")
            if aria != "true":
                log("  Period select now enabled")
                break
        else:
            log("  Still disabled after 30s — giving up")
            return False

    # Click to open dropdown
    try:
        trigger.click(timeout=10000)
        log("  Opened dropdown")
    except Exception as e:
        log(f"  Click failed: {e}")
        return False

    page.wait_for_timeout(2000)

    # Click the option
    for sel in [
        f'li[role="option"]:has-text("{period_label}")',
        f'[role="option"]:has-text("{period_label}")',
        f'li:has-text("{period_label}")',
    ]:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                loc.click(timeout=5000)
                log(f"  Selected '{period_label}'")
                page.wait_for_timeout(3000)
                return True
            except Exception:
                continue

    log(f"  Option '{period_label}' not found")
    # Close dropdown
    page.keyboard.press("Escape")
    return False


# ─────────────────────────────────────────────────────────────────
# WAIT FOR DATAGRID DATA
# ─────────────────────────────────────────────────────────────────
def _wait_for_datagrid_ready(page: Page, max_wait_sec: int = 90) -> str:
    """
    Wait for DataGrid to finish loading.
    Returns footer text like '1-5 of 68' or '0-0 of 0'.
    """
    log("  Waiting for DataGrid...")
    for i in range(max_wait_sec):
        loading = page.locator("text=Loading data").count() > 0
        try:
            footer = page.locator(
                '.MuiTablePagination-displayedRows'
            ).first.inner_text(timeout=800)
        except Exception:
            footer = ""

        if not loading and footer and "of" in footer.lower():
            log(f"    Ready after {i+1}s (footer: '{footer}')")
            # Extra safety: wait for any pending animations
            page.wait_for_timeout(1500)
            return footer
        page.wait_for_timeout(1000)

    log(f"    Timed out after {max_wait_sec}s")
    return ""


# ─────────────────────────────────────────────────────────────────
# DATAGRID EXTRACTION (handles virtualization)
# ─────────────────────────────────────────────────────────────────
def _extract_headers(page: Page) -> List[str]:
    """
    Get column names. Prefer human-readable innerText over data-field.
    """
    # Try innerText first (human labels like "Email"), fallback to data-field
    headers_text = page.eval_on_selector_all(
        '[role="columnheader"]',
        """els => els.map(e => {
            // Look for the header title span inside
            const title = e.querySelector('.MuiDataGrid-columnHeaderTitle');
            if (title && title.innerText.trim()) return title.innerText.trim();
            return (e.innerText || '').trim();
        })"""
    )
    headers_field = page.eval_on_selector_all(
        '[role="columnheader"]',
        "els => els.map(e => e.getAttribute('data-field') || '')"
    )

    # Use text if available, else data-field
    headers = []
    for i in range(max(len(headers_text), len(headers_field))):
        t = headers_text[i] if i < len(headers_text) else ""
        f = headers_field[i] if i < len(headers_field) else ""
        # Pick text if meaningful, else field
        h = t if t and len(t) < 40 and t.lower() not in ("", "actions") else f
        if h:
            headers.append(h)
    return headers


def _scroll_datagrid_and_extract(page: Page, tab_label: str,
                                  headers: List[str]) -> List[Dict[str, Any]]:
    """
    MUI DataGrid virtualizes — rows outside viewport aren't in DOM.
    Scroll the internal scroller down to force all rows to render on this page.
    """
    # Scroll the virtual scroller to bottom to render everything on current page
    try:
        page.evaluate("""
            const scroller = document.querySelector('.MuiDataGrid-virtualScroller');
            if (scroller) {
                scroller.scrollTop = scroller.scrollHeight;
            }
        """)
        page.wait_for_timeout(1500)
        # Scroll back to top
        page.evaluate("""
            const scroller = document.querySelector('.MuiDataGrid-virtualScroller');
            if (scroller) {
                scroller.scrollTop = 0;
            }
        """)
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Now extract rows
    rows_raw = page.eval_on_selector_all(
        '.MuiDataGrid-row',
        """rows => rows.map(row => {
            const cells = Array.from(row.querySelectorAll('.MuiDataGrid-cell'));
            const result = {};
            cells.forEach(c => {
                const field = c.getAttribute('data-field') || 'col_' + result.length;
                // Get text — prefer inner text over textContent
                const text = (c.innerText || c.textContent || '').trim();
                result[field] = text;
            });
            return result;
        })"""
    )

    rows_data: List[Dict[str, Any]] = []
    for row_dict in rows_raw:
        if not row_dict or all(not v for v in row_dict.values()):
            continue
        row_dict["__scraped_at__"] = SCRAPE_TS
        row_dict["__scrape_date__"] = SCRAPE_DATE
        row_dict["__tab__"] = tab_label
        rows_data.append(row_dict)

    return rows_data


def _get_footer_text(page: Page) -> str:
    try:
        return page.locator(
            '.MuiTablePagination-displayedRows'
        ).first.inner_text(timeout=800) or ""
    except Exception:
        return ""


def _mui_next_page(page: Page) -> bool:
    """
    Advance MUI DataGrid to next page.

    Strategy: try up to 8 times with growing waits. Between attempts,
    fire a Page-Down key or JS scroll to unstick any animation lock.
    Verify success via footer text change.
    """
    footer_before = _get_footer_text(page)

    NEXT_SELECTORS = [
        'button[aria-label="Go to next page"]',
        'button[title="Go to next page"]',
    ]

    for attempt in range(8):
        # Progressive wait between attempts
        wait_ms = 800 + attempt * 400
        page.wait_for_timeout(wait_ms)

        for sel in NEXT_SELECTORS:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue

            disabled_attr = loc.get_attribute("disabled")
            aria_disabled = loc.get_attribute("aria-disabled")

            # If button says disabled, MAYBE it's animation-lock. Try JS click.
            try:
                # Use JS to click regardless of disabled state
                # (some MUI apps re-enable button JUST after click event fires)
                clicked = page.evaluate("""(sel) => {
                    const btns = document.querySelectorAll(sel);
                    for (const b of btns) {
                        if (b) {
                            b.removeAttribute('disabled');
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }""", sel)

                if clicked:
                    page.wait_for_timeout(2000)
                    footer_after = _get_footer_text(page)
                    if footer_after and footer_after != footer_before:
                        return True
            except Exception as e:
                pass

    # After 8 attempts, verify we're TRULY on last page by checking footer
    footer_final = _get_footer_text(page)
    if footer_final:
        import re
        # Footer format: "N-M of TOTAL"
        m = re.search(r"(\d+)[–-](\d+)\s+of\s+(\d+)", footer_final)
        if m:
            end = int(m.group(2))
            total = int(m.group(3))
            if end >= total:
                log(f"    Truly on last page (footer: '{footer_final}')")
            else:
                log(f"    Pagination STUCK at '{footer_final}' — reached only {end}/{total}")
    return False


def _mui_reset_to_first_page(page: Page) -> None:
    """
    Reset MUI DataGrid to page 1.
    Try "Go to first page" button, or click "previous" repeatedly until disabled.
    """
    # Try "Go to first page" button (present on some MUI versions)
    for sel in [
        'button[aria-label="Go to first page"]',
        'button[title="Go to first page"]',
    ]:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                if loc.is_enabled():
                    loc.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                pass

    # Fallback: click "Previous" until disabled (max 100 clicks)
    for _ in range(100):
        prev_locs = [
            'button[aria-label="Go to previous page"]',
            'button[title="Go to previous page"]',
        ]
        clicked = False
        for sel in prev_locs:
            loc = page.locator(sel).first
            if loc.count() > 0:
                try:
                    disabled = loc.get_attribute("disabled")
                    aria_disabled = loc.get_attribute("aria-disabled")
                    if disabled is not None or aria_disabled == "true":
                        return  # already on first page
                    if not loc.is_enabled():
                        return
                    loc.click(timeout=2000)
                    page.wait_for_timeout(1200)
                    clicked = True
                    break
                except Exception:
                    continue
        if not clicked:
            return


def _click_tab(page: Page, tab_name: str) -> bool:
    for sel in [f'button:has-text("{tab_name}")',
                f'[role="tab"]:has-text("{tab_name}")']:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                loc.click(timeout=5000)
                page.wait_for_timeout(2000)
                log(f"  Clicked tab '{tab_name}'")
                return True
            except Exception:
                continue
    log(f"  Could not click tab '{tab_name}'")
    return False


# ─────────────────────────────────────────────────────────────────
# TAB SCRAPING
# ─────────────────────────────────────────────────────────────────
def scrape_tab(page: Page, tab_name: str,
               mongo_collection: str,
               period_label: str = "Current Month") -> Dict[str, Any]:
    log(f"Scraping tab '{tab_name}'")

    _click_tab(page, tab_name)
    _wait_for_datagrid_ready(page, max_wait_sec=60)

    # Reset to page 1
    log("  Resetting pagination to first page...")
    _mui_reset_to_first_page(page)
    page.wait_for_timeout(1500)

    # CRITICAL: RE-APPLY period to force DataGrid to invalidate stale cache
    # Click on some other period, then back to current — forces full refetch
    log(f"  Re-applying period '{period_label}' to force fresh data...")
    _select_mui_period(page, "All Time" if period_label != "All Time" else "Last Month")
    page.wait_for_timeout(2000)
    _select_mui_period(page, period_label)
    page.wait_for_timeout(3000)

    # Reset pagination AGAIN after period change
    _mui_reset_to_first_page(page)
    page.wait_for_timeout(1500)

    # Now wait for footer to stabilize with REAL count
    log("  Waiting for footer to stabilize (real data loaded)...")
    stable_count = 0
    last_footer = ""
    for i in range(60):
        cur = _get_footer_text(page)
        if cur and cur == last_footer:
            stable_count += 1
            if stable_count >= 5:  # 5s stable
                log(f"    Footer stable at '{cur}' after {i+1}s")
                break
        else:
            stable_count = 0
            last_footer = cur
        page.wait_for_timeout(1000)

    footer = last_footer or _get_footer_text(page)
    log(f"  Final footer: '{footer}'")

    # Parse total rows from footer (e.g., "1–5 of 68" → 68)
    total_expected = 0
    try:
        import re
        m = re.search(r"of\s+(\d+)", footer)
        if m:
            total_expected = int(m.group(1))
            log(f"  Expected total rows: {total_expected}")
    except Exception:
        pass

    if total_expected == 0:
        log("  DataGrid is empty for this period")
        return {"tab": tab_name, "rows": 0, "pages": 0}

    headers = _extract_headers(page)
    log(f"  Headers ({len(headers)}): {headers}")

    all_rows: List[Dict[str, Any]] = []
    pages_seen = 0
    max_pages = 500

    while pages_seen < max_pages:
        page_rows = _scroll_datagrid_and_extract(page, tab_name, headers)
        pages_seen += 1
        all_rows.extend(page_rows)
        log(f"  Page {pages_seen}: +{len(page_rows)} rows (total: {len(all_rows)}/{total_expected})")

        if len(all_rows) >= total_expected:
            log("  All expected rows collected")
            break

        if not _mui_next_page(page):
            break

    log(f"  TOTAL: {len(all_rows)} rows in {pages_seen} pages "
        f"(expected {total_expected})")

    if all_rows:
        from mongo_client import get_raw_db
        db = get_raw_db()
        if db is not None:
            try:
                db[mongo_collection].delete_many({})
                log(f"  Cleared {mongo_collection}")
            except Exception:
                pass

        n = write_tab_data(mongo_collection.replace("sheet_", ""), all_rows,
                           conflict_field=None, replace=True)
        log(f"  Wrote {n} rows to {mongo_collection}")

    return {"tab": tab_name, "rows": len(all_rows), "pages": pages_seen}


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main() -> int:
    log("=" * 60)
    log("SCRAPE_KPI STARTING (MUI-aware, wait-for-enabled)")
    log("=" * 60)

    if FORCE_HISTORICAL or not HISTORICAL_MARKER.exists():
        period = "Last 6 Month"
        log("Mode: HISTORICAL (Last 6 Month)")
    else:
        period = "Current Month"
        log("Mode: DAILY (Current Month)")

    results = []
    with sync_playwright() as p:
        browser, ctx = _launch_browser(p)
        page = ctx.new_page()

        try:
            page.goto(KPI_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)

            # Login
            if page.locator('input[type="password"]').count() > 0:
                if not _login_in_page(page):
                    browser.close()
                    return 1

            if page.locator('input[type="password"]').count() > 0:
                log("Still logged out — aborting")
                page.screenshot(path=str(DEBUG_DIR / "still_logged_out.png"),
                                full_page=True)
                browser.close()
                return 1

            log(f"URL after auth: {page.url}")

            # WAIT FOR APP TO BE FULLY READY (period select enabled)
            if not _wait_for_app_ready(page, max_wait_sec=120):
                log("App failed to become ready — trying anyway")

            # CHANGE PERIOD FIRST (default is "Last Month")
            _select_mui_period(page, period)

            # Wait for DataGrid to reload after period change
            page.wait_for_timeout(3000)
            _wait_for_datagrid_ready(page, max_wait_sec=120)

            # Now scrape both tabs
            results.append(scrape_tab(page, "FREE", "sheet_raw_free"))
            results.append(scrape_tab(page, "FIRST UPLOAD",
                                       "sheet_raw_first_upload"))

            if FORCE_HISTORICAL or not HISTORICAL_MARKER.exists():
                HISTORICAL_MARKER.write_text(SCRAPE_TS)
                log(f"Marked historical done ({HISTORICAL_MARKER})")

        except Exception as e:
            log(f"Scrape error: {e}")
            import traceback
            traceback.print_exc()
            try:
                page.screenshot(path=str(DEBUG_DIR / "kpi_error.png"),
                                full_page=True)
            except Exception:
                pass
            browser.close()
            return 1

        browser.close()

    log("=" * 60)
    log("SCRAPE_KPI COMPLETE")
    total = 0
    for r in results:
        log(f"  {r['tab']:15s}: {r['rows']} rows, {r['pages']} pages")
        total += r['rows']
    log("=" * 60)

    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
