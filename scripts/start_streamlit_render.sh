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
SECRETS

echo "== Render Streamlit startup =="
echo "Wrote .streamlit/secrets.toml from env"
echo "MONGO_DB=${MONGO_DB:-eagle3d}"
echo "APP_PASSWORD_PRESENT=$([ -n "${APP_PASSWORD:-}" ] && echo yes || echo no)"
echo "MONGO_URI_PRESENT=$([ -n "${MONGO_URI:-}" ] && echo yes || echo no)"

exec streamlit run app.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
