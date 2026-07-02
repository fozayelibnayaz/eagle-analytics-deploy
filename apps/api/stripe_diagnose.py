"""
STRIPE DIAGNOSTIC - just opens Stripe and reports what it sees.
No filtering, no writing, just inspection.
"""
import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
from config import STRIPE_SESSION_DIR, STRIPE_CUSTOMERS_URL, DEBUG_DIR


def main():
    print("=" * 60)
    print("STRIPE DIAGNOSTIC")
    print("=" * 60)
    print(f"URL: {STRIPE_CUSTOMERS_URL}")

    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    chrome_exec = next((p for p in chrome_paths if os.path.exists(p)), None)

    with sync_playwright() as p:
        launch_args = dict(
            user_data_dir=str(STRIPE_SESSION_DIR),
            headless=False,
            slow_mo=100,
            viewport={"width": 1600, "height": 1000},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        if chrome_exec:
            launch_args["executable_path"] = chrome_exec

        ctx = p.chromium.launch_persistent_context(**launch_args)
        page = ctx.new_page()
        page.goto(STRIPE_CUSTOMERS_URL, wait_until="domcontentloaded")
        print("Waiting 15 seconds for Stripe to load...")
        time.sleep(15)

        print(f"Current URL: {page.url}")

        if "login" in page.url.lower():
            print("PROBLEM: redirected to login. Re-export cookies.")
            ctx.close()
            return

        # Save full screenshot
        png = DEBUG_DIR / f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(png), full_page=True)
        print(f"Screenshot saved: {png}")

        # Look for tables
        print()
        print("=== INSPECTION ===")
        for sel in ["table", "[role='table']", "[role='grid']"]:
            count = page.locator(sel).count()
            print(f"  '{sel}' count: {count}")

        # Look for rows
        for sel in ["table tbody tr", "[role='row']", "tr"]:
            count = page.locator(sel).count()
            print(f"  '{sel}' count: {count}")

        # Look for headers
        for sel in ["table thead th", "[role='columnheader']", "th"]:
            try:
                cells = page.locator(sel).all_text_contents()
                cells = [c.strip() for c in cells if c.strip()]
                if cells:
                    print(f"  '{sel}' headers: {cells}")
            except Exception:
                pass

        # Get first few row texts
        print()
        print("=== FIRST 5 ROW SAMPLES ===")
        for sel in ["table tbody tr", "[role='row']"]:
            try:
                rows = page.locator(sel).all()[:5]
                for i, row in enumerate(rows):
                    cells = row.locator("td, [role='cell']").all_text_contents()
                    cells = [c.strip() for c in cells]
                    if cells:
                        print(f"  Row {i}: {cells}")
                if rows:
                    break
            except Exception:
                pass

        # Save HTML
        html_path = DEBUG_DIR / f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        html_path.write_text(page.content())
        print(f"HTML saved: {html_path}")

        print()
        print("Browser stays open 30s for you to inspect manually.")
        time.sleep(30)
        ctx.close()


if __name__ == "__main__":
    main()
