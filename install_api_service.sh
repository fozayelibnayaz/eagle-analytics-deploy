#!/bin/bash
# Install macOS launchd service for FastAPI server
# - Auto-starts on Mac boot
# - Auto-restarts if it crashes
# - Logs to logs/api_server.log

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
PLIST="$HOME/Library/LaunchAgents/com.eagle3d.api.plist"

mkdir -p "$PROJECT_DIR/logs"

cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.eagle3d.api</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>cd ${PROJECT_DIR} && source venv/bin/activate && python3 api_server.py</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${PROJECT_DIR}/logs/api_server.stdout.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_DIR}/logs/api_server.stderr.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✅ API service installed"
echo ""
echo "The API server will now:"
echo "  • Start automatically when your Mac boots"
echo "  • Auto-restart within seconds if it crashes"
echo "  • Log to: logs/api_server.stdout.log + stderr.log"
echo ""
echo "Manual controls:"
echo "  launchctl unload $PLIST   # stop"
echo "  launchctl load   $PLIST   # start"
echo "  launchctl list | grep eagle3d.api"
echo ""
echo "URL: http://localhost:8000/docs"
