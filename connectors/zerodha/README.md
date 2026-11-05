# TraderSkill Zerodha connector

Your own Zerodha connector for Claude. It has two parts:

1. **A local connector on your Mac** (`server.py`) that Claude uses for quotes, candles and ATR, holdings, positions, margins, orders, GTTs and gated live orders. Cowork sessions see it as `zerodha`.
2. **A one-tap phone login.** This is a small callback (a Supabase Edge Function) that turns your morning Zerodha login into the day's session, so Claude can carry on without you at the Mac.

## What it can't do, by design

- **It can't skip your daily login.** Zerodha ends every API session around 06:00 IST, and Indian rules require *your* 2FA for a new one. The connector never stores or types your password or TOTP. You tap one link on your phone, approve in Zerodha, and you're done for the day.
- **It never moves money.** Kite Connect has no fund-transfer API, and the connector adds none.
- **Live orders are double-locked.** They're refused unless `profile.json` → `mode` is `live` and `risk_check.py` passes. Even then they're two-step: the preview gives a one-time code (valid 10 minutes), you confirm that exact order in the chat, and only then is it sent. Scheduled runs never place orders.

## Costs to know

| Kite Connect plan | Price | What you get here |
|---|---|---|
| Personal | Free | Holdings, positions, margins, orders and GTT. **No live quotes or history**, so the connector uses Yahoo Finance prices (may be delayed) |
| Connect | ₹500/month per app | Adds real-time quotes and historical candles straight from Zerodha |

On a ₹10,000 trading budget, ₹500 a month is 5% of the budget before any trade. Starting with **Personal** is sensible. Zerodha also says that from 1 April 2026 **placing orders through the API needs a static IP** registered in your developer profile. That only matters once you go live, and reading data works from any IP.

## Setup (about 15 minutes, once)

**0. Install on your Mac.** Double-click `connectors/zerodha/install.command`. It installs one Python package (`cryptography`), makes your login keys in `trader-data/`, and adds the `zerodha` connector to the Claude desktop app. Then quit and reopen Claude.

**1. Create the Kite developer app.** Go to <https://developers.kite.trade>, sign in with your Zerodha ID, and choose **Create new app**.
- Type: **Personal** (free) to start.
- App name: `TraderSkill`. Zerodha Client ID: your client ID.
- Redirect URL: the callback URL Claude gives you, which looks like `https://<project>.supabase.co/functions/v1/kite-session/callback`.
- Postback URL: leave it empty.

**2. Put the API key on your Mac.** Open `trader-data/secrets.env` in TextEdit and set `KITE_API_KEY=` to the app's API key. Never paste keys into the chat.

**3. Put both keys in Supabase.** When Claude asks, Supabase opens a box where *you* enter `KITE_API_KEY` and `KITE_API_SECRET`. Claude never sees them.

**4. Save the login link on your phone.** The link is `https://<project>.supabase.co/functions/v1/kite-session/login`. In Safari, use Share → **Add to Home Screen**. Each trading morning, tap it, approve in Zerodha, and you'll see "✅ Zerodha connected for today".

Check it any time with `python3 connectors/zerodha/kite_client.py status`, or ask Claude for "zerodha status".

## Files

| File | What it is |
|---|---|
| `server.py` | The local connector (stdio, Python 3.9+ stdlib) |
| `kite_client.py` | Session handling, Kite REST calls, Yahoo fallback, gated orders. Also a command-line tool |
| `keys.py` | Makes the RSA key pair and fetch secret (`init`) and stores the callback URL (`set-url`) |
| `install.command` | One-time Mac installer |
| `edge/kite-session/index.ts` | The phone-login callback (Supabase Edge Function, deployed with `verify_jwt=false`) |
| `edge/kite-session/config.example.ts` | Template for your public key and secret hash (the real `config.ts` is git-ignored) |
| `edge/schema.sql` | One table holding only the *encrypted* session |

What lives in `trader-data/` (git-ignored, permissions 600): `secrets.env` (`KITE_API_KEY`, `KITE_SESSION_URL`, `KITE_FETCH_SECRET`), `kite_private.pem`, `kite_session.json`, `kite_pending.json`, and `kite_edge_config.json` (public values only).

## Security notes

- The callback sees the day's token for a moment while it exchanges it, then stores it **encrypted with your Mac's public key**. Only `kite_private.pem` on your Mac can read it.
- Your Mac fetches the session with a random secret. The callback stores only that secret's SHA-256 hash.
- To revoke everything, delete the app at developers.kite.trade, or regenerate its secret. Zerodha's "log out of all sessions" also ends the day's token.
- If your Mac is lost, run `keys.py init --force` on the new one and ask Claude to redeploy the callback.
