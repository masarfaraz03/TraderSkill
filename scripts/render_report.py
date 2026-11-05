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



POS, NEG, ACC = "#2a78d6", "#e34948", "#2a78d6"   # diverging pair: gain blue / cost-loss red
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
ASSET_COLOR = {"Stock": "#2a78d6", "Crypto": "#eb6834", "Option": "#1baf7a", "Future": "#eda100", "Fund": "#6250d6", "Cash": "#b9b8b2"}


def _tip(s):
    return html.escape(s, quote=True)


def svg_bars(rows, w=560, row_h=30, unit=""):
    """Horizontal diverging bars. rows: [(label, value, tooltip)]. Zero baseline, blue +, red -."""
    if not rows:
        return '<div class="muted small">Nothing to show yet.</div>'
    vals = [v for _, v, _ in rows]
    lo, hi = min(0, min(vals)), max(0, max(vals))
    rng = (hi - lo) or 1
    lab_w, val_w = 150, 90
    plot = w - lab_w - val_w
    x0 = lab_w + (0 - lo) / rng * plot
    h = row_h * len(rows) + 8
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" width="100%" role="img">',
           f'<line x1="{x0:.1f}" x2="{x0:.1f}" y1="0" y2="{h}" class="axis"/>']
    for i, (lab, v, tip) in enumerate(rows):
        y = 4 + i * row_h
        bw = abs(v) / rng * plot
        x = x0 if v >= 0 else x0 - bw
        col = POS if v >= 0 else NEG
        out.append(f'<g class="hit" tabindex="0" data-tip="{_tip(tip)}">'
                   f'<rect x="0" y="{y}" width="{w}" height="{row_h}" fill="transparent"/>'
                   f'<text x="{lab_w - 8}" y="{y + row_h / 2 + 4}" text-anchor="end" class="lbl">{html.escape(lab)}</text>'
                   f'<rect x="{x:.1f}" y="{y + 7}" width="{max(bw, 1.5):.1f}" height="{row_h - 14}" rx="4" fill="{col}"/>'
                   f'<text x="{w - 4}" y="{y + row_h / 2 + 4}" text-anchor="end" class="val">{html.escape(unit_fmt(v, unit))}</text></g>')
    out.append("</svg>")
    return "".join(out)


def unit_fmt(v, unit):
    return fmt(unit, v, True) if unit in SYM else f"{v:+.2f}{unit}"


