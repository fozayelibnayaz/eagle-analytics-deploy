from pathlib import Path
from datetime import datetime
import re
import sys

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PROFILE_DIR = Path("browser_session/linkedin_persistent_profile")
EXPORT_DIR = Path("downloads/linkedin_exports")
URL = "https://www.linkedin.com/company/68624141/admin/analytics/updates/"

BAD_MARKERS = (
    "/login",
    "/uas/",
    "/checkpoint",
    "/challenge",
    "flagship-web/login",
    "authwall",
)

def bad(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in BAD_MARKERS)

def main():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        errors = []
        context = None

        for kwargs in (
            {"channel": "chrome", "headless": False},
            {"headless": False},
        ):
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    **kwargs,
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="en-US",
                    accept_downloads=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-default-browser-check",
                        "--disable-gpu",
                    ],
                )
                print(f"OK: persistent browser launch -> {kwargs}")
                break
            except Exception as e:
                errors.append(f"{kwargs}: {e}")

        if context is None:
            print("❌ Could not launch persistent browser")
            for err in errors:
                print("  -", err)
            raise SystemExit(1)

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        page.wait_for_timeout(5000)

        print("Current URL:", page.url)
        if bad(page.url):
            print("❌ Still not authenticated on admin analytics page")
            context.close()
            raise SystemExit(1)

        # Print some visible buttons for debugging
        buttons = page.locator("button").all_inner_texts()
        clean_buttons = []
        for b in buttons:
            s = " ".join(str(b).split())
            if s and s not in clean_buttons:
                clean_buttons.append(s)

        print("Visible buttons (sample):")
        for b in clean_buttons[:30]:
            print(" -", b)

        selectors = [
            "button:has-text('Export')",
            "[aria-label*='Export']",
            "button[aria-label*='export']",
            "text=Export",
        ]

        clicked = False
        download_saved = None

        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = loc.count()
                if count < 1:
                    continue

                print(f"Trying selector: {sel} (count={count})")
                with page.expect_download(timeout=30000) as dl_info:
                    loc.first.click()
                download = dl_info.value

                suggested = download.suggested_filename or f"linkedin_updates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
                out = EXPORT_DIR / suggested
                download.save_as(str(out))
                download_saved = out
                clicked = True
                break
            except PlaywrightTimeoutError:
                print(f"Timeout waiting for download after selector: {sel}")
            except Exception as e:
                print(f"Selector failed {sel}: {e}")

        if not clicked:
            screenshot = EXPORT_DIR / f"linkedin_updates_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=str(screenshot), full_page=True)
            print(f"❌ Export button probe failed. Screenshot saved -> {screenshot}")
            context.close()
            raise SystemExit(1)

        print(f"✅ Export downloaded -> {download_saved}")
        context.close()

if __name__ == "__main__":
    main()
