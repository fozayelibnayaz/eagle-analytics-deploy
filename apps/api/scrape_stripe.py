"""
scrape_stripe.py - PROPER FIX
Uses data-column-id to map cells to columns correctly.
Stripe rows have 9 cells but only 5 have real data (the rest are sticky/spacer).
"""
import json
import time
import os
import re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

from sheets_writer import write_tab_data, read_tab_data, write_run_summary
from pipeline_health import record_success, record_failure, detect_stripe_cookie_issue
from notifications import alert_stripe_cookies_expired

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)
SCRAPE_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
SCRAPE_DATE = datetime.now().strftime("%Y-%m-%d")

STRIPE_URL = (
    "https://dashboard.stripe.com/acct_1J7M5XIKrnGFhGm1"
    "/customers?sort_field=first_payment&sort_direction=desc"
    "&payment_count[gte]=1"
)

STRIPE_SESSION_DIR = Path("stripe_session")
STRIPE_MARKER = DATA_DIR / ".stripe_historical_done"
FORCE_HISTORICAL = os.environ.get("FORCE_HISTORICAL", "") == "1"

# Map Stripe data-column-id -> our friendly column name
COLUMN_MAP = {
    "email":          "Email",
    "created":        "Created",
    "payment_date":   "First payment",   # Stripe dashboard uses payment_date for first payment
    "net_volume":     "Total spend",
    "customer":       "Customer",
    "first_payment":  "First payment",   # fallback
    "description":    "Description",
    "country":        "Country",
    "payment_count":  "Payment Count",
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Stripe] {msg}", flush=True)


def determine_mode():
    if FORCE_HISTORICAL:
        log("FORCE_HISTORICAL=1 - HISTORICAL")
        return "historical"
    if STRIPE_MARKER.exists():
        log("Marker exists - DAILY")
        return "daily"
    try:
        existing = read_tab_data("Raw_STRIPE")
        if len(existing) >= 50:
            log(f"Sheet has {len(existing)} - DAILY")
            STRIPE_MARKER.write_text(f"Auto at {SCRAPE_TS}\n")
            return "daily"
    except Exception:
        pass
    log("First time - HISTORICAL")
    return "historical"


def normalize_cookies(raw):
    out = []
    for c in raw:
        cookie = {
            "name":   str(c.get("name","")),
            "value":  str(c.get("value","")),
            "domain": c.get("domain", ".stripe.com"),
            "path":   c.get("path", "/"),
        }
        exp = c.get("expirationDate") or c.get("expires")
        if exp:
            try: cookie["expires"] = float(exp)
            except: pass
        cookie["httpOnly"] = bool(c.get("httpOnly", False))
        cookie["secure"]   = bool(c.get("secure", True))
        ss = str(c.get("sameSite","Lax")).lower()
        cookie["sameSite"] = {
            "no_restriction":"None","lax":"Lax","strict":"Strict",
            "unspecified":"Lax","none":"None"
        }.get(ss, "Lax")
        if cookie["name"] and cookie["value"]:
            out.append(cookie)
    return out


def extract_table(page):
    """
    Extract using data-column-id attribute on each TD.
    This is the reliable way to get Stripe table data.
    """
    return page.evaluate("""
        () => {
            const tables = document.querySelectorAll('table');
            let best = null, maxR = 0;
            for (const t of tables) {
                const r = t.querySelectorAll('tbody tr').length;
                if (r > maxR) { maxR = r; best = t; }
            }
            if (!best) return {rows: [], footer_text: ''};
            
            const rows = [];
            const trEls = best.querySelectorAll('tbody tr');
            
            for (const tr of trEls) {
                const cells = tr.querySelectorAll('td');
                if (!cells.length) continue;
                
                const rowData = {};
                let nonEmptyCount = 0;
                
                for (const td of cells) {
                    const colId = td.getAttribute('data-column-id');
                    if (!colId) continue;  // skip sticky/spacer cells
                    
                    const text = (td.innerText || td.textContent || '').trim();
                    rowData[colId] = text;
                    if (text && text.length > 1 && text !== '—') {
                        nonEmptyCount++;
                    }
                }
                
                // Must have at least email + something else
                if (rowData.email && nonEmptyCount >= 2) {
                    rows.push(rowData);
                }
            }
            
            // Footer
            let footer_text = '';
            const allText = document.body.innerText || '';
            const m = allText.match(/(\\d+)[\\u2013\\-](\\d+)\\s+of\\s+(\\d[\\d,]*)\\s+results?/i);
            if (m) footer_text = m[0];
            
            return {rows: rows, footer_text: footer_text};
        }
    """)


