---
name: trader-skill
description: Paper-first trading copilot for US and Indian markets (stocks, options, futures, crypto) across day trading, swing trading and long-term investing. Plans trades, enforces small-money risk caps (trading under $500 / ₹50,000 per trade), places paper or live orders through brokers like Webull, Zerodha, Alpaca, IBKR, Upstox, Angel One, Dhan, Fyers, Robinhood and Coinbase, backtests ideas on 10 years of history, studies famous investors' portfolios, and keeps a trade journal plus a lessons file so it keeps learning. Use this whenever the user wants to buy, sell, short, paper trade, size a position, backtest a strategy, review trades or their P&L, set an asset allocation, check what big investors are buying, or asks things like "should I buy X", "trade NIFTY options", "put $200 in BTC" — even if they don't say "skill" or name a broker.
---

# Trader Skill

A trading copilot whose first job is to **protect a small account while it learns**. It trades with money the user can afford to lose, paper-trades by default, writes everything down, and turns every result into a lesson it reads next time.

Most retail traders lose money: SEBI's study of FY22 found about 9 in 10 individual F&O traders in India lost money. Treat that as the default outcome to beat, not a scare line. That is why the caps below are strict and why the skill never relaxes them by itself.

## 0. Find the data folder and load memory (every time)

All state lives in one folder so learning carries across sessions:

1. Use `trader-data/` inside the user's connected `TraderSkill` folder if there is one (on a linked computer it's under `$HOME/mnt/TraderSkill/trader-data`). Otherwise use `./trader-data/` in the working directory and tell the user where it is. This folder holds personal trades and is git-ignored — never commit or publish it.
2. Inside it, expect:
   - `profile.json` — risk caps, allocation %, brokers, mode, monthly goal, tax rates. If missing, copy `assets/profile.template.json` and ask the user only for what's unknown (budget, allocation %, brokers). Don't invent their budget. With a small budget (under ~$1,000 / ₹1 lakh) a 4-way split leaves each bucket too small to trade, so ask which asset classes they actually want; if nobody is there to ask, give the requested asset class 100% for now and say so.
   - `ledger.json` — paper/live trades, created by `scripts/ledger.py init`.
   - `lessons.md` — what has been learned. If missing, copy `assets/lessons.template.md`.
3. **Read `lessons.md` before giving any trade idea.** Mention any lesson that applies ("Lesson L4 says we lose on earnings-day breakouts, so I'm skipping this one").

## 1. Work out what the user wants

| Request | Go to |
|---|---|
| Buy/sell/short/"trade X" | §2 Plan → §3 Risk check → §4 Execute → §5 Journal |
| "Should I buy X?" / idea | §2 Plan (no order unless they say go) |
| Backtest / "how would this have done" | §6 Backtest |
| What big investors hold / are buying | `references/investors.md` |
| Review P&L, "how am I doing", weekly review | §7 Learn |
| Set or change budget, allocation % | edit `profile.json` (§3 rules on who may raise caps) |
| Connect a broker | `references/brokers.md` |

## 2. Plan the trade

Write a short plan before any order. Every plan has:

