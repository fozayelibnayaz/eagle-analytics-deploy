from pathlib import Path
from datetime import datetime

path = Path("linkedin_browser_scraper.py")
if not path.exists():
    print("❌ linkedin_browser_scraper.py not found")
    raise SystemExit(1)

text = path.read_text(encoding="utf-8", errors="ignore")

setup_markers = [
    "def _setup_browser(headless=False):",
    "def setup_browser(headless=False):",
]
next_markers = [
    "\ndef _safe_int",
    "\ndef safe_int",
]

setup_marker = next((m for m in setup_markers if m in text), None)
if not setup_marker:
    print("❌ Could not find setup_browser function marker")
    raise SystemExit(1)

start = text.find(setup_marker)

end = -1
for marker in next_markers:
    pos = text.find(marker, start)
    if pos != -1:
        end = pos
        break

if start == -1 or end == -1 or end <= start:
    print("❌ Could not locate setup_browser() block accurately")
    raise SystemExit(1)

func_name = "_setup_browser" if "def _setup_browser(" in text else "setup_browser"

new_func = f'''def {func_name}(headless=False):
    """
    Cookies-only auth bootstrap for LinkedIn.
    Each run starts a fresh browser context, injects Cookie Editor JSON,
    validates feed + admin analytics access, then continues scraping.
    """
    import os
    from playwright.sync_api import sync_playwright
    from linkedin_cookie_bootstrap import (
        apply_cookie_editor_cookies,
        prime_linkedin_auth,
        save_runtime_auth,
    )

    p = sync_playwright().start()

    forced_headless = str(
        os.environ.get(
            "LINKEDIN_HEADLESS",
            "false"
        )
    ).strip().lower() == "true"

    launch_errors = []
    browser = None

    launch_plan = [
        {{"channel": "chrome", "headless": forced_headless}},
        {{"headless": forced_headless}},
    ]

    for kwargs in launch_plan:
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
            log(f"Browser launch OK: channel={{kwargs.get('channel', 'chromium')}} headless={{kwargs.get('headless')}}")
            break
        except Exception as e:
            launch_errors.append(f"{{kwargs}}: {{e}}")

    if browser is None:
        raise RuntimeError("Could not launch LinkedIn browser: " + " | ".join(launch_errors))

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={{"width": 1440, "height": 900}},
        locale="en-US",
    )

    count, source = apply_cookie_editor_cookies(context)
    log(f"Applied {{count}} cookies from {{source}}")

    page = context.new_page()
    ok, final_url = prime_linkedin_auth(page, company_id=COMPANY_ID)
    if not ok:
        raise RuntimeError(f"Login redirect: {{final_url}}")

    save_runtime_auth(context)
    log(f"Authenticated cookies OK: {{final_url}}")
    return p, browser, page

'''

backup = Path("backups") / f"linkedin_browser_scraper.py.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

new_text = text[:start] + new_func + text[end:]
path.write_text(new_text, encoding="utf-8")

print(f"OK: backup written -> {backup}")
print(f"OK: patched -> {path}")
print(f"OK: function name kept as {func_name}")
