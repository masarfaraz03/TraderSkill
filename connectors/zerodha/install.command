#!/usr/bin/env bash
# TraderSkill Zerodha connector — one-time install on your Mac (double-click).
# 1) installs the `cryptography` package, 2) makes your login keys, 3) adds the "zerodha"
# local connector to the Claude desktop app. Asks for nothing secret.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
ROOT="$(cd ../.. && pwd)"
DATA="$ROOT/trader-data"

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$c" ] && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3.9+ not found. Install Xcode Command Line Tools: xcode-select --install"; read -r -p "Enter to close"; exit 1; }
echo "Using $PY ($("$PY" --version))"

if ! "$PY" -c 'import cryptography' 2>/dev/null; then
  echo "Installing cryptography…"
  "$PY" -m pip install --user --quiet cryptography || "$PY" -m pip install --user --quiet --break-system-packages cryptography
fi

TRADERSKILL_DATA="$DATA" "$PY" "$HERE/keys.py" init

CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
mkdir -p "$(dirname "$CFG")"
[ -f "$CFG" ] && cp "$CFG" "$CFG.bak-$(date +%Y%m%d%H%M%S)"
"$PY" - "$CFG" "$PY" "$HERE/server.py" "$DATA" <<'EOF'
import json, os, sys
cfg, py, server, data = sys.argv[1:]
c = {}
if os.path.exists(cfg):
    try:
        c = json.load(open(cfg))
    except ValueError:
        sys.exit("Your claude_desktop_config.json isn't valid JSON — fix it first (a backup was made).")
c.setdefault("mcpServers", {})["zerodha"] = {"command": py, "args": [server], "env": {"TRADERSKILL_DATA": data}}
json.dump(c, open(cfg, "w"), indent=2)
print("Added the 'zerodha' connector to Claude desktop.")
EOF

echo
echo "Quick self-test:"
TRADERSKILL_DATA="$DATA" "$PY" "$HERE/kite_client.py" status || true
echo
echo "Done. Quit and reopen the Claude app so it loads the connector."
echo "Next: follow connectors/zerodha/README.md steps 1-4 (Kite developer app + Supabase secrets)."
read -r -p "Press Enter to close..." _
