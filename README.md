# TraderSkill

An agent skill (for Claude and other agents that read `SKILL.md`) that acts as a **paper-first trading copilot for US and Indian markets**: stocks, options, futures and crypto, across day trading, swing trading and long-term investing.

## What it does

- **Protects a small account**: trading capped at $500 / ₹50,000 per trade, money at risk capped at 2% of the trading budget, daily loss limit, allocation % per asset class, no naked option selling. Caps only go down automatically.
- **Paper trading for any broker**, including ones with no sandbox (Zerodha), through a local ledger at real prices. Live orders need `mode: live` *and* confirmation of each order.
- **Broker map** for Webull, Alpaca, Interactive Brokers, tastytrade, Schwab, Tradier, E*TRADE, Robinhood (crypto), Coinbase, Kraken, Zerodha, Upstox, Angel One, Dhan, Fyers, ICICI Breeze, Kotak Neo, Shoonya and Groww. Works with Alpaca's official skills (`alpacahq/alpaca-skills`).
- **Backtests** ideas on up to 10 years of daily data (`buy_hold`, `sma_cross`, `breakout`, `rsi_reversion`).
- **Learns from history and big investors**: 2016–2026 market regimes and famous US/Indian investors' public holdings.
- **Continuous learning**: every trade is journalled with a thesis; `lessons.md` is updated from evidence and read at the start of every session.
- **Official add-ons under your rules** (`addons/`): Alpaca paper trading & backtest, Upstox trading, and Anthropic equity-research skills (thesis tracker, earnings preview/analysis, catalysts, ideas, sector overview, DCF, comps). Each is renamed `ADDON.md` so it only runs through trader-skill's risk check and journal. Official broker MCP connectors (Zerodha Kite, Upstox, Fyers, Kotak Neo, Dhan, Groww) are mapped with what each can do.
- **Monthly after-tax report** against a goal (default 8–16% a month on the trading budget).

## About the monthly goal

8–16% a month compounds to roughly 150–490% a year — far above what even the best-known long-term investors achieve (Berkshire Hathaway has averaged about 20% a year since 1965). The skill tracks the goal honestly and **never adds risk to chase it**. Most retail traders lose money (SEBI found ~9 in 10 individual F&O traders lost money in FY22). Use money you can afford to lose. Nothing here is financial or tax advice.

## Install

```bash
npx skills add masarfaraz03/TraderSkill
```

or copy this folder to `~/.claude/skills/trader-skill/`.

## Layout

```
SKILL.md                       instructions the agent follows
scripts/risk_check.py          checks an order against your caps
scripts/ledger.py              paper/live ledger, journal, stats, monthly after-tax report
scripts/backtest.py            daily-bar backtester (CSV or yfinance)
references/brokers.md          US & India broker APIs, paper support, symbols, rules
references/market-history.md   2016–2026 regimes and lessons
references/investors.md        big investors and how to look up their holdings
assets/profile.template.json   default caps, allocation, goal, tax rates
assets/lessons.template.md     starter lessons file
addons/                        official third-party skills, guarded (see addons/THIRD_PARTY.md)
evals/                         test cases
```

Your personal data (`trader-data/`: profile, ledger, lessons) is created at first use and is git-ignored.
