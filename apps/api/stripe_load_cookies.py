"""
STRIPE COOKIE LOADER
Loads cookies exported from your real Chrome via Cookie-Editor extension,
and saves them into a Playwright-compatible session.

Run ONCE (or whenever cookies expire and you re-export).
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).parent
COOKIE_FILE = PROJECT_ROOT / "stripe_cookies.json"
STRIPE_SESSION_DIR = PROJECT_ROOT / "stripe_session"
STRIPE_DASHBOARD_URL = "https://dashboard.stripe.com/"


def normalize_cookies(raw_cookies):
    """
    Cookie-Editor exports cookies in a slightly different format than
    Playwright expects. Convert them.
    """
    normalized = []
    for c in raw_cookies:
        cookie = {
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain"),
            "path": c.get("path", "/"),
        }

        # Optional fields
        if "expirationDate" in c:
            cookie["expires"] = float(c["expirationDate"])
        if "httpOnly" in c:
            cookie["httpOnly"] = bool(c["httpOnly"])
        if "secure" in c:
            cookie["secure"] = bool(c["secure"])

        # SameSite mapping
        ss = c.get("sameSite", "no_restriction")
        ss_map = {
            "no_restriction": "None",
            "lax": "Lax",
            "strict": "Strict",
            "unspecified": "Lax",
            "none": "None",
        }
        cookie["sameSite"] = ss_map.get(str(ss).lower(), "Lax")

        # Skip cookies without name or value
        if cookie["name"] and cookie["value"] is not None:
            normalized.append(cookie)

    return normalized


def main():
    print("=" * 60, flush=True)
    print("  STRIPE COOKIE LOADER", flush=True)
    print("=" * 60, flush=True)

    if not COOKIE_FILE.exists():
        print(f"❌ {COOKIE_FILE} not found.", flush=True)
        print("", flush=True)
        print("Steps to create it:", flush=True)
        print("  1. Install 'Cookie-Editor' extension in your real Chrome", flush=True)
        print("  2. Go to https://dashboard.stripe.com (logged in)", flush=True)
        print("  3. Open Cookie-Editor -> Export -> JSON (copies to clipboard)", flush=True)
        print("  4. Run: pbpaste > stripe_cookies.json", flush=True)
        return

    with open(COOKIE_FILE) as f:
        raw = json.load(f)

    print(f"Loaded {len(raw)} cookies from {COOKIE_FILE.name}", flush=True)

    cookies = normalize_cookies(raw)
    print(f"Normalized to {len(cookies)} valid cookies for Playwright", flush=True)

    # Wipe any old Stripe session and start fresh
    STRIPE_SESSION_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(STRIPE_SESSION_DIR),
            headless=False,
            viewport={"width": 1500, "height": 950},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )

        # Inject cookies BEFORE navigating
        try:
            context.add_cookies(cookies)
            print(f"✅ Injected {len(cookies)} cookies into browser session.", flush=True)
        except Exception as e:
            print(f"⚠️  Some cookies failed to inject: {e}", flush=True)
            # Try one-by-one to skip bad ones
            ok = 0
            for c in cookies:
                try:
                    context.add_cookies([c])
                    ok += 1
                except Exception:
                    continue
            print(f"   Injected {ok}/{len(cookies)} individually.", flush=True)

        page = context.new_page()
        print(f"Navigating to {STRIPE_DASHBOARD_URL}...", flush=True)
        page.goto(STRIPE_DASHBOARD_URL, wait_until="domcontentloaded")

        import time
        time.sleep(5)

        current_url = page.url
        print(f"Current URL: {current_url}", flush=True)

        if "login" in current_url.lower():
            print("", flush=True)
            print("❌ Cookies did not log you in. Possible reasons:", flush=True)
            print("   - Cookies expired (re-export them)", flush=True)
            print("   - Different account / session", flush=True)
            print("   - Browser will stay open 30s for inspection", flush=True)
            time.sleep(30)
        else:
            print("", flush=True)
            print("🎉 SUCCESS! You are logged in to Stripe via cookies.", flush=True)
            print("   Browser will close in 5 seconds. Session is saved.", flush=True)
            time.sleep(5)

        try:
            context.close()
        except Exception:
            pass

    print("", flush=True)
    print("✅ Done. Session saved to:", STRIPE_SESSION_DIR, flush=True)
    print("Now run: python scrape_stripe.py", flush=True)


if __name__ == "__main__":
    main()
