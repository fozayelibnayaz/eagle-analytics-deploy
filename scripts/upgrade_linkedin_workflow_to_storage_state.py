from pathlib import Path
from datetime import datetime
import textwrap

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.linkedin_storage_state_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# 1) write a restore script
rs = ROOT / "scripts" / "restore_linkedin_auth_files.py"
rs.write_text(textwrap.dedent("""\
from pathlib import Path
import os

Path("data").mkdir(exist_ok=True)
Path("data_output").mkdir(exist_ok=True)

cookies = os.environ.get("LINKEDIN_COOKIES_JSON", "").strip()
state = os.environ.get("LINKEDIN_STORAGE_STATE_JSON", "").strip()

if state:
    Path("data/linkedin_session_state.json").write_text(state, encoding="utf-8")
    Path("data_output/linkedin_session_state.json").write_text(state, encoding="utf-8")
    print("✅ Restored LinkedIn storage state from secret")

if cookies:
    Path("data/linkedin_cookies.json").write_text(cookies, encoding="utf-8")
    Path("data_output/linkedin_cookies.json").write_text(cookies, encoding="utf-8")
    print("✅ Restored LinkedIn cookies from secret")

if not state and not cookies:
    raise SystemExit("❌ Neither LINKEDIN_STORAGE_STATE_JSON nor LINKEDIN_COOKIES_JSON is set")
"""), encoding="utf-8")
print("✅ scripts/restore_linkedin_auth_files.py written")

# 2) rewrite workflow
wf = ROOT / ".github" / "workflows" / "linkedin-export-sync.yml"
backup(wf)
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
      LINKEDIN_STORAGE_STATE_JSON: ${{ secrets.LINKEDIN_STORAGE_STATE_JSON }}
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

      - name: Restore LinkedIn auth files
        run: |
          python scripts/restore_linkedin_auth_files.py

      - name: Install/sanitize cookies
        if: env.LINKEDIN_COOKIES_JSON != ''
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
            logs/linkedin_export_sync.out.log
            logs/linkedin_export_sync.err.log
"""), encoding="utf-8")
print("✅ linkedin-export-sync.yml upgraded to storage_state + cookies fallback")
