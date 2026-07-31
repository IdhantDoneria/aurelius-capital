#!/usr/bin/env python
"""Ingest the cleaned Yahoo US + India NSE CSVs through the real pipeline.

    CSVLoader.load_file -> RawBar -> DuckDBStore.write_bars (data/analytics.duckdb)

Same components/mapping as scripts/load_and_run_momentum.py, just multi-file.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aurelius.market_data.adapters.csv_loader import CSVLoader
from aurelius.market_data.storage.duckdb_store import DuckDBStore

FETCHER = Path.home() / "market_data_fetcher" / "ingest_ready"
DATASETS = [("US", FETCHER / "us_ohlcv.csv"), ("INDIA_NSE", FETCHER / "india_ohlcv.csv")]
STORE_DB = "./data/analytics.duckdb"


def load(store: DuckDBStore, csv: Path) -> int:
    bars = CSVLoader().load_file(csv, frequency="1d")
    dicts = [
        {
            "symbol": b.symbol, "timestamp": b.timestamp, "frequency": b.frequency,
            # float/int, not Decimal: DuckDB infers a too-narrow DECIMAL from a
            # Decimal object column (DECIMAL(9,0) on big volumes, DECIMAL(25,17)
            # on many-decimal prices) and overflows. Floats infer DOUBLE, which
            # casts cleanly into the wide target columns. Source is float anyway.
            "open": float(b.open), "high": float(b.high),
            "low": float(b.low), "close": float(b.close),
            "volume": int(b.volume), "vwap": b.vwap, "trade_count": b.trade_count,
            "quality_score": None, "source": b.source,
        }
        for b in bars
    ]
    return store.write_bars(dicts)


def main() -> None:
    store = DuckDBStore(STORE_DB)
    for name, csv in DATASETS:
        n = load(store, csv)
        print(f"{name}: wrote {n} bars from {csv.name}")
    q = store.query(
        "SELECT COUNT(*) n, COUNT(DISTINCT symbol) syms, "
        "MIN(timestamp) lo, MAX(timestamp) hi FROM ohlcv"
    )[0]
    print(f"\nStore total: rows={q['n']} securities={q['syms']} "
          f"range={q['lo'].date()}..{q['hi'].date()}")
    store.close()


if __name__ == "__main__":
    main()
