#!/bin/bash
set -euo pipefail

ROOT="$HOME/eagle3d-kpi-automation"
LOGDIR="$ROOT/logs"
LOCKDIR="$ROOT/.linkedin_refresh.lock"

mkdir -p "$LOGDIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] SKIP: linkedin refresh already running" >> "$LOGDIR/linkedin_refresh.out.log"
  exit 0
fi

cleanup() {
  rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT

cd "$ROOT"
source venv/bin/activate

TMP_OUT="$(mktemp)"
TMP_ERR="$(mktemp)"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START linkedin_daily_pipeline.py (cookies-only mode)" >> "$LOGDIR/linkedin_refresh.out.log"

set +e
python3 linkedin_daily_pipeline.py > "$TMP_OUT" 2> "$TMP_ERR"
PY_STATUS=$?
set -e

cat "$TMP_OUT" >> "$LOGDIR/linkedin_refresh.out.log"
cat "$TMP_ERR" >> "$LOGDIR/linkedin_refresh.err.log"

if grep -qiE "Scrape error:|Login redirect:|Browser setup failed:|Could not launch LinkedIn" "$TMP_OUT" "$TMP_ERR"; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: LinkedIn refresh detected scrape/login failure" >> "$LOGDIR/linkedin_refresh.err.log"
  rm -f "$TMP_OUT" "$TMP_ERR"
  exit 1
fi

if [ "$PY_STATUS" -ne 0 ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: linkedin_daily_pipeline.py exited with status $PY_STATUS" >> "$LOGDIR/linkedin_refresh.err.log"
  rm -f "$TMP_OUT" "$TMP_ERR"
  exit "$PY_STATUS"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] END" >> "$LOGDIR/linkedin_refresh.out.log"
rm -f "$TMP_OUT" "$TMP_ERR"