def get_total_count(footer):
    if not footer: return -1
    m = re.search(r"of\s+(\d[\d,]*)", footer)
    return int(m.group(1).replace(",","")) if m else -1


def get_range(footer):
    if not footer: return (-1, -1)
    m = re.search(r"(\d+)[\u2013\-](\d+)\s+of", footer)
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def click_next_page(page, current_footer):
    current_start, _ = get_range(current_footer)
    log(f"  At row {current_start}, clicking Next...")
    
    try:
        next_btn = page.locator('a[aria-label="Next page"]')
        if next_btn.count() == 0:
            return False
        if next_btn.first.get_attribute("aria-disabled") == "true":
            log("  Last page reached")
            return False
        
        next_btn.first.click(timeout=5000)
        time.sleep(4)
        
        new_data = extract_table(page)
        new_start, _ = get_range(new_data.get("footer_text",""))
        if new_start > current_start:
            log(f"  Now at row {new_start}")
            return True
        log(f"  Page didn't advance")
        return False
    except Exception as e:
        log(f"  Click error: {e}")
        return False


def get_existing_emails():
    try:
        rows = read_tab_data("Raw_STRIPE")
        return {str(r.get("Email","")).strip().lower()
                for r in rows
                if r.get("Email") and "@" in str(r.get("Email",""))}
    except Exception:
        return set()


def merge_with_existing(tab_name, new_rows):
    try:
        existing = read_tab_data(tab_name)
        log(f"  Existing in {tab_name}: {len(existing)}")
    except Exception:
        existing = []
    
    by_email = {}
    for r in existing:
        email = ""
        for k in ("Email","email"):
            if k in r and r[k] and "@" in str(r[k]):
                email = str(r[k]).strip().lower()
                break
        if email:
            by_email[email] = r
    
    new_count = 0
    for r in new_rows:
        email = ""
        for k in ("Email","email"):
            if k in r and r[k] and "@" in str(r[k]):
                email = str(r[k]).strip().lower()
                break
        if not email:
            continue
        
        if email in by_email:
            old = by_email[email]
            merged = {**old, **r}
            merged["__first_seen__"] = old.get("__first_seen__", old.get("__scraped_at__", SCRAPE_TS))
            by_email[email] = merged
        else:
            r["__first_seen__"] = SCRAPE_TS
            by_email[email] = r
            new_count += 1
    
    log(f"  After merge: {len(by_email)} (+{new_count} NEW)")
    return list(by_email.values()), new_count


