from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PROFILE_DIR = Path("browser_session/linkedin_persistent_profile")
EXPORT_DIR = Path("downloads/linkedin_exports")
COMPANY_ID = "68624141"

# Keep only the datasets that are working or most important first.
# search_appearances is intentionally skipped for now because it broke the whole run.
PAGES = {
    "updates": f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/updates/",
    "visitors": f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/visitors/",
    "followers": f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/followers/",
    "competitors": f"https://www.linkedin.com/company/{COMPANY_ID}/admin/analytics/competitors/",
}

BAD_MARKERS = (
    "/login",
    "/uas/",
    "/checkpoint",
    "/challenge",
    "flagship-web/login",
    "authwall",
)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [LI-export] {msg}", flush=True)


def bad(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in BAD_MARKERS)


def wait_ready(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(4000)


def close_noise(page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    selectors = [
        "button[aria-label='Dismiss']",
        "button[aria-label='Close']",
        "button:has-text('Got it')",
        "button:has-text('Close')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500)
                page.wait_for_timeout(1000)
        except Exception:
            continue


def filename_from_ambry_url(url: str, dataset_key: str) -> str:
    try:
        qs = parse_qs(urlparse(url).query)
        vals = qs.get("x-ambry-um-filename") or []
        if vals:
            return f"{dataset_key}__{vals[0]}"
    except Exception:
        pass
    return f"{dataset_key}__linkedin_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xls"


def is_real_export_response(resp) -> bool:
    try:
        u = resp.url.lower()
        return "linkedin.com/ambry/" in u and "x-ambry-um-filename=" in u
    except Exception:
        return False


def save_ambry_response(resp, dataset_key: str) -> Path:
    name = filename_from_ambry_url(resp.url, dataset_key)
    out = EXPORT_DIR / name
    out.write_bytes(resp.body())
    return out


def find_visible_export_button(page):
    # Use only real visible button elements, not generic text locators.
    btns = page.locator("button")
    count = btns.count()
    for i in range(min(count, 200)):
        try:
            btn = btns.nth(i)
            if not btn.is_visible():
                continue
            text = " ".join((btn.inner_text() or "").split()).strip().lower()
            aria = " ".join((btn.get_attribute("aria-label") or "").split()).strip().lower()
            if text == "export" or "export" in aria:
                return btn
        except Exception:
            continue
    return None


def export_one_dataset(context, dataset_key: str, url: str) -> Path:
    page = context.new_page()
    try:
        export_hits = []

        def on_response(resp):
            if is_real_export_response(resp):
                export_hits.append(resp)
                log(f"Real export response detected: {resp.url}")

        page.on("response", on_response)

        log("=" * 60)
        log(f"DATASET: {dataset_key}")
        log(f"URL: {url}")

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        wait_ready(page)
        close_noise(page)

        log(f"Current URL: {page.url}")
        if bad(page.url):
            raise RuntimeError(f"Login/authwall redirect on {dataset_key}: {page.url}")

        btn = find_visible_export_button(page)
        if btn is None:
            screenshot = EXPORT_DIR / f"{dataset_key}__no_export_button_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=str(screenshot), full_page=True)
            raise RuntimeError(f"No visible Export button found for {dataset_key}. Screenshot: {screenshot}")

        # Prefer browser download event
        try:
            with page.expect_download(timeout=15000) as dlinfo:
                btn.click(force=True)
            dl = dlinfo.value
            suggested = dl.suggested_filename or f"{dataset_key}__linkedin_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xls"
            if "__" not in suggested:
                suggested = f"{dataset_key}__{suggested}"
            out = EXPORT_DIR / suggested
            dl.save_as(str(out))
            log(f"Downloaded via browser download event -> {out}")
            return out
        except PlaywrightTimeoutError:
            log("No direct browser download event; waiting for real ambry export response...")
        except Exception as e:
            log(f"Direct export click/download failed: {e}")

        # Sometimes Export opens a tiny follow-up menu. Try common second-step buttons.
        page.wait_for_timeout(2000)
        second_steps = [
            "button:has-text('Download')",
            "button:has-text('CSV')",
            "button:has-text('Excel')",
            "button:has-text('Export')",
            "[role='menuitem']:has-text('Download')",
            "[role='menuitem']:has-text('CSV')",
            "[role='menuitem']:has-text('Excel')",
        ]

        for sel in second_steps:
            try:
                loc = page.locator(sel)
                if loc.count() < 1 or not loc.first.is_visible():
                    continue
                log(f"Trying second-step action: {sel}")
                try:
                    with page.expect_download(timeout=10000) as dlinfo:
                        loc.first.click(force=True)
                    dl = dlinfo.value
                    suggested = dl.suggested_filename or f"{dataset_key}__linkedin_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xls"
                    if "__" not in suggested:
                        suggested = f"{dataset_key}__{suggested}"
                    out = EXPORT_DIR / suggested
                    dl.save_as(str(out))
                    log(f"Downloaded via second-step browser download -> {out}")
                    return out
                except Exception:
                    loc.first.click(force=True)
                    page.wait_for_timeout(2000)
            except Exception:
                continue

        # If LinkedIn serves export via ambry response, save body from that
        deadline = time.time() + 20
        while time.time() < deadline:
            if export_hits:
                out = save_ambry_response(export_hits[-1], dataset_key)
                log(f"Downloaded via ambry response body -> {out}")
                return out
            page.wait_for_timeout(500)

        screenshot = EXPORT_DIR / f"{dataset_key}__export_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(screenshot), full_page=True)
        raise RuntimeError(f"Export capture failed for dataset={dataset_key}. Screenshot: {screenshot}")
    finally:
        try:
            page.close()
        except Exception:
            pass


def run_export_sync():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    headless = str(os.environ.get("LINKEDIN_HEADLESS", "false")).strip().lower() == "true"

    with sync_playwright() as p:
        errors = []
        context = None

        for kwargs in (
            {"channel": "chrome", "headless": headless},
            {"headless": headless},
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
                log(f"Persistent browser launch OK: {kwargs}")
                break
            except Exception as e:
                errors.append(f"{kwargs}: {e}")

        if context is None:
            raise RuntimeError("Could not launch persistent browser: " + " | ".join(errors))

        downloaded = []
        failed = []

        try:
            for dataset_key, url in PAGES.items():
                try:
                    out = export_one_dataset(context, dataset_key, url)
                    downloaded.append(str(out))
                except Exception as e:
                    log(f"FAILED dataset={dataset_key}: {e}")
                    failed.append({"dataset": dataset_key, "error": str(e)})

            print()
            print("Downloaded files:")
            for f in downloaded:
                print(" -", f)

            if failed:
                print()
                print("Failed datasets:")
                for f in failed:
                    print(f" - {f['dataset']}: {f['error']}")

            if not downloaded:
                raise RuntimeError("No LinkedIn export files were downloaded")

            return downloaded
        finally:
            try:
                context.close()
            except Exception:
                pass


if __name__ == "__main__":
    run_export_sync()
