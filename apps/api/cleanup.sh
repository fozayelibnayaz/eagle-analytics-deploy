#!/bin/bash
# Cleanup script for eagle3d-kpi-automation

echo "=== EAGLE3D KPI CLEANUP ==="
echo "Current size: $(du -sh . | cut -f1)"

# 1. Remove Chrome browser cache (4GB) - MAIN CULPRIT
echo "Removing stripe_session (Chrome cache)..."
rm -rf stripe_session/

# 2. Remove browser session caches
echo "Removing browser_session*..."
rm -rf browser_session browser_session_fresh browser_session_new

# 3. Remove virtual environment (recreate after)
echo "Removing venv..."
rm -rf venv/

# 4. Remove duplicate disposable domains in data_output
echo "Removing duplicate disposable_domains.txt in data_output..."
rm -f data_output/disposable_domains.txt

# 5. Remove backup files (keep only last 2 app.py backups)
echo "Removing old backup files..."
ls -t app.py.backup_* 2>/dev/null | tail -n +3 | xargs rm -f 2>/dev/null
ls -t dashboard.py.backup_* 2>/dev/null | tail -n +3 | xargs rm -f 2>/dev/null
rm -f *.b64 v83_*.b64 update_v*.b64

# 6. Remove deploy backup directories
rm -rf _deploy_backup_* _safe_backup/

# 7. Clean __pycache__ and .pytest_cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null

echo "=== DONE ==="
echo "New size: $(du -sh . | cut -f1)"
echo ""
echo "To restore: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
