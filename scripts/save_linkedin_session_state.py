from pathlib import Path
import json
import sys

LOGIN_BAD_MARKERS = ("/login", "/uas/", "/checkpoint", "/challenge")

SESSION_PATHS = [
    Path("data/linkedin_session_state.json"),
    Path("data_output/linkedin_session_state.json"),
]

COOKIE_PATHS = [
    Path("data/linkedin_cookies.json"),
    Path("data_output/linkedin_cookies.json"),
]

PROFILE_DIR = Path("browser_session/linkedin_playwright_profile")


def ensure_dirs():
    for p in SESSION_PATHS + COOKIE_PATHS:
        p.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def bad_login_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in LOGIN_BAD_MARKERS)


def save_all(context):
    state = context.storage_state()
    cookies = context.cookies()

    for sp in SESSION_PATHS:
        sp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"OK: wrote session state -> {sp}")

    for cp in COOKIE_PATHS:
        cp.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        print(f"OK: wrote cookies -> {cp}")


def launch_context(playwright):
    errors = []

    # Prefer real Chrome for less bot friction
    try:
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
            ],
        )
        print("OK: launched persistent Google Chrome context")
        return ctx
    except Exception as e:
        errors.append(f"chrome: {e}")

    # Fallback to bundled Chromium
    try:
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        print("OK: launched persistent Chromium context")
        return ctx
    except Exception as e:
        errors.append(f"chromium: {e}")

    print("❌ Could not launch any browser context")
    for err in errors:
        print("  -", err)
    raise SystemExit(1)


def main():
    ensure_dirs()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"❌ Playwright import failed: {e}")
        raise SystemExit(1)

    with sync_playwright() as p:
        context = launch_context(p)
        page = context.pages[0] if context.pages else context.new_page()

        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"❌ Initial navigation failed: {e}")
            context.close()
            raise SystemExit(1)

        print()
        print("=" * 72)
        print("LinkedIn session saver")
        print("=" * 72)
        print("1. In the opened browser, log into LinkedIn")
        print("2. After login, manually open one of these pages and confirm it loads:")
        print("   - https://www.linkedin.com/feed/")
        print("   - your company admin analytics page")
        print("3. Only then come back to terminal and press ENTER")
        print("=" * 72)
        input("Press ENTER only after LinkedIn is fully logged in and visible... ")

        try:
            page.wait_for_timeout(2000)
        except Exception:
            pass

        current_url = page.url
        if bad_login_url(current_url):
            print(f"❌ Still on login/checkpoint page: {current_url}")
            context.close()
            raise SystemExit(1)

        save_all(context)
        context.close()
        print("✅ LinkedIn session state saved successfully")


if __name__ == "__main__":
    main()
