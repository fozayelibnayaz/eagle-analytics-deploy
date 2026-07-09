#!/bin/bash
# Install macOS launchd jobs with MORE FREQUENT schedules:
#   - Full pipeline:   4× daily (6am, 12pm, 6pm, 12am)
#   - Rich alerts:     4× daily (9am, 1pm, 5pm, 9pm)
#   - Anomaly check:   every 15 minutes
#   - Attribution:     3× daily (9am, 3pm, 9pm)

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "════════════════════════════════════════════════════════════"
echo "Installing MORE FREQUENT schedulers"
echo "════════════════════════════════════════════════════════════"

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

# ── 1. Full pipeline: 4× daily (every 6 hours) ──
PLIST1="$HOME/Library/LaunchAgents/com.eagle3d.pipeline.plist"
cat > "$PLIST1" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.eagle3d.pipeline</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${PROJECT_DIR}/run_pipeline_local.sh</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_DIR}</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>${PROJECT_DIR}/logs/pipeline.stdout.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_DIR}/logs/pipeline.stderr.log</string>
</dict>
</plist>
PLISTEOF

# ── 2. Rich alerts: 4× daily ──
PLIST2="$HOME/Library/LaunchAgents/com.eagle3d.alerts.plist"
cat > "$PLIST2" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.eagle3d.alerts</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-c</string>
    <string>cd ${PROJECT_DIR} && source venv/bin/activate && python3 rich_alerts_engine.py >> logs/alerts.log 2>&1</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_DIR}</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>${PROJECT_DIR}/logs/alerts.stdout.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_DIR}/logs/alerts.stderr.log</string>
</dict>
</plist>
PLISTEOF

# ── 3. Anomaly detection every 15 minutes ──
PLIST3="$HOME/Library/LaunchAgents/com.eagle3d.anomaly.plist"
cat > "$PLIST3" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.eagle3d.anomaly</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-c</string>
    <string>cd ${PROJECT_DIR} && source venv/bin/activate && python3 anomaly_detector.py >> logs/anomaly.log 2>&1</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_DIR}</string>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>${PROJECT_DIR}/logs/anomaly.stdout.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_DIR}/logs/anomaly.stderr.log</string>
</dict>
</plist>
PLISTEOF

# ── 4. Attribution alerts: 3× daily ──
PLIST4="$HOME/Library/LaunchAgents/com.eagle3d.attribution.plist"
cat > "$PLIST4" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.eagle3d.attribution</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-c</string>
    <string>cd ${PROJECT_DIR} && source venv/bin/activate && python3 -c "from attribution_tracker import send_attribution_alert; send_attribution_alert(1)" >> logs/attribution.log 2>&1</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_DIR}</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>${PROJECT_DIR}/logs/attribution.stdout.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_DIR}/logs/attribution.stderr.log</string>
</dict>
</plist>
PLISTEOF

# Reload all
for LABEL in com.eagle3d.pipeline com.eagle3d.alerts com.eagle3d.anomaly com.eagle3d.attribution; do
    launchctl unload "$HOME/Library/LaunchAgents/${LABEL}.plist" 2>/dev/null || true
    launchctl load   "$HOME/Library/LaunchAgents/${LABEL}.plist"
    echo "  ✅ Loaded: $LABEL"
done

echo ""
echo "════════════════════════════════════════════════════════════"
echo "NEW SCHEDULE:"
echo "  • Full pipeline:      6am, 12pm, 6pm, 12am  (every 6h)"
echo "  • Rich alerts:        9am, 1pm, 5pm, 9pm"
echo "  • Anomaly detection:  every 15 minutes"
echo "  • Attribution alerts: 9:30am, 3:30pm, 9:30pm"
echo ""
echo "Total alerts per day: ~120+ (pipeline runs + anomaly checks + alerts)"
echo "════════════════════════════════════════════════════════════"
