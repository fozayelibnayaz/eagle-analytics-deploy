from pathlib import Path
from datetime import datetime
import re
import sys

path = Path("linkedin_browser_scraper.py")
if not path.exists():
    print("❌ linkedin_browser_scraper.py not found")
    raise SystemExit(1)

text = path.read_text(encoding="utf-8", errors="ignore")

pattern = re.compile(
    r"def setup_browser\(headless=False\):.*?(?=^def\s+\w+\s*\(|\Z)",
    re.S | re.M,
)

replacement = '''def setup_browser(headless=False):
    """
    Use the same browser/session strategy that passed probe_linkedin_session.py.
    IMPORTANT: force real Google Chrome + visible session for reliability.
    """
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()

    session_candidates = [
        DATA_DIR / "linkedin_session_state.json",
        Path("data/linkedin_session_state.json"),
        Path("data_output/linkedin_session_state.json"),
    ]
    session_file = next((f for f in session_candidates if f.exists()), None)

    launch_errors = []
    browser = None

    launch_plan = [
        {"channel": "chrome", "headless": False},
        {"headless": False},
    ]

    for kwargs in launch_plan:
        try:
            browser = p.chromium.launch(
                **kwargs,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-default-browser-check",
                ],
            )
            log(f"Browser launch OK: channel={kwargs.get('channel', 'chromium')} headless={kwargs.get('headless')}")
            break
        except Exception as e:
            launch_errors.append(f"{kwargs}: {e}")

    if browser is None:
        raise RuntimeError("Could not launch LinkedIn browser: " + " | ".join(launch_errors))

    context_args = {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
    }

    if session_file is not None:
        log(f"Using saved session state: {session_file}")
        context_args["storage_state"] = str(session_file)

    context = browser.new_context(**context_args)

    if session_file is None:
        try:
            cookies = load_cookies()
            if cookies:
                context.add_cookies(cookies)
                log(f"Loaded {len(cookies)} cookies into browser context")
        except Exception as e:
            log(f"Cookie load warning: {e}")

    page = context.new_page()
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    current_url = page.url
    if "/login" in current_url or "/uas/" in current_url or "/checkpoint" in current_url or "/challenge" in current_url:
        raise RuntimeError(f"Login redirect: {current_url}")

    return p, browser, context

'''

new_text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    print("❌ Could not patch setup_browser() in linkedin_browser_scraper.py")
    raise SystemExit(1)

# If scraper explicitly asks for headless=True anywhere, force it off for now
new_text = re.sub(
    r"setup_browser\(\s*headless\s*=\s*True\s*\)",
    "setup_browser(headless=False)",
    new_text,
)

backup = Path("backups") / f"linkedin_browser_scraper.py.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")
path.write_text(new_text, encoding="utf-8")

print(f"OK: backup written -> {backup}")
print(f"OK: patched -> {path}")
