# Third-party add-ons

Official skills bundled under trader-skill's guardrails. Each `SKILL.md` was renamed `ADDON.md` so it is reachable only through trader-skill (it never triggers on its own and bypasses the risk rules), and a guardrail block was added at the top. Content is otherwise unchanged.

| Folder | Source | Author | License | Fetched |
|---|---|---|---|---|
| `alpaca/` (backtest, paper-trading, paper-trading-cli, paper-trading-mcp) | github.com/alpacahq/alpaca-skills `skills/trading-api/` | Alpaca (official) | Apache-2.0 | 2026-11-05 |
| `zerodha/` (kite CLI skill + CLI reference snapshot; `TRADERSKILL-NOTES.md` is ours) | github.com/zerodha/kite-cli `skills/kite/`, `docs/CLI_REFERENCE.md` | Zerodha (official) | MIT | 2026-11-05 |
| `upstox/` | github.com/upstox/upstox-skills `skills/upstox/` | Upstox (official) | MIT | 2026-11-05 |
| `research/` (thesis-tracker, earnings-preview, earnings-analysis, catalyst-calendar, idea-generation, sector-overview, dcf-model, comps-analysis) | github.com/anthropics/financial-services-plugins | Anthropic (official) | Apache-2.0 | 2026-11-05 |

To update: re-copy from the source, rename `SKILL.md` → `ADDON.md`, keep the guardrail block, and re-run the trader-skill tests.

Not bundled (reviewed 2026-11-05): community IBKR/options skills (staskh/trading_skills — places stop orders, single author), community Robinhood skills, and a 500-skill algo-trading collection — unknown authors and too broad to vet. Use only with the same guardrails if added later.
