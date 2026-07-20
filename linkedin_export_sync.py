from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from linkedin_cookie_bootstrap import apply_cookie_editor_cookies, prime_linkedin_auth, save_runtime_auth

EXPORT_DIR = Path("downloads/linkedin_exports")
COMPANY_ID = "68624141"

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

STATE_PATHS = [
    Path("data/linkedin_session_state.json"),
    Path("data_output/linkedin_session_state.json"),
    Path("data/linkedin_storage_state_runtime.json"),
    Path("data_output/linkedin_storage_state_runtime.json"),
]

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

def pick_storage_state_path() -> Path | None:
    for path in STATE_PATHS:
        try:
            if path.exists() and path.read_text(encoding="utf-8", errors="ignore").strip():
                return path
        except Exception:
            continue
    return None

def build_context(browser):
    common = dict(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1440, "height": 900},
        locale="en-US",
        accept_downloads=True,
    )

    state_path = pick_storage_state_path()
    if state_path:
        try:
            context = browser.new_context(storage_state=str(state_path), **common)
            log(f"Loaded storage_state from {state_path}")
            return context, f"storage_state:{state_path}"
        except Exception as e:
            log(f"Storage state load failed ({state_path}): {e}")

    context = browser.new_context(**common)
    count, source = apply_cookie_editor_cookies(context)
    log(f"Applied {count} cookies from {source}")
    return context, f"cookies:{source}"

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
    btns = page.locator("button")
    count = btns.count()
    for i in range(min(count, 200)):
        try:
            btn = btns.nth(i)
            if not btn.is_visible():
                continue
            txt = " ".join((btn.inner_text() or "").split()).strip().lower()
            aria = " ".join((btn.get_attribute("aria-label") or "").split()).strip().lower()
            if txt == "export" or "export" in aria:
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
            raise RuntimeError(f"No visible Export button found for {dataset_key}")

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
            log("No direct download event; waiting for ambry response...")

        deadline = time.time() + 20
        while time.time() < deadline:
            if export_hits:
                out = save_ambry_response(export_hits[-1], dataset_key)
                log(f"Downloaded via ambry response body -> {out}")
                return out
            page.wait_for_timeout(500)

        raise RuntimeError(f"Export capture failed for dataset={dataset_key}")
    finally:
        try:
            page.close()
        except Exception:
            pass

def launch_browser(p, headless: bool):
    log(f"Launching Chromium headless={headless}")
    return p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-default-browser-check",
            "--disable-gpu",
        ],
    )

def run_once(p, headless: bool):
    browser = launch_browser(p, headless=headless)
    context = None
    try:
        context, auth_mode = build_context(browser)
        log(f"Auth bootstrap mode: {auth_mode}")

        downloaded = []
        failed = []

        page = context.new_page()
        try:
            ok, final_url = prime_linkedin_auth(page, company_id=COMPANY_ID)
            log(f"Prime auth result: ok={ok} url={final_url}")
            save_runtime_auth(context)
            if not ok:
                raise RuntimeError(f"LinkedIn authwall after bootstrap: {final_url}")
        finally:
            try:
                page.close()
            except Exception:
                pass

        for dataset_key, url in PAGES.items():
            try:
                out = export_one_dataset(context, dataset_key, url)
                downloaded.append(str(out))
            except Exception as e:
                failed.append({"dataset": dataset_key, "error": str(e)})
                log(f"FAILED dataset={dataset_key}: {e}")

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
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass

def run_export_sync():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    requested_headless = str(os.environ.get("LINKEDIN_HEADLESS", "true")).strip().lower() == "true"

    with sync_playwright() as p:
        attempts = [requested_headless]
        if requested_headless:
            attempts.append(False)

        errors = []
        for headless in attempts:
            try:
                return run_once(p, headless=headless)
            except Exception as e:
                msg = f"headless={headless}: {e}"
                errors.append(msg)
                log(f"RUN FAILED {msg}")

        raise RuntimeError(" | ".join(errors))

if __name__ == "__main__":
    run_export_sync()
