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
    Reuse the same persistent LinkedIn Chrome profile seeded from full cookies.
    """
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()

    profile_dir = Path("browser_session/linkedin_persistent_profile")
    profile_dir.mkdir(parents=True, exist_ok=True)

    launch_errors = []
    context = None

    for kwargs in (
        {{"channel": "chrome", "headless": False}},
        {{"headless": False}},
    ):
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                **kwargs,
                viewport={{"width": 1440, "height": 900}},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-default-browser-check",
                    "--disable-gpu",
                ],
            )
            log(f"Persistent browser launch OK: channel={{kwargs.get('channel', 'chromium')}} headless={{kwargs.get('headless')}} profile={{profile_dir}}")
            break
        except Exception as e:
            launch_errors.append(f"{{kwargs}}: {{e}}")

    if context is None:
        raise RuntimeError("Could not launch LinkedIn persistent browser: " + " | ".join(launch_errors))

    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://www.linkedin.com/company/68624141/admin/analytics/updates/", wait_until="domcontentloaded", timeout=60000)

    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass

    page.wait_for_timeout(5000)

    current_url = page.url.lower()
    if "login" in current_url or "uas/" in current_url or "authwall" in current_url or "checkpoint" in current_url or "challenge" in current_url or "flagship-web/login" in current_url:
        raise RuntimeError(f"Login redirect: {{page.url}}")

    log(f"Authenticated persistent profile OK: {{page.url}}")

    class _BrowserProxy:
        def __init__(self, ctx):
            self._ctx = ctx
        def close(self):
            try:
                self._ctx.close()
            except Exception:
                pass

    browser = _BrowserProxy(context)
    return p, browser, page

'''

backup = Path("backups") / f"linkedin_browser_scraper.py.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

new_text = text[:start] + new_func + text[end:]
path.write_text(new_text, encoding="utf-8")

print(f"OK: backup written -> {backup}")
print(f"OK: patched -> {path}")
print(f"OK: function name kept as {func_name}")
