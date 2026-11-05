#!/usr/bin/env python3
"""Paper/live trade ledger and journal.

Works for any broker (including ones with no sandbox, like Zerodha) by
recording fills locally at real prices. One JSON file holds every trade.

Examples
  ledger.py --ledger L.json init
  ledger.py --ledger L.json open --market US --asset stock --symbol AAPL --side buy \
      --qty 2 --price 190 --stop 182 --target 205 --horizon swing --broker webull \
      --thesis "Pullback to 50DMA in uptrend"
  ledger.py --ledger L.json close --id T1 --price 201 --note "Hit target; plan followed"
  ledger.py --ledger L.json positions
  ledger.py --ledger L.json stats
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

CURRENCY = {"US": "USD", "IN": "INR"}
SYMBOL = {"USD": "$", "INR": "₹"}
DEFAULT_MULT = {"stock": 1, "crypto": 1, "option": 1, "future": 1, "fund": 1}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path):
    if not os.path.exists(path):
        sys.exit(f"Ledger {path} not found. Run: ledger.py --ledger {path} init")
    with open(path) as f:
        return json.load(f)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def money(ccy, x):
    return f"{SYMBOL.get(ccy, '')}{x:,.2f}"


def cmd_init(a):
    if os.path.exists(a.ledger) and not a.force:
        print(f"Ledger already exists at {a.ledger} (use --force to reset).")
        return
    os.makedirs(os.path.dirname(os.path.abspath(a.ledger)), exist_ok=True)
    save(a.ledger, {"created": now(), "next_id": 1, "trades": []})
    print(f"Created ledger {a.ledger}")


def cmd_open(a):
    d = load(a.ledger)
    ccy = CURRENCY[a.market]
    mult = a.multiplier if a.multiplier else DEFAULT_MULT[a.asset]
    cost = a.qty * a.price * mult
    capital = a.margin if (a.asset == "future" and a.margin) else cost
    risk = None
    if a.stop is not None:
        risk = abs(a.price - a.stop) * a.qty * mult
    t = {
        "id": f"T{d['next_id']}",
        "status": "open",
        "mode": a.mode,
        "market": a.market,
        "currency": ccy,
        "asset": a.asset,
        "symbol": a.symbol,
        "side": a.side,
        "qty": a.qty,
        "multiplier": mult,
        "entry": a.price,
        "stop": a.stop,
        "target": a.target,
        "capital": round(capital, 2),
        "risk": round(risk, 2) if risk is not None else None,
        "horizon": a.horizon,
        "strategy": a.strategy,
        "broker": a.broker,
        "price_source": a.price_source,
        "thesis": a.thesis,
        "lessons_used": [x.strip() for x in a.lessons.split(",")] if a.lessons else [],
        "fees": a.fees,
        "opened": now(),
    }
    d["trades"].append(t)
    d["next_id"] += 1
    save(a.ledger, d)
    r = money(ccy, risk) if risk is not None else "n/a (no stop)"
    print(f"OPENED {t['id']} [{a.mode}] {a.side} {a.qty} {a.symbol} @ {a.price} "
          f"| capital {money(ccy, capital)} | risk {r}")


def cmd_sip(a):
    d = load(a.ledger)
    d.setdefault("sips", [])
    if a.action == "add":
        sid = f"S{len(d['sips']) + 1}"
        d["sips"].append({"id": sid, "status": "active", "mode": a.mode, "market": a.market,
                          "currency": CURRENCY[a.market], "symbol": a.symbol, "monthly": a.monthly,
                          "day": a.day, "broker": a.broker, "thesis": a.thesis, "created": now(),
                          "instalments": []})
        print(f"SIP {sid} [{a.mode}] {money(CURRENCY[a.market], a.monthly)}/month in {a.symbol} on day {a.day}")
    elif a.action == "instalment":
        s = next(x for x in d["sips"] if x["id"] == a.id)
        units = a.monthly_amount / a.nav if a.nav else None
        s["instalments"].append({"date": now(), "amount": a.monthly_amount, "nav": a.nav, "units": units})
        print(f"{a.id}: recorded {money(s['currency'], a.monthly_amount)} at NAV {a.nav}")
    elif a.action == "stop":
        s = next(x for x in d["sips"] if x["id"] == a.id)
        s["status"] = "stopped"; s["stopped"] = now()
        print(f"{a.id} stopped")
    else:
        for s in d["sips"]:
            inv = sum(i["amount"] for i in s["instalments"])
            units = sum(i["units"] or 0 for i in s["instalments"])
            print(f"{s['id']} [{s['mode']}, {s['status']}] {s['symbol']} {money(s['currency'], s['monthly'])}/month "
                  f"| {len(s['instalments'])} instalments, invested {money(s['currency'], inv)}, units {units:.3f}")
    save(a.ledger, d)


def pnl_of(t, exit_price):
    sign = 1 if t["side"] == "buy" else -1
    gross = (exit_price - t["entry"]) * t["qty"] * t["multiplier"] * sign
    return gross - (t.get("fees") or 0) - (t.get("exit_fees") or 0)


def cmd_close(a):
    d = load(a.ledger)
    t = next((x for x in d["trades"] if x["id"] == a.id), None)
    if not t:
        sys.exit(f"No trade {a.id}")
    if t["status"] != "open":
        sys.exit(f"{a.id} is already {t['status']}")
    t["exit_fees"] = a.fees
    p = pnl_of(t, a.price)
    t.update({
        "status": "closed",
        "exit": a.price,
        "closed": now(),
        "pnl": round(p, 2),
        "r_multiple": round(p / t["risk"], 2) if t.get("risk") else None,
        "note": a.note,
        "plan_followed": a.plan_followed,
    })
    save(a.ledger, d)
    r = f" | {t['r_multiple']}R" if t["r_multiple"] is not None else ""
    print(f"CLOSED {a.id} {t['symbol']} @ {a.price} | P&L {money(t['currency'], p)}{r}")


def cmd_positions(a):
    d = load(a.ledger)
    prices = json.loads(a.prices) if a.prices else {}
    opens = [t for t in d["trades"] if t["status"] == "open"]
    if not opens:
        print("No open positions.")
        return
    for t in opens:
        line = (f"{t['id']} [{t['mode']}] {t['market']} {t['asset']} {t['side']} {t['qty']} "
                f"{t['symbol']} @ {t['entry']} stop {t['stop']} tgt {t['target']} "
                f"capital {money(t['currency'], t['capital'])} ({t['horizon']}, {t['broker']})")
        if t["symbol"] in prices:
            line += f" | unrealised {money(t['currency'], pnl_of(t, prices[t['symbol']]))}"
        print(line)


def summarize(trades):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    rs = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    return {
        "trades": n,
        "win_rate_pct": round(100 * len(wins) / n, 1) if n else 0,
        "pnl": round(sum(t["pnl"] for t in trades), 2),
        "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
        "plan_followed_pct": round(100 * sum(1 for t in trades if t.get("plan_followed")) / n, 1) if n else 0,
    }


def cmd_stats(a):
    d = load(a.ledger)
    closed = [t for t in d["trades"] if t["status"] == "closed"]
    out = {"open": sum(1 for t in d["trades"] if t["status"] == "open")}
    for ccy in ("USD", "INR"):
        c = [t for t in closed if t["currency"] == ccy]
        if c:
            out[f"overall_{ccy}"] = summarize(c)
    for key in ("strategy", "horizon", "asset", "market", "broker"):
        groups = defaultdict(list)
        for t in closed:
            groups[f"{t.get(key) or 'unspecified'} ({t['currency']})"].append(t)
        out[f"by_{key}"] = {k: summarize(v) for k, v in groups.items()}
    today = datetime.now(timezone.utc).date().isoformat()
    for ccy in ("USD", "INR"):
        out[f"today_realised_{ccy}"] = round(sum(
            t["pnl"] for t in closed if t["currency"] == ccy and t["closed"][:10] == today), 2)
    print(json.dumps(out, indent=2, ensure_ascii=False))


def tax_bucket(t):
    """Which tax rate applies to a closed trade (estimate)."""
    try:
        held = (datetime.fromisoformat(t["closed"]) - datetime.fromisoformat(t["opened"])).days
    except Exception:
        held = 0
    term = "long_term" if held > 365 else "short_term"
    if t["market"] == "IN" and t["asset"] in ("option", "future"):
        return "fno"
    if t["market"] == "US" and t["asset"] == "future":
        return "us_1256"  # 60% long-term / 40% short-term
    if t["asset"] == "crypto":
        return f"crypto_{term}"
    return term


def cmd_monthly(a):
    d = load(a.ledger)
    prof = json.load(open(a.profile)) if a.profile else {}
    tax = prof.get("tax", {})
    goal = prof.get("goal", {}).get("monthly_after_tax_return_pct", {})
    budget = prof.get("trading", {}).get("budget", {})
    closed = [t for t in d["trades"] if t["status"] == "closed"]
    if not closed:
        print("No closed trades yet.")
        return
    months = defaultdict(lambda: defaultdict(float))  # (month, ccy) -> bucket -> pnl
    counts = defaultdict(int)
    for t in closed:
        key = (t["closed"][:7], t["currency"])
        months[key][tax_bucket(t)] += t["pnl"]
        counts[key] += 1
    rows = []
    for (month, ccy) in sorted(months):
        rates = tax.get("US" if ccy == "USD" else "IN", {})
        gross, est_tax = 0.0, 0.0
        for bucket, p in months[(month, ccy)].items():
            gross += p
            if p <= 0:
                continue  # losses: no tax; set-off rules vary, so not credited here
            if bucket == "us_1256":
                r = 0.6 * rates.get("long_term", 0.15) + 0.4 * rates.get("short_term", 0.24)
            else:
                r = rates.get(bucket, rates.get("short_term", 0.0))
            est_tax += p * r
        after = gross - est_tax
        b = budget.get(ccy)
        pct = round(100 * after / b, 2) if b else None
        status = None
        if pct is not None and goal:
            status = ("above goal" if pct > goal.get("max", 1e9) else
                      "in goal range" if pct >= goal.get("min", 0) else "below goal")
        rows.append({"month": month, "currency": ccy, "trades": counts[(month, ccy)],
                     "realised_pnl": round(gross, 2), "est_tax": round(est_tax, 2),
                     "after_tax_pnl": round(after, 2), "after_tax_return_pct": pct,
                     "goal_pct": f"{goal.get('min')}–{goal.get('max')}" if goal else None,
                     "vs_goal": status})
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    print("month    ccy  trades  realised      est.tax     after-tax   return%  goal      status")
    for r in rows:
        s = SYMBOL.get(r["currency"], "")
        print(f"{r['month']}  {r['currency']}  {r['trades']:>6}  {s}{r['realised_pnl']:>10,.2f}  "
              f"{s}{r['est_tax']:>9,.2f}  {s}{r['after_tax_pnl']:>10,.2f}  "
              f"{r['after_tax_return_pct'] if r['after_tax_return_pct'] is not None else 'n/a':>7}  "
              f"{r['goal_pct'] or '':<8}  {r['vs_goal'] or ''}")
    print("Tax figures are planning estimates from profile.json rates; confirm with a tax professional.")


def cmd_report(a):
    """Daily or monthly progress report: actions, outcomes, open positions, costs, net vs goal."""
    d = load(a.ledger)
    prof = json.load(open(a.profile)) if a.profile else {}
    prices = json.loads(a.prices) if a.prices else {}
    today = (a.date or datetime.now(timezone.utc).date().isoformat())
    month = today[:7]
    budget = prof.get("trading", {}).get("budget", {})
    goal = prof.get("goal", {}).get("monthly_after_tax_return_pct", {})
    ai = prof.get("costs", {}).get("ai_monthly", {})
    tax = prof.get("tax", {})
    trades = d["trades"]
    lines = [f"# TraderSkill {'daily' if a.period == 'day' else 'monthly'} report — {today if a.period == 'day' else month}",
             f"Mode: {prof.get('mode', 'paper').upper()}" + (f" (paper until {prof['paper_until']})" if prof.get("paper_until") else "")]

    def in_period(ts):
        return bool(ts) and (ts[:10] == today if a.period == "day" else ts[:7] == month)

    opened = [t for t in trades if in_period(t.get("opened"))]
    closed = [t for t in trades if t["status"] == "closed" and in_period(t.get("closed"))]
    lines.append("\n## What I did")
    if not opened and not closed:
        lines.append("- No trades this period.")
    for t in opened:
        lines.append(f"- Opened {t['id']} [{t['mode']}] {t['side']} {t['qty']} {t['symbol']} @ {t['entry']} "
                     f"({t['horizon']}, {t['broker']}) — {t['thesis']}")
    for t in closed:
        lines.append(f"- Closed {t['id']} {t['symbol']} @ {t['exit']}: {money(t['currency'], t['pnl'])}"
                     f"{' (' + str(t['r_multiple']) + 'R)' if t.get('r_multiple') is not None else ''} — {t.get('note', '')}")
    for s in d.get("sips", []):
        for i in s["instalments"]:
            if in_period(i["date"]):
                lines.append(f"- SIP {s['id']} instalment {money(s['currency'], i['amount'])} in {s['symbol']}")

    lines.append("\n## Open positions")
    opens = [t for t in trades if t["status"] == "open"]
    if not opens:
        lines.append("- None.")
    for t in opens:
        u = ""
        if t["symbol"] in prices:
            p = pnl_of(t, prices[t["symbol"]])
            u = f" | now {prices[t['symbol']]} → unrealised {money(t['currency'], p)} ({100 * p / t['capital']:.1f}%)" if t["capital"] else ""
        lines.append(f"- {t['id']} {t['symbol']} {t['qty']} @ {t['entry']} stop {t['stop']} tgt {t['target']} ({t['horizon']}){u}")

    # Month-to-date economics
    lines.append(f"\n## Month to date ({month}) — after brokerage, taxes and AI cost")
    mtd = [t for t in trades if t["status"] == "closed" and t.get("closed", "")[:7] == month]
    for ccy in ("USD", "INR"):
        c = [t for t in mtd if t["currency"] == ccy]
        gross_before_fees = sum(t["pnl"] + (t.get("fees") or 0) + (t.get("exit_fees") or 0) for t in c)
        fees = sum((t.get("fees") or 0) + (t.get("exit_fees") or 0) for t in c)
        after_fees = gross_before_fees - fees
        rates = tax.get("US" if ccy == "USD" else "IN", {})
        est_tax = 0.0
        buckets = defaultdict(float)
        for t in c:
            buckets[tax_bucket(t)] += t["pnl"]
        for b, p in buckets.items():
            if p > 0:
                r = (0.6 * rates.get("long_term", 0.15) + 0.4 * rates.get("short_term", 0.24)) if b == "us_1256" \
                    else rates.get(b, rates.get("short_term", 0.0))
                est_tax += p * r
        ai_cost = ai.get(ccy, 0) or 0
        net = after_fees - est_tax - ai_cost
        b = budget.get(ccy)
        pct = f"{100 * net / b:.2f}%" if b else "n/a"
        if not c and not ai_cost:
            continue
        lines.append(f"- {ccy}: {len(c)} closed | before fees {money(ccy, gross_before_fees)} − brokerage "
                     f"{money(ccy, fees)} − est. tax {money(ccy, est_tax)} − AI {money(ccy, ai_cost)} = "
                     f"**{money(ccy, net)} ({pct} of {money(ccy, b or 0)})**"
                     + (f" | goal {goal.get('min')}–{goal.get('max')}%" if goal else ""))

    lines.append("\n## Trend & lessons")
    lines.append("- (Agent fills in: market/holding trends from live quotes, which lessons fired or changed, "
                 "and what needs the user's decision or approval.)")
    lines.append("\nTaxes are estimates from profile.json; money in/out of the broker is done by you, never by the skill.")
    out = "\n".join(lines)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w").write(out + "\n")
    print(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("--force", action="store_true")

    s = sub.add_parser("open")
    s.add_argument("--market", choices=["US", "IN"], required=True)
    s.add_argument("--asset", choices=["stock", "option", "future", "crypto", "fund"], required=True)
    s.add_argument("--symbol", required=True)
    s.add_argument("--side", choices=["buy", "sell"], required=True)
    s.add_argument("--qty", type=float, required=True, help="shares/coins, or contracts*lot units for options")
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--stop", type=float)
    s.add_argument("--target", type=float)
    s.add_argument("--multiplier", type=float, help="e.g. 100 for US options, 5 for MES")
    s.add_argument("--margin", type=float, help="margin blocked for futures")
    s.add_argument("--horizon", choices=["day", "swing", "long"], required=True)
    s.add_argument("--strategy", default=None)
    s.add_argument("--broker", default="paper")
    s.add_argument("--mode", choices=["paper", "live"], default="paper")
    s.add_argument("--price-source", default=None, help="where/when the price came from")
    s.add_argument("--thesis", required=True)
    s.add_argument("--lessons", default="", help="comma-separated lesson IDs used")
    s.add_argument("--fees", type=float, default=0.0)

    s = sub.add_parser("close")
    s.add_argument("--id", required=True)
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--note", required=True, help="2-3 line post-mortem")
    s.add_argument("--plan-followed", action=argparse.BooleanOptionalAction, default=True)
    s.add_argument("--fees", type=float, default=0.0)

    s = sub.add_parser("positions"); s.add_argument("--prices", help='JSON map, e.g. {"AAPL": 195}')
    sub.add_parser("stats")
    s = sub.add_parser("sip", help="track SIPs / recurring investments")
    s.add_argument("action", choices=["add", "instalment", "stop", "list"])
    s.add_argument("--id"); s.add_argument("--market", choices=["US", "IN"], default="IN")
    s.add_argument("--symbol"); s.add_argument("--monthly", type=float)
    s.add_argument("--day", type=int, default=5); s.add_argument("--broker", default="paper")
    s.add_argument("--mode", choices=["paper", "live"], default="paper"); s.add_argument("--thesis", default="")
    s.add_argument("--monthly-amount", type=float, help="instalment amount"); s.add_argument("--nav", type=float)
    s = sub.add_parser("report", help="daily/monthly progress report")
    s.add_argument("--period", choices=["day", "month"], default="day")
    s.add_argument("--profile"); s.add_argument("--prices", help='JSON map of current prices')
    s.add_argument("--date", help="YYYY-MM-DD (default today UTC)"); s.add_argument("--out", help="write markdown here")
    s = sub.add_parser("monthly", help="after-tax monthly results vs goal")
    s.add_argument("--profile", help="profile.json for tax rates, budget and goal")
    s.add_argument("--json", action="store_true")

    a = p.parse_args()
    {"init": cmd_init, "open": cmd_open, "close": cmd_close,
     "positions": cmd_positions, "stats": cmd_stats, "monthly": cmd_monthly, "sip": cmd_sip, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
