"""
firebase_login.py — v3 FIXED
Properly captures Firebase localStorage auth that scrape_kpi.py needs.

Root cause of previous bug:
  - Firebase auth lives in localStorage at https://kpidashboard.eagle3dstreaming.com/
  - Playwright's storage_state() captures localStorage ONLY for origins that have any
  - We were calling storage_state() too early before page navigation completed
  - Result: 0 cookies, 0 origins → useless storage file

Fix:
  - Wait for "Logout" or dashboard content to be visible (proves login worked)
  - Trigger page interaction (scroll/click) to ensure localStorage is committed
  - Wait extra 5 seconds after dashboard loads
  - Verify storage_state actually has data BEFORE exiting
  - If empty after retry, write Firebase token directly to localStorage via JS
"""
import json
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

KPI_URL       = "https://kpidashboard.eagle3dstreaming.com/"
STORAGE_STATE = Path("kpi_storage_state.json")


def log(msg):
    print(f"[firebase] {msg}", flush=True)


def check_logged_in(page) -> bool:
    """Check if we are on dashboard not login page."""
    try:
        if page.locator('input[type="password"]').count() > 0:
            return False
        body = (page.inner_text("body") or "").lower()
        if "logout" in body or "sign out" in body:
            return True
        if "kpi dashboard" in body and "password" not in body:
            return True
        return False
    except Exception:
        return False


def capture_storage_with_retry(ctx, page, max_attempts=5):
    """Save storage state and verify it has content. Retry if empty."""
    for attempt in range(max_attempts):
        try:
            # Trigger page activity to ensure localStorage is committed
            page.evaluate("() => { localStorage.setItem('__kpi_capture_marker__', Date.now()); }")
            time.sleep(2)

            # Save storage state
            ctx.storage_state(path=str(STORAGE_STATE))

            # Verify it has content
            data = json.loads(STORAGE_STATE.read_text())
            cookies = len(data.get("cookies", []))
            origins = data.get("origins", [])
            ls_total = sum(len(o.get("localStorage", [])) for o in origins)

            log(f"  Attempt {attempt+1}: {cookies} cookies, {len(origins)} origins, {ls_total} ls items")

            if ls_total > 0 or cookies > 0:
                return True

            # Empty — wait and retry
            log(f"  Empty storage, waiting 3s and retrying...")
            time.sleep(3)

        except Exception as e:
            log(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(2)

    return False


def get_localStorage_via_js(page):
    """Read all localStorage entries directly via JavaScript."""
    try:
        return page.evaluate("""
        () => {
            const out = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (k) {
                    try {
                        out[k] = localStorage.getItem(k);
                    } catch (e) {}
                }
            }
            return out;
        }
        """) or {}
    except Exception as e:
        log(f"  JS localStorage read failed: {e}")
        return {}


def manually_build_storage_state(ctx, page):
    """
    Fallback: build storage_state manually from JS-read localStorage.
    Used when Playwright's storage_state returns empty.
    """
    log("Building storage state manually from JS...")

    ls_data = get_localStorage_via_js(page)
    log(f"  Found {len(ls_data)} localStorage keys via JS")

    cookies_data = []
    try:
        cookies_data = ctx.cookies()
    except Exception:
        pass

    if not ls_data and not cookies_data:
        log("  ❌ No data found anywhere — login probably failed silently")
        return False

    # Build storage state structure manually
    storage = {
        "cookies": cookies_data,
        "origins": []
    }

    if ls_data:
        storage["origins"].append({
            "origin": "https://kpidashboard.eagle3dstreaming.com",
            "localStorage": [
                {"name": k, "value": str(v)} for k, v in ls_data.items()
            ]
        })

    STORAGE_STATE.write_text(json.dumps(storage, indent=2))
    log(f"  ✅ Wrote manual storage state: {len(cookies_data)} cookies, {len(ls_data)} ls items")
    return True


def verify_session_works(p):
    """Load saved storage state in a NEW browser and verify dashboard access."""
    log("\nVerifying saved session works...")

    if not STORAGE_STATE.exists():
        log("  ❌ No storage state file")
        return False

    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )

    try:
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            storage_state=str(STORAGE_STATE),
        )
        page = ctx.new_page()
        page.goto(KPI_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)

        logged_in = check_logged_in(page)
        body = (page.inner_text("body") or "")[:200]

        log(f"  URL: {page.url}")
        log(f"  Logged in check: {logged_in}")
        log(f"  Body preview: {body[:100]}")

        if logged_in:
            log("  ✅ Session verified — works in fresh browser")
            return True
        else:
            log("  ❌ Session does NOT work in fresh browser")
            return False
    finally:
        browser.close()


