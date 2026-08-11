"""AIDP M21 — open data provider benchmarks (deterministic, offline).

Times provider conversion at 100k and 1M observations. No network. Run:
    uv run python scripts/benchmark_m21_providers.py
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date, timedelta

from aurelius.research.market_data.providers.openbb import OpenBBSourceAdapter
from aurelius.research.market_data.providers.yahoo import YahooFinanceSourceAdapter
from aurelius.research.market_data.providers.fred import FREDSourceAdapter
from aurelius.research.market_data.providers.sec import SECSourceAdapter


def _equity_records(n: int) -> list[dict]:
    base = date(2020, 1, 1)
    return [
        {"symbol": f"S{i % 500:04d}",
         "date": (base + timedelta(days=i % 1000)).isoformat(),
         "open": 100.0 + (i % 50), "high": 105.0 + (i % 50),
         "low": 98.0 + (i % 50), "close": 101.0 + (i % 50),
         "volume": float(1_000_000 + i)}
        for i in range(n)
    ]


def _fred_records(n: int) -> list[dict]:
    base = date(2010, 1, 1)
    return [
        {"date": (base + timedelta(days=i * 30)).isoformat(),
         "realtime_start": (base + timedelta(days=i * 30 + 45)).isoformat(),
         "value": str(27000.0 + i * 10)}
        for i in range(n)
    ]


def _bench(label: str, fn, *args, **kwargs):
    tracemalloc.start()
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    _, peak_mb = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    n = len(result) if hasattr(result, "__len__") else "?"
    print(f"  {label:<40} {n:>9} msgs  {elapsed:6.2f}s  {peak_mb / 1e6:6.1f} MB")
    return elapsed


def run_benchmarks():
    as_of = date(2024, 12, 31)
    print("\n=== M21 Provider Benchmarks ===\n")

    print("OpenBB equity conversion:")
    for n, target in ((100_000, 10.0), (1_000_000, 120.0)):
        records = _equity_records(n)
        adapter = OpenBBSourceAdapter()
        elapsed = _bench(f"  {n:>9,} records", adapter.convert, records, as_of)
        status = "PASS" if elapsed < target else f"FAIL (target <{target:.0f}s)"
        print(f"    → {status}")

    print("\nYahoo Finance conversion (with adj_close):")
    yahoo_records = [
        {**r, "adj_close": r["close"] * 1.02, "dividends": 0.0, "stock_splits": 0.0}
        for r in _equity_records(100_000)
    ]
    _bench("  100,000 records (close+adj)", YahooFinanceSourceAdapter().convert,
           yahoo_records, as_of)

    print("\nFRED macro conversion (vintage-aware):")
    fred_obs = _fred_records(10_000)
    _bench("  10,000 vintage observations", FREDSourceAdapter().convert,
           fred_obs, "GDP", as_of)

    print()


if __name__ == "__main__":
    run_benchmarks()
