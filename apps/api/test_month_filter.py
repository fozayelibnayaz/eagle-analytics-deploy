"""
FOCUSED TEST: Just change month filter from 'Last Month' to 'Current Month'.
Watch the browser visually to confirm.
"""
import time
from playwright.sync_api import sync_playwright
from config import BROWSER_SESSION_DIR, KPI_URL

def log(msg):
    print(f">>> {msg}", flush=True)

def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_SESSION_DIR),
            headless=False,
            slow_mo=400,  # slow so we can SEE every action
            viewport={"width": 1600, "height": 1000},
        )
        page = context.new_page()
        page.goto(KPI_URL, wait_until="domcontentloaded")

        log("Waiting for dashboard...")
        page.wait_for_selector("text=Free Trial Accounts", timeout=20000)
        time.sleep(3)
        log("Dashboard ready.")

        # ── INSPECT: find ALL combobox / select elements and report them ──
        log("Inspecting all dropdown-like elements on the page...")

        all_selects = page.locator("div[role='combobox'], .MuiSelect-select").all()
        log(f"Found {len(all_selects)} dropdown elements.")
        for i, el in enumerate(all_selects):
            try:
                txt = el.text_content() or ""
                disabled = el.get_attribute("aria-disabled")
                visible = el.is_visible()
                log(f"  [{i}] text='{txt.strip()}' disabled={disabled} visible={visible}")
            except Exception as e:
                log(f"  [{i}] error: {e}")

        # ── STRATEGY: find the dropdown that contains 'Month' text ──
        log("\nLooking for the dropdown showing 'Last Month'...")

        target_dropdown = None
        for i, el in enumerate(all_selects):
            try:
                txt = (el.text_content() or "").strip()
                if "Month" in txt or "month" in txt:
                    target_dropdown = el
                    log(f"  -> Found month dropdown at index [{i}]: '{txt}'")
                    break
            except Exception:
                continue

        if not target_dropdown:
            log("❌ No month dropdown found. Saving screenshot...")
            page.screenshot(path="data/debug_no_dropdown.png", full_page=True)
            time.sleep(5)
            context.close()
            return

        # ── CLICK the dropdown ──
        log("\nAttempting to click the month dropdown...")

        # Method 1: Direct click
        try:
            target_dropdown.click(timeout=5000)
            log("✅ Method 1 (direct click) worked.")
        except Exception as e:
            log(f"Method 1 failed: {str(e)[:100]}")

            # Method 2: Force click
            try:
                target_dropdown.click(force=True, timeout=5000)
                log("✅ Method 2 (force click) worked.")
            except Exception as e2:
                log(f"Method 2 failed: {str(e2)[:100]}")

                # Method 3: JavaScript click
                try:
                    target_dropdown.evaluate("el => el.click()")
                    log("✅ Method 3 (JS click) worked.")
                except Exception as e3:
                    log(f"Method 3 failed: {str(e3)[:100]}")

                    # Method 4: Click parent
                    try:
                        target_dropdown.locator("xpath=..").click(force=True, timeout=5000)
                        log("✅ Method 4 (parent click) worked.")
                    except Exception as e4:
                        log(f"❌ All click methods failed.")
                        page.screenshot(path="data/debug_click_failed.png", full_page=True)
                        time.sleep(5)
                        context.close()
                        return

        time.sleep(2)
        page.screenshot(path="data/debug_after_dropdown_click.png", full_page=True)

        # ── Look for the dropdown options menu ──
        log("\nLooking for menu options...")
        time.sleep(1)

        options = page.locator("li[role='option']").all()
        log(f"Found {len(options)} menu options.")
        for i, opt in enumerate(options):
            try:
                txt = (opt.text_content() or "").strip()
                log(f"  Option [{i}]: '{txt}'")
            except Exception:
                pass

        # ── Click 'Current Month' ──
        log("\nClicking 'Current Month' option...")
        clicked = False
        for opt in options:
            try:
                txt = (opt.text_content() or "").strip()
                if txt == "Current Month":
                    opt.click(timeout=5000)
                    clicked = True
                    log("✅ Clicked 'Current Month'!")
                    break
            except Exception as e:
                log(f"  Click failed: {e}")

        if not clicked:
            log("❌ 'Current Month' option not found in menu.")

        time.sleep(3)
        page.screenshot(path="data/debug_after_month_change.png", full_page=True)

        log("\n✅ Test complete. Browser will stay open 15 seconds so you can verify.")
        time.sleep(15)
        context.close()

if __name__ == "__main__":
    main()
