#!/usr/bin/env bash
# Double-click each morning to sign in to Zerodha for TraderSkill (you type your own credentials).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if kite --json doctor 2>/dev/null | grep -q '"ok": *true'; then
  echo "Kite is already signed in for today."
else
  kite auth login
fi
read -r -p "Press Enter to close..." _
