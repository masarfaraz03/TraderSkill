#!/usr/bin/env bash
# TraderSkill one-click Mac setup — double-click this file in Finder.
# 1) installs Zerodha's official kite CLI (if missing)
# 2) installs yfinance for US prices
# 3) installs the 5-minute paper-trade monitor (launchd, no AI, no notifications)
# 4) starts `kite auth login` — YOU type your Zerodha ID, password and 2FA (never stored by TraderSkill)
set -u
cd "$(dirname "$0")/.." || exit 1
echo "== TraderSkill setup in: $(pwd)"

if ! command -v kite >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/kite" ]; then
  echo "== Installing Zerodha kite CLI (official installer, checksum-verified)"
  curl -fsSL https://raw.githubusercontent.com/zerodha/kite-cli/main/scripts/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "== Installing yfinance (US prices for the monitor)"
python3 -m pip install --user --quiet yfinance || echo "   (yfinance install failed — US auto-checks will fall back to hourly AI check-ins)"

echo "== Installing the 5-minute monitor"
bash scripts/install_monitor.sh

if kite --json doctor 2>/dev/null | grep -q '"ok": *true'; then
  echo "== Kite is already signed in for today."
else
  echo "== Sign in to Zerodha (type your own ID, password and 2FA below):"
  kite auth login
fi
echo
echo "Done. You can close this window. Repeat only 'kite auth login' each morning (Zerodha sessions expire daily)."
read -r -p "Press Enter to close..." _
