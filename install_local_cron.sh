#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# install_local_cron.sh — Install macOS launchd job to run the
# pipeline twice daily (9am + 9pm local time)
# ═══════════════════════════════════════════════════════════════

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
PLIST_NAME="com.eagle3d.pipeline"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "═══════════════════════════════════════════════════════════════"
echo "Installing scheduled pipeline (macOS launchd)"
echo "Project: $PROJECT_DIR"
echo "═══════════════════════════════════════════════════════════════"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/logs"

cat > "$PLIST_PATH" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_NAME}</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${PROJECT_DIR}/run_pipeline_local.sh</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>

  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key><integer>9</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key><integer>21</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
  </array>

  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/logs/launchd.stdout.log</string>

  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/logs/launchd.stderr.log</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLISTEOF

# Unload if already loaded
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Load new
launchctl load "$PLIST_PATH"

echo "✅ Scheduled job installed: $PLIST_NAME"
echo "   Runs at: 09:00 and 21:00 daily (local time)"
echo "   Logs:    $PROJECT_DIR/logs/"
echo ""
echo "Manage with:"
echo "  launchctl list | grep eagle3d"
echo "  launchctl unload $PLIST_PATH   # to disable"
echo "  launchctl load   $PLIST_PATH   # to re-enable"
echo ""
echo "Run once manually:"
echo "  ./run_pipeline_local.sh"
