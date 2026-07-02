"""
Just wait for the month dropdown to become enabled, then change it.
No tab clicking, no extra actions. Pure wait + click.
"""
import time
from playwright.sync_api import sync_playwright
from config import BROWSER_SESSION_DIR, KPI_URL

def log(msg):
    print(f">>> {msg}", flush=True)

def is_dropdown_enabled(page):
    """Returns True only if the dropdown is truly clickable."""
    try:
        el = page.locator(".MuiSelect-select").first
        if el.count() == 0:
            return False
        aria_disabled = el.get_attribute("aria-disabled")
        class_attr = el.get_attribute("class") or ""
        if aria_disabled == "true":
            return False
        if "Mui-disabled" in class_attr:
            return False
        return True
    except Exception:
        return False

def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_SESSION_DIR),
            headless=False,
            slow_mo=200,
            viewport={"width": 1600, "height": 1000},
        )
        page = context.new_page()
        page.goto(KPI_URL, wait_until="domcontentloaded")

        log("Dashboard opened. Waiting for the month dropdown to become enabled...")
        log("(Doing nothing else — just waiting patiently.)")

        # Wait up to 3 minutes (180 seconds), checking every 1 second
        MAX_WAIT_SECONDS = 180
        elapsed = 0
        enabled = False

        while elapsed < MAX_WAIT_SECONDS:
            if is_dropdown_enabled(page):
                enabled = True
                log(f"🎉 Dropdown became ENABLED after {elapsed} seconds!")
                break
            if elapsed % 5 == 0:  # log every 5 seconds
                try:
                    el = page.locator(".MuiSelect-select").first
                    txt = (el.text_content() or "").strip()
                    log(f"  [{elapsed}s] still disabled. Current text: '{txt}'")
                except Exception:
                    log(f"  [{elapsed}s] still disabled.")
            time.sleep(1)
            elapsed += 1

        if not enabled:
            log(f"❌ Dropdown stayed disabled for full {MAX_WAIT_SECONDS} seconds.")
            log("   Browser will stay open 30s so you can check manually.")
            page.screenshot(path="data/debug_never_enabled.png", full_page=True)
            time.sleep(30)
            context.close()
            return

        # ── Now click it ──
        log("\nClicking the dropdown...")
        page.locator(".MuiSelect-select").first.click(timeout=5000)
        time.sleep(1.5)

        # ── List options that appeared ──
        options = page.locator("li[role='option']").all()
        log(f"Menu opened. Found {len(options)} options:")
        for i, opt in enumerate(options):
            try:
                txt = (opt.text_content() or "").strip()
                log(f"  [{i}] '{txt}'")
            except Exception:
                pass

        # ── Click 'Current Month' ──
        log("\nClicking 'Current Month'...")
        clicked = False
        for opt in options:
            try:
                txt = (opt.text_content() or "").strip()
                if txt == "Current Month":
                    opt.click(timeout=5000)
                    clicked = True
                    log("✅ 'Current Month' clicked!")
                    break
            except Exception as e:
                log(f"  click error: {e}")

        if not clicked:
            log("❌ Could not find 'Current Month' option.")

        time.sleep(3)

        # ── Verify ──
        try:
            el = page.locator(".MuiSelect-select").first
            new_txt = (el.text_content() or "").strip()
            log(f"\nDropdown now shows: '{new_txt}'")
        except Exception:
            pass

        page.screenshot(path="data/debug_final.png", full_page=True)
        log("\n✅ Done. Browser open 20s for you to verify.")
        time.sleep(20)
        context.close()

if __name__ == "__main__":
    main()
