#!/bin/bash
# Install macOS launchd service to keep ngrok running 24/7
# Auto-starts on boot + auto-restarts if crashed

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
PLIST="$HOME/Library/LaunchAgents/com.eagle3d.ngrok.plist"

mkdir -p "$PROJECT_DIR/logs"

NGROK_BIN=$(which ngrok)
if [ -z "$NGROK_BIN" ]; then
    echo "❌ ngrok not found in PATH. Install with: brew install ngrok"
    exit 1
fi

cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.eagle3d.ngrok</string>
  <key>ProgramArguments</key>
  <array>
    <string>${NGROK_BIN}</string>
    <string>http</string>
    <string>8000</string>
    <string>--log</string>
    <string>stdout</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${PROJECT_DIR}/logs/ngrok.stdout.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_DIR}/logs/ngrok.stderr.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✅ ngrok service installed and started"
echo ""
echo "Manage:"
echo "  launchctl list | grep eagle3d.ngrok"
echo "  launchctl unload $PLIST   # stop"
echo "  launchctl load   $PLIST   # start"
echo ""
echo "Logs: tail -f logs/ngrok.stdout.log"
echo ""
echo "Get current public URL:"
echo "  curl -s http://127.0.0.1:4040/api/tunnels | python3 -c \"import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])\""