def main():
    log("=" * 60)
    log(f"STRIPE SCRAPER - {SCRAPE_TS}")
    log("=" * 60)
    
    cookies_file = Path("stripe_cookies.json")
    if not cookies_file.exists() or cookies_file.stat().st_size < 100:
        log("No cookies - skipping")
        return
    
    mode = determine_mode()
    log(f"MODE: {mode.upper()}")
    existing_emails = get_existing_emails() if mode == "daily" else set()
    
    with sync_playwright() as p:
        STRIPE_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(STRIPE_SESSION_DIR),
            headless=True,
            viewport={"width": 1920, "height": 1080},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        
        try:
            raw = json.loads(cookies_file.read_text())
            ctx.add_cookies(normalize_cookies(raw))
        except Exception as e:
            log(f"Cookie error: {e}")
        
        page = ctx.new_page()
        
        try:
            log("Loading Stripe...")
            page.goto(STRIPE_URL, wait_until="domcontentloaded", timeout=90000)
            time.sleep(15)
            
            page.screenshot(path=str(DATA_DIR / "debug_stripe_loaded.png"))
            
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            
            # Wait for table — try multiple selectors for resilience
            table_found = False
            for selector in ["table tbody tr", "table tr", "[data-testid='table'] tr", ".Table tbody tr", "tbody tr"]:
                try:
                    page.wait_for_selector(selector, timeout=10000)
                    table_found = True
                    log(f"Table found with selector: {selector}")
                    break
                except Exception:
                    continue
            
            if not table_found:
                log("⚠️ No table found on Stripe page — taking screenshot and using existing data")
                page.screenshot(path=str(DATA_DIR / "debug_stripe_no_table.png"))
                # Don't crash — just return empty so pipeline continues with existing Stripe data
                return
            time.sleep(5)
            
            log(f"\n=== Pagination ({mode} mode) ===")
            
            all_rows_by_email = {}
            page_num = 1
            expected_total = -1
            no_progress = 0
            consecutive_all_known = 0
            
            MAX_PAGES = 5 if mode == "daily" else 50
            
            while page_num <= MAX_PAGES:
                time.sleep(3)
                data = extract_table(page)
                
                footer = data.get("footer_text", "")
                if expected_total < 0:
                    expected_total = get_total_count(footer)
                    if expected_total > 0:
                        log(f"EXPECTED TOTAL: {expected_total}")
                
                page_rows = data.get("rows", [])
                start, end = get_range(footer)
                
                # Quality check
                full_rows = sum(1 for r in page_rows
                                if r.get("email") and r.get("created") and r.get("customer"))
                
                new_on_page = 0
                known_on_page = 0
                page_has_new = False
                
                for row in page_rows:
                    email = (row.get("email") or "").strip().lower()
                    if not email or "@" not in email:
                        continue
                    if email in all_rows_by_email:
                        # Update if new row has more data
                        old = all_rows_by_email[email]
                        for k, v in row.items():
                            if v and not old.get(k):
                                old[k] = v
                        continue
                    all_rows_by_email[email] = row
                    new_on_page += 1
                    
                    if mode == "daily":
                        if email in existing_emails:
                            known_on_page += 1
                        else:
                            page_has_new = True
                
                progress = f" / {expected_total}" if expected_total > 0 else ""
                log(f"  page {page_num} (rows {start}-{end}): "
                    f"+{new_on_page} | total: {len(all_rows_by_email)}{progress} | "
                    f"full_rows: {full_rows}/{len(page_rows)}")
                
                if mode == "daily" and len(page_rows) > 0:
                    if not page_has_new and known_on_page == len(page_rows):
                        consecutive_all_known += 1
                        if consecutive_all_known >= 2:
                            log("  DAILY EARLY EXIT")
                            break
                    else:
                        consecutive_all_known = 0
                
                if expected_total > 0 and len(all_rows_by_email) >= expected_total:
                    log(f"  Reached expected total")
                    break
                
                if new_on_page == 0:
                    no_progress += 1
                    if no_progress >= 3:
                        break
                else:
                    no_progress = 0
                
                if not click_next_page(page, footer):
                    break
                
                page_num += 1
            
            # Convert to enriched rows with friendly column names
            enriched_rows = []
            for row in all_rows_by_email.values():
                enriched = {}
                for col_id, friendly_name in COLUMN_MAP.items():
                    enriched[friendly_name] = row.get(col_id, "")
                enriched["__scraped_at__"]  = SCRAPE_TS
                enriched["__scrape_date__"] = SCRAPE_DATE
                enriched["__tab__"]         = "STRIPE"
                enriched["__scrape_mode__"] = mode
                enriched_rows.append(enriched)
            
            log(f"\nScraped {len(enriched_rows)} rows from {page_num} pages")
            
            if enriched_rows:
                merged, new_added = merge_with_existing("Raw_STRIPE", enriched_rows)
                ok = write_tab_data("Raw_STRIPE", merged)
                log(f"Sheets: {'OK' if ok else 'CSV'}")
                
                # Quality report
                with_created = sum(1 for r in merged if r.get("Created") and str(r.get("Created")).strip())
                with_customer = sum(1 for r in merged if r.get("Customer") and str(r.get("Customer")).strip())
                with_spend = sum(1 for r in merged if r.get("Total spend") and str(r.get("Total spend")).strip())
                
                log(f"\n=== DATA QUALITY ===")
                log(f"  Total: {len(merged)}")
                log(f"  With Created: {with_created}/{len(merged)} ({100*with_created/len(merged):.0f}%)")
                log(f"  With Customer: {with_customer}/{len(merged)} ({100*with_customer/len(merged):.0f}%)")
                log(f"  With Total spend: {with_spend}/{len(merged)} ({100*with_spend/len(merged):.0f}%)")
                
                if mode == "historical" and len(merged) >= 50 and with_created >= len(merged) * 0.8:
                    STRIPE_MARKER.write_text(
                        f"Stripe historical at {SCRAPE_TS}\n"
                        f"Quality: {with_created}/{len(merged)} have dates\n"
                    )
                    log(f"\nMarker created (good quality)")
                
                write_run_summary({
                    "run_at": SCRAPE_TS,
                    "stage": "stripe",
                    "mode": mode,
                    "scraped": len(enriched_rows),
                    "new_added": new_added,
                    "total": len(merged),
                    "with_dates": with_created,
                    "expected": expected_total,
                    "pages": page_num,
                })
        
        except Exception as e:
            log(f"FATAL: {e}")
            import traceback
            traceback.print_exc()
            
            # Health tracking + cookie alert
            err_str = str(e)
            record_failure("stripe", err_str)
            
            if detect_stripe_cookie_issue(err_str):
                log("DETECTED: Stripe cookie issue - sending alert")
                try:
                    alert_stripe_cookies_expired()
                except Exception as alert_err:
                    log(f"Alert send error: {alert_err}")
        finally:
            try: ctx.close()
            except: pass


