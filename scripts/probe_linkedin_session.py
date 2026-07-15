from pathlib import Path
import sys

LOGIN_BAD_MARKERS = ("/login", "/uas/", "/checkpoint", "/challenge")

def bad_login_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in LOGIN_BAD_MARKERS)

def main():
    session_file = None
    for p in [
        Path("data/linkedin_session_state.json"),
        Path("data_output/linkedin_session_state.json"),
    ]:
        if p.exists():
            session_file = p
            break

    if session_file is None:
        print("❌ No LinkedIn session file found")
        raise SystemExit(1)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"❌ Playwright import failed: {e}")
        raise SystemExit(1)

    with sync_playwright() as p:
        errors = []

        context = None
        try:
            browser = p.chromium.launch(channel="chrome", headless=False)
            context = browser.new_context(
                storage_state=str(session_file),
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            print("OK: launched Google Chrome with saved storage_state")
        except Exception as e:
            errors.append(f"chrome failed: {e}")
            try:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context(
                    storage_state=str(session_file),
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                print("OK: launched Chromium with saved storage_state")
            except Exception as e2:
                errors.append(f"chromium failed: {e2}")
                print("❌ Could not launch browser for probe")
                for err in errors:
                    print("  -", err)
                raise SystemExit(1)

        page = context.new_page()
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        current_url = page.url
        print("Probe URL:", current_url)

        if bad_login_url(current_url):
            print("❌ Probe failed: still redirected to LinkedIn login")
            context.close()
            raise SystemExit(1)

        print("✅ Probe succeeded: LinkedIn session is valid")
        context.close()

if __name__ == "__main__":
    main()
