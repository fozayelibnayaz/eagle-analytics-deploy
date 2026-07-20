from pathlib import Path
from datetime import datetime

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.legacy_sync_speed_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# ------------------------------------------------------------
# 1) Make scrape_stripe.py configurable by env
# ------------------------------------------------------------
stripe = ROOT / "scrape_stripe.py"
if stripe.exists():
    backup(stripe)
    text = stripe.read_text(encoding="utf-8", errors="ignore")

    text = text.replace(
        "MAX_PAGES = 50",
        'MAX_PAGES = int(os.environ.get("STRIPE_MAX_PAGES", "20"))'
    )
    text = text.replace(
        "PAGE_LOAD_WAIT = 6000  # ms",
        'PAGE_LOAD_WAIT = int(os.environ.get("STRIPE_PAGE_LOAD_WAIT_MS", "4000"))  # ms'
    )
    text = text.replace(
        "INITIAL_LOAD_WAIT = 12000  # ms — Stripe React app needs time to hydrate",
        'INITIAL_LOAD_WAIT = int(os.environ.get("STRIPE_INITIAL_LOAD_WAIT_MS", "9000"))  # ms'
    )

    stripe.write_text(text, encoding="utf-8")
    print("✅ scrape_stripe.py patched for env-based speed controls")
else:
    print("WARN: scrape_stripe.py not found")

# ------------------------------------------------------------
# 2) Rewrite Cloud Legacy Data Sync workflow
# ------------------------------------------------------------
wf = ROOT / ".github" / "workflows" / "cloud-legacy-data-sync.yml"
backup(wf)
wf.write_text("""name: Cloud Legacy Data Sync

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */6 * * *"

concurrency:
  group: cloud-legacy-data-sync
  cancel-in-progress: false

jobs:
  sync_legacy_data:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
      KPI_EMAIL: ${{ secrets.KPI_EMAIL }}
      KPI_PASSWORD: ${{ secrets.KPI_PASSWORD }}
      STRIPE_COOKIES_JSON: ${{ secrets.STRIPE_COOKIES_JSON }}
      FORCE_HISTORICAL: "0"
      HEADLESS_MODE: "true"
      PLAYWRIGHT_BROWSERS_PATH: "0"
      STRIPE_MAX_PAGES: "20"
      STRIPE_PAGE_LOAD_WAIT_MS: "4000"
      STRIPE_INITIAL_LOAD_WAIT_MS: "9000"
      KPI_REBUILD_LOOKBACK_DAYS: "120"

    steps:
      - name: Checkout
        uses: actions/checkout@v4

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

      - name: Restore Stripe cookies
        run: |
          python scripts/restore_stripe_cookies.py

      - name: Scrape KPI dashboard
        run: |
          xvfb-run -a python scrape_kpi.py

      - name: Scrape Stripe dashboard
        run: |
          xvfb-run -a python scrape_stripe.py

      - name: Process raw data into signups/uploads/payments
        run: |
          python scripts/run_process_data_pipeline.py

      - name: Rebuild daily_kpis fast
        run: |
          python scripts/fix_daily_kpis_fast.py

      - name: Upload debug artifacts (non-blocking)
        if: always()
        continue-on-error: true
        uses: actions/upload-artifact@v4
        with:
          name: cloud-legacy-data-sync
          if-no-files-found: ignore
          path: |
            data_output/debug
            data_output/debug_stripe_last.png
            data_output/debug_stripe_nav.png
            data_output/debug_stripe_stale.png
""", encoding="utf-8")
print("✅ cloud-legacy-data-sync.yml rewritten for timeout/speed/reliability")
