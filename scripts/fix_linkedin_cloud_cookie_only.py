from pathlib import Path
from datetime import datetime
import textwrap

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.linkedin_cookie_only_cloud.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# -------------------------------------------------------------------
# Rewrite linkedin_export_sync.py to use cookies-only browser context
# -------------------------------------------------------------------
les = ROOT / "linkedin_export_sync.py"
backup(les) if les.exists() else None
les.write_text(textwrap.dedent("""\
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from linkedin_cookie_bootstrap import apply_cookie_editor_cookies

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

def run_export_sync():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    headless = str(os.environ.get("LINKEDIN_HEADLESS", "true")).strip().lower() == "true"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            accept_downloads=True,
        )

        count, source = apply_cookie_editor_cookies(context)
        log(f"Applied {count} cookies from {source}")

        downloaded = []
        failed = []

        try:
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
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

if __name__ == "__main__":
    run_export_sync()
"""), encoding="utf-8")
print("✅ linkedin_export_sync.py rewritten for cookie-only cloud mode")

# -------------------------------------------------------------------
# Rewrite LinkedIn workflow to remove persistent profile step
# -------------------------------------------------------------------
wf = ROOT / ".github" / "workflows" / "linkedin-export-sync.yml"
backup(wf) if wf.exists() else None
wf.write_text(textwrap.dedent("""\
name: LinkedIn Export Sync

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */12 * * *"

jobs:
  sync-linkedin:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      LINKEDIN_COOKIES_JSON: ${{ secrets.LINKEDIN_COOKIES_JSON }}
      LINKEDIN_HEADLESS: "true"
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y xvfb

      - name: Install Python deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install python-calamine xlrd lxml html5lib beautifulsoup4

      - name: Install Playwright Chromium
        run: |
          python -m playwright install chromium

      - name: Install/sanitize cookies
        run: |
          python scripts/install_linkedin_cookies_full.py

      - name: Run LinkedIn export sync
        run: |
          xvfb-run -a python linkedin_export_sync.py

      - name: Import LinkedIn exports
        run: |
          python linkedin_import_exports.py

      - name: Transform LinkedIn exports
        run: |
          python linkedin_transform_exports.py

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: linkedin-export-sync
          path: |
            downloads/linkedin_exports
            data_output/linkedin_exports_json
"""), encoding="utf-8")
print("✅ linkedin-export-sync.yml rewritten for cookie-only cloud mode")

print("✅ LinkedIn cookie-only cloud fix complete")
