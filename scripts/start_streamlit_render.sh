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
text += "\n[ga4_service_account]\n"
for k, v in data.items():
    if isinstance(v, str):
        text += f'{k} = "{v.replace(chr(34), chr(92)+chr(34))}"\n'
    elif isinstance(v, bool):
        text += f"{k} = {'true' if v else 'false'}\n"
    else:
        text += f"{k} = {json.dumps(v)}\n"
p.write_text(text, encoding="utf-8")
print("GA4 service account written to secrets.toml")
PY
fi

echo "== Render Streamlit startup =="
echo "APP_PASSWORD_PRESENT=$([ -n "${APP_PASSWORD:-}" ] && echo yes || echo no)"
echo "MONGO_URI_PRESENT=$([ -n "${MONGO_URI:-}" ] && echo yes || echo no)"
echo "GA4_PROPERTY_ID_PRESENT=$([ -n "${GA4_PROPERTY_ID:-}" ] && echo yes || echo no)"
echo "GA4_SERVICE_ACCOUNT_JSON_PRESENT=$([ -n "${GA4_SERVICE_ACCOUNT_JSON:-}" ] && echo yes || echo no)"

exec streamlit run app.py   --server.port "$PORT"   --server.address 0.0.0.0   --server.headless true   --browser.gatherUsageStats false
