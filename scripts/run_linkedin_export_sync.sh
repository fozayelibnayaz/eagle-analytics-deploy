#!/bin/bash
set -euo pipefail

ROOT="$HOME/eagle3d-kpi-automation"
LOGDIR="$ROOT/logs"
LOCKDIR="$ROOT/.linkedin_export_sync.lock"

mkdir -p "$LOGDIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] SKIP: linkedin export sync already running" >> "$LOGDIR/linkedin_export_sync.out.log"
  exit 0
fi

cleanup() {
  rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT

cd "$ROOT"
source venv/bin/activate

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START linkedin_export_sync.py" >> "$LOGDIR/linkedin_export_sync.out.log"
set +e
python3 linkedin_export_sync.py >> "$LOGDIR/linkedin_export_sync.out.log" 2>> "$LOGDIR/linkedin_export_sync.err.log"
EXPORT_STATUS=$?
set -e

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START linkedin_import_exports.py" >> "$LOGDIR/linkedin_export_sync.out.log"
set +e
python3 linkedin_import_exports.py >> "$LOGDIR/linkedin_export_sync.out.log" 2>> "$LOGDIR/linkedin_export_sync.err.log"
IMPORT_STATUS=$?
set -e

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START linkedin_transform_exports.py" >> "$LOGDIR/linkedin_export_sync.out.log"
set +e
python3 linkedin_transform_exports.py >> "$LOGDIR/linkedin_export_sync.out.log" 2>> "$LOGDIR/linkedin_export_sync.err.log"
TRANSFORM_STATUS=$?
set -e

echo "[$(date '+%Y-%m-%d %H:%M:%S')] END" >> "$LOGDIR/linkedin_export_sync.out.log"

if [ "$EXPORT_STATUS" -ne 0 ] && [ "$IMPORT_STATUS" -ne 0 ] && [ "$TRANSFORM_STATUS" -ne 0 ]; then
  exit 1
fi
