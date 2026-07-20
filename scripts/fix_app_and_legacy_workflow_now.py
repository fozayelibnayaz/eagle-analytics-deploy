from pathlib import Path
from datetime import datetime
import re
import textwrap

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.fix_app_and_legacy_workflow.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# ------------------------------------------------------------
# 1) Repair app.py so __future__ stays first and nav helper is safe
# ------------------------------------------------------------
app = ROOT / "app.py"
backup(app)
text = app.read_text(encoding="utf-8", errors="ignore")

# Remove any previously injected _page_href block anywhere
text = re.sub(
    r'\ndef _page_href\(page_key: str, keep_token: bool = True\) -> str:[\s\S]*?return "\?" \+ query\n',
    '\n',
    text,
    flags=re.M
)

helper = textwrap.dedent("""\

def _page_href(page_key: str, keep_token: bool = True) -> str:
    qp = st.query_params
    extras = []

    def _one(v):
        if isinstance(v, list):
            return v[0] if v else ""
        return str(v or "")

    if keep_token:
        for key in ("t", "prd", "cmp"):
            val = _one(qp.get(key, ""))
            if val:
                extras.append(f"{key}={val}")

    query = "&".join([f"page={page_key}"] + extras)
    return "?" + query

""")

# Insert helper AFTER imports, not before __future__
future_line = "from __future__ import annotations"
if future_line in text and "_page_href(page_key" not in text:
    # insert after the streamlit imports block
    anchor = "import streamlit.components.v1 as components"
    if anchor in text:
        text = text.replace(anchor, anchor + helper, 1)
    else:
        # fallback: after future import
        text = text.replace(future_line, future_line + helper, 1)

# Patch nav hrefs safely
text = text.replace(
    'f\'href="?page={k}" target="_top">',
    'f\'href="{_page_href(k)}" target="_self">'
)
text = text.replace(
    'href="?page=dashboard" target="_top"',
    'href="{_page_href(\'dashboard\')}" target="_self"'
)
text = text.replace(
    'f\'<a class="{cls}" href="?page={k}" \'',
    'f\'<a class="{cls}" href="{_page_href(k, keep_token=(k != "_logout"))}" \''
)
text = text.replace('target="top" title="{lbl}"', 'target="_self" title="{lbl}"')
text = text.replace(
    'href="?page=settings" target="_top"',
    'href="{_page_href(\'settings\')}" target="_self"'
)

app.write_text(text, encoding="utf-8")
print("✅ app.py nav helper repaired safely")

# ------------------------------------------------------------
# 2) Rewrite legacy-kpi-sync.yml from scratch, valid YAML
# ------------------------------------------------------------
wf = ROOT / ".github" / "workflows" / "legacy-kpi-sync.yml"
backup(wf) if wf.exists() else None
wf.write_text(textwrap.dedent("""\
name: Legacy KPI Sync

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */6 * * *"

jobs:
  sync-legacy-kpi:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
      KPI_EMAIL: ${{ secrets.KPI_EMAIL }}
      KPI_PASSWORD: ${{ secrets.KPI_PASSWORD }}
      STRIPE_COOKIES_JSON: ${{ secrets.STRIPE_COOKIES_JSON }}
      FORCE_HISTORICAL: "0"
      HEADLESS_MODE: "true"
      PLAYWRIGHT_BROWSERS_PATH: "0"
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

      - name: Restore Stripe cookies from secret
        run: |
          mkdir -p data_output
          python - <<'PY'
import os
from pathlib import Path
raw = os.environ.get("STRIPE_COOKIES_JSON", "").strip()
if not raw:
    raise SystemExit("Missing STRIPE_COOKIES_JSON")
Path("stripe_cookies.json").write_text(raw, encoding="utf-8")
Path("data_output/stripe_cookies.json").write_text(raw, encoding="utf-8")
print("✅ Stripe cookies restored")
PY

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
        env:
          KPI_REBUILD_LOOKBACK_DAYS: "120"
        run: |
          python scripts/fix_daily_kpis_fast.py

      - name: Upload debug artifacts
        uses: actions/upload-artifact@v4
        with:
          name: legacy-kpi-sync
          path: |
            data_output/debug
            data_output/debug_stripe_last.png
            data_output/debug_stripe_nav.png
            data_output/debug_stripe_stale.png
"""), encoding="utf-8")
print("✅ legacy-kpi-sync.yml rewritten cleanly")
