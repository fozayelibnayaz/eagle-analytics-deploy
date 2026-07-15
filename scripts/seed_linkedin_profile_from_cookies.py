import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from linkedin_cookie_bootstrap import apply_cookie_editor_cookies, save_runtime_auth

PROFILE_DIR = Path("browser_session/linkedin_persistent_profile")
ADMIN_URL = "https://www.linkedin.com/company/68624141/admin/analytics/updates/"
BAD_MARKERS = ("/login", "/uas/", "/checkpoint", "/challenge", "flagship-web/login", "authwall")

def bad(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in BAD_MARKERS)

with sync_playwright() as p:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        viewport={"width": 1440, "height": 900},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="en-US",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-default-browser-check",
            "--disable-gpu",
        ],
    )

    count, source = apply_cookie_editor_cookies(ctx)
    print(f"OK: applied {count} cookies from {source}")

    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    for url in [
        "https://www.linkedin.com/",
        "https://www.linkedin.com/feed/",
        ADMIN_URL,
    ]:
        print("Navigating:", url)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        print("Current URL:", page.url)
        if bad(page.url):
            print("❌ Seeding failed due to login/authwall redirect")
            ctx.close()
            raise SystemExit(1)

    save_runtime_auth(ctx)
    print("✅ Persistent LinkedIn profile seeded successfully")
    ctx.close()