def svg_line(curve, ccy, w=560, h=170):
    if len(curve) < 2:
        return '<div class="muted small">The equity curve appears after two closed trades.</div>'
    pts_v = [("start", 0.0)] + curve
    vals = [v for _, v in pts_v]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 8, 8, 10, 22
    X = lambda i: L + i * (w - L - R) / (len(pts_v) - 1)
    Y = lambda v: T + (hi - v) / (hi - lo) * (h - T - B)
    path = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(pts_v))
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" width="100%" role="img">',
           f'<line x1="{L}" x2="{w - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" class="axis dash"/>',
           f'<polyline points="{path}" fill="none" stroke="{ACC}" stroke-width="2" stroke-linejoin="round"/>']
    step = (w - L - R) / (len(pts_v) - 1)
    for i, (dte, v) in enumerate(pts_v):
        prev = pts_v[i - 1][1] if i else 0
        tip = f"{dte}: cumulative {fmt(ccy, v, True)}" + (f" (trade {fmt(ccy, v - prev, True)})" if i else "")
        out.append(f'<g class="hit pt" tabindex="0" data-tip="{_tip(tip)}"><rect x="{X(i) - step / 2:.1f}" y="0" width="{step:.1f}" height="{h}" fill="transparent"/>'
                   f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{T}" y2="{h - B}" class="cross"/>'
                   f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" fill="{ACC}" stroke="var(--card)" stroke-width="2"/></g>')
    out.append(f'<text x="{L}" y="{h - 6}" class="tick">{html.escape(pts_v[1][0])}</text>'
               f'<text x="{w - R}" y="{h - 6}" text-anchor="end" class="tick">{html.escape(pts_v[-1][0])}</text></svg>')
    return "".join(out)


def svg_goal(pct, gmin, gmax, w=560, h=46):
    """Bullet: net % vs goal band."""
    lo, hi = min(-5.0, (pct or 0) - 2), max(gmax * 1.25, (pct or 0) + 2)
    X = lambda v: 6 + (v - lo) / (hi - lo) * (w - 12)
    p = pct or 0
    col = POS if p >= 0 else NEG
    return (f'<svg class="chart" viewBox="0 0 {w} {h}" width="100%" role="img">'
            f'<g class="hit" tabindex="0" data-tip="{_tip(f"Goal band {gmin}–{gmax}% a month after all costs")}">'
            f'<rect x="{X(gmin):.1f}" y="8" width="{X(gmax) - X(gmin):.1f}" height="18" rx="4" class="band"/></g>'
            f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="4" y2="30" class="axis"/>'
            f'<g class="hit" tabindex="0" data-tip="{_tip(f"Month to date: {p:+.2f}% of budget after brokerage, tax and AI cost")}">'
            f'<rect x="{min(X(0), X(p)):.1f}" y="13" width="{max(abs(X(p) - X(0)), 2):.1f}" height="8" rx="4" fill="{col}"/></g>'
            f'<text x="{X(0):.1f}" y="42" text-anchor="middle" class="tick">0%</text>'
            f'<text x="{X(gmin):.1f}" y="42" text-anchor="middle" class="tick">{gmin}%</text>'
            f'<text x="{X(gmax):.1f}" y="42" text-anchor="middle" class="tick">{gmax}%</text></svg>')


def svg_stack(parts, ccy, w=560, h=34):
    """100% stacked bar of capital by bucket. parts: [(label, value)]"""
    tot = sum(v for _, v in parts) or 1
    x, out = 0.0, [f'<svg class="chart" viewBox="0 0 {w} {h}" width="100%" role="img">']
    for i, (lab, v) in enumerate(parts):
        bw = v / tot * w
        out.append(f'<g class="hit" tabindex="0" data-tip="{_tip(f"{lab}: {fmt(ccy, v)} ({100 * v / tot:.0f}%)")}">'
                   f'<rect x="{x + (1 if i else 0):.1f}" y="4" width="{max(bw - 2, 1):.1f}" height="{h - 8}" rx="4" fill="{ASSET_COLOR.get(lab, CAT[i % len(CAT)])}"/></g>')
        x += bw
    out.append("</svg>")
    leg = "".join(f'<span class="lg"><i style="background:{ASSET_COLOR.get(l, CAT[i % len(CAT)])}"></i>{html.escape(l)} {100 * v / tot:.0f}%</span>' for i, (l, v) in enumerate(parts))
    return "".join(out) + f'<div class="legend">{leg}</div>'


def chart_data(d):
    """Shared chart inputs for HTML + email images."""
    out = {}
    for ccy, c in d["per_ccy"].items():
        costs = [("Gross P&L", c["gross"], f"Realised profit before costs: {fmt(ccy, c['gross'], True)}"),
                 ("Brokerage", -c["fees"], f"Brokerage, STT, exchange & other charges: {neg(ccy, c['fees'])}"),
                 ("Est. tax", -c["tax"], f"Estimated tax on this month's gains: {neg(ccy, c['tax'])}"),
                 ("AI cost", -c["ai"], f"AI cost counted this month: {neg(ccy, c['ai'])}"),
                 ("Net", c["net"], f"Net after all costs: {fmt(ccy, c['net'], True)}")]
        pos = []
        for t, px, u in d["opens"]:
            if t["currency"] != ccy:
                continue
            uu = u or 0.0
            dist = f"; stop {t['stop']}, target {t['target']}" if t.get("stop") else ""
            pos.append((t["symbol"], uu, f"{t['symbol']}: {t['qty']:g} @ {t['entry']} → now {px if px is not None else 'n/a'}; "
                                        f"unrealised {fmt(ccy, uu, True)}{dist} ({t['horizon']}, {t['mode']})"))
        alloc = defaultdict(float)
        for t, _, _ in d["opens"]:
            if t["currency"] == ccy:
                alloc[t["asset"]] += t["capital"]
        cash = max((c["budget"] or 0) - sum(alloc.values()), 0)
        parts = [(k.title(), v) for k, v in sorted(alloc.items(), key=lambda kv: -kv[1])] + ([("Cash", cash)] if cash else [])
        out[ccy] = {"costs": costs, "positions": pos, "alloc": parts, "curve": c["curve"]}
    return out


def render_html(d, notes, title):
    """Interactive report: every mark has a hover/tap tooltip; light + dark."""
    e = html.escape
    goal = d["goal"]
    cdat = chart_data(d)
    panels = []
    for ccy, c in d["per_ccy"].items():
        cd = cdat[ccy]
        tone = "pos" if c["net"] > 0 else ("neg" if c["net"] < 0 else "")
        pct = c["net_pct"]
        panels.append(f"""
  <section class="market">
    <div class="hero card">
      <div class="eyebrow">{'India · ₹' if ccy == 'INR' else 'US · $'} — net month to date, after all costs</div>
      <div class="big {tone}">{fmt(ccy, c['net'], True)}</div>
      <div class="muted">{f'{pct:+.2f}%' if pct is not None else 'n/a'} of {fmt(ccy, c['budget'])} budget · {c['closed']} closed, {c['wins']} won · unrealised {fmt(ccy, c['unrealised'], True)}</div>
      {svg_goal(pct, goal.get('min', 8), goal.get('max', 16)) if goal else ''}
    </div>
    <div class="card"><h3>Where the money went</h3>{svg_bars(cd['costs'], unit=ccy)}</div>
    <div class="card"><h3>Equity curve <span class="muted small">cumulative realised P&amp;L</span></h3>{svg_line(cd['curve'], ccy)}</div>
    <div class="card"><h3>Open positions <span class="muted small">unrealised P&amp;L</span></h3>{svg_bars(cd['positions'], unit=ccy)}</div>
    <div class="card"><h3>Capital allocation</h3>{svg_stack(cd['alloc'], ccy) if cd['alloc'] else '<div class="muted small">No capital deployed.</div>'}</div>
  </section>""")

    def lst(items):
        return "".join(f"<li>{e(x)}</li>" for x in items) or "<li class='muted'>—</li>"
    acts = "".join(
        f"<tr><td>{k}</td><td>{e(t['symbol'])}</td><td>{t['qty']:g} @ {t['entry'] if k == 'Opened' else t['exit']}</td>"
        f"<td class='{'pos' if (p or 0) > 0 else 'neg' if (p or 0) < 0 else ''}'>{fmt(t['currency'], p, True) if p is not None else '—'}</td>"
        f"<td class='small'>{e((t.get('note') if k == 'Closed' else t['thesis']) or '')}</td></tr>"
        for k, t, p in d["actions"]) or "<tr><td colspan='5' class='muted'>No trades this period.</td></tr>"
    mode = d["mode"].upper() + (f" until {d['paper_until']}" if d["paper_until"] and d["mode"] == "paper" else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>
:root{{color-scheme:light;--bg:#f4f4f2;--card:#fcfcfb;--ink:#0b0b0b;--muted:#52514e;--line:#e4e3df;--pos:#2a78d6;--neg:#e34948;--band:rgba(27,175,122,.18)}}
@media (prefers-color-scheme:dark){{:root{{color-scheme:dark;--bg:#111110;--card:#1a1a19;--ink:#f0efec;--muted:#c3c2b7;--line:#2f2f2c;--pos:#3987e5;--neg:#e66767;--band:rgba(25,158,112,.28)}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:24px 16px 48px}}
header h1{{font-size:24px;margin:0}}.sub{{color:var(--muted);font-size:13px}}
.badge{{display:inline-block;padding:2px 10px;border:1px solid var(--line);border-radius:999px;font-size:12px;color:var(--muted);margin-left:8px;vertical-align:middle}}
.headline{{margin:16px 0;padding:12px 16px;border-left:4px solid var(--pos);background:var(--card);border-radius:8px}}
.markets{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px}}
.market{{display:grid;gap:12px;align-content:start}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}}
.card h3{{margin:0 0 8px;font-size:14px;font-weight:600}}
.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.big{{font-size:38px;font-weight:700;line-height:1.15;margin:4px 0;font-variant-numeric:tabular-nums}}
.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}.muted{{color:var(--muted)}}.small{{font-size:12px;font-weight:400}}
.chart{{display:block;overflow:visible}}.chart .lbl,.chart .val{{font-size:12px;fill:var(--ink)}}.chart .val{{font-variant-numeric:tabular-nums}}
.chart .tick{{font-size:11px;fill:var(--muted)}}.chart .axis{{stroke:var(--line);stroke-width:1}}.chart .dash{{stroke-dasharray:4 4}}.chart .band{{fill:var(--band)}}
.chart .cross{{stroke:var(--muted);stroke-width:1;opacity:0}}.hit{{cursor:default;outline:none}}.hit:hover rect[rx],.hit:focus rect[rx]{{opacity:.8}}
.pt:hover .cross,.pt:focus .cross{{opacity:.5}}
.legend{{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:6px;font-size:12px;color:var(--muted)}}.lg i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}}
#tip{{position:fixed;pointer-events:none;z-index:9;max-width:300px;padding:8px 10px;border-radius:8px;background:var(--ink);color:var(--card);font-size:12.5px;line-height:1.4;box-shadow:0 4px 16px rgba(0,0,0,.2);opacity:0;transition:opacity .08s}}
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:18px}}.cols ul{{margin:0;padding-left:18px}}
h2{{font-size:16px;margin:26px 0 8px}}.scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:13px}}
td,th{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left}}tr:last-child td{{border-bottom:0}}
details summary{{cursor:pointer;color:var(--muted);margin-top:22px}}
footer{{margin-top:24px;color:var(--muted);font-size:12px}}
</style></head><body><div class="wrap">
<header><h1>{e(title)}<span class="badge">{e(mode)}</span></h1><div class="sub">Hover or tap any bar, point or band for details · generated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}</div></header>
{f'<div class="headline">{e(notes.get("headline", ""))}</div>' if notes.get("headline") else ''}
<div class="markets">{''.join(panels) or '<div class="card muted">No budget or trades yet.</div>'}</div>
<div class="cols">
<div class="card"><h3>Trends</h3><ul>{lst(notes.get('trends', []))}</ul></div>
<div class="card"><h3>Lessons</h3><ul>{lst(notes.get('lessons', []))}</ul></div>
<div class="card"><h3>Needs you</h3><ul>{lst(notes.get('needs_you', []))}</ul></div>
</div>
<details><summary>Trade log (table view)</summary><div class="scroll"><table><tr><th></th><th>Symbol</th><th>Order</th><th>P&amp;L</th><th>Why / review</th></tr>{acts}</table></div></details>
<footer>Taxes are estimates. Deposits and withdrawals are always done by you in the broker app. Not financial advice.</footer>
</div><div id="tip" role="tooltip"></div>
<script>
(function(){{var t=document.getElementById('tip');
function show(el,x,y){{t.textContent=el.getAttribute('data-tip');t.style.opacity=1;var r=t.getBoundingClientRect();
var nx=Math.min(x+14,innerWidth-r.width-8),ny=y-r.height-12;if(ny<8)ny=y+16;t.style.left=nx+'px';t.style.top=ny+'px';}}
document.querySelectorAll('[data-tip]').forEach(function(el){{
el.addEventListener('mousemove',function(ev){{show(el,ev.clientX,ev.clientY)}});
el.addEventListener('mouseleave',function(){{t.style.opacity=0}});
el.addEventListener('focus',function(){{var b=el.getBoundingClientRect();show(el,b.left+b.width/2,b.top)}});
el.addEventListener('blur',function(){{t.style.opacity=0}});
el.addEventListener('touchstart',function(ev){{var p=ev.touches[0];show(el,p.clientX,p.clientY)}},{{passive:true}});
}});}})();
</script></body></html>"""


def render_email_images(d, outdir):
    """Static PNG charts for the email body (email clients can't run hover). Returns list of paths."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    INK, MUT, LINE, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
    plt.rcParams.update({"font.size": 11, "text.color": INK, "axes.edgecolor": LINE, "axes.labelcolor": MUT,
                         "xtick.color": MUT, "ytick.color": INK, "font.family": "DejaVu Sans", "text.parse_math": False})
    cdat = chart_data(d)
    goal = d["goal"]
    paths = []
    for ccy, c in d["per_ccy"].items():
        cd = cdat[ccy]
        sym = SYM[ccy]
        fig = plt.figure(figsize=(6.4, 7.6), dpi=150, facecolor=SURF)
        gs = fig.add_gridspec(4, 1, height_ratios=[1.15, 1.5, 1.4, 1.4], hspace=0.75, left=0.24, right=0.86, top=0.97, bottom=0.04)
        # hero + goal bullet
        ax = fig.add_subplot(gs[0]); ax.set_axis_off()
        col = POS if c["net"] >= 0 else NEG
        fig.text(0.05, 0.955, ("INDIA · ₹" if ccy == "INR" else "US · $") + "  —  NET MONTH TO DATE, AFTER ALL COSTS", fontsize=9, color=MUT)
        fig.text(0.05, 0.90, fmt(ccy, c["net"], True), fontsize=30, fontweight="bold", color=col)
        pct = c["net_pct"] or 0
        fig.text(0.05, 0.868, f"{pct:+.2f}% of {fmt(ccy, c['budget'])} budget  ·  goal {goal.get('min', 8)}–{goal.get('max', 16)}% / month  ·  unrealised {fmt(ccy, c['unrealised'], True)}", fontsize=9, color=MUT)
        axg = fig.add_axes([0.05, 0.815, 0.9, 0.03])
        gmin, gmax = goal.get("min", 8), goal.get("max", 16)
        lo, hi = min(-5, pct - 2), max(gmax * 1.25, pct + 2)
        axg.barh(0, gmax - gmin, left=gmin, height=1, color="#1baf7a", alpha=0.2)
        axg.barh(0, pct, height=0.45, color=col)
        axg.axvline(0, color=LINE); axg.set_xlim(lo, hi); axg.set_yticks([]); axg.set_xticks([0, gmin, gmax]); axg.set_xticklabels(["0%", f"{gmin}%", f"{gmax}%"], fontsize=8)
        for sp in axg.spines.values(): sp.set_visible(False)

        def hbar(axx, rows, title):
            axx.set_title(title, loc="left", fontsize=11, fontweight="bold", color=INK, x=-0.3)
            if not rows:
                axx.text(0, 0.5, "Nothing yet", color=MUT, transform=axx.transAxes); axx.set_axis_off(); return
            labs = [r[0] for r in rows]; vals = [r[1] for r in rows]
            axx.barh(labs, vals, color=[POS if v >= 0 else NEG for v in vals], height=0.55)
            axx.set_ylim(max(len(vals), 4) - 0.4, -0.6)
            axx.axvline(0, color=LINE, lw=1)
            span = max(abs(v) for v in vals) or 1
            axx.set_xlim(min(0, min(vals)) - span * 0.05, max(0, max(vals)) + span * 0.05)
            for i, v in enumerate(vals):
                axx.annotate(fmt(ccy, v, True), (1.0, i), xycoords=("axes fraction", "data"), xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
            axx.set_xticks([]);
            for sp in ("top", "right", "bottom", "left"): axx.spines[sp].set_visible(False)
            axx.tick_params(axis="y", length=0)
        hbar(fig.add_subplot(gs[1]), [(r[0], r[1]) for r in cd["costs"]], "Where the money went")
        axl = fig.add_subplot(gs[2])
        axl.set_title("Equity curve — cumulative realised P&L", loc="left", fontsize=11, fontweight="bold", x=-0.3)
        if len(cd["curve"]) >= 2:
            ys = [0] + [v for _, v in cd["curve"]]
            axl.plot(range(len(ys)), ys, color=ACC, lw=2, marker="o", ms=4)
            axl.axhline(0, color=LINE, ls="--", lw=1)
            axl.set_xticks([1, len(ys) - 1]); axl.set_xticklabels([cd["curve"][0][0], cd["curve"][-1][0]], fontsize=8)
            axl.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{sym}{v:,.0f}"))
            axl.tick_params(axis="y", labelsize=8, colors=MUT)
            for sp in ("top", "right"): axl.spines[sp].set_visible(False)
        else:
            axl.text(0, 0.5, "Appears after two closed trades", color=MUT, transform=axl.transAxes); axl.set_axis_off()
        hbar(fig.add_subplot(gs[3]), [(r[0], r[1]) for r in cd["positions"]], "Open positions — unrealised P&L")
        pth = os.path.join(outdir, f"glance_{ccy}.png")
        fig.savefig(pth, facecolor=SURF, dpi=110); plt.close(fig)
        try:
            from PIL import Image
            Image.open(pth).convert("RGB").quantize(colors=48, method=Image.Quantize.MEDIANCUT).save(pth, optimize=True)
        except Exception:
            pass
        paths.append(pth)
    return paths


def render_email_rich(d, notes, title, n_images):
    """Email body for clients that allow inline images (Gmail inline attachments).
    Images are referenced as cid:img<N>; the sender swaps in whatever inline syntax its tool needs."""
    e = html.escape
    parts = [f'<div style="font-family:Segoe UI,Arial,sans-serif;color:#0b0b0b;max-width:640px">',
             f'<h2 style="margin:0 0 4px">{e(title)}</h2>',
             f'<p style="margin:0 0 12px;color:#52514e">Mode: {e(d["mode"].upper())}'
             + (f' until {e(d["paper_until"])}' if d["paper_until"] and d["mode"] == "paper" else "") + "</p>"]
    if notes.get("headline"):
        parts.append(f'<p style="font-size:16px;margin:0 0 14px"><b>{e(notes["headline"])}</b></p>')
    for i in range(n_images):
        parts.append(f'<p style="margin:0 0 10px"><img src="cid:{i}" width="600" style="max-width:100%;border:1px solid #e4e3df;border-radius:10px"></p>')
    if notes.get("needs_you"):
        parts.append('<p style="margin:14px 0 4px"><b>Needs you</b></p><ul style="margin:0">' + "".join(f"<li>{e(x)}</li>" for x in notes["needs_you"]) + "</ul>")
    parts.append('<p style="margin:16px 0 0;color:#52514e;font-size:13px">📎 Open the attached <b>interactive report</b> in your browser — hover or tap any chart for details.</p>'
                 '<p style="color:#52514e;font-size:12px">Taxes are estimates. Deposits and withdrawals are always done by you. Not financial advice.</p></div>')
    return "\n".join(parts)


def render_html_classic(d, notes, title):
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


def render_email_charts(d, notes, title):
    """Glanceable email: charts built from table cells (bgcolor/width), no images, no scripts.
    Hover a bar (desktop mail) for its details via title= tooltips."""
    e = html.escape
    goal = d["goal"]
    cdat = chart_data(d)
    F = "font-family:Segoe UI,Helvetica,Arial,sans-serif"
    MUT, LINE, GBAND = "#52514e", "#e4e3df", "#d3efe3"

    def bar_rows(rows, ccy):
        if not rows:
            return f'<p style="{F};color:{MUT};font-size:13px;margin:4px 0">Nothing yet.</p>'
        span = max(abs(v) for _, v, _ in rows) or 1
        neg_any = any(v < 0 for _, v, _ in rows)
        pos_any = any(v > 0 for _, v, _ in rows)
        L = 50 if (neg_any and pos_any) else (100 if neg_any else 0)   # % width given to the negative side
        out = [f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{F};font-size:13px">']
        for lab, v, tip in rows:
            w = max(int(abs(v) / span * 100), 1 if v else 0)
            col = POS if v >= 0 else NEG
            negcell = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td width="{100 - w}%"></td>'
                       f'<td width="{w}%" bgcolor="{col}" height="12" style="background:{col};border-radius:3px" title="{_tip(tip)}"></td></tr></table>') if v < 0 else ""
            poscell = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                       f'<td width="{w}%" bgcolor="{col}" height="12" style="background:{col};border-radius:3px" title="{_tip(tip)}"></td><td width="{100 - w}%"></td></tr></table>') if v > 0 else ""
            out.append(f'<tr title="{_tip(tip)}"><td width="26%" style="padding:5px 8px 5px 0;text-align:right;color:#0b0b0b;white-space:nowrap">{e(lab)}</td>'
                       + (f'<td width="{int(L * 0.56)}%" style="padding:5px 0;border-right:1px solid {LINE}">{negcell}</td>' if L else "")
                       + (f'<td width="{int((100 - L) * 0.56)}%" style="padding:5px 0;border-left:1px solid {LINE}">{poscell}</td>' if L < 100 else "")
                       + f'<td width="18%" style="padding:5px 0 5px 8px;text-align:right;white-space:nowrap;color:#0b0b0b">{e(fmt(ccy, v, True))}</td></tr>')
        out.append("</table>")
        return "".join(out)

    def goal_bar(pct, gmin, gmax):
        lo, hi = min(-5.0, pct - 2), max(gmax * 1.25, pct + 2)
        P = lambda v: int(round((v - lo) / (hi - lo) * 100))
        z, a, b, x = P(0), P(gmin), P(gmax), P(pct)
        col = POS if pct >= 0 else NEG
        # row 1: progress bar from 0 to pct; row 2: goal band
        left, right = sorted([z, x])
        r1 = (f'<td width="{left}%"></td><td width="{max(right - left, 1)}%" bgcolor="{col}" height="8" style="background:{col};border-radius:3px" '
              f'title="{_tip(f"Month to date {pct:+.2f}% of budget, after all costs")}"></td><td width="{100 - right}%"></td>')
        r2 = (f'<td width="{a}%" style="font-size:10px;color:{MUT}">{"0%" if z < a else ""}</td>'
              f'<td width="{b - a}%" bgcolor="{GBAND}" height="8" style="background:{GBAND};border-radius:3px;font-size:10px;color:{MUT};text-align:center" '
              f'title="{_tip(f"Goal band {gmin}–{gmax}% a month after all costs")}">goal {gmin}–{gmax}%</td><td width="{100 - b}%"></td>')
        return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{F};margin:6px 0 2px"><tr>{r1}</tr></table>'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{F};margin:2px 0 0"><tr>{r2}</tr></table>')

    def alloc_bar(parts, ccy):
        tot = sum(v for _, v in parts) or 1
        cells = "".join(f'<td width="{max(int(v / tot * 100), 1)}%" bgcolor="{ASSET_COLOR.get(l, "#999")}" height="14" '
                        f'style="background:{ASSET_COLOR.get(l, "#999")};border-right:2px solid #fff" title="{_tip(f"{l}: {fmt(ccy, v)} ({100 * v / tot:.0f}%)")}"></td>'
                        for l, v in parts)
        leg = " &nbsp; ".join(f'<span style="color:{ASSET_COLOR.get(l, "#999")}">■</span> {e(l)} {100 * v / tot:.0f}%' for l, v in parts)
        return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'
                f'<p style="{F};font-size:12px;color:{MUT};margin:4px 0 0">{leg}</p>')

    def card(inner):
        return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 12px">'
                f'<tr><td style="border:1px solid {LINE};border-radius:12px;padding:14px 16px;background:#ffffff">{inner}</td></tr></table>')

    def h(t, sub=""):
        return f'<p style="{F};font-size:14px;font-weight:600;margin:0 0 6px;color:#0b0b0b">{e(t)} <span style="font-weight:400;color:{MUT};font-size:12px">{e(sub)}</span></p>'

    out = [f'<div style="{F};color:#0b0b0b;max-width:640px;margin:0 auto">',
           f'<p style="margin:0;font-size:20px;font-weight:700">{e(title)}</p>',
           f'<p style="margin:2px 0 12px;color:{MUT};font-size:12px">Mode {e(d["mode"].upper())}'
           + (f' until {e(d["paper_until"])}' if d["paper_until"] and d["mode"] == "paper" else "")
           + ' · hover any bar for details</p>']
    if notes.get("headline"):
        out.append(card(f'<p style="{F};margin:0;font-size:15px"><b>{e(notes["headline"])}</b></p>'))
    for ccy, c in d["per_ccy"].items():
        cd = cdat[ccy]
        col = POS if c["net"] > 0 else (NEG if c["net"] < 0 else "#0b0b0b")
        pct = c["net_pct"] or 0
        hero = (f'<p style="{F};margin:0;font-size:11px;letter-spacing:.05em;color:{MUT}">{"INDIA · ₹" if ccy == "INR" else "US · $"} — NET MONTH TO DATE, AFTER ALL COSTS</p>'
                f'<p style="{F};margin:2px 0;font-size:34px;font-weight:700;color:{col}" title="{_tip(f"Gross {fmt(ccy, c[chr(103)+"ross"], True)} − brokerage {fmt(ccy, c[chr(102)+"ees"])} − tax {fmt(ccy, c[chr(116)+"ax"])} − AI {fmt(ccy, c[chr(97)+"i"])}")}">{e(fmt(ccy, c["net"], True))}</p>'
                f'<p style="{F};margin:0;font-size:12px;color:{MUT}">{pct:+.2f}% of {e(fmt(ccy, c["budget"]))} · {c["closed"]} closed, {c["wins"]} won · unrealised {e(fmt(ccy, c["unrealised"], True))}</p>'
                + (goal_bar(pct, goal.get("min", 8), goal.get("max", 16)) if goal else ""))
        out.append(card(hero))
        out.append(card(h("Where the money went") + bar_rows(cd["costs"], ccy)))
        trades = [(f"{t['symbol']}", t["pnl"], f"{t['symbol']} closed {t.get('closed', '')[:10]}: {fmt(ccy, t['pnl'], True)} — {t.get('note') or ''}")
                  for k, t, p in d["actions"] if k == "Closed" and t["currency"] == ccy]
        if trades:
            out.append(card(h("Closed trades", "realised P&L") + bar_rows(trades, ccy)))
        out.append(card(h("Open positions", "unrealised P&L") + bar_rows(cd["positions"], ccy)))
        if cd["alloc"]:
            out.append(card(h("Capital allocation") + alloc_bar(cd["alloc"], ccy)))
    for key, label in (("trends", "Trends"), ("needs_you", "Needs you")):
        items = notes.get(key, [])
        if items:
            out.append(card(h(label) + f'<ul style="{F};margin:0;padding-left:18px;font-size:13px">' + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>"))
    out.append(f'<p style="{F};color:{MUT};font-size:11px;margin:8px 0 0">Full interactive report (all charts, hover details, trade log) is saved on your computer in trader-data/reports/. '
               'Taxes are estimates. Deposits and withdrawals are always done by you. Not financial advice.</p></div>')
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
    p.add_argument("--market", choices=["IN", "US"], help="only this market (separate India / US reports)")
    p.add_argument("--html", help="interactive report with hover tooltips")
    p.add_argument("--email", help="plain email HTML (tables/lists) for sanitizing senders")
    p.add_argument("--email-rich", help="email HTML with inline chart images (cid:img0..)")
    p.add_argument("--images", help="folder for email chart PNGs (used with --email-rich)")
    p.add_argument("--email-charts", help="email HTML with charts built from table cells (no images) — default for daily email")
    p.add_argument("--deck")
    a = p.parse_args()
    ledger, profile = json.load(open(a.ledger)), json.load(open(a.profile))
    if a.market:
        ledger = dict(ledger, trades=[t for t in ledger["trades"] if t["market"] == a.market],
                      sips=[x for x in ledger.get("sips", []) if x.get("market") == a.market])
        ccy = "INR" if a.market == "IN" else "USD"
        profile = json.loads(json.dumps(profile))
        for k in ("budget",):
            if k in profile.get("trading", {}):
                profile["trading"][k] = {ccy: profile["trading"][k].get(ccy)}
    notes = json.load(open(a.notes)) if a.notes and os.path.exists(a.notes) else {}
    date = a.date or datetime.now(timezone.utc).date().isoformat()
    d = compute(ledger, profile, json.loads(a.prices), a.period, date)
    mk = {"IN": "India ", "US": "US "}.get(a.market or "", "")
    title = f"TraderSkill {mk}{'daily' if a.period == 'day' else 'monthly'} report — " + (
        datetime.fromisoformat(date).strftime("%a %d %b %Y") if a.period == "day" else d["month"])
    for path, fn in ((a.html, lambda: render_html(d, notes, title)), (a.email, lambda: render_email(d, notes, title))):
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            open(path, "w").write(fn())
            print(f"wrote {path}")
    if a.email_charts:
        os.makedirs(os.path.dirname(os.path.abspath(a.email_charts)), exist_ok=True)
        open(a.email_charts, "w").write(render_email_charts(d, notes, title))
        print(f"wrote {a.email_charts}")
    if a.email_rich:
        imgs = render_email_images(d, a.images or os.path.join(os.path.dirname(os.path.abspath(a.email_rich)), "img"))
        os.makedirs(os.path.dirname(os.path.abspath(a.email_rich)), exist_ok=True)
        open(a.email_rich, "w").write(render_email_rich(d, notes, title, len(imgs)))
        print(f"wrote {a.email_rich}")
        for pth in imgs:
            print(f"wrote {pth}")
    if a.deck:
        render_deck(d, notes, title, a.deck)
        print(f"wrote {a.deck}")
    if not (a.html or a.email or a.deck or a.email_rich or a.email_charts):
        print(render_email(d, notes, title))


if __name__ == "__main__":
    main()
