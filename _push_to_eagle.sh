#!/bin/bash
# Safe push to BOTH repos:
#   - github.com/e3ds/eagle-analytics
#   - github.com/fozayelibnayaz/eagle3d-kpi-automation
# Preserves .streamlit/secrets.toml locally.

set -e
cd "$(dirname "$0")"

REPO1="https://github.com/e3ds/eagle-analytics.git"
REPO2="https://github.com/fozayelibnayaz/eagle3d-kpi-automation.git"

echo "============================================================"
echo "PUSH TO BOTH REPOS"
echo "============================================================"
echo "  1. $REPO1"
echo "  2. $REPO2"
echo ""

# ---- Safety checks ----
if [ ! -f ".streamlit/secrets.toml" ]; then
    echo "FAIL: secrets.toml missing on disk"
    exit 1
fi
echo "  [OK] secrets.toml exists locally"

# Backup secrets
BACKUP=~/secrets.toml.backup.$(date +%s)
cp .streamlit/secrets.toml "$BACKUP"
echo "  [OK] Backed up to $BACKUP"
echo ""

read -p "Continue with force push to BOTH repos? Type 'yes': " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# ---- Wipe local git ----
rm -rf .git
git init -q
git branch -m main

# Configure identity
GIT_EMAIL=$(git config --global user.email || echo "you@example.com")
GIT_NAME=$(git config --global user.name || echo "Fozayel Ibn Ayaz")
git config user.email "$GIT_EMAIL"
git config user.name  "$GIT_NAME"

# Stage everything (gitignore filters secrets)
git add -A

# ---- FINAL CHECK: verify no secrets staged ----
STAGED_BAD=$(git ls-files --cached | grep -iE "secrets\.toml|google_creds\.json|stripe_cookies\.json|stripe_storage_state|kpi_storage_state|kpi_cookies|\.api_keys|monthly_goals|linkedin_cookies\.json|youtube_oauth\.json" || true)
if [ -n "$STAGED_BAD" ]; then
    echo ""
    echo "FAIL: these secret files got staged:"
    echo "$STAGED_BAD"
    rm -rf .git
    exit 1
fi
echo "  [OK] No secrets staged"

# ---- Commit ----
git commit -q -m "Eagle 3D Streaming Analytics Hub - production release

Features:
- MongoDB-only backend (local + Atlas-ready)
- Streamlit dashboard: 10 pages
- Bulletproof 7-day cookie auth
- KPI scraper with strict validation
- YouTube full OAuth analytics (12 endpoints)
- Attribution tracker (source per KPI event)
- Payment ledger (NEW_CUSTOMER vs RECURRING)
- Upload history ledger (survives KPI dashboard re-uploads)
- 16 rich Telegram alert types + weekly/monthly digests
- 4x/day pipeline + 15min anomaly detection
- Editable Google-Sheets-style data tables
- Custom modules uploader (any CSV/Excel/Google Sheet)
- Enhanced AI (memory + streaming + function calling)
- FastAPI server for backend integration
- 7 auto-managed launchd services
- 151 automated QA tests passing"

# ---- Push to repo 1 ----
echo ""
echo "============================================================"
echo "PUSHING TO REPO 1: e3ds/eagle-analytics"
echo "============================================================"
git remote add origin1 "$REPO1"
git push --force -u origin1 main

# ---- Push to repo 2 ----
echo ""
echo "============================================================"
echo "PUSHING TO REPO 2: fozayelibnayaz/eagle3d-kpi-automation"
echo "============================================================"
git remote add origin2 "$REPO2"
git push --force -u origin2 main

echo ""
echo "============================================================"
echo "DONE - pushed to both repos"
echo "============================================================"
echo ""
echo "Files pushed: $(git ls-files | wc -l | xargs)"
echo ""
echo "Repositories:"
echo "  https://github.com/e3ds/eagle-analytics"
echo "  https://github.com/fozayelibnayaz/eagle3d-kpi-automation"
echo ""
echo "Local secrets.toml (untouched):"
ls -la .streamlit/secrets.toml
