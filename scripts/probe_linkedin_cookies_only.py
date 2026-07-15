import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from linkedin_cookie_bootstrap import apply_cookie_editor_cookies, prime_linkedin_auth

COMPANY_ID = "68624141"

with sync_playwright() as p:
    errors = []
    browser = None

    for kwargs in (
        {"channel": "chrome", "headless": False},
        {"headless": False},
    ):
        try:
            browser = p.chromium.launch(
                **kwargs,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-default-browser-check",
                    "--disable-gpu",
                ],
            )
            print(f"OK: browser launch -> {kwargs}")
            break
        except Exception as e:
            errors.append(f"{kwargs}: {e}")

    if browser is None:
        print("❌ Could not launch browser")
        for err in errors:
            print("  -", err)
        raise SystemExit(1)

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1440, "height": 900},
        locale="en-US",
    )

    count, source = apply_cookie_editor_cookies(context)
    print(f"OK: applied {count} cookies from {source}")

    page = context.new_page()
    ok, final_url = prime_linkedin_auth(page, company_id=COMPANY_ID)
    print("Final URL:", final_url)

    browser.close()

    if not ok:
        print("❌ Cookies-only probe failed")
        raise SystemExit(1)

    print("✅ Cookies-only probe succeeded")
