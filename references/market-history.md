# Market history 2016–2026: regimes and lessons

Use these as **analogies, not predictions**. When a current setup resembles one of these, say so, and check the analogy with a backtest over the matching period. For anything after mid-2026, search the news instead of relying on this file.

## How to use
- Identify the current regime: trend (above/below 200-day average), volatility (VIX / India VIX), rates direction, and liquidity/news shocks.
- Find the closest period below and note what worked and what failed.
- Backtest the setup on that period (`backtest.py` with a CSV trimmed to those dates) before relying on it.

## United States

| Period | What happened | What worked | What failed / lesson |
|---|---|---|---|
| 2016–2017 | Low volatility melt-up after the 2016 election; VIX near record lows | Buy-and-hold, trend following, buying dips | Selling volatility looked free — until it wasn't |
| Feb 2018 "Volmageddon" | VIX doubled in a day; XIV (short-vol ETN) lost ~90% and was terminated | Having stops and cash | Short-volatility / naked option selling can wipe out an account overnight |
| Q4 2018 | Fed hikes + trade war; S&P fell ~20% into Christmas Eve | Patience; buying the capitulation for long-term | Breakouts and dip-buys kept failing while trend was down |
| Feb–Mar 2020 COVID | Fastest 30%+ crash on record, then V-shaped recovery from 23 Mar | Long-term buying in tranches; staying invested | Panic selling at the low; leveraged positions got liquidated |
| 2020–2021 | Stimulus boom; tech, SPACs, meme stocks (GME Jan 2021), crypto | Momentum, growth stocks | Chasing meme spikes; buying after 100%+ runs |
| 2022 | Fastest Fed hikes in decades; S&P −19%, Nasdaq −33%; growth crushed | Cash, energy, short-term Treasuries; selling rallies | Buy-the-dip in unprofitable tech; trend-following long entries |
| Mar 2023 | SVB and regional bank failures | Quality large caps | Concentration in one sector |
| 2023–2024 | AI rally led by NVDA and mega caps; S&P +24% (2023), +23% (2024) | Trend following in leaders | Shorting "overvalued" leaders too early |
| Aug 2024 | Yen carry-trade unwind; VIX spiked above 60 intraday, recovered within weeks | Waiting a few days before acting | Selling into a liquidity shock |
| Apr 2025 | Tariff announcements; sharp selloff then rapid rebound after a pause | Small size, defined risk | Big directional bets on headlines |

## India

| Period | What happened | What worked | What failed / lesson |
|---|---|---|---|
| Nov 2016 | Demonetisation shock | Patience; quality large caps recovered | Overreacting to policy headlines |
| 2017 | Small/mid-cap boom | Momentum in small caps | Buying at the top of the boom |
| 2018 | Small-cap crash; IL&FS default (Sep) hit NBFCs (DHFL etc.) | Large caps, cash | Leveraged NBFCs; ignoring balance-sheet risk |
| Mar 2020 | Nifty fell ~38% then recovered strongly | Systematic SIP-style buying | Panic exits; F&O positions without stops |
| 2020–2021 | Retail demat explosion; IPO frenzy | Broad market | Many hyped IPOs (e.g. Paytm Nov 2021) fell well below issue price |
| Jan 2023 | Hindenburg report on Adani group; group stocks fell sharply | Diversification | Concentration in one group on story stocks |
| 4 Jun 2024 | Election-result day: Nifty fell ~6% intraday, recovered within days | Defined-risk option positions; small size | Big leveraged event bets |
| Sep 2024 – early 2025 | Nifty peaked late Sep 2024, then a multi-month correction with heavy FII selling | Patience; staggered long-term buying | Assuming the bull market only goes up |
| Nov 2024 onward | SEBI F&O curbs: bigger contract sizes, one weekly expiry per exchange | Fewer, better trades | Expiry-day option-buying lottery tickets |
| FY22 SEBI study | ~89% of individual F&O traders lost money; average loss ~₹1.1 lakh | — | The base rate for retail F&O is losing; keep it small and defined-risk |

## Crypto

| Period | What happened | Lesson |
|---|---|---|
| 2017 → 2018 | BTC ~$20k peak (Dec 2017), then ~−80% bear | Parabolic tops retrace hard |
| Mar 2020 | BTC halved in a day ("Black Thursday") | Crypto falls with everything in a liquidity crash |
| 2021 | BTC ~$69k peak (Nov); alt/NFT mania | Alts fall far more than BTC |
| 2022 | LUNA/UST collapse (May), Celsius, 3AC, FTX (Nov) | Counterparty risk: not your keys / exchange can fail; yields that look too good are |
| Jan 2024 | US spot BTC ETFs approved | Institutional flows matter |
| Apr 2024 | Halving; BTC new highs later in 2024 above $100k | Cycles exist but timing them is unreliable |
| 2025 | Large swings; leveraged liquidations on single days in the billions | Leverage in crypto is the fastest way to zero |

## Cross-cutting lessons (seed `lessons.md` from these)
1. Size from the stop; one gap can erase months.
2. Shocks (2020, Aug 2024, Jun 2024 India, Apr 2025) often recover quickly — the loss comes from selling at the low or being forced out by leverage.
3. Trend-following long entries fail in falling regimes (2018 Q4, 2022); check the 200-day average first.
4. Short volatility / naked selling: small steady gains, rare catastrophic losses (2018).
5. Concentration in a story or group (Adani 2023, meme stocks 2021, FTX 2022) is the big-loss pattern.
6. Hype IPOs and post-100% spikes underperform on average.
