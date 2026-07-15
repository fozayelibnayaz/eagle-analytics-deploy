from pathlib import Path
from datetime import datetime
import json
import re
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PROFILE_DIR = Path("browser_session/linkedin_persistent_profile")
EXPORT_DIR = Path("downloads/linkedin_exports")
URL = "https://www.linkedin.com/company/68624141/admin/analytics/updates/"

BAD_MARKERS = (
    "/login",
    "/uas/",
    "/checkpoint",
    "/challenge",
    "flagship-web/login",
    "authwall",
)

EXPORT_HINTS = [
    "export", "download", "csv", "xls", "xlsx", "excel"
]

FILE_HINTS = [
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
]

def bad(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in BAD_MARKERS)

def norm_text(s: str) -> str:
    return " ".join(str(s or "").split()).strip()

def looks_like_file_response(resp) -> bool:
    try:
        url = resp.url.lower()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        ct = headers.get("content-type", "").lower()
        cd = headers.get("content-disposition", "").lower()
        if any(x in ct for x in FILE_HINTS):
            return True
        if "attachment" in cd:
            return True
        if any(x in url for x in [".csv", ".xls", ".xlsx", "download", "export"]):
            return True
    except Exception:
        pass
    return False

def ext_from_response(resp) -> str:
    try:
        url = resp.url.lower()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        ct = headers.get("content-type", "").lower()
        cd = headers.get("content-disposition", "").lower()
        if ".csv" in url or "text/csv" in ct:
            return ".csv"
        if ".xlsx" in url or "openxmlformats-officedocument.spreadsheetml.sheet" in ct:
            return ".xlsx"
        if ".xls" in url or "vnd.ms-excel" in ct:
            return ".xls"
        if "attachment" in cd:
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m:
                name = m.group(1)
                if "." in name:
                    return "." + name.split(".")[-1]
    except Exception:
        pass
    return ".bin"

def visible_actions(page):
    actions = []
    selectors = [
        "button",
        "a",
        "[role='button']",
        "[role='menuitem']",
        "[role='option']",
        "[role='link']",
        "[aria-label]",
    ]
    seen = set()
    for sel in selectors:
        loc = page.locator(sel)
        count = min(loc.count(), 200)
        for i in range(count):
            try:
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                txt = norm_text(el.inner_text() or el.get_attribute("aria-label") or "")
                if not txt:
                    continue
                key = (sel, txt)
                if key in seen:
                    continue
                seen.add(key)
                actions.append((sel, txt, i))
            except Exception:
                continue
    return actions

def save_response_body(resp, out_dir: Path):
    try:
        ext = ext_from_response(resp)
        out = out_dir / f"linkedin_export_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        body = resp.body()
        out.write_bytes(body)
        print(f"Saved file-like response body -> {out}")
        return out
    except Exception as e:
        print(f"Could not save response body: {e}")
        return None

def try_click_and_download(page, description, locator, out_dir: Path):
    # 1) direct download event
    try:
        with page.expect_download(timeout=12000) as dlinfo:
            locator.click(force=True)
        dl = dlinfo.value
        name = dl.suggested_filename or f"linkedin_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
        out = out_dir / name
        dl.save_as(str(out))
        print(f"Download event success via {description} -> {out}")
        return out
    except Exception:
        pass

    # 2) popup/new tab possibility
    try:
        with page.expect_popup(timeout=6000) as popinfo:
            locator.click(force=True)
        pop = popinfo.value
        pop.wait_for_load_state("domcontentloaded", timeout=10000)
        print(f"Popup opened via {description}: {pop.url}")
        pop.close()
    except Exception:
        pass

    # 3) plain click fallback
    try:
        locator.click(force=True)
        page.wait_for_timeout(3000)
        print(f"Clicked without immediate download via {description}")
    except Exception as e:
        print(f"Click failed via {description}: {e}")

    return None

def main():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        errors = []
        context = None

        for kwargs in (
            {"channel": "chrome", "headless": False},
            {"headless": False},
        ):
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    **kwargs,
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="en-US",
                    accept_downloads=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-default-browser-check",
                        "--disable-gpu",
                    ],
                )
                print(f"OK: persistent browser launch -> {kwargs}")
                break
            except Exception as e:
                errors.append(f"{kwargs}: {e}")

        if context is None:
            print("❌ Could not launch persistent browser")
            for err in errors:
                print("  -", err)
            raise SystemExit(1)

        page = context.pages[0] if context.pages else context.new_page()

        file_like_responses = []

        def on_response(resp):
            if looks_like_file_response(resp):
                file_like_responses.append(resp)
                try:
                    print("File-like response detected:", resp.url)
                except Exception:
                    pass

        page.on("response", on_response)

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(5000)

        print("Current URL:", page.url)
        if bad(page.url):
            print("❌ Still not authenticated on admin analytics page")
            context.close()
            raise SystemExit(1)

        before = [txt for _, txt, _ in visible_actions(page)]
        print("Visible actions before Export (sample):")
        for x in before[:30]:
            print(" -", x)

        # Save before screenshot
        before_ss = EXPORT_DIR / f"linkedin_updates_before_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(before_ss), full_page=True)
        print("Saved screenshot ->", before_ss)

        export_loc = page.locator("button:has-text('Export')")
        if export_loc.count() < 1:
            print("❌ Export button not found")
            context.close()
            raise SystemExit(1)

        result = try_click_and_download(page, "primary Export button", export_loc.first, EXPORT_DIR)
        if result:
            context.close()
            print(f"✅ Export downloaded -> {result}")
            return

        page.wait_for_timeout(3000)

        # Save after screenshot
        after_ss = EXPORT_DIR / f"linkedin_updates_after_click_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(after_ss), full_page=True)
        print("Saved screenshot ->", after_ss)

        after_actions = [txt for _, txt, _ in visible_actions(page)]
        new_actions = [x for x in after_actions if x not in before]
        print("Visible NEW actions after Export click:")
        for x in new_actions[:40]:
            print(" +", x)

        # Try likely second-step actions
        tried = set()
        selectors = [
            "button",
            "a",
            "[role='button']",
            "[role='menuitem']",
            "[role='option']",
            "[role='link']",
        ]

        for sel in selectors:
            loc = page.locator(sel)
            count = min(loc.count(), 200)
            for i in range(count):
                try:
                    el = loc.nth(i)
                    if not el.is_visible():
                        continue
                    txt = norm_text(el.inner_text() or el.get_attribute("aria-label") or "")
                    if not txt:
                        continue
                    low = txt.lower()
                    if not any(h in low for h in EXPORT_HINTS):
                        continue
                    key = (sel, txt, i)
                    if key in tried:
                        continue
                    tried.add(key)

                    print(f"Trying second-step action: selector={sel} text={txt!r} index={i}")
                    result = try_click_and_download(page, f"{sel}::{txt}", el, EXPORT_DIR)
                    if result:
                        context.close()
                        print(f"✅ Export downloaded -> {result}")
                        return
                except Exception:
                    continue

        # If no download event, try saving file-like network response
        if file_like_responses:
            out = save_response_body(file_like_responses[-1], EXPORT_DIR)
            if out:
                context.close()
                print(f"✅ Export captured from network response -> {out}")
                return

        print("❌ Export flow still not resolved automatically")
        context.close()
        raise SystemExit(1)

if __name__ == "__main__":
    main()
