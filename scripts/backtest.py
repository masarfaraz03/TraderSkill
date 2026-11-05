#!/usr/bin/env python3
"""Simple daily-bar backtester (long-only) for idea screening.

Data: --csv file with Date and Close columns (Open/High/Low optional), or
--symbol with yfinance installed and internet access (e.g. AAPL, RELIANCE.NS,
^NSEI, BTC-USD).

Strategies
  buy_hold                       hold the whole period
  sma_cross   --fast 50 --slow 200   long while fast SMA > slow SMA
  breakout    --lookback 20 --exit 10  buy close above N-day high, exit below M-day low
  rsi_reversion --rsi 14 --low 30 --high 55  buy RSI<low, sell RSI>high

Signals use the prior day's close (no look-ahead). Costs via --cost-bps per side.
"""
import argparse
import json
import sys

import numpy as np
import pandas as pd


def load(a):
    if a.csv:
        df = pd.read_csv(a.csv)
        cols = {c.lower(): c for c in df.columns}
        date_col = cols.get("date") or cols.get("datetime") or df.columns[0]
        close_col = cols.get("adj close") or cols.get("close")
        if close_col is None:
            sys.exit("CSV needs a Close column")
        df = df.rename(columns={date_col: "Date", close_col: "Close"})
        df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.tz_localize(None)
        df = df.set_index("Date").sort_index()
    else:
        try:
            import yfinance as yf
        except ImportError:
            sys.exit("yfinance not installed; pip install yfinance, or pass --csv")
        df = yf.download(a.symbol, period=f"{a.years}y", auto_adjust=True, progress=False)
        if df is None or df.empty:
            sys.exit(f"No data for {a.symbol} (network blocked or bad symbol). Use --csv.")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    if a.years and a.csv:
        start = df.index.max() - pd.DateOffset(years=a.years)
        df = df[df.index >= start]
    return df


def rsi(s, n):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def positions(df, a):
    c = df["Close"]
    if a.strategy == "buy_hold":
        return pd.Series(1.0, index=c.index)
    if a.strategy == "sma_cross":
        return (c.rolling(a.fast).mean() > c.rolling(a.slow).mean()).astype(float)
    if a.strategy == "breakout":
        hi = c.rolling(a.lookback).max().shift(1)
        lo = c.rolling(a.exit).min().shift(1)
        pos, state = [], 0.0
        for px, h, l in zip(c, hi, lo):
            if state == 0 and not np.isnan(h) and px > h:
                state = 1.0
            elif state == 1 and not np.isnan(l) and px < l:
                state = 0.0
            pos.append(state)
        return pd.Series(pos, index=c.index)
    if a.strategy == "rsi_reversion":
        r = rsi(c, a.rsi)
        pos, state = [], 0.0
        for v in r:
            if state == 0 and v < a.low:
                state = 1.0
            elif state == 1 and v > a.high:
                state = 0.0
            pos.append(state)
        return pd.Series(pos, index=c.index)
    sys.exit("unknown strategy")


def stats(equity, rets):
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = equity.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0
    dd = (equity / equity.cummax() - 1).min()
    vol = rets.std() * np.sqrt(252)
    sharpe = (rets.mean() * 252) / vol if vol > 0 else 0
    return {"total_return_pct": round((equity.iloc[-1] - 1) * 100, 1), "cagr_pct": round(cagr * 100, 2),
            "max_drawdown_pct": round(dd * 100, 1), "sharpe": round(sharpe, 2)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--symbol")
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--strategy", default="sma_cross",
                   choices=["buy_hold", "sma_cross", "breakout", "rsi_reversion"])
    p.add_argument("--fast", type=int, default=50)
    p.add_argument("--slow", type=int, default=200)
    p.add_argument("--lookback", type=int, default=20)
    p.add_argument("--exit", type=int, default=10)
    p.add_argument("--rsi", type=int, default=14)
    p.add_argument("--low", type=float, default=30)
    p.add_argument("--high", type=float, default=55)
    p.add_argument("--cost-bps", type=float, default=5.0, help="cost per side in basis points")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    df = load(a)
    if len(df) < 60:
        sys.exit("Not enough data")
    mret = df["Close"].pct_change().fillna(0)
    pos = positions(df, a).shift(1).fillna(0)  # trade on next bar
    turns = pos.diff().abs().fillna(pos.iloc[0])
    sret = pos * mret - turns * a.cost_bps / 1e4
    eq, bh = (1 + sret).cumprod(), (1 + mret).cumprod()

    # trades
    trades, entry = [], None
    for d, (pv, px) in enumerate(zip(pos, df["Close"])):
        if pv == 1 and entry is None:
            entry = df["Close"].iloc[d - 1] if d > 0 else px
        elif pv == 0 and entry is not None:
            trades.append(df["Close"].iloc[d - 1] / entry - 1)
            entry = None
    if entry is not None:
        trades.append(df["Close"].iloc[-1] / entry - 1)
    wins = [t for t in trades if t > 0]

    yearly = pd.DataFrame({"strategy": (1 + sret).groupby(sret.index.year).prod() - 1,
                           "buy_hold": (1 + mret).groupby(mret.index.year).prod() - 1}) * 100
    out = {
        "source": a.csv or a.symbol, "strategy": a.strategy,
        "period": f"{df.index[0].date()} to {df.index[-1].date()}", "bars": len(df),
        "strategy_stats": stats(eq, sret), "buy_hold_stats": stats(bh, mret),
        "trades": len(trades), "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
        "avg_trade_pct": round(100 * float(np.mean(trades)), 2) if trades else None,
        "time_in_market_pct": round(100 * pos.mean(), 1),
        "yearly_returns_pct": {int(k): {c: round(v, 1) for c, v in r.items()} for k, r in yearly.iterrows()},
    }
    if a.json:
        print(json.dumps(out, indent=2))
        return
    print(f"Backtest {out['strategy']} on {out['source']}  ({out['period']}, {out['bars']} bars)")
    for k, label in (("strategy_stats", "strategy"), ("buy_hold_stats", "buy&hold")):
        s = out[k]
        print(f"  {label:<9} total {s['total_return_pct']:>7}%  CAGR {s['cagr_pct']:>6}%  "
              f"maxDD {s['max_drawdown_pct']:>6}%  Sharpe {s['sharpe']}")
    print(f"  trades {out['trades']}  win rate {out['win_rate_pct']}%  avg trade {out['avg_trade_pct']}%  "
          f"in market {out['time_in_market_pct']}%")
    print("  year   strategy  buy&hold")
    for y, r in out["yearly_returns_pct"].items():
        print(f"  {y}  {r['strategy']:>8}%  {r['buy_hold']:>8}%")


if __name__ == "__main__":
    main()