def fetch_stripe_api_counts():
    """Use official Stripe API (STRIPE_SECRET_KEY) to get accurate payment counts.
    Returns dict with total/accepted/declined/revenue for the current month, or None if not available."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key or not stripe_key.startswith("sk_"):
        return None
    try:
        import stripe as stripe_lib
        stripe_lib.api_key = stripe_key
        now = datetime.now()
        month_start = datetime(now.year, now.month, 1)
        import calendar
        month_end = datetime(now.year, now.month, calendar.monthrange(now.year, now.month)[1], 23, 59, 59)
        month_start_ts = int(month_start.timestamp())
        
        all_intents = []
        has_more = True
        starting_after = None
        while has_more:
            params = {"created": {"gte": month_start_ts}, "limit": 100}
            if starting_after:
                params["starting_after"] = starting_after
            resp = stripe_lib.PaymentIntent.list(**params)
            all_intents.extend(resp.data)
            has_more = resp.has_more
            if has_more and resp.data:
                starting_after = resp.data[-1].id
        
        total = len(all_intents)
        accepted = sum(1 for i in all_intents if i.status == "succeeded")
        declined = sum(1 for i in all_intents if i.status in 
                      ["requires_payment_method", "canceled", "payment_failed"])
        revenue = sum(i.amount / 100 for i in all_intents if i.status == "succeeded")
        
        log(f"Stripe API verification: total={total}, accepted={accepted}, declined={declined}, revenue=${revenue:.2f}")
        return {
            "total_payments": total,
            "accepted_payments": accepted,
            "declined_payments": declined,
            "total_revenue": round(revenue, 2),
            "month": now.strftime("%Y-%m"),
            "source": "stripe_api",
        }
    except Exception as e:
        log(f"Stripe API verification failed (non-fatal): {e}")
        return None


if __name__ == "__main__":
    # If STRIPE_SECRET_KEY is set, also verify via API
    api_data = fetch_stripe_api_counts()
    if api_data:
        log(f"\n=== STRIPE API VERIFICATION ===")
        log(f"  Month: {api_data['month']}")
        log(f"  Total Payments: {api_data['total_payments']}")
        log(f"  Accepted (succeeded): {api_data['accepted_payments']}")
        log(f"  Declined: {api_data['declined_payments']}")
        log(f"  Revenue: ${api_data['total_revenue']:.2f}")
    main()