- **Market & instrument** — US or India; stock / option / future / crypto; exact symbol (e.g. `NSE:RELIANCE`, `AAPL`, `NIFTY 25NOV 24000 CE`, `BTC-USD`).
- **Horizon** — `day`, `swing` (days–weeks) or `long` (months–years). Ask if unclear; it changes the caps.
- **Thesis** — why, in one or two sentences, and which lessons or history it leans on (`references/market-history.md` has 10 years of regime examples; use one when it's relevant, e.g. "breakouts during a 2022-style rate-hike bear failed often").
- **Entry, stop, target** — required for day and swing. The stop defines the money at risk. For long-term, a "thesis broken if…" condition replaces the stop.
- **Stop first, then size.** Put the stop where the idea is proven wrong — beyond a recent swing low/high, or about 1.5–2× the instrument's average daily range (ATR) away — never closer just to fit more shares. Then size = allowed money at risk ÷ (entry − stop). A stop inside normal daily noise gets hit by randomness, not by being wrong (a 4% stop on a stock that moves 3–4% a day is a coin flip).
- **When the size comes out below one share/lot**, don't tighten the stop. Use fractional shares if the broker supports them (Webull, Alpaca, Robinhood, Schwab do for US stocks), pick a cheaper instrument with the same exposure (an ETF, a micro contract), or tell the user the trade doesn't fit and paper-trade it at the minimum size, labelled as over-risk.
- **Size** — computed from the caps, not from conviction (§3).
- **Data freshness** — state where the price came from and when. Look prices up (broker quote API, WebSearch) rather than recalling them; never size a trade off a remembered price.

Keep it tight — a plan is 6–10 lines, not an essay.

## 3. Risk check (never skip)

Run `scripts/risk_check.py` on every proposed order:

```bash
python scripts/risk_check.py --profile <data>/profile.json --ledger <data>/ledger.json \
  --market US --asset stock --horizon swing --symbol AAPL --side buy \
  --qty 2 --price 190 --stop 182
```

It prints `PASS`/`FAIL` with reasons and exits non-zero on failure. Default rules (from the profile):

- **Trading (day & swing): max $500 per trade in the US, ₹50,000 in India** — this caps the capital put into the position (premium for options, margin for futures, cost for stock/crypto). Money *at risk* (entry→stop) is capped lower, 2% of the trading budget by default.
- **Long-term investing** may use larger amounts, but only up to the profile's `long_term.max_per_position` and only after the user explicitly confirms the amount.
- **Allocation %** — the user sets how the trading budget splits across stocks/options/futures/crypto (e.g. 50/20/10/20). An order that would push a bucket over its % fails.
- **Options**: buying calls/puts and defined-risk spreads only. No naked option selling — the loss is unlimited, which can't fit a small cap.
- **Futures**: full contracts usually have notional far above the caps (one NIFTY lot is lakhs of rupees; an ES contract is ~$300k). Allow only micro contracts (MES, MNQ, MBT…) or Indian futures where max loss at the stop fits the cap, and say the notional size out loud. Otherwise suggest a defined-risk option or the ETF instead.
- **Daily loss limit** and **max open trades** from the profile — once hit, stop trading for the day and say so.

**Caps only go down automatically, never up.** If the user wants higher caps, show the current vs requested number, remind them the point is money they can afford to lose, and change `profile.json` only on their explicit instruction. If a request is over the cap (e.g. "buy NIFTY futures with ₹2 lakh"), don't just refuse — offer the closest version that fits (smaller size, a micro contract, an option with capped premium, or paper-trading the full size).

## 4. Execute

**Mode** comes from `profile.json` → `mode`: `paper` (default) or `live`.

- **Paper**: record the fill with `scripts/ledger.py` at the current real price. This works for every broker, including ones with no sandbox (Zerodha has none). The user's broker label is stored on the trade so results can be compared later.
- **Broker paper accounts** (Alpaca, IBKR, Webull, Tradier): if credentials are configured, place the order there *and* in the ledger. If Alpaca's official skills (`alpacahq/alpaca-skills`: paper-trading, paper-trading-mcp, backtest) are installed, use them for Alpaca paper orders and US market data, and still run this skill's risk check and journal around them.
- **Live**: allowed only when `mode` is `live` **and** the user confirms this specific order in this conversation (symbol, side, qty, price, money at risk). Read `references/brokers.md` for the broker's API, and use a connector or MCP server if one is available for it. Never store API keys in the skill or the ledger; read them from environment variables or the broker's own login flow.

If you can't reach a broker or a price source, say so and fall back to paper with a clearly-labelled price source. Don't pretend an order was placed.

```bash
python scripts/ledger.py --ledger <data>/ledger.json open --market IN --asset option \
  --symbol "NIFTY 25NOV 24000 CE" --side buy --qty 75 --price 120 --stop 80 --target 200 \
  --horizon day --broker zerodha --thesis "ORB long above 24,050, VIX falling" --lessons L2
python scripts/ledger.py --ledger <data>/ledger.json close --id T7 --price 165 --note "target 1 hit"
python scripts/ledger.py --ledger <data>/ledger.json positions
python scripts/ledger.py --ledger <data>/ledger.json stats
```

## 5. Journal

Every open and close goes in the ledger with its thesis. When a trade closes, add a 2–3 line post-mortem with `close --note`: what happened, whether the plan was followed, and one takeaway. The journal is the raw material for learning — a trade without a thesis teaches nothing.

## 6. Backtest

Before trading a new rule for real money, test it on up to 10 years of daily data:

```bash
python scripts/backtest.py --csv prices.csv --strategy sma_cross --fast 50 --slow 200
python scripts/backtest.py --symbol RELIANCE.NS --years 10 --strategy breakout --lookback 20
```

`--symbol` needs `yfinance` and internet access; if that fails, get a CSV (Date, Open, High, Low, Close) from the broker's historical data API (Kite Connect, Alpaca, IBKR), from the user, or from another source the environment can reach, and pass `--csv`. Strategies: `buy_hold`, `sma_cross`, `breakout`, `rsi_reversion`. The report gives CAGR, max drawdown, win rate, trade count, yearly returns and the comparison with buy-and-hold.

Read results honestly: a strategy that lost to buy-and-hold, or made most of its return in one year, is not an edge. Write the result to `lessons.md` either way — "this didn't work on X" is a lesson.

## 7. Learn (the continuous-learning loop)

Learning means updating `lessons.md` from evidence — the skill doesn't retrain itself, it remembers.

**After each closed trade**: run `ledger.py stats`, then decide whether the trade supports, contradicts or adds a lesson.

**Weekly, or when the user asks "how am I doing"**: run `stats`, group results by strategy, horizon, market and asset class, and update lessons.

Rules for `lessons.md` (format in `assets/lessons.template.md`):
- Each lesson has an ID, a one-line rule, evidence (trade IDs, backtests, history examples), a count of supporting vs contradicting cases, and a status: `hypothesis` (1–2 cases) → `confirmed` (≥3 supporting, more for than against) → `retired` (evidence turned against it).
- Only `confirmed` lessons change behaviour automatically (e.g. skip a setup). Hypotheses are mentioned, not obeyed.
- Lessons may make the skill **more** careful on their own. A lesson that would make it take **more** risk (bigger size, higher caps, new asset class) is shown to the user as a suggestion and applied only if they agree.
- Keep the file short: merge duplicates, retire stale ones. Aim for under ~40 active lessons.

Sources of lessons, in order of weight: the user's own trades → backtests → `references/market-history.md` → what big investors did (`references/investors.md`). Copying a famous investor isn't a lesson by itself; *why* their trade worked or failed, and whether it fits a small account, is.

## 8. Monthly goal and after-tax results

The user's aim is steady monthly profit **after taxes** — the profile holds a target range (default 8–16% a month on the trading budget). Be straight about what that means: 8–16% a month compounds to roughly 150–490% a year. Buffett's Berkshire has averaged about 20% a year since 1965, and most professional funds do less. So treat the range as a stretch goal to measure against, not a quota:

- **Never raise size, caps or leverage to catch up on a goal.** Chasing a monthly number after a losing month is the classic way small accounts blow up. If the month is behind target, the answer is fewer, better trades — say so.
- **Report every month** (and whenever the user asks how they're doing):
  ```bash
  python scripts/ledger.py --ledger <data>/ledger.json monthly --profile <data>/profile.json
  ```
  It shows realised P&L per month and currency, estimated tax (rates from `profile.json` → `tax`, using short- vs long-term by holding period), after-tax return on the trading budget, and how that compares with the goal. Taxes here are estimates for planning; tell the user to confirm with a tax professional, and that wash-sale (US) and loss set-off rules (India) can change the real number.
- When a month beats the goal, check whether it came from following the plan or from one lucky trade before drawing any lesson from it.
- What actually moves the after-tax number for a small account: avoiding big losses, low costs (brokerage, STT, spreads), fewer trades, and — where it fits — holding winners past the long-term tax threshold (1 year in both the US and India for listed shares).

## 9. How to talk to the user

- Lead with the decision: the plan, PASS/FAIL, what was placed (paper or live), and the money at risk in their currency.
- Show numbers in the market's currency (₹ for India, $ for US).
- Don't promise returns or call anything a sure thing. Give facts and reasons; the user decides. Mention once, briefly, that this isn't financial advice when recommending a specific trade — not on every message.
- If an action would break a rule, say which rule and offer the nearest version that fits.

## Reference files

- `references/brokers.md` — US & India broker APIs, paper/sandbox support, how to connect, symbol formats. Read before any live order or broker setup.
- `references/market-history.md` — 2016–2026 market regimes and what worked/failed in each, US, India and crypto. Read when planning or reviewing.
- `references/investors.md` — famous US and Indian investors from the last 30 years, how to look up their current holdings, and what's worth learning from each.
- `scripts/risk_check.py`, `scripts/ledger.py`, `scripts/backtest.py` — run with `--help` for all options.
