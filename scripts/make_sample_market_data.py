#!/usr/bin/env python
"""Generate a sample OHLCV CSV in the exact schema CSVLoader expects.

Real vendor history (CRSP/Compustat/Yahoo) is network/paywall-blocked from this
environment, so this emits a DOCUMENTED SYNTHETIC daily-bar universe with
dispersed per-symbol drift — enough cross-sectional structure for a momentum
experiment to produce an honest verdict. Replace this file with a real vendor
CSV of the same schema and the loader/store/experiment path is unchanged.

Schema (see docs/MARKET_DATA_SPEC.md):
    symbol,timestamp,open,high,low,close,volume
    - timestamp: YYYY-MM-DD
    - ticker:    uppercase
    - prices:    split/dividend-ADJUSTED close (adjustment_factor assumed 1.0)

    python scripts/make_sample_market_data.py
"""
from __future__ import annotations

import csv
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path("data/market_data/sample_momentum_universe.csv")
SYMBOLS = ["AAPL", "MSFT", "AMZN", "GOOG", "META", "NVDA",
           "JPM", "XOM", "PG", "KO", "T", "GE"]
DAYS = 520          # ~2 trading years; > momentum lookback + IS/OOS split room
SEED = 42


def _business_days(start: datetime, n: int) -> list[datetime]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def main() -> None:
    rnd = random.Random(SEED)
    dates = _business_days(datetime(2022, 1, 3, tzinfo=UTC), DAYS)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    rows = 0
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "timestamp", "open", "high", "low", "close", "volume"])
        for i, sym in enumerate(SYMBOLS):
            # Persistent per-name drift, spread from clear losers to clear winners.
            drift = -0.0006 + (i / (len(SYMBOLS) - 1)) * 0.0018
            vol = 0.012 + rnd.random() * 0.006
            price = 50.0 + i * 5
            for dt in dates:
                ret = rnd.gauss(drift, vol)
                price = max(1.0, price * (1 + ret))
                intraday = abs(rnd.gauss(0, vol)) * price
                close = round(price, 4)
                open_ = round(price * (1 - rnd.gauss(0, vol) * 0.5), 4)
                high = round(max(open_, close) + intraday * 0.5, 4)
                low = round(min(open_, close) - intraday * 0.5, 4)
                volume = rnd.randint(500_000, 5_000_000)
                w.writerow([sym, dt.strftime("%Y-%m-%d"), open_, high, low, close, volume])
                rows += 1

    print(f"Wrote {rows} rows, {len(SYMBOLS)} symbols, {len(dates)} days -> {OUT}")
    print(f"Date range: {dates[0].date()} .. {dates[-1].date()}")


if __name__ == "__main__":
    main()
