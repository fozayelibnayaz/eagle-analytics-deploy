#!/bin/bash
set -euo pipefail

ROOT="$HOME/eagle3d-kpi-automation"
LOGDIR="$ROOT/logs"
LOCKDIR="$ROOT/.engagement_alerts.lock"

mkdir -p "$LOGDIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] SKIP: engagement alerts already running" >> "$LOGDIR/engagement_alerts.out.log"
  exit 0
fi

cleanup() {
  rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT

cd "$ROOT"
source venv/bin/activate

SCRIPT="$ROOT/engagement_alerts.py"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] START $SCRIPT" >> "$LOGDIR/engagement_alerts.out.log"
python3 "$SCRIPT" >> "$LOGDIR/engagement_alerts.out.log" 2>> "$LOGDIR/engagement_alerts.err.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] END" >> "$LOGDIR/engagement_alerts.out.log"
