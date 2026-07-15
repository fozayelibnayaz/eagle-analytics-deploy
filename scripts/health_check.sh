#!/bin/bash
set -euo pipefail

ROOT="$HOME/eagle3d-kpi-automation"
cd "$ROOT"
source venv/bin/activate

echo "== FILES =="
ls -l scripts/run_linkedin_export_sync.sh scripts/run_engagement_alerts.sh 2>/dev/null || true

echo
echo "== LAUNCHD STATUS: linkedin export sync =="
launchctl print "gui/$(id -u)/com.eagle3d.linkedin-export-sync" 2>/dev/null | sed -n '1,80p' || echo "not loaded"

echo
echo "== LAUNCHD STATUS: engagement alerts =="
launchctl print "gui/$(id -u)/com.eagle3d.engagement" 2>/dev/null | sed -n '1,80p' || echo "not loaded"

echo
echo "== RECENT LOGS: linkedin export sync =="
tail -n 40 logs/linkedin_export_sync.out.log 2>/dev/null || true
tail -n 40 logs/linkedin_export_sync.err.log 2>/dev/null || true

echo
echo "== RECENT LOGS: engagement alerts =="
tail -n 40 logs/engagement_alerts.out.log 2>/dev/null || true
tail -n 40 logs/engagement_alerts.err.log 2>/dev/null || true

echo
echo "== MONGO SNAPSHOT CHECK =="
python3 - <<'PY'
from datetime import datetime
from mongo_client import find_all

def show_latest(name, sort_field):
    rows = find_all(name, sort=[(sort_field, -1)], limit=1)
    print(name, "->", rows[0] if rows else "NONE")

show_latest("linkedin_highlights_daily", "snapshot_date")
show_latest("linkedin_updates_metrics_daily", "snapshot_date")
show_latest("engagement_snapshots", "saved_at")
PY

echo
echo "✅ health check completed"
