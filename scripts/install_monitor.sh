#!/usr/bin/env bash
# Install the TraderSkill 5-minute monitor as a macOS launchd job (no AI, no notifications).
# Run from the TraderSkill folder:   bash scripts/install_monitor.sh
# Remove:                            bash scripts/install_monitor.sh --uninstall
set -eu
LABEL="com.traderskill.monitor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Monitor removed."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/trader-data/reports"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>$REPO/scripts/monitor.py</string><string>--data</string><string>$REPO/trader-data</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>300</integer>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>$REPO/trader-data/reports/monitor.out.log</string>
  <key>StandardErrorPath</key><string>$REPO/trader-data/reports/monitor.err.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Monitor installed: runs every 5 minutes, acts only during NSE/NYSE hours, paper trades only."
echo "Optional for US prices: python3 -m pip install --user yfinance"
echo "India prices: run 'kite auth login' each morning."
