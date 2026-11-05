# How trader-skill uses Zerodha `kite` (trading + investing)

Source: Zerodha's official `kite` CLI and agent skill (github.com/zerodha/kite-cli, MIT). Full command reference: `CLI_REFERENCE.md` in this folder (snapshot); `kite <command> --help` is the source of truth.

## Setup (once, on the user's own computer)

1. Install: `curl -fsSL https://raw.githubusercontent.com/zerodha/kite-cli/main/scripts/install.sh | sh` (macOS/Linux). The installer verifies a SHA-256 checksum.
2. The **user** signs in in their own terminal: `kite auth login` (user ID, password, 2FA). Never run this for them or ask for those values. Sessions expire daily (~06:00 IST).
3. Check: `kite --json doctor | jq -e .ok`.

The agent needs to run where `kite` is installed and signed in — normally Claude Code on the user's machine. A cloud session can't use the user's Kite session; there, fall back to paper trading with prices the user gives or a read-only connector (Kite MCP `mcp.kite.trade/mcp`).

## Prices for planning (fixes the data gap)

- Quote: `kite --json market ltp NSE:INFY` / `market quote` for depth.
- 10-year history for `scripts/backtest.py`: resolve the token with `kite --json market resolve NSE:RELIANCE`, then `kite --json historical candles --instrument-token <t> --interval day --from ... --to ...`, convert to CSV (Date, Open, High, Low, Close) and pass `--csv`.
- ATR for stop placement: compute from the last ~20 daily candles.

## Map trader-skill horizons to Kite products

| trader-skill | Kite `--product` | Notes |
|---|---|---|
| `day` (intraday equity/F&O) | `MIS` | Auto square-off near 3:20 pm; place the stop as an `SL`/`SL-M` order right after the fill |
| `swing` (equity) | `CNC` | Delivery; protect with a GTT (single-leg stop or OCO stop+target) |
| `swing` (F&O) | `NRML` | Futures/options carried overnight; check lot size and margin with `kite --json margins orders ...` |
| `long` (investing) | `CNC` | Delivery shares/ETFs; prefer LIMIT orders; staggered buys are fine |

## Order flow (every order)

1. Plan (§2) with a live `ltp`, stop first, then size.
2. `risk_check.py` → stop on FAIL.
3. Paper mode: record with `ledger.py open --broker zerodha` at the live price. Done.
4. Live mode: run the kite command **without** `--confirm` (dry run), show the exact request, get the user's approval for that request, then run the identical command with `--confirm`. One approval = one request.
5. Place the protective stop (SL order for MIS, GTT for CNC/NRML) the same way — dry run, approve, confirm.
6. Record in `ledger.py` (mode `live`, the Kite order ID in the thesis/notes). On a timeout, check `kite --json orders list` before retrying so nothing is placed twice.
7. Before using margin numbers, run `kite --json user margins` and `margins charges` so costs show up in the plan.

## Mutual funds and SIPs (long-term investing)

- Read: `kite --json mf holdings`, `mf sips`, `mf orders`, `mf search "<fund>"`, `mf instruments`.
- Placing a lumpsum MF order or creating/modifying a SIP has no dedicated `kite mf` write command; use the Kite Connect endpoints through the raw request command, which is also a dry run until `--confirm`:
  `kite --json request post /mf/orders ...` and `kite --json request post /mf/sips ...` — check the exact fields in the Kite Connect v3 docs (kite.trade/docs/connect/v3/mf/) before building the request, and show the dry run to the user.
- MF/SIP amounts count against `long_term.max_per_position` (per fund) and need the user's confirmation of the amount.

## Never

- Sign in, log out, read `config.json`, or print tokens/API keys.
- Open the TUI (`kite` with no args).
- Use `--confirm` without the user's approval of that exact request in this conversation.
