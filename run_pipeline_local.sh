#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# run_pipeline_local.sh — Eagle 3D Streaming Analytics Hub
# Runs the full daily pipeline LOCALLY on MacBook (MongoDB only)
# ═══════════════════════════════════════════════════════════════

set -e
cd "$(dirname "$0")"

# ── Colors ──
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"; }
ok()  { echo -e "${GREEN}✅ $1${NC}"; }
err() { echo -e "${RED}❌ $1${NC}"; }
warn(){ echo -e "${YELLOW}⚠️  $1${NC}"; }

# ── Pre-flight ──
log "Pre-flight checks..."

# 1. venv
if [ ! -d "venv" ]; then
    err "venv/ not found. Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
source venv/bin/activate
ok "venv activated ($(python3 --version))"

# 2. MongoDB
if ! pgrep -x "mongod" > /dev/null 2>&1; then
    warn "MongoDB not running — starting..."
    brew services start mongodb-community@7.0 || {
        err "Failed to start MongoDB. Install: brew tap mongodb/brew && brew install mongodb-community@7.0"
        exit 1
    }
    sleep 3
fi

python3 -c "
from mongo_client import get_mongo_status
s = get_mongo_status()
if not s['connected']:
    print('❌ MongoDB unreachable:', s.get('message'))
    exit(1)
print(f'✅ MongoDB: db={s[\"db\"]} | {s[\"collections\"]} collections | {s[\"daily_kpis_count\"]:,} daily rows')
"

# 3. logs dir
mkdir -p logs
LOG_FILE="logs/pipeline_$(date +%Y%m%d_%H%M%S).log"

# ── Run pipeline ──
echo ""
log "Starting pipeline (log: $LOG_FILE)"
echo "═══════════════════════════════════════════════════════════════"

python3 daily_pipeline.py 2>&1 | tee "$LOG_FILE"
RC=${PIPESTATUS[0]}

echo "═══════════════════════════════════════════════════════════════"
if [ $RC -eq 0 ]; then
    ok "Pipeline completed successfully"
else
    err "Pipeline exited with code $RC — see $LOG_FILE"
fi

# ── Cleanup old logs (keep last 30) ──
ls -1t logs/pipeline_*.log 2>/dev/null | tail -n +31 | xargs -I {} rm -f {} 2>/dev/null

exit $RC
