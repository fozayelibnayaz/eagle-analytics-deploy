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
safe_markers = [
    "\ndef _safe_int",
    "\ndef safe_int",
]

setup_marker = next((m for m in setup_markers if m in text), None)
if not setup_marker:
    print("❌ Could not find setup_browser marker")
    raise SystemExit(1)

start = text.find(setup_marker)

end = -1
for marker in safe_markers:
    pos = text.find(marker, start)
    if pos != -1:
        end = pos
        break

if start == -1 or end == -1 or end <= start:
    print("❌ Could not locate setup_browser() block accurately")
    raise SystemExit(1)

setup_name = "_setup_browser" if "def _setup_browser(" in text else "setup_browser"
cookie_func = "_load_cookies" if "def _load_cookies(" in text else "load_cookies"

new_func = f'''def {setup_name}(headless=False):
    """
    Use the same browser/session strategy that already passed the direct probe:
    real Google Chrome + visible session + storage_state.
    """
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()

    session_candidates = [
        Path("data/linkedin_session_state.json"),
        Path("data_output/linkedin_session_state.json"),
        DATA_DIR / "linkedin_session_state.json",
    ]
    session_file = next((f for f in session_candidates if f.exists()), None)

    launch_errors = []
    browser = None

    launch_plan = [
        {{"channel": "chrome", "headless": False}},
        {{"headless": False}},
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

    context_args = {{
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport": {{"width": 1440, "height": 900}},
        "locale": "en-US",
    }}

    if session_file is not None and session_file.exists():
        log(f"Using saved session state: {{session_file}}")
        context_args["storage_state"] = str(session_file)

    context = browser.new_context(**context_args)

    # Only add cookies if no saved storage_state exists
    if "storage_state" not in context_args:
        cookies = {cookie_func}()
        pw_cookies = []
        for c in cookies:
            try:
                domain = c.get("domain", ".linkedin.com")
                if not domain.startswith("."):
                    domain = "." + domain.lstrip(".")
                pw_c = {{
                    "name": c["name"],
                    "value": c["value"],
                    "domain": domain,
                    "path": c.get("path", "/"),
                    "secure": c.get("secure", True),
                    "httpOnly": c.get("httpOnly", False),
                }}
                exp = c.get("expirationDate")
                if exp and not c.get("session"):
                    pw_c["expires"] = int(exp)
                pw_cookies.append(pw_c)
            except Exception:
                continue

        if pw_cookies:
            context.add_cookies(pw_cookies)
            log(f"Loaded {{len(pw_cookies)}} cookies into browser context")

    page = context.new_page()
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    page.wait_for_timeout(4000)

    current_url = page.url.lower()
    if "login" in current_url or "uas/" in current_url or "authwall" in current_url or "checkpoint" in current_url or "challenge" in current_url:
        raise RuntimeError(f"Login redirect: {{page.url}}")

    log(f"Authenticated session OK: {{page.url}}")
    return p, browser, page

'''

backup = Path("backups") / f"linkedin_browser_scraper.py.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

new_text = text[:start] + new_func + text[end:]
path.write_text(new_text, encoding="utf-8")

print(f"OK: backup written -> {backup}")
print(f"OK: patched -> {path}")
print(f"OK: function name kept as {setup_name}")
print(f"OK: cookie loader used as {cookie_func}")
