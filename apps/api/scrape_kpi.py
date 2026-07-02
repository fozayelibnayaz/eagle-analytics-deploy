"""
scrape_kpi.py - FINAL VERSION

CRITICAL SEQUENCE:
  1. Load page (default Last Month - shows 65)
  2. Wait for dropdown enabled
  3. Change dropdown to target filter (Last 6 Month for first time, Current Month for daily)
  4. Wait for KPI card to update (proves data refreshed)
  5. CLICK THE TAB (this re-loads the table with NEW filter data)
  6. Wait for footer to show new total (619 not 65)
  7. Set max page size  
  8. Paginate ALL pages

DAILY MODE LOGIC:
  - First time (no historical marker): use "Last 6 Month" → ~619 rows
  - After first time: use "Current Month" → ~50-100 rows daily
  - APPEND mode dedupes by email
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

from sheets_writer import write_tab_data, read_tab_data, write_run_summary

DATA_DIR    = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)
SCRAPE_TS   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
SCRAPE_DATE = datetime.now().strftime("%Y-%m-%d")

KPI_URL = "https://kpidashboard.eagle3dstreaming.com/"

# Marker file to track if historical scrape is done
HISTORICAL_MARKER = DATA_DIR / ".historical_done"

FORCE_HISTORICAL = os.environ.get("FORCE_HISTORICAL", "") == "1"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [KPI] {msg}", flush=True)


# ─── AUTH ─────────────────────────────────────────────
def get_context(p):
    storage_file = Path("kpi_storage_state.json")
    session_dir  = Path("browser_session")

    if storage_file.exists() and storage_file.stat().st_size > 200:
        log("Auth: kpi_storage_state.json")
        browser = p.chromium.launch(
            headless=True, args=["--no-sandbox","--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            viewport={"width":1920,"height":1080},
            storage_state=str(storage_file),
        )
        return browser, ctx

    if session_dir.exists() and len(list(session_dir.iterdir())) > 3:
        log("Auth: browser_session/")
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"],
            viewport={"width":1920,"height":1080},
        )
        return None, ctx

    log("WARNING: no auth")
    browser = p.chromium.launch(
        headless=True, args=["--no-sandbox","--disable-dev-shm-usage"]
    )
    ctx = browser.new_context(viewport={"width":1920,"height":1080})
    return browser, ctx


def check_logged_in(page) -> bool:
    return page.locator('input[type="password"]').count() == 0


def perform_login(page) -> bool:
    """Fallback: log in directly if storage state failed."""
    email = os.environ.get("KPI_EMAIL", "").strip()
    password = os.environ.get("KPI_PASSWORD", "").strip()

    if not email or not password:
        log("  No KPI_EMAIL/PASSWORD env vars for fallback login")
        return False

    log(f"  Attempting fallback login as {email}...")

    try:
        # Fill email
        for sel in ['input[type="email"]', 'input[type="text"]',
                    'input[placeholder*="mail" i]']:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.fill(email)
                break

        time.sleep(1)
        page.locator('input[type="password"]').first.fill(password)
        time.sleep(1)

        # Submit
        for sel in ['button[type="submit"]', 'button:has-text("SIGN IN")',
                    'button:has-text("Sign In")', 'button:has-text("Login")']:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                break
        else:
            page.locator('input[type="password"]').first.press("Enter")

        # Wait for login
        for i in range(30):
            time.sleep(2)
            if page.locator('input[type="password"]').count() == 0:
                log(f"  ✅ Fallback login succeeded after {(i+1)*2}s")
                time.sleep(5)  # let dashboard load
                return True

        log("  ❌ Fallback login failed")
        return False
    except Exception as e:
        log(f"  Fallback login error: {e}")
        return False


# ─── DETERMINE TARGET FILTER ───────────────────────────
def determine_target_filter() -> str:
    """
    First run ever (no marker file): "Last 6 Month" - get historical
    All subsequent runs: "Current Month" - daily incremental
    FORCE_HISTORICAL=1 overrides to always use Last 6 Month
    """
    if FORCE_HISTORICAL:
        log("FORCE_HISTORICAL=1 - using 'Last 6 Month'")
        return "Last 6 Month"

    if HISTORICAL_MARKER.exists():
        log("Historical scrape already done - using 'Current Month' for daily")
        return "Current Month"

    log("First time - using 'Last 6 Month' for historical scrape")
    return "Last 6 Month"


# ─── DROPDOWN INTERACTION ──────────────────────────────
def wait_for_dropdown_enabled(page, max_wait=90) -> bool:
    log("Waiting for dropdown to be enabled...")
    for sec in range(max_wait):
        try:
            el = page.locator(".MuiSelect-select").first
            if el.count() > 0:
                cls = el.get_attribute("class") or ""
                if "Mui-disabled" not in cls and el.is_visible(timeout=500):
                    log(f"  ENABLED after {sec}s")
                    return True
        except Exception:
            pass
        if sec % 10 == 0 and sec > 0:
            log(f"  ({sec}s) still waiting for dropdown...")
        time.sleep(1)
    return False


def get_current_filter(page) -> str:
    try:
        return page.locator(".MuiSelect-select").first.inner_text().strip()
    except Exception:
        return "?"


def get_free_card_value(page) -> int:
    """Read the 'Free Trial Accounts' big number on KPI cards."""
    try:
        return page.evaluate("""
            () => {
                // Find the card containing "Free Trial Accounts" text
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const txt = (el.innerText || '').trim();
                    if (!txt.startsWith('Free Trial Accounts')) continue;
                    if (txt.length > 300) continue;
                    // Extract first number after the label
                    const m = txt.match(/Free Trial Accounts\\s*\\n?\\s*(\\d[\\d,]*)/);
                    if (m) return parseInt(m[1].replace(/,/g,''));
                }
                return -1;
            }
        """)
    except Exception:
        return -1


def change_filter(page, target: str) -> tuple:
    """
    Change the dropdown filter and wait for data to refresh.
    Returns (success, actual_filter, free_card_value).
    """
    log(f"\n{'='*50}")
    log(f"CHANGING FILTER TO: '{target}'")
    log(f"{'='*50}")

    if not wait_for_dropdown_enabled(page):
        log("FAILED: dropdown never enabled")
        return False, "?", -1

    current = get_current_filter(page)
    baseline = get_free_card_value(page)
    log(f"Current filter: '{current}', baseline FREE card: {baseline}")

    if current == target:
        log(f"Already on '{target}' - but will re-click to force refresh")
        # Don't skip - re-click to ensure fresh data is loaded
        # (cached data from yesterday's run might be stale), baseline

    # Open dropdown
    log(f"Opening dropdown...")
    page.locator(".MuiSelect-select").first.click()
    time.sleep(2.5)

    # Find and click target option
    options = page.locator("li[role='option']").all()
    avail = [(o.text_content() or "").strip() for o in options]
    log(f"Available options: {avail}")

    found = False
    for opt in options:
        if (opt.text_content() or "").strip() == target:
            opt.click()
            found = True
            log(f"Clicked: '{target}'")
            break

    if not found:
        log(f"ERROR: '{target}' not found in {avail}")
        page.keyboard.press("Escape")
        return False, current, baseline

    # CRITICAL: Wait for KPI card to change (proof data refreshed)
    log(f"Waiting for KPI card to update from {baseline}...")
    new_value = baseline
    refreshed = False
    for sec in range(90):
        time.sleep(1)
        new_value = get_free_card_value(page)
        if new_value > 0 and new_value != baseline:
            log(f"  KPI card updated after {sec+1}s: {baseline} → {new_value}")
            refreshed = True
            break
        if sec % 5 == 0 and sec > 0:
            log(f"  ({sec+1}s) Card still: {new_value}")

    if not refreshed:
        log(f"  WARNING: card never changed ({baseline} → {new_value})")
        log(f"  Continuing anyway - dropdown shows: '{get_current_filter(page)}'")

    # Extra wait for tables/charts to fully render
    log(f"Waiting 8s for full data render...")
    time.sleep(8)

    actual = get_current_filter(page)
    final = get_free_card_value(page)
    log(f"DONE: filter='{actual}', FREE card={final}")
    return True, actual, final


# ─── TAB CLICKING (FORCES TABLE RELOAD) ────────────────


def wait_for_table_stable(page, max_wait=30):
    """
    Wait until table footer total is the SAME for 5 consecutive seconds.
    This means data has fully loaded and stopped changing.
    Returns the stable total or -1 if never stable.
    """
    log("  Waiting for table to stabilize...")
    last_total = -1
    stable_count = 0
    
    for sec in range(max_wait):
        try:
            footer = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('[class*="MuiTablePagination"]');
                    for (const el of els) {
                        const t = (el.innerText || '').trim();
                        if (t.match(/of\\s+\\d/)) return t;
                    }
                    return '';
                }
            """)
            
            if footer:
                m = re.search(r"of\s+(\d[\d,]*)", footer)
                if m:
                    total = int(m.group(1).replace(",",""))
                    if total == last_total and total > 0:
                        stable_count += 1
                        if stable_count >= 5:
                            log(f"  Table stable at {total} rows ({sec+1}s elapsed)")
                            return total
                    else:
                        if last_total > 0 and total != last_total:
                            log(f"  Total changed: {last_total} → {total}")
                        stable_count = 0
                        last_total = total
        except Exception:
            pass
        time.sleep(1)
    
    log(f"  Table never stabilized in {max_wait}s (last total: {last_total})")
    return last_total


