#!/usr/bin/env python3
"""Render a designed TraderSkill report from the ledger.

Outputs (any combination):
  --html  report.html   full designed page (cards, equity chart, tables) for viewing / sharing
  --email email.html    email-safe version: plain tables, headings, bold, lists only — survives
                        Outlook/Gmail sanitizers (no <style>, <img>, <span>, scripts)
  --deck  report.pptx   5-slide presentation (needs `pip install python-pptx`; matplotlib optional)

Narrative (written by the agent) comes from --notes notes.json:
  {"headline": "...", "trends": ["..."], "lessons": ["..."], "needs_you": ["..."]}

Example
  render_report.py --ledger trader-data/ledger.json --profile trader-data/profile.json \
     --prices '{"NSE:ITC": 431}' --notes trader-data/reports/notes.json --period day \
     --html trader-data/reports/2026-11-05.html --email trader-data/reports/2026-11-05.email.html
"""
import argparse
import html
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger import pnl_of, tax_bucket  # noqa: E402

SYM = {"USD": "$", "INR": "₹"}


def fmt(ccy, x, sign=False):
    s = f"{SYM.get(ccy, '')}{abs(x):,.2f}"
    if x < 0:
        return "−" + s
    return ("+" + s) if sign and x > 0 else s


def neg(ccy, x):
    return fmt(ccy, 0) if not x else "−" + fmt(ccy, x)


def compute(ledger, profile, prices, period, date):
    trades = ledger["trades"]
    month = date[:7]
    budget = profile.get("trading", {}).get("budget", {})
    ai = profile.get("costs", {}).get("ai_monthly", {})
    tax = profile.get("tax", {})
    goal = profile.get("goal", {}).get("monthly_after_tax_return_pct", {})

    def in_period(ts):
        return bool(ts) and (ts[:10] == date if period == "day" else ts[:7] == month)

    actions = []
    for t in trades:
        if in_period(t.get("opened")):
            actions.append(("Opened", t, None))
        if t["status"] == "closed" and in_period(t.get("closed")):
            actions.append(("Closed", t, t["pnl"]))
    opens = []
    for t in trades:
        if t["status"] != "open":
            continue
        px = prices.get(t["symbol"])
        u = pnl_of(t, px) if px is not None else None
        opens.append((t, px, u))

    per_ccy = {}
    for ccy in ("USD", "INR"):
        mtd = [t for t in trades if t["status"] == "closed" and t["currency"] == ccy
               and t.get("closed", "")[:7] == month]
        fees = sum((t.get("fees") or 0) + (t.get("exit_fees") or 0) for t in mtd)
        after_fees = sum(t["pnl"] for t in mtd)
        rates = tax.get("US" if ccy == "USD" else "IN", {})
        b = defaultdict(float)
        for t in mtd:
            b[tax_bucket(t)] += t["pnl"]
        est_tax = sum(p * ((0.6 * rates.get("long_term", .15) + 0.4 * rates.get("short_term", .24))
                           if k == "us_1256" else rates.get(k, rates.get("short_term", 0)))
                      for k, p in b.items() if p > 0)
        ai_cost = ai.get(ccy, 0) or 0
        net = after_fees - est_tax - ai_cost
        unreal = sum(u for t, _, u in opens if u is not None and t["currency"] == ccy)
        bud = budget.get(ccy) or 0
        wins = sum(1 for t in mtd if t["pnl"] > 0)
        # equity curve from all closed trades in this currency
        closed_all = sorted([t for t in trades if t["status"] == "closed" and t["currency"] == ccy],
                            key=lambda t: t["closed"])
        curve, run = [], 0.0
        for t in closed_all:
            run += t["pnl"]
            curve.append((t["closed"][:10], run))
        if not (mtd or any(t["currency"] == ccy for t, _, _ in opens) or bud):
            continue
        per_ccy[ccy] = {
            "budget": bud, "closed": len(mtd), "wins": wins, "fees": fees, "after_fees": after_fees,
            "gross": after_fees + fees, "tax": est_tax, "ai": ai_cost, "net": net,
            "net_pct": (100 * net / bud) if bud else None, "unrealised": unreal, "curve": curve,
        }
    return {"actions": actions, "opens": opens, "per_ccy": per_ccy, "goal": goal,
            "mode": profile.get("mode", "paper"), "paper_until": profile.get("paper_until"),
            "month": month}