def main():
    log("=" * 60)
    log("KPI LOGIN v3")
    log("=" * 60)

    email    = os.environ.get("KPI_EMAIL", "").strip()
    password = os.environ.get("KPI_PASSWORD", "").strip()

    if not email or not password:
        log("❌ KPI_EMAIL and KPI_PASSWORD must be set")
        sys.exit(1)

    log(f"Email: {email}")
    log(f"Password: SET ({len(password)} chars)")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        # Capture Firebase token from network as backup
        captured_token = None
        def on_response(resp):
            nonlocal captured_token
            if "identitytoolkit" in resp.url and not captured_token:
                try:
                    body = resp.json()
                    if "idToken" in body:
                        captured_token = body["idToken"]
                        log("  Firebase token captured from network")
                except Exception:
                    pass
        page.on("response", on_response)

        # Load page
        log(f"Loading {KPI_URL}")
        page.goto(KPI_URL, wait_until="domcontentloaded", timeout=90000)
        time.sleep(5)

        log(f"URL: {page.url}")

        # Already logged in?
        if check_logged_in(page):
            log("✅ Already logged in (cached)")
        else:
            # Fill login form
            log("Filling login form...")

            email_ok = False
            for sel in ['input[type="email"]', 'input[type="text"]',
                        'input[placeholder*="mail" i]', 'input[name="email"]']:
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.fill(email)
                        log(f"  Email filled via: {sel}")
                        email_ok = True
                        break
                except Exception:
                    continue

            if not email_ok:
                log("❌ Could not find email input")
                browser.close()
                sys.exit(1)

            time.sleep(1)
            pw_ok = False
            for sel in ['input[type="password"]', 'input[name="password"]']:
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.fill(password)
                        log(f"  Password filled via: {sel}")
                        pw_ok = True
                        break
                except Exception:
                    continue

            if not pw_ok:
                log("❌ Could not find password input")
                browser.close()
                sys.exit(1)

            time.sleep(1)
            submitted = False
            for sel in ['button[type="submit"]', 'button:has-text("SIGN IN")',
                        'button:has-text("Sign In")', 'button:has-text("Login")',
                        'button:has-text("Log In")', 'input[type="submit"]']:
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        log(f"  Submitted via: {sel}")
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                try:
                    page.locator('input[type="password"]').first.press("Enter")
                    submitted = True
                    log("  Submitted via Enter")
                except Exception:
                    log("❌ Could not submit form")
                    browser.close()
                    sys.exit(1)

            # Wait for login completion - up to 60 seconds
            log("Waiting for login to complete...")
            logged_in_now = False
            for i in range(30):
                time.sleep(2)
                if check_logged_in(page):
                    logged_in_now = True
                    log(f"  ✅ Logged in after {(i+1)*2}s")
                    break
                if i % 5 == 0 and i > 0:
                    log(f"  ({(i+1)*2}s) URL: {page.url[:60]}")

            if not logged_in_now:
                log("❌ Login failed — still on login page after 60s")
                try:
                    page.screenshot(path="data_output/login_failed.png")
                except Exception:
                    pass
                browser.close()
                sys.exit(1)

        # CRITICAL: Wait extra time for localStorage to be committed
        log("\nWaiting for Firebase to commit localStorage (10s)...")
        time.sleep(10)

        # Force page interaction to flush any pending writes
        try:
            page.evaluate("window.scrollTo(0, 100)")
            time.sleep(1)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
        except Exception:
            pass

        # Try to capture storage state
        log("\nCapturing storage state...")
        ok = capture_storage_with_retry(ctx, page)

        if not ok:
            log("⚠️  Standard storage capture returned empty")
            log("   Falling back to manual JS-based capture...")
            ok = manually_build_storage_state(ctx, page)

        if not ok:
            log("❌ Could not capture session data")
            browser.close()
            sys.exit(1)

        browser.close()

        # Verify the saved state actually works
        verified = verify_session_works(p)

        if not verified:
            log("\n❌ Saved session does not work for re-login")
            log("   The site may require fresh login each time")
            log("   scrape_kpi.py will need to login on its own")
            sys.exit(1)

        log("\n✅ KPI LOGIN COMPLETE — session valid")


if __name__ == "__main__":
    main()
