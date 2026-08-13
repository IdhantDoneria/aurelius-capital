"""Backfill the PIT price store from Yahoo (raw prices + split events).

Populates raw_ohlcv + corporate_actions in the analytics DuckDB, feeding the
PIT-correct read path (PitPriceStore). Additive — does not touch the legacy
`ohlcv` table. Needs network (yfinance).

Usage:
    python scripts/backfill_pit_store.py AAPL MSFT --start 2000-01-01
    python scripts/backfill_pit_store.py --symbols-file universe.txt --db data/analytics.duckdb
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from mentisrex.market_data.adapters.yahoo import YahooFinanceAdapter
from mentisrex.market_data.storage.pit_store import PitPriceStore


async def _run(symbols: list[str], start: datetime, end: datetime, db_path: str) -> None:
    adapter = YahooFinanceAdapter()
    store = PitPriceStore(db_path)
    try:
        for sym in symbols:
            bars, actions = await adapter.fetch_raw_and_splits(sym, start, end)
            n_bars = store.write_raw_bars(bars)
            n_act = store.record_actions(actions)
            print(f"{sym}: {n_bars} raw bars, {n_act} splits")
    finally:
        store.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("symbols", nargs="*", help="ticker symbols")
    p.add_argument("--symbols-file", help="file with one ticker per line")
    p.add_argument("--start", default="2000-01-01", help="YYYY-MM-DD")
    p.add_argument("--end", default=datetime.now(UTC).date().isoformat(), help="YYYY-MM-DD")
    p.add_argument("--db", default="./data/analytics.duckdb")
    args = p.parse_args()

    symbols = list(args.symbols)
    if args.symbols_file:
        symbols += [s.strip() for s in Path(args.symbols_file).read_text().splitlines() if s.strip()]
    if not symbols:
        p.error("no symbols given")

    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    asyncio.run(_run(symbols, start, end, args.db))


if __name__ == "__main__":
    main()