def svg_curve(curve, w=520, h=120, color="#2f6fed"):
    if len(curve) < 2:
        return '<div class="muted small">Equity curve appears after two closed trades.</div>'
    vals = [0.0] + [v for _, v in curve]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pts = [(i * (w - 10) / (len(vals) - 1) + 5, h - 10 - (v - lo) / rng * (h - 20)) for i, v in enumerate(vals)]
    zero_y = h - 10 - (0 - lo) / rng * (h - 20)
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" role="img" aria-label="Cumulative P&L">'
            f'<line x1="0" x2="{w}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" class="axis"/>'
            f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/></svg>')


def render_html(d, notes, title):
    e = html.escape
    goal = d["goal"]
    cards = []
    for ccy, c in d["per_ccy"].items():
        pct = f"{c['net_pct']:+.2f}%" if c["net_pct"] is not None else "n/a"
        tone = "pos" if c["net"] > 0 else ("neg" if c["net"] < 0 else "")
        gtxt = f"Goal {goal.get('min')}–{goal.get('max')}% / month" if goal else ""
        cards.append(f"""
      <section class="card">
        <div class="eyebrow">{'India · ₹' if ccy == 'INR' else 'US · $'} — month to date</div>
        <div class="big {tone}">{fmt(ccy, c['net'], True)}</div>
        <div class="muted">{pct} of {fmt(ccy, c['budget'])} budget · {gtxt}</div>
        <dl class="waterfall">
          <dt>Gross P&amp;L</dt><dd>{fmt(ccy, c['gross'], True)}</dd>
          <dt>Brokerage &amp; charges</dt><dd>{neg(ccy, c['fees'])}</dd>
          <dt>Est. tax</dt><dd>{neg(ccy, c['tax'])}</dd>
          <dt>AI cost</dt><dd>{neg(ccy, c['ai'])}</dd>
          <dt class="strong">Net</dt><dd class="strong">{fmt(ccy, c['net'], True)}</dd>
        </dl>
        <div class="muted small">{c['closed']} closed · {c['wins']} won · unrealised {fmt(ccy, c['unrealised'], True)}</div>
        {svg_curve(c['curve'])}
      </section>""")
    acts = "".join(
        f"<tr><td><span class='pill {'pill-open' if k == 'Opened' else 'pill-close'}'>{k}</span></td>"
        f"<td>{e(t['symbol'])}</td><td>{e(t['side'])} {t['qty']:g} @ {t['entry'] if k == 'Opened' else t['exit']}</td>"
        f"<td class='{'pos' if (p or 0) > 0 else 'neg' if (p or 0) < 0 else ''}'>{fmt(t['currency'], p, True) if p is not None else '—'}</td>"
        f"<td class='muted'>{e(t['mode'])} · {e(t['broker'])}</td><td class='small'>{e((t.get('note') if k == 'Closed' else t['thesis']) or '')}</td></tr>"
        for k, t, p in d["actions"]) or "<tr><td colspan='6' class='muted'>No trades this period.</td></tr>"
    pos = "".join(
        f"<tr><td>{e(t['symbol'])}</td><td>{t['qty']:g} @ {t['entry']}</td><td>{px if px is not None else '—'}</td>"
        f"<td class='{'pos' if (u or 0) > 0 else 'neg' if (u or 0) < 0 else ''}'>{fmt(t['currency'], u, True) if u is not None else '—'}</td>"
        f"<td>{t['stop'] if t['stop'] is not None else '—'} / {t['target'] if t['target'] is not None else '—'}</td><td class='muted'>{e(t['horizon'])}</td></tr>"
        for t, px, u in d["opens"]) or "<tr><td colspan='6' class='muted'>No open positions.</td></tr>"

    def lst(items):
        return "".join(f"<li>{e(x)}</li>" for x in items) or "<li class='muted'>—</li>"
    mode = d["mode"].upper() + (f" until {d['paper_until']}" if d["paper_until"] and d["mode"] == "paper" else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#667085;--line:#e5e7eb;--pos:#0f8a5f;--neg:#c2410c;--accent:#2f6fed}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1115;--card:#171a21;--ink:#e8eaed;--muted:#9aa3b2;--line:#2a2f3a;--pos:#34d399;--neg:#fb923c;--accent:#7aa2ff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}}
.wrap{{max-width:980px;margin:0 auto;padding:28px 16px 48px}}
header h1{{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}}header .sub{{color:var(--muted)}}
.badge{{display:inline-block;padding:2px 10px;border-radius:999px;border:1px solid var(--line);font-size:12px;margin-left:8px;color:var(--muted)}}
.headline{{margin:18px 0;padding:14px 16px;border-left:4px solid var(--accent);background:var(--card);border-radius:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}}
.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}}
.big{{font-size:34px;font-weight:700;margin:6px 0 2px;font-variant-numeric:tabular-nums}}
.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}.muted{{color:var(--muted)}}.small{{font-size:13px}}.strong{{font-weight:700}}
.waterfall{{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin:14px 0 8px;font-variant-numeric:tabular-nums}}
.waterfall dt{{color:var(--muted)}}.waterfall dd{{margin:0;text-align:right}}.waterfall dt.strong{{color:var(--ink);border-top:1px solid var(--line);padding-top:4px}}.waterfall dd.strong{{border-top:1px solid var(--line);padding-top:4px}}
svg .axis{{stroke:var(--line);stroke-dasharray:4 4}}
h2{{font-size:17px;margin:28px 0 10px}}
.table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
.table th,.table td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}.table th{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.table tr:last-child td{{border-bottom:0}}.scroll{{overflow-x:auto}}
.pill{{font-size:12px;padding:2px 8px;border-radius:999px}}.pill-open{{background:rgba(47,111,237,.12);color:var(--accent)}}.pill-close{{background:rgba(15,138,95,.12);color:var(--pos)}}
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}.cols ul{{margin:0;padding-left:18px}}
footer{{margin-top:28px;color:var(--muted);font-size:12px}}
</style></head><body><div class="wrap">
<header><h1>{e(title)}<span class="badge">{e(mode)}</span></h1>
<div class="sub">Generated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}</div></header>
{f'<div class="headline">{e(notes.get("headline", ""))}</div>' if notes.get("headline") else ''}
<div class="grid">{''.join(cards) or '<section class="card muted">No budget or trades yet.</section>'}</div>
<h2>What I did</h2><div class="scroll"><table class="table"><thead><tr><th></th><th>Symbol</th><th>Order</th><th>P&amp;L</th><th>Mode</th><th>Why / review</th></tr></thead><tbody>{acts}</tbody></table></div>
<h2>Open positions</h2><div class="scroll"><table class="table"><thead><tr><th>Symbol</th><th>Entry</th><th>Now</th><th>Unrealised</th><th>Stop / target</th><th>Horizon</th></tr></thead><tbody>{pos}</tbody></table></div>
<div class="cols">
<section><h2>Trends</h2><div class="card"><ul>{lst(notes.get('trends', []))}</ul></div></section>
<section><h2>Lessons</h2><div class="card"><ul>{lst(notes.get('lessons', []))}</ul></div></section>
<section><h2>Needs you</h2><div class="card"><ul>{lst(notes.get('needs_you', []))}</ul></div></section>
</div>
<footer>Taxes are estimates. Deposits and withdrawals are always done by you in the broker app. Not financial advice.</footer>
</div></body></html>"""


def render_email(d, notes, title):
    """Sanitizer-safe: only h2/h3/p/b/table/tr/th/td/ul/li."""
    e = html.escape
    goal = d["goal"]
    out = [f"<h2>{e(title)}</h2>",
           f"<p><b>Mode:</b> {e(d['mode'].upper())}" + (f" (paper until {e(d['paper_until'])})" if d['paper_until'] and d['mode'] == 'paper' else "") + "</p>"]
    if notes.get("headline"):
        out.append(f"<p><b>{e(notes['headline'])}</b></p>")
    out.append("<h3>Month to date — after brokerage, tax and AI cost</h3>")
    out.append("<table border='1' cellpadding='6' cellspacing='0'><tr><th>Market</th><th>Gross</th><th>Brokerage</th><th>Est. tax</th><th>AI</th><th>Net</th><th>Return</th><th>Goal</th></tr>")
    for ccy, c in d["per_ccy"].items():
        pct = f"{c['net_pct']:+.2f}%" if c["net_pct"] is not None else "n/a"
        arrow = "▲" if c["net"] > 0 else ("▼" if c["net"] < 0 else "•")
        out.append(f"<tr><td>{'India ₹' if ccy == 'INR' else 'US $'}</td><td>{fmt(ccy, c['gross'], True)}</td><td>{neg(ccy, c['fees'])}</td>"
                   f"<td>{neg(ccy, c['tax'])}</td><td>{neg(ccy, c['ai'])}</td><td><b>{arrow} {fmt(ccy, c['net'], True)}</b></td>"
                   f"<td>{pct} of {fmt(ccy, c['budget'])}</td><td>{goal.get('min', '')}–{goal.get('max', '')}%</td></tr>")
    out.append("</table>")
    out.append("<h3>What I did</h3>")
    if d["actions"]:
        out.append("<ul>" + "".join(
            f"<li><b>{k}</b> {e(t['symbol'])} — {e(t['side'])} {t['qty']:g} @ {t['entry'] if k == 'Opened' else t['exit']}"
            f"{' — <b>' + fmt(t['currency'], p, True) + '</b>' if p is not None else ''} ({e(t['mode'])}, {e(t['broker'])}). "
            f"{e((t.get('note') if k == 'Closed' else t['thesis']) or '')}</li>" for k, t, p in d["actions"]) + "</ul>")
    else:
        out.append("<p>No trades this period.</p>")
    out.append("<h3>Open positions</h3>")
    if d["opens"]:
        out.append("<table border='1' cellpadding='6' cellspacing='0'><tr><th>Symbol</th><th>Entry</th><th>Now</th><th>Unrealised</th><th>Stop / target</th></tr>" + "".join(
            f"<tr><td>{e(t['symbol'])}</td><td>{t['qty']:g} @ {t['entry']}</td><td>{px if px is not None else '—'}</td>"
            f"<td>{fmt(t['currency'], u, True) if u is not None else '—'}</td><td>{t['stop']} / {t['target']}</td></tr>"
            for t, px, u in d["opens"]) + "</table>")
    else:
        out.append("<p>None.</p>")
    for key, label in (("trends", "Trends"), ("lessons", "Lessons"), ("needs_you", "Needs you")):
        items = notes.get(key, [])
        if items:
            out.append(f"<h3>{label}</h3><ul>" + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>")
    out.append("<p><i>Taxes are estimates. Deposits and withdrawals are always done by you. Not financial advice.</i></p>")
    return "\n".join(out)


def render_deck(d, notes, title, path):
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
    except ImportError:
        sys.exit("python-pptx not installed: pip install python-pptx")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    INK, MUTED, ACC = RGBColor(0x14, 0x17, 0x1C), RGBColor(0x66, 0x70, 0x85), RGBColor(0x2F, 0x6F, 0xED)

    def text(slide, s, x, y, w, h, size=18, bold=False, color=INK):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
        tb.word_wrap = True
        for i, line in enumerate(s if isinstance(s, list) else [s]):
            p = tb.paragraphs[0] if i == 0 else tb.add_paragraph()
            p.text = line
            p.font.size, p.font.bold, p.font.color.rgb = Pt(size), bold, color
        return tb

    s = prs.slides.add_slide(blank)
    text(s, title, 0.8, 2.4, 11.5, 1.2, 40, True)
    text(s, notes.get("headline", ""), 0.8, 3.7, 11.5, 1.2, 20, color=MUTED)
    text(s, f"Mode: {d['mode'].upper()}", 0.8, 6.4, 6, 0.5, 14, color=ACC)

    s = prs.slides.add_slide(blank)
    text(s, "Month to date — net after costs", 0.8, 0.5, 11.5, 0.8, 28, True)
    x = 0.8
    for ccy, c in d["per_ccy"].items():
        text(s, ("India" if ccy == "INR" else "US"), x, 1.6, 5.6, 0.5, 16, color=MUTED)
        text(s, fmt(ccy, c["net"], True), x, 2.1, 5.6, 1.0, 44, True,
             RGBColor(0x0F, 0x8A, 0x5F) if c["net"] > 0 else (RGBColor(0xC2, 0x41, 0x0C) if c["net"] < 0 else INK))
        text(s, [f"Gross {fmt(ccy, c['gross'], True)}", f"Brokerage {neg(ccy, c['fees'])}",
                 f"Est. tax {neg(ccy, c['tax'])}", f"AI cost {neg(ccy, c['ai'])}",
                 f"{c['closed']} closed · {c['wins']} won"], x, 3.3, 5.6, 3, 16, color=MUTED)
        x += 6.0

    s = prs.slides.add_slide(blank)
    text(s, "What I did", 0.8, 0.5, 11.5, 0.8, 28, True)
    lines = [f"{k}: {t['symbol']} {t['side']} {t['qty']:g} @ {t['entry'] if k == 'Opened' else t['exit']}"
             + (f"  →  {fmt(t['currency'], p, True)}" if p is not None else "") for k, t, p in d["actions"]] or ["No trades this period."]
    text(s, lines[:12], 0.8, 1.5, 11.8, 5.5, 18)

    s = prs.slides.add_slide(blank)
    text(s, "Open positions", 0.8, 0.5, 11.5, 0.8, 28, True)
    lines = [f"{t['symbol']}: {t['qty']:g} @ {t['entry']}  now {px if px is not None else '—'}  "
             f"unrealised {fmt(t['currency'], u, True) if u is not None else '—'}  stop {t['stop']} / tgt {t['target']}"
             for t, px, u in d["opens"]] or ["None."]
    text(s, lines[:12], 0.8, 1.5, 11.8, 5.5, 18)

    s = prs.slides.add_slide(blank)
    text(s, "Trends, lessons & what needs you", 0.8, 0.5, 11.5, 0.8, 28, True)
    col = 0.8
    for key, label in (("trends", "Trends"), ("lessons", "Lessons"), ("needs_you", "Needs you")):
        text(s, label, col, 1.5, 3.9, 0.5, 18, True, ACC)
        text(s, notes.get(key, []) or ["—"], col, 2.1, 3.9, 4.8, 15)
        col += 4.0
    prs.save(path)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--prices", default="{}", help="JSON map symbol -> current price")
    p.add_argument("--notes", help="JSON file with headline/trends/lessons/needs_you")
    p.add_argument("--period", choices=["day", "month"], default="day")
    p.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    p.add_argument("--html"); p.add_argument("--email"); p.add_argument("--deck")
    a = p.parse_args()
    ledger, profile = json.load(open(a.ledger)), json.load(open(a.profile))
    notes = json.load(open(a.notes)) if a.notes and os.path.exists(a.notes) else {}
    date = a.date or datetime.now(timezone.utc).date().isoformat()
    d = compute(ledger, profile, json.loads(a.prices), a.period, date)
    title = f"TraderSkill {'daily' if a.period == 'day' else 'monthly'} report — " + (
        datetime.fromisoformat(date).strftime("%a %d %b %Y") if a.period == "day" else d["month"])
    for path, fn in ((a.html, lambda: render_html(d, notes, title)), (a.email, lambda: render_email(d, notes, title))):
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            open(path, "w").write(fn())
            print(f"wrote {path}")
    if a.deck:
        render_deck(d, notes, title, a.deck)
        print(f"wrote {a.deck}")
    if not (a.html or a.email or a.deck):
        print(render_email(d, notes, title))


if __name__ == "__main__":
    main()
