"""
INVESTIGATE: What enables the month dropdown?
Tries multiple actions and watches the dropdown's disabled state.
"""
import time
from playwright.sync_api import sync_playwright
from config import BROWSER_SESSION_DIR, KPI_URL

def log(msg):
    print(f">>> {msg}", flush=True)

def check_dropdown(page, label=""):
    """Check the current state of the month dropdown."""
    try:
        el = page.locator("div[role='combobox'], .MuiSelect-select").first
        txt = (el.text_content() or "").strip()
        disabled_attr = el.get_attribute("aria-disabled")
        class_attr = el.get_attribute("class") or ""
        has_disabled_class = "Mui-disabled" in class_attr
        log(f"  [{label}] text='{txt}' aria-disabled={disabled_attr} has-disabled-class={has_disabled_class}")
        return disabled_attr != "true" and not has_disabled_class
    except Exception as e:
        log(f"  [{label}] error: {e}")
        return False

def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_SESSION_DIR),
            headless=False,
            slow_mo=300,
            viewport={"width": 1600, "height": 1000},
        )
        page = context.new_page()
        page.goto(KPI_URL, wait_until="domcontentloaded")

        log("Waiting for dashboard...")
        page.wait_for_selector("text=Free Trial Accounts", timeout=20000)

        # ── Check dropdown state at multiple points in time ──
        log("\n=== Checking dropdown state over time (no interaction) ===")
        for i in range(8):
            time.sleep(1)
            check_dropdown(page, f"t+{i+1}s")

        # ── Try clicking each tab and recheck ──
        log("\n=== Clicking each tab and checking dropdown ===")
        for tab in ["FREE", "PAID", "500 MIN", "FIRST UPLOAD"]:
            try:
                btn = page.locator(f"button:has-text('{tab}')").first
                btn.click(timeout=5000)
                log(f"\nClicked '{tab}' tab")
                time.sleep(3)
                enabled = check_dropdown(page, f"after {tab}")
                if enabled:
                    log(f"  🎉 Dropdown ENABLED after clicking {tab}!")
            except Exception as e:
                log(f"  Tab click failed: {e}")

        # ── Inspect the dropdown's full HTML ──
        log("\n=== Full dropdown HTML ===")
        try:
            el = page.locator(".MuiSelect-select").first
            html = el.evaluate("el => el.outerHTML")
            log(html[:500])

            # Also inspect parent
            parent_html = el.evaluate("el => el.parentElement.outerHTML")
            log("\n=== Parent HTML ===")
            log(parent_html[:800])
        except Exception as e:
            log(f"HTML inspect failed: {e}")

        # ── Look for hidden <select> element ──
        log("\n=== Looking for native <select> elements ===")
        selects = page.locator("select").all()
        log(f"Found {len(selects)} native <select> elements.")
        for i, s in enumerate(selects):
            try:
                name = s.get_attribute("name") or ""
                value = s.input_value()
                visible = s.is_visible()
                log(f"  [{i}] name='{name}' value='{value}' visible={visible}")

                # Get options
                opts = s.locator("option").all_text_contents()
                log(f"      options: {opts}")
            except Exception as e:
                log(f"  [{i}] error: {e}")

        # ── Try setting value via the hidden native select ──
        log("\n=== Attempting to change month via JavaScript ===")
        try:
            result = page.evaluate("""() => {
                // Find all selects
                const selects = document.querySelectorAll('select');
                const info = [];
                selects.forEach((s, i) => {
                    const opts = Array.from(s.options).map(o => o.text + '=' + o.value);
                    info.push({
                        index: i,
                        name: s.name,
                        value: s.value,
                        disabled: s.disabled,
                        options: opts
                    });
                });
                return info;
            }""")
            log(f"JS select inspection: {result}")
        except Exception as e:
            log(f"JS inspect failed: {e}")

        log("\n✅ Investigation done. Browser open 20s.")
        page.screenshot(path="data/debug_investigation.png", full_page=True)
        time.sleep(20)
        context.close()

if __name__ == "__main__":
    main()
