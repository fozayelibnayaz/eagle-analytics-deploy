from pathlib import Path
from datetime import datetime
import textwrap

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.render_workflow_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# ------------------------------------------------------------------
# Fix scripts/start_streamlit_render.sh
# ------------------------------------------------------------------
ss = ROOT / "scripts" / "start_streamlit_render.sh"
backup(ss) if ss.exists() else None
ss.write_text(textwrap.dedent("""\
    #!/bin/bash
    set -euo pipefail

    ROOT="$(cd "$(dirname "$0")/.." && pwd)"
    cd "$ROOT"

    mkdir -p .streamlit

    cat > .streamlit/secrets.toml <<SECRETS
    APP_PASSWORD = "${APP_PASSWORD:-}"
    MONGO_URI = "${MONGO_URI:-}"
    MONGO_DB = "${MONGO_DB:-eagle3d}"
    TELEGRAM_BOT_TOKEN = "${TELEGRAM_BOT_TOKEN:-}"
    TELEGRAM_CHAT_ID = "${TELEGRAM_CHAT_ID:-}"
    YOUTUBE_API_KEY = "${YOUTUBE_API_KEY:-}"
    YOUTUBE_CHANNEL_ID = "${YOUTUBE_CHANNEL_ID:-}"
    WEBHOOK_API_KEY = "${WEBHOOK_API_KEY:-}"
    GA4_PROPERTY_ID = "${GA4_PROPERTY_ID:-}"
    SECRETS

    if [ -n "${GA4_SERVICE_ACCOUNT_JSON:-}" ]; then
    python3 - <<'PY'
import json
import os
from pathlib import Path

raw = os.environ.get("GA4_SERVICE_ACCOUNT_JSON", "").strip()
if not raw:
    raise SystemExit(0)

try:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("GA4_SERVICE_ACCOUNT_JSON is not a JSON object")
except Exception as e:
    print(f"WARNING: invalid GA4_SERVICE_ACCOUNT_JSON, skipping injection: {e}")
    raise SystemExit(0)

p = Path(".streamlit/secrets.toml")
text = p.read_text(encoding="utf-8")
text += "\\n[ga4_service_account]\\n"
for k, v in data.items():
    if isinstance(v, str):
        text += f'{k} = "{v.replace(chr(34), chr(92)+chr(34))}"\\n'
    elif isinstance(v, bool):
        text += f"{k} = {'true' if v else 'false'}\\n"
    else:
        text += f"{k} = {json.dumps(v)}\\n"
p.write_text(text, encoding="utf-8")
print("GA4 service account written to secrets.toml")
PY
    fi

    echo "== Render Streamlit startup =="
    echo "APP_PASSWORD_PRESENT=$([ -n "${APP_PASSWORD:-}" ] && echo yes || echo no)"
    echo "MONGO_URI_PRESENT=$([ -n "${MONGO_URI:-}" ] && echo yes || echo no)"
    echo "GA4_PROPERTY_ID_PRESENT=$([ -n "${GA4_PROPERTY_ID:-}" ] && echo yes || echo no)"
    echo "GA4_SERVICE_ACCOUNT_JSON_PRESENT=$([ -n "${GA4_SERVICE_ACCOUNT_JSON:-}" ] && echo yes || echo no)"

    exec streamlit run app.py \
      --server.port "$PORT" \
      --server.address 0.0.0.0 \
      --server.headless true \
      --browser.gatherUsageStats false
"""), encoding="utf-8")
ss.chmod(0o755)
print("✅ scripts/start_streamlit_render.sh rewritten safely")

# ------------------------------------------------------------------
# Add scripts/send_telegram_test.py
# ------------------------------------------------------------------
stt = ROOT / "scripts" / "send_telegram_test.py"
stt.write_text(textwrap.dedent("""\
    import json
    import os
    import urllib.request

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    payload = json.dumps({
        "chat_id": chat_id,
        "text": "✅ GitHub manual workflow heartbeat reached Telegram.",
        "parse_mode": "Markdown",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
        print(body)
        if not body.get("ok"):
            raise SystemExit("Telegram send failed")
"""), encoding="utf-8")
print("✅ scripts/send_telegram_test.py created")

# ------------------------------------------------------------------
# Add KPI rebuild workflow
# ------------------------------------------------------------------
kpi = ROOT / ".github" / "workflows" / "kpi-rebuild.yml"
kpi.write_text(textwrap.dedent("""\
    name: KPI Rebuild

    on:
      workflow_dispatch:
      schedule:
        - cron: "15 * * * *"

    jobs:
      rebuild:
        runs-on: ubuntu-latest
        timeout-minutes: 20
        env:
          MONGO_URI: ${{ secrets.MONGO_URI }}
          MONGO_DB: ${{ secrets.MONGO_DB }}
        steps:
          - uses: actions/checkout@v4

          - name: Set up Python
            uses: actions/setup-python@v5
            with:
              python-version: "3.11"

          - name: Install deps
            run: |
              python -m pip install --upgrade pip
              pip install -r requirements.txt

          - name: Rebuild daily_kpis
            run: |
              python scripts/fix_daily_kpis_safe.py
"""), encoding="utf-8")
print("✅ .github/workflows/kpi-rebuild.yml created")

# ------------------------------------------------------------------
# Patch engagement-alerts.yml with manual heartbeat
# ------------------------------------------------------------------
eaw = ROOT / ".github" / "workflows" / "engagement-alerts.yml"
if eaw.exists():
    backup(eaw)
    txt = eaw.read_text(encoding="utf-8", errors="ignore")
    if "send_telegram_test.py" not in txt:
        insert_after = """      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install python-calamine xlrd lxml html5lib beautifulsoup4
"""
        addition = """      - name: Telegram heartbeat on manual dispatch
        if: github.event_name == 'workflow_dispatch'
        run: |
          python scripts/send_telegram_test.py
"""
        if insert_after in txt:
            txt = txt.replace(insert_after, insert_after + addition)
            eaw.write_text(txt, encoding="utf-8")
            print("✅ engagement-alerts.yml patched with manual heartbeat")
        else:
            print("WARN: could not find Install deps block in engagement-alerts.yml")
else:
    print("WARN: .github/workflows/engagement-alerts.yml not found")

print("✅ render/workflow hotfix complete")
