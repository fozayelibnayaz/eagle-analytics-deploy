"""
STRIPE LOGIN via your REAL Chrome user profile.
This uses your actual Chrome where you are already logged in to Stripe.

IMPORTANT: Close ALL Chrome windows before running this!
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import os
import shutil

STRIPE_SESSION_DIR = Path(__file__).parent / "stripe_session"
STRIPE_URL = "https://dashboard.stripe.com/login"

# Your real Chrome profile path on Mac
REAL_CHROME_PROFILE = Path.home() / "Library/Application Support/Google/Chrome"
CHROME_EXEC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def main():
    print("=" * 60, flush=True)
    print("  STRIPE LOGIN via your REAL Chrome profile", flush=True)
    print("=" * 60, flush=True)
    print("", flush=True)
    print("⚠️  IMPORTANT: Close ALL Chrome windows first!", flush=True)
    print("    (Cmd+Q on Chrome to quit completely)", flush=True)
    print("", flush=True)
    input("Press ENTER once Chrome is fully closed... ")

    if not REAL_CHROME_PROFILE.exists():
        print(f"❌ Chrome profile not found at: {REAL_CHROME_PROFILE}")
        return

    # Copy your real Chrome profile (so we don't mess with it)
    print("Copying your Chrome profile (one-time, ~30 seconds)...", flush=True)
    if STRIPE_SESSION_DIR.exists():
        shutil.rmtree(STRIPE_SESSION_DIR)
    try:
        shutil.copytree(
            REAL_CHROME_PROFILE,
            STRIPE_SESSION_DIR,
            ignore=shutil.ignore_patterns("Singleton*", "*Cache*", "*.log"),
            dirs_exist_ok=False,
        )
        print("✅ Profile copied.", flush=True)
    except Exception as e:
        print(f"❌ Copy failed: {e}")
        return

    print("", flush=True)
    print("Launching browser with your real profile...", flush=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(STRIPE_SESSION_DIR),
            executable_path=CHROME_EXEC,
            headless=False,
            viewport={"width": 1500, "height": 950},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()
        page.goto(STRIPE_URL)

        print("", flush=True)
        print(">>> If you were already logged in to Stripe in your normal Chrome,", flush=True)
        print(">>> you should now see the Stripe dashboard immediately.", flush=True)
        print(">>> If not, log in normally.", flush=True)
        print(">>> Close the window when done.", flush=True)
        print("", flush=True)

        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass

    print("✅ Session saved.", flush=True)

if __name__ == "__main__":
    main()