def click_tab_force_reload(page, tab_name: str, expected_min: int = 0) -> bool:
    """
    Click tab to force table to reload with current filter data.
    Wait for footer total to be reasonable (matches expected_min if given).
    """
    log(f"\n--- Clicking tab: {tab_name} ---")

    # Click another tab first to force reload state, then click target
    # This handles MUI tab caching behavior
    other_tabs = ["PAID", "500 MIN", "FIRST UPLOAD", "FREE"]
    other = next((t for t in other_tabs if t != tab_name), None)

    # Click an OTHER tab first to clear state
    if other:
        try:
            for sel in [f'button:has-text("{other}")']:
                el = page.locator(sel).first
                if el.is_visible(timeout=1500):
                    el.click()
                    log(f"  Clicked '{other}' first to reset state")
                    time.sleep(3)
                    break
        except Exception:
            pass

    # Now click target tab
    clicked = False
    for sel in [
        f'button:has-text("{tab_name}")',
        f'[role="tab"]:has-text("{tab_name}")',
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                clicked = True
                log(f"  Clicked '{tab_name}'")
                break
        except Exception:
            continue

    if not clicked:
        log(f"  Tab '{tab_name}' not found")
        return False

    # Wait for table to appear
    try:
        page.wait_for_selector(".MuiDataGrid-root, table", timeout=20000)
    except Exception:
        log(f"  No table appeared")
        return False

    time.sleep(5)

    # Wait for footer to show expected total
    log(f"  Waiting for footer total (expected ~{expected_min})...")
    for sec in range(45):
        time.sleep(1)
        try:
            footer = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('[class*="MuiTablePagination"]');
                    for (const el of els) {
                        const t = (el.innerText || '').trim();
                        if (t.match(/of\\s+\\d/)) return t;
                    }
                    return '';
                }
            """)
            if footer:
                m = re.search(r'of\s+(\d[\d,]*)', footer)
                if m:
                    total = int(m.group(1).replace(",",""))
                    if expected_min == 0 or total >= expected_min * 0.5:
                        log(f"  Footer: '{footer}' (total: {total})")
                        return True
                    elif sec >= 20:
                        log(f"  Footer shows {total} but expected ~{expected_min}")
                        log(f"  ({sec}s) waiting for more data...")
        except Exception:
            pass
        if sec % 10 == 0 and sec > 0:
            log(f"  ({sec}s) footer: '{footer}'...")

    log(f"  Tab loaded (footer: '{footer}')")
    return True


# ─── MAX PAGE SIZE ─────────────────────────────────────
def set_max_page_size(page) -> int:
    log("Setting max page size...")

    # Try multiple selectors
    selectors = [
        ".MuiTablePagination-select",
        ".MuiTablePagination-input .MuiSelect-select",
        ".MuiTablePagination-toolbar .MuiSelect-select",
        ".MuiTablePagination-displayedRows + div .MuiSelect-select",
        '[id*="MuiTablePagination"]',
        'div.MuiTablePagination-root .MuiSelect-select',
    ]

    for sel in selectors:
        try:
            els = page.locator(sel).all()
            for el in els:
                try:
                    if not el.is_visible(timeout=500):
                        continue
                    txt = el.inner_text().strip()
                    # Page size selector usually shows a number like "5" or "10"
                    if txt.isdigit():
                        log(f"  Found page size selector via '{sel}' showing '{txt}'")
                        el.click()
                        time.sleep(2)

                        options = page.locator("li[role='option']").all()
                        sized = []
                        for opt in options:
                            t = (opt.text_content() or "").strip()
                            if t.isdigit():
                                sized.append((int(t), opt, t))

                        if sized:
                            sized.sort(key=lambda x: x[0], reverse=True)
                            biggest = sized[0]
                            log(f"  Available: {[s[2] for s in sized]}, picking {biggest[0]}")
                            biggest[1].click()
                            time.sleep(5)
                            return biggest[0]
                        else:
                            page.keyboard.press("Escape")
                except Exception:
                    continue
        except Exception:
            continue

    log("  No page size selector found - keeping default")
    return 5


# ─── EXTRACT TABLE ─────────────────────────────────────
def extract_table_full(page) -> dict:
    return page.evaluate("""
        () => {
            const candidates = [
                ...document.querySelectorAll('[role="grid"]'),
                ...document.querySelectorAll('[class*="MuiDataGrid"]'),
                ...document.querySelectorAll('table'),
            ];
            let best = null, maxR = 0;
            for (const c of candidates) {
                const r = c.querySelectorAll('[role="row"], tr').length;
                if (r > maxR) { maxR = r; best = c; }
            }
            if (!best) return {headers:[], rows:[], total:-1, footer:''};

            const hEls = best.querySelectorAll('[role="columnheader"], th');
            const headers = Array.from(hEls)
                .map(h => h.innerText.trim())
                .filter(h => h);

            const rows = [];
            const seen_ids = new Set();

            const rowsWithId = best.querySelectorAll('[role="row"][data-id]');
            for (const r of rowsWithId) {
                const id = r.getAttribute('data-id');
                if (seen_ids.has(id)) continue;
                seen_ids.add(id);
                const cells = r.querySelectorAll('[role="cell"], [role="gridcell"]');
                if (!cells.length) continue;
                const vals = Array.from(cells).map(c => c.innerText.trim());
                if (vals.every(v => !v)) continue;
                rows.push({id: id, vals: vals});
            }

            if (rows.length === 0) {
                const allRows = best.querySelectorAll('[role="row"], tr');
                let idx = 0;
                for (const r of allRows) {
                    const cells = r.querySelectorAll('[role="cell"], [role="gridcell"], td');
                    if (!cells.length) continue;
                    const vals = Array.from(cells).map(c => c.innerText.trim());
                    if (vals.every(v => !v)) continue;
                    if (headers.length && vals[0] === headers[0]) continue;
                    if (vals.filter(v => v.length > 0).length < 2) continue;
                    rows.push({id: 'idx_' + idx++, vals: vals});
                }
            }

            let total = -1;
            let footer = '';
            const pagEls = document.querySelectorAll('[class*="MuiTablePagination"]');
            for (const el of pagEls) {
                const t = (el.innerText || '').trim();
                if (t) footer = t;
                const m = t.match(/of\\s+(\\d[\\d,]*)/i);
                if (m) {
                    total = parseInt(m[1].replace(/,/g,''));
                    break;
                }
            }
            // Normalize column names to match pipeline expectations
            const normalizedHeaders = headers.map(h => {
                const map = {
                    "Signup_Date": "Account Created On",
                    "First_Upload_Date": "Upload Date",
                    "Payment_Date": "First payment",
                };
                return map[h] || h;
            });
            return {headers: normalizedHeaders, rows, total, footer};
        }
    """)


# ─── EXTRACT APP URLS ──────────────────────────────────
def extract_app_urls(page) -> dict:
    """Extract App Name -> URL mapping from the current table view.
    The KPI Dashboard has clickable App Name links pointing to
    connector.eagle3dstreaming.com project URLs.
    Scrolls through all pages to get ALL URLs.
    """
    try:
        # First, scroll through all grid pages to load all rows
        page.evaluate("""async () => {
            const grid = document.querySelector('[role="grid"]') ||
                         document.querySelector('[class*="MuiDataGrid"]');
            if (!grid) return;
            
            // Try to set page size to maximum (shows all rows)
            const pageSizeSelectors = [
                'select[class*="PageSize"]',
                '[class*="pageSize"]',
                'input[class*="PageSize"]',
            ];
            for (const sel of pageSizeSelectors) {
                const el = document.querySelector(sel);
                if (el) {
                    el.value = '100';
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    break;
                }
            }
            
            // Wait a moment for grid to update
            await new Promise(r => setTimeout(r, 500));
            
            // Also scroll the grid container to trigger virtualization
            const gridContainer = grid.querySelector('[class*="virtualScroller"]') ||
                                  grid.querySelector('[class*="VirtualScroller"]') ||
                                  grid.querySelector('[role="rowgroup"]') ||
                                  grid;
            if (gridContainer) {
                const maxScroll = gridContainer.scrollHeight || 50000;
                for (let pos = 0; pos < maxScroll; pos += 500) {
                    gridContainer.scrollTop = pos;
                    await new Promise(r => setTimeout(r, 50));
                }
                // Scroll back to top
                gridContainer.scrollTop = 0;
                await new Promise(r => setTimeout(r, 300));
            }
        }""")
        
        # Now extract all visible URLs
        urls = page.evaluate("""() => {
            const result = {};
            const grid = document.querySelector('[role="grid"]') ||
                         document.querySelector('[class*="MuiDataGrid"]');
            if (!grid) return result;
            
            // Find the App Name column index
            const hEls = grid.querySelectorAll('[role="columnheader"], th');
            let appIdx = -1;
            for (let i = 0; i < hEls.length; i++) {
                const txt = (hEls[i].innerText || '').trim().toLowerCase();
                if (txt === 'app name' || txt === 'app' || txt === 'project' || txt === 'project name') {
                    appIdx = i;
                    break;
                }
            }
            if (appIdx < 0) return result;
            
            // Extract links from App Name cells
            const rows = grid.querySelectorAll('[role="row"][data-id]');
            for (const row of rows) {
                const cells = row.querySelectorAll('[role="cell"], [role="gridcell"]');
                if (appIdx < cells.length) {
                    const cell = cells[appIdx];
                    const links = cell.querySelectorAll('a[href]');
                    if (links.length > 0) {
                        const href = links[0].getAttribute('href');
                        const text = links[0].innerText.trim() || cell.innerText.trim();
                        if (href && text && href.startsWith('http')) {
                            result[text] = href;
                        }
                    }
                }
            }
            
            // Also try without data-id rows
            if (Object.keys(result).length === 0) {
                const allRows = grid.querySelectorAll('[role="row"], tr');
                for (const row of allRows) {
                    const cells = row.querySelectorAll('[role="cell"], [role="gridcell"], td');
                    if (appIdx < cells.length) {
                        const cell = cells[appIdx];
                        const links = cell.querySelectorAll('a[href]');
                        if (links.length > 0) {
                            const href = links[0].getAttribute('href');
                            const text = links[0].innerText.trim() || cell.innerText.trim();
                            if (href && text && href.startsWith('http')) {
                                result[text] = href;
                            }
                        }
                    }
                }
            }
            return result;
        }""")
        if urls:
            log(f"  Extracted {len(urls)} App URLs")
        return urls
    except Exception as e:
        log(f"  App URL extraction failed: {e}")
        return {}


# ─── PAGINATE ──────────────────────────────────────────
def paginate_all(page, tab_label: str) -> tuple:
    log(f"\nPagination: {tab_label}")

    page_size = set_max_page_size(page)
    log(f"  Page size: {page_size}")
    time.sleep(3)

    all_rows_dict = {}
    headers       = []
    page_num      = 1
    expected      = -1
    no_progress   = 0
    max_pages     = 500

    while page_num <= max_pages:
        time.sleep(2)
        data = extract_table_full(page)

        if data.get("headers"):
            headers = data["headers"]

        if expected < 0 and data.get("total", -1) > 0:
            expected = data["total"]
            log(f"  EXPECTED TOTAL: {expected} rows")

        page_rows = data.get("rows", [])
        if not page_rows:
            log(f"  p{page_num}: 0 rows")
            no_progress += 1
            if no_progress >= 3:
                break
        else:
            new_count = 0
            for r in page_rows:
                if r["id"] not in all_rows_dict:
                    all_rows_dict[r["id"]] = r["vals"]
                    new_count += 1

            footer = data.get("footer","")[:60]
            suffix = f" / {expected}" if expected > 0 else ""
            log(f"  p{page_num}: +{new_count} | total: {len(all_rows_dict)}{suffix} | {footer}")

            if new_count == 0:
                no_progress += 1
                if no_progress >= 3:
                    break
            else:
                no_progress = 0

        if expected > 0 and len(all_rows_dict) >= expected:
            log(f"  Reached expected total {expected}")
            break

        # Try scroll first
        try:
            scroller = page.locator(".MuiDataGrid-virtualScroller").first
            if scroller.count() > 0:
                scroller.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                time.sleep(2)
                d2 = extract_table_full(page)
                more = 0
                for r in d2.get("rows", []):
                    if r["id"] not in all_rows_dict:
                        all_rows_dict[r["id"]] = r["vals"]
                        more += 1
                if more > 0:
                    log(f"  Scroll added: +{more}")
                    continue
        except Exception:
            pass

        # Click next page
        clicked = False
        for sel in [
            'button[aria-label="Go to next page"]',
            'button[aria-label="Next page"]',
            'button[title="Go to next page"]',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=800):
                    cls = btn.get_attribute("class") or ""
                    if (btn.get_attribute("disabled") is not None
                            or "Mui-disabled" in cls):
                        log(f"  Last page reached")
                        return headers, [v for v in all_rows_dict.values()]
                    btn.click()
                    clicked = True
                    page_num += 1
                    time.sleep(3)
                    break
            except Exception:
                continue

        if not clicked:
            log(f"  No next button")
            break

    final = list(all_rows_dict.values())
    log(f"{tab_label}: {len(final)} unique rows" +
        (f" (expected {expected}, missing {expected-len(final)})" if expected > 0 else ""))
    return headers, final


# ─── APPEND MODE ───────────────────────────────────────
def merge_with_existing(tab_name: str, new_rows: list) -> list:
    try:
        existing = read_tab_data(tab_name)
        log(f"  Existing in {tab_name}: {len(existing)}")
    except Exception:
        existing = []

    by_email = {}
    for r in existing:
        email = ""
        for k in ("Email","email","__email_normalized__"):
            if k in r and r[k] and "@" in str(r[k]):
                email = str(r[k]).strip().lower()
                break
        if email:
            by_email[email] = r

    new_count = updated = 0
    for r in new_rows:
        email = ""
        for k in ("Email","email"):
            if k in r and r[k] and "@" in str(r[k]):
                email = str(r[k]).strip().lower()
                break
        if email:
            if email in by_email:
                by_email[email] = {**by_email[email], **r}
                updated += 1
            else:
                by_email[email] = r
                new_count += 1

    log(f"  After merge: {len(by_email)} (+{new_count} new, {updated} updated)")
    return list(by_email.values())


TABS = {"FREE": "FREE", "FIRST UPLOAD": "FIRST_UPLOAD"}


# ─── MAIN ──────────────────────────────────────────────
def main():
    log("=" * 60)
    log(f"KPI SCRAPER - {SCRAPE_TS}")
    log("=" * 60)

    target_filter = determine_target_filter()
    log(f"TARGET FILTER: '{target_filter}'")

    with sync_playwright() as p:
        browser, ctx = get_context(p)

        try:
            page = ctx.new_page()
            log(f"Loading {KPI_URL}")
            page.goto(KPI_URL, wait_until="domcontentloaded", timeout=90000)
            time.sleep(12)  # Long initial wait for full app load

            log(f"URL: {page.url}")
            page.screenshot(path=str(DATA_DIR / "debug_01_loaded.png"))

            if not check_logged_in(page):
                log("Not logged in via storage state — attempting fresh login...")
                if not perform_login(page):
                    try:
                        page.screenshot(path=str(DATA_DIR / "debug_not_logged_in.png"))
                    except Exception:
                        pass
                    raise RuntimeError("KPI login failed — both storage state and fresh login failed")
                log("✅ Fresh login successful, continuing scrape")

            # ─── STEP 1: CHANGE FILTER FIRST ───
            success, actual_filter, free_card = change_filter(page, target_filter)
            log(f"\nFilter result: actual='{actual_filter}', FREE card={free_card}")
            page.screenshot(path=str(DATA_DIR / "debug_02_filter_set.png"))

            if free_card <= 0:
                log("WARNING: free_card is invalid - data may not have loaded")

            # ─── STEP 2: For each tab, click + wait + paginate ───
            summary = {}
            for tab_label, tab_key in TABS.items():
                # CRITICAL: click tab AFTER filter is set, then paginate
                if not click_tab_force_reload(page, tab_label,
                                              expected_min=free_card if tab_label == "FREE" else 100):
                    summary[tab_key] = 0
                    continue

                page.screenshot(path=str(DATA_DIR / f"debug_tab_{tab_key}.png"))

                headers, raw_rows = paginate_all(page, tab_label)

                if not raw_rows:
                    summary[tab_key] = 0
                    continue

                # Extract App URLs from the KPI Dashboard (project hyperlinks)
                app_url_map = {}
                if tab_key == "FIRST_UPLOAD":
                    try:
                        app_url_map = extract_app_urls(page)
                        if app_url_map:
                            log(f"  App URLs: {len(app_url_map)} project links found")
                    except Exception as e:
                        log(f"  App URL extraction skipped: {e}")

                enriched = []
                for r in raw_rows:
                    d = {headers[i]: r[i] if i < len(r) else ""
                         for i in range(len(headers))}
                    d["__tab__"]         = tab_label
                    d["__period__"]      = actual_filter
                    d["__scraped_at__"]  = SCRAPE_TS
                    d["__scrape_date__"] = SCRAPE_DATE
                    # Add App URL from the extracted mapping
                    if app_url_map:
                        _app_name_val = d.get("App Name", d.get("App", d.get("Project", "")))
                        if _app_name_val and str(_app_name_val).strip() in app_url_map:
                            d["App URL"] = app_url_map[str(_app_name_val).strip()]
                    enriched.append(d)

                merged = merge_with_existing(f"Raw_{tab_key}", enriched)
                ok = write_tab_data(f"Raw_{tab_key}", merged)
                summary[tab_key] = {"scraped": len(enriched), "total": len(merged)}

            # Mark historical done if Last 6 Month succeeded
            if (target_filter == "Last 6 Month"
                    and isinstance(summary.get("FREE"), dict)
                    and summary["FREE"].get("scraped", 0) >= 100):
                HISTORICAL_MARKER.write_text(
                    f"Historical scrape completed at {SCRAPE_TS}\n"
                    f"Filter: {target_filter}\n"
                    f"Free card: {free_card}\n"
                    f"FREE scraped: {summary['FREE']['scraped']}\n"
                    f"FIRST_UPLOAD scraped: {summary.get('FIRST_UPLOAD',{}).get('scraped',0)}\n"
                    f"\nFrom now on, daily runs will use 'Current Month'.\n"
                    f"Delete this file to force another historical scrape.\n"
                )
                log(f"\n✓ Marked HISTORICAL_DONE → {HISTORICAL_MARKER}")
                log(f"  Future runs will use 'Current Month' (daily mode)")

            log(f"\n{'='*60}")
            log("COMPLETE")
            for k, v in summary.items():
                if isinstance(v, dict):
                    log(f"  {k}: scraped={v['scraped']}, total={v['total']}")

            write_run_summary({
                "run_at":    SCRAPE_TS,
                "stage":     "kpi",
                "filter":    actual_filter,
                "free_card": free_card,
                "historical_done": HISTORICAL_MARKER.exists(),
                **{f"{k}_scraped": v.get('scraped',0) if isinstance(v,dict) else v
                   for k,v in summary.items()},
                **{f"{k}_total": v.get('total',0) if isinstance(v,dict) else v
                   for k,v in summary.items()},
            })

        except Exception as e:
            log(f"FATAL: {e}")
            import traceback
            traceback.print_exc()
            try:
                page.screenshot(path=str(DATA_DIR / "debug_FATAL.png"))
            except Exception:
                pass
        finally:
            try: ctx.close()
            except: pass
            if browser:
                try: browser.close()
                except: pass


if __name__ == "__main__":
    main()
