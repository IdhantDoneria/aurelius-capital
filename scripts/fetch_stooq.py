"""Stooq daily OHLCV downloader — cross-check layer for US prices.

Stooq provides free daily OHLCV CSV per ticker at:
  https://stooq.com/q/d/l/?s={ticker}.us&i=d

Use this to spot-check Alpaca/yfinance prices for divergences.
NOT a primary source — coverage and reliability are inconsistent.

Usage:
    python scripts/fetch_stooq.py AAPL MSFT KO XOM --out data/stooq_spot.duckdb
    python scripts/fetch_stooq.py --ticker-file cik_list_tickers.txt --out data/stooq_spot.duckdb
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import httpx

_STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker}.us&i=d"
_DELAY = 0.5  # seconds between requests — Stooq has no published limit; be conservative


def fetch_ticker(ticker: str) -> list[dict]:
    url = _STOOQ_URL.format(ticker=ticker.lower())
    r = httpx.get(url, timeout=20.0, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    text = r.text.strip()
    if not text or "No data" in text:
        return []
    import csv as _csv
    rows = []
    for row in _csv.DictReader(io.StringIO(text)):
        try:
            rows.append({
                "symbol": ticker.upper(),
                "date": row["Date"],
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(float(row.get("Volume") or 0)),
                "source": "stooq",
            })
        except (KeyError, ValueError):
            continue
    return rows


def write_duckdb(all_rows: list[dict], db_path: str) -> int:
    import duckdb
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS stooq_prices (
            symbol VARCHAR, date DATE, open DOUBLE, high DOUBLE,
            low DOUBLE, close DOUBLE, volume BIGINT, source VARCHAR,
            PRIMARY KEY (symbol, date)
        )
    """)
    if not all_rows:
        con.close()
        return 0
    import pandas as pd
    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    con.execute("INSERT OR REPLACE INTO stooq_prices SELECT * FROM df")
    n = len(all_rows)
    con.close()
    return n


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("tickers", nargs="*")
    p.add_argument("--ticker-file", help="file with one ticker per line")
    p.add_argument("--out", default="./data/stooq_spot.duckdb")
    args = p.parse_args()

    tickers = list(args.tickers)
    if args.ticker_file:
        tickers += [t.strip() for t in Path(args.ticker_file).read_text().splitlines() if t.strip()]
    if not tickers:
        p.error("no tickers given")

    all_rows: list[dict] = []
    for i, ticker in enumerate(tickers):
        try:
            rows = fetch_ticker(ticker)
            print(f"  {ticker}: {len(rows)} rows")
            all_rows.extend(rows)
        except Exception as exc:  # noqa: BLE001
            print(f"  {ticker}: ERROR {exc}", file=sys.stderr)
        if i < len(tickers) - 1:
            time.sleep(_DELAY)

    n = write_duckdb(all_rows, args.out)
    print(f"\nWrote {n} rows to {args.out}")
    print("Use for spot-checks only — do not build primary price series from Stooq.")


if __name__ == "__main__":
    main()
