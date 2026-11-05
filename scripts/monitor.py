#!/usr/bin/env python3
"""TraderSkill local 5-minute monitor — no AI, no notifications, paper trades only.

Runs on the user's own computer (launchd/cron every 5 minutes). During each market's hours it
fetches prices for open PAPER positions and closes any that hit their stop or target, writing one
line per action to trader-data/reports/<date>.<IN|US>.log. Outside market hours it exits at once.

It never places, modifies or cancels a live order and never moves money: live positions are only
logged as alerts for the next AI check-in / report.

Prices (read-only):
  India: Zerodha `kite --json market ltp NSE:SYMBOL` (needs `kite auth login` each morning)
  US:    yfinance (pip install yfinance) — stocks/ETFs/crypto like AMD, SPY, BTC-USD

Usage:  monitor.py --data trader-data [--force]     (--force ignores market hours, for testing)
Install as a 5-minute job:  scripts/install_monitor.sh
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger import load, save, pnl_of, now  # noqa: E402

MARKETS = {
    "IN": {"tz": "Asia/Kolkata", "open": time(9, 15), "close": time(15, 30), "mis_cutoff": time(15, 15)},
    "US": {"tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "mis_cutoff": time(15, 55)},
}


def market_open(mkt, force=False):
    m = MARKETS[mkt]
    t = datetime.now(ZoneInfo(m["tz"]))
    if force:
        return True, t
    return (t.weekday() < 5 and m["open"] <= t.time() <= m["close"]), t


def prices_in(symbols):
    if not symbols:
        return {}
    try:
        out = subprocess.run(["kite", "--json", "market", "ltp", *symbols], capture_output=True, text=True, timeout=30)
        data = json.loads(out.stdout or "{}")
    except Exception:
        return {}
    if isinstance(data, dict) and data.get("ok") is False:
        return {}
    res = {}
    for s in symbols:
        v = data.get(s) if isinstance(data, dict) else None
        if isinstance(v, dict) and "last_price" in v:
            res[s] = float(v["last_price"])
    return res


def prices_us(symbols):
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}
    res = {}
    for s in symbols:
        try:
            h = yf.Ticker(s).history(period="1d", interval="1m")
            if len(h):
                res[s] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    return res


def log(data, mkt, local_now, msg):
    d = os.path.join(data, "reports")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{local_now.date().isoformat()}.{mkt}.log"), "a") as f:
        f.write(f"{local_now.strftime('%H:%M')} {msg}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="trader-data")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    lp = os.path.join(a.data, "ledger.json")
    if not os.path.exists(lp):
        return
    for mkt in ("IN", "US"):
        is_open, t = market_open(mkt, a.force)
        if not is_open:
            continue
        d = load(lp)
        opens = [x for x in d["trades"] if x["status"] == "open" and x["market"] == mkt]
        if not opens:
            continue
        syms = sorted({x["symbol"] for x in opens})
        px = prices_in(syms) if mkt == "IN" else prices_us(syms)
        if not px:
            log(a.data, mkt, t, "no price source available (kite not signed in / yfinance missing) — skipped")
            continue
        changed = False
        for x in opens:
            p = px.get(x["symbol"])
            if p is None:
                continue
            buy = x["side"] == "buy"
            hit = None
            if x.get("stop") is not None and ((buy and p <= x["stop"]) or (not buy and p >= x["stop"])):
                hit = "stop"
            elif x.get("target") is not None and ((buy and p >= x["target"]) or (not buy and p <= x["target"])):
                hit = "target"
            elif x["horizon"] == "day" and t.time() >= MARKETS[mkt]["mis_cutoff"]:
                hit = "day-trade cutoff"
            if not hit:
                continue
            if x["mode"] != "paper":
                log(a.data, mkt, t, f"ALERT live {x['id']} {x['symbol']} reached {hit} at {p} — not touched (live orders need the user)")
                continue
            pnl = pnl_of(x, p)
            x.update({"status": "closed", "exit": p, "closed": now(), "pnl": round(pnl, 2),
                      "r_multiple": round(pnl / x["risk"], 2) if x.get("risk") else None,
                      "note": f"Auto-closed by 5-min monitor: {hit} at {p}. Post-mortem pending at next check-in.",
                      "plan_followed": True, "exit_fees": 0.0})
            changed = True
            log(a.data, mkt, t, f"closed {x['id']} {x['symbol']} at {p} ({hit}) P&L {pnl:+.2f}")
        if changed:
            save(lp, d)


if __name__ == "__main__":
    main()
