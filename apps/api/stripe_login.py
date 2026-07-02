"""
ONE-TIME STRIPE LOGIN v2
Uses your REAL Chrome (or Chromium) instead of Playwright's bundled one.
Stripe's bot detection cant tell the difference from a normal user.
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import sys
import os

STRIPE_SESSION_DIR = Path(__file__).parent / "stripe_session"
STRIPE_URL = "https://dashboard.stripe.com/login"

# Try to find your real Chrome on Mac
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

def find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None

def main():
    print("=" * 60, flush=True)
    print("  ONE-TIME STRIPE LOGIN v2 (using real Chrome)", flush=True)
    print("=" * 60, flush=True)

    chrome_path = find_chrome()
    if chrome_path:
        print(f"Using browser: {chrome_path}", flush=True)
    else:
        print("Real Chrome not found - falling back to Chromium.", flush=True)

    print("", flush=True)
    print("A browser will open Stripe login.", flush=True)
    print("Log in normally (with 2FA if asked).", flush=True)
    print("Once you see the Stripe dashboard, CLOSE the window.", flush=True)
    print("", flush=True)
    input("Press ENTER to launch... ")

    with sync_playwright() as p:
        launch_args = {
            "user_data_dir": str(STRIPE_SESSION_DIR),
            "headless": False,
            "viewport": {"width": 1500, "height": 950},
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
            "ignore_default_args": ["--enable-automation"],
        }
        if chrome_path:
            launch_args["executable_path"] = chrome_path
            launch_args["channel"] = None  # use the executable directly

        context = p.chromium.launch_persistent_context(**launch_args)

        # Hide the webdriver flag (extra anti-detection)
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
        """)

        page = context.new_page()
        page.goto(STRIPE_URL)

        print("", flush=True)
        print(">>> Browser open. Log in to Stripe now.", flush=True)
        print(">>> When you see the dashboard, just close the window.", flush=True)
        print("", flush=True)

        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass

    print("", flush=True)
    print("Session saved to:", STRIPE_SESSION_DIR, flush=True)
    print("Now run: python scrape_stripe.py", flush=True)

if __name__ == "__main__":
    main()
