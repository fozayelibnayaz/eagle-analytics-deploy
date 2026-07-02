#!/usr/bin/env python3
"""
LinkedIn Login + Session Saver
1. Opens visible browser
2. You log in MANUALLY (handles 2FA, captcha, security checks)
3. After login, script saves fresh cookies + session state
4. linkedin_browser_scraper.py can then reuse this for headless scraping
"""

import json
import time
from datetime import datetime
from pathlib import Path

DATA_DIR       = Path("data_output")
COOKIES_FILE   = DATA_DIR / "linkedin_cookies.json"
SESSION_FILE   = DATA_DIR / "linkedin_session_state.json"


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("LINKEDIN LOGIN + SESSION SAVER")
    print("=" * 60)
    print()
    print("INSTRUCTIONS:")
    print("  1. A Chrome window will open")
    print("  2. Log into LinkedIn manually")
    print("  3. Complete any 2FA / security check if asked")
    print("  4. Navigate to your company admin page to verify access")
    print("  5. Return to this terminal and press Enter")
    print("  6. Cookies + session will be saved")
    print()
    input("Press Enter to open browser...")

    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=False,
        args=['--disable-blink-features=AutomationControlled'],
    )

    # Try to reuse existing session if available
    context_args = {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport":   {"width": 1440, "height": 900},
    }
    if SESSION_FILE.exists():
        log(f"Found existing session: {SESSION_FILE}")
        context_args["storage_state"] = str(SESSION_FILE)

    context = browser.new_context(**context_args)
    page = context.new_page()

    log("Opening LinkedIn...")
    page.goto("https://www.linkedin.com/login", timeout=60000)

    print()
    print("=" * 60)
    print("LOGIN NOW IN THE BROWSER")
    print("=" * 60)
    print()
    print("After you have successfully logged in and can see the LinkedIn feed,")
    print("navigate to:")
    print("  https://www.linkedin.com/company/68624141/admin/analytics/updates/")
    print()
    print("Once you can see the analytics page in the browser, return here.")
    print()
    input("Press Enter when you are fully logged in and see the analytics page...")

    # Verify login by checking URL
    log(f"Current URL: {page.url}")
    if "login" in page.url.lower() or "authwall" in page.url.lower():
        print()
        print("WARNING: Still on login page. Did you log in?")
        confirm = input("Continue anyway? (y/n): ").strip().lower()
        if confirm != "y":
            browser.close()
            p.stop()
            return

    # Save cookies
    cookies = context.cookies()
    log(f"Capturing {len(cookies)} cookies...")

    # Format to match expected structure
    formatted = []
    for c in cookies:
        if "linkedin" in c.get("domain", "").lower():
            formatted.append({
                "domain":   c.get("domain"),
                "name":     c.get("name"),
                "value":    c.get("value"),
                "path":     c.get("path", "/"),
                "secure":   c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": c.get("sameSite", "no_restriction"),
                "expirationDate": c.get("expires"),
                "session":  c.get("expires", -1) == -1,
            })

    COOKIES_FILE.write_text(json.dumps(formatted, indent=2, default=str))
    log(f"Saved {len(formatted)} LinkedIn cookies: {COOKIES_FILE}")

    # Save full session state (includes localStorage, etc)
    context.storage_state(path=str(SESSION_FILE))
    log(f"Saved session state: {SESSION_FILE}")

    # Verify key cookies
    li_at = next((c for c in formatted if c["name"] == "li_at"), None)
    jsessid = next((c for c in formatted if c["name"] == "JSESSIONID"), None)
    print()
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    print(f"  li_at present:     {'YES' if li_at else 'NO (CRITICAL)'}")
    print(f"  JSESSIONID present: {'YES' if jsessid else 'NO (CRITICAL)'}")
    print(f"  Total LinkedIn cookies: {len(formatted)}")
    print()

    if li_at and jsessid:
        print("SUCCESS - Session saved")
        print()
        print("NEXT STEP: Run scraper now")
        print("  python3 linkedin_browser_scraper.py")
    else:
        print("WARNING: Critical cookies missing. Re-run and ensure full login.")

    # Optional: paste cookies into Streamlit secrets format
    cookies_json = json.dumps(formatted, separators=(",", ":"))
    secrets_file = DATA_DIR / "linkedin_cookies_for_secrets.txt"
    secrets_file.write_text(f"LINKEDIN_COOKIES_JSON = '{cookies_json}'\n")
    print()
    print(f"For Streamlit Cloud secrets, paste this line from: {secrets_file}")
    print()

    browser.close()
    p.stop()


if __name__ == "__main__":
    main()
