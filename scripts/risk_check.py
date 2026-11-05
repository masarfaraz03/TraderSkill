#!/usr/bin/env python3
"""Check a proposed order against the user's profile caps.

Prints PASS or FAIL with reasons (and warnings), exit code 0 on PASS, 2 on FAIL.

Example
  risk_check.py --profile profile.json --ledger ledger.json --market IN --asset future \
     --horizon day --symbol "NIFTY NOV FUT" --side buy --qty 75 --price 24100 \
     --stop 24000 --margin 160000
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

CURRENCY = {"US": "USD", "IN": "INR"}
SYM = {"USD": "$", "INR": "₹"}
MICRO_FUTURES = {"MES", "MNQ", "MYM", "M2K", "MBT", "MET", "MGC", "MCL", "SIL", "M6E"}


def m(ccy, x):
    return f"{SYM[ccy]}{x:,.2f}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True)
    p.add_argument("--ledger")
    p.add_argument("--market", choices=["US", "IN"], required=True)
    p.add_argument("--asset", choices=["stock", "option", "future", "crypto"], required=True)
    p.add_argument("--horizon", choices=["day", "swing", "long"], required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--qty", type=float, required=True)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--stop", type=float)
    p.add_argument("--multiplier", type=float, default=1.0, help="100 for US equity options, 5 for MES ...")
    p.add_argument("--margin", type=float, help="margin required (futures)")
    p.add_argument("--option-type", choices=["call", "put", "spread"], help="for options")
    p.add_argument("--max-loss", type=float, help="defined max loss for spreads")
    p.add_argument("--confirmed", action="store_true", help="user confirmed a long-term amount")
    a = p.parse_args()

    prof = json.load(open(a.profile))
    tr, lt = prof["trading"], prof.get("long_term", {})
    ccy = CURRENCY[a.market]
    fails, warns = [], []

    notional = a.qty * a.price * a.multiplier
    capital = a.margin if (a.asset == "future" and a.margin) else notional
    if a.asset == "option" and a.side == "buy":
        capital = notional  # premium paid
    risk = None
    if a.stop is not None:
        risk = abs(a.price - a.stop) * a.qty * a.multiplier
    if a.asset == "option" and a.side == "buy" and a.stop is None:
        risk = notional  # premium can go to zero
    if a.max_loss is not None:
        risk = a.max_loss

    # Options: no naked selling
    if a.asset == "option" and a.side == "sell" and a.option_type != "spread" \
            and not tr.get("allow_naked_option_selling", False):
        fails.append("Naked option selling has unlimited/large loss; only buying or defined-risk spreads are allowed.")

    if a.horizon in ("day", "swing"):
        cap = tr["max_per_trade"][ccy]
        if capital > cap:
            fails.append(f"Capital {m(ccy, capital)} exceeds per-trade trading cap {m(ccy, cap)}. "
                         f"Max qty at this price ≈ {int(cap // (a.price * a.multiplier)) if a.asset != 'future' else 'n/a'}.")
        if a.stop is None and not (a.asset == "option" and a.side == "buy") and a.max_loss is None:
            fails.append("Day/swing trades need a stop-loss (it defines money at risk).")
        budget = tr["budget"][ccy]
        max_risk = budget * tr.get("max_risk_pct_of_budget", 2.0) / 100
        if risk is not None and risk > max_risk:
            fails.append(f"Money at risk {m(ccy, risk)} exceeds {tr.get('max_risk_pct_of_budget', 2.0)}% "
                         f"of trading budget ({m(ccy, max_risk)}). Tighten the stop or cut size.")
        # Allocation bucket
        alloc = tr.get("allocation_pct", {}).get(a.asset)
        if alloc is not None:
            bucket = budget * alloc / 100
            used = 0.0
            if a.ledger and os.path.exists(a.ledger):
                L = json.load(open(a.ledger))
                used = sum(t["capital"] for t in L["trades"] if t["status"] == "open"
                           and t["asset"] == a.asset and t["currency"] == ccy and t["horizon"] != "long")
            if used + capital > bucket:
                fails.append(f"{a.asset} allocation is {alloc}% = {m(ccy, bucket)}; already used {m(ccy, used)}, "
                             f"this order would make {m(ccy, used + capital)}.")
        if alloc == 0:
            fails.append(f"{a.asset} has 0% allocation in the profile.")
    else:  # long-term
        cap = lt.get("max_per_position", {}).get(ccy)
        if cap is not None and capital > cap:
            fails.append(f"Long-term position {m(ccy, capital)} exceeds long-term cap {m(ccy, cap)}.")
        if lt.get("require_confirmation", True) and not a.confirmed:
            warns.append("Long-term amount needs the user's explicit confirmation (pass --confirmed once they agree).")
        if a.asset in ("option", "future"):
            fails.append("Options/futures aren't long-term investments here; use stock/ETF/crypto.")

    # Futures notional
    if a.asset == "future":
        root = a.symbol.split()[0].upper()
        warns.append(f"Futures notional exposure is {m(ccy, notional)} even if margin is smaller; "
                     f"losses are on the notional.")
        if a.market == "US" and root not in MICRO_FUTURES and a.horizon != "long":
            fails.append(f"{root} is not a micro contract; full-size US futures don't fit a small account. "
                         f"Use a micro (e.g. MES/MNQ/MBT) or the ETF.")
        if a.margin is None and a.horizon != "long":
            warns.append("Margin not given; capital check used full notional.")

    # Daily loss limit & open trades
    if a.ledger and os.path.exists(a.ledger):
        L = json.load(open(a.ledger))
        today = datetime.now(timezone.utc).date().isoformat()
        lost = -sum(t["pnl"] for t in L["trades"] if t["status"] == "closed"
                    and t["currency"] == ccy and t.get("closed", "")[:10] == today)
        dl = tr.get("daily_loss_limit", {}).get(ccy)
        if dl is not None and lost >= dl and a.horizon != "long":
            fails.append(f"Daily loss limit reached ({m(ccy, lost)} lost today, limit {m(ccy, dl)}). Stop for today.")
        n_open = sum(1 for t in L["trades"] if t["status"] == "open" and t["horizon"] != "long")
        if a.horizon != "long" and n_open >= tr.get("max_open_trades", 5):
            fails.append(f"Already {n_open} open trades (max {tr.get('max_open_trades', 5)}).")

    if prof.get("mode", "paper") != "live":
        warns.append("Profile mode is PAPER: record in ledger, don't send a live order.")

    print("FAIL" if fails else "PASS")
    print(f"  capital {m(ccy, capital)} | notional {m(ccy, notional)} | at risk "
          f"{m(ccy, risk) if risk is not None else 'unknown'}")
    for f in fails:
        print("  ✗ " + f)
    for w in warns:
        print("  ! " + w)
    sys.exit(2 if fails else 0)


if __name__ == "__main__":
    main()
