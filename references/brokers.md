# Broker connections (US & India)

Broker APIs, prices and rules change often. Treat this file as a map, and **check the broker's current developer docs (WebSearch/WebFetch) before the first live connection**. Never put API keys in the skill, the ledger or chat; use environment variables (e.g. `KITE_API_KEY`, `ALPACA_API_KEY`) or the broker's login flow.

Before building an adapter, check whether a connector or MCP server for the broker is already available in the session (ToolSearch / connector registry). Use it if it exists.

## Common order interface

Whatever the broker, map the plan to: `market, asset, symbol, side, qty, order_type (market/limit/stop), limit_price, stop_price, product (intraday/delivery/margin), validity`. Prefer **limit orders** for small accounts; market orders in thin options/crypto can fill far from the quote. Place the stop as a real broker order when the broker supports it (bracket/OCO/GTT), not just in the plan.

## Paper trading options

| How | Works for |
|---|---|
| `scripts/ledger.py` local paper fills at real prices | every broker, including ones with no sandbox |
| Broker paper/sandbox account via API | Alpaca, IBKR, tastytrade, Tradier, E*TRADE, Webull (OpenAPI simulation) |

## United States

| Broker | API | Assets via API | Paper / sandbox | Notes |
|---|---|---|---|---|
| **Webull** (user's broker) | Webull OpenAPI (developer.webull.com); apply for access. An unofficial-looking `webull-openapi-mcp` package also exists on PyPI — verify its publisher before use | stocks, ETFs, options (check docs for crypto/futures) | Webull announced OpenAPI multi-asset paper simulation in 2026 | App also has paper trading for manual practice |
| Alpaca | alpaca-py, REST + websockets | stocks, ETFs, options, crypto | Yes, free paper account (`paper-api.alpaca.markets`) | Easiest paper API; free market data tier |
| Interactive Brokers | TWS API, Client Portal Web API; `ib_async` | stocks, options, futures incl. micros, forex, crypto | Yes, paper account | Broadest asset coverage; needs TWS/Gateway running |
| tastytrade | Open API | stocks, options, futures, crypto | Yes, sandbox (cert) | Options-friendly |
| Charles Schwab | Schwab Trader API; `schwab-py` | stocks, ETFs, options | No API paper (thinkorswim paperMoney is manual) | Token refresh every 7 days |
| Tradier | REST | stocks, options | Yes, sandbox | |
| E*TRADE | REST | stocks, options | Yes, sandbox | |
| Robinhood | Official Crypto Trading API | crypto only | No | No official stock API |
| Coinbase | Advanced Trade API | crypto | Partial sandbox | |
| Kraken | REST/WebSocket | crypto, crypto futures (where allowed) | Futures demo | |

**Alpaca's official agent skills** — `npx skills add alpacahq/alpaca-skills` (github.com/alpacahq/alpaca-skills) installs skills for paper trading (CLI or MCP), backtesting, orders and market data. Needs the Alpaca CLI and paper API keys. Use them for Alpaca execution/data; keep this skill's risk check and journal around them.

US symbols: `AAPL`, options OCC style (`AAPL 251121C00200000`), micro futures `MES`, `MNQ`, `MBT`; crypto `BTC-USD`. US equity options multiplier is 100.

**Pattern day trader rule**: margin accounts under $25,000 are limited to 3 day trades in 5 business days (FINRA has been reviewing changes to this rule; check current status). Cash accounts avoid it but must wait for settlement.

## India

| Broker | API | Cost (check current) | Paper / sandbox | Notes |
|---|---|---|---|---|
| **Zerodha** (user's broker) | Kite Connect; `kiteconnect` | Personal: free (orders, no market data). Connect: ~₹2,000/month incl. live quotes + historical data (bundled since Feb 2025) | **No sandbox** → use `ledger.py` paper fills | **Official `kite` CLI + agent skill** (bundled as `addons/zerodha/`) does quotes, history, orders, GTT, MF/SIP; user runs `kite auth login` daily. GTT orders for stops |
| Upstox | Upstox API v2/v3; `upstox-python-sdk` | free | Check docs (sandbox for order APIs announced) | |
| Angel One | SmartAPI; `smartapi-python` | free | No | TOTP login |
| Dhan | DhanHQ; `dhanhq` | trading free, data paid | No | |
| Fyers | Fyers API v3; `fyers-apiv3` | free | No | |
| ICICI Direct | Breeze API | free, includes historical data | No | |
| Kotak Securities | Neo API | free | No | |
| Shoonya (Finvasia) | Shoonya API | free | No | |
| Groww | Trading API (launched 2025) | check | No | |
| Crypto (India) | CoinDCX, Mudrex, WazirX APIs | — | No | 30% tax on gains + 1% TDS per sale; losses can't offset other income |

**Official broker MCP servers (India, checked Oct 2026)**: Zerodha `mcp.kite.trade/mcp` (read-only except GTT; open-source code github.com/zerodha/kite-mcp-server has order tools if self-hosted), Upstox `mcp.upstox.com/mcp` (read-only, re-auth daily), Fyers `mcp.fyers.in/mcp` (read-only), Kotak Neo `neo.kotaksecurities.com/mcp-server/mcp` (read-only), Dhan `mcp.dhan.co/mcp` (orders), Groww `mcp.groww.in/mcp` (orders; sells need DDPI). Angel One has no official server — avoid community ones that need your PIN/TOTP. Upstox also publishes an official agent skill, bundled as `addons/upstox/`.

**OpenAlgo** (open source, docs.openalgo.in) gives one API across 20+ Indian brokers; useful if the user wants several Indian brokers behind one adapter.

Indian symbols: `NSE:RELIANCE`, `BSE:500325`, F&O on NFO e.g. `NFO:NIFTY25NOV24000CE`. **Lot sizes and expiry days change** (SEBI raised minimum F&O contract values and cut weekly expiries to one index per exchange from Nov 2024) — look up the current lot size before sizing; one NIFTY lot is worth lakhs of rupees, so plain index futures rarely fit a ₹50,000 cap.

**SEBI retail algo framework** (circular Feb 2025, phased in from late 2025): API orders go through broker-approved setups, may need a registered static IP, and strategies above an order-rate threshold need exchange registration. Check the user's broker for current requirements before automating live orders.

## Connecting a broker — steps

1. Confirm the broker and whether the user wants paper (sandbox) or live.
2. Point them to the developer portal to create an app / API key; they keep the secret.
3. Store keys as environment variables on their machine; never echo them back.
4. Test with a read-only call (profile, funds, positions) before any order.
5. Record the broker name in `profile.json` → `brokers`.
