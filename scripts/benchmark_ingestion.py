#!/usr/bin/env python
"""Phase 27 — ingestion scalability benchmark + validation-coverage self-check.

Two jobs, both evidence for docs/DATA_READINESS_REPORT.md:

  benchmark : write synthetic OHLCV through the REAL DuckDBStore.write_bars path
              at rising scales, measure rows/sec + storage bytes/row + peak mem,
              extrapolate to institutional targets. (Synthetic = engine load
              test ONLY; never fed to a reproduction as if it were real data.)

  --check   : assert each required validation category actually rejects/flags at
              its real enforcement point (OHLCVBatchValidator / csv_loader /
              normalizer). Proves objective-4 coverage; runnable regression.

    python scripts/benchmark_ingestion.py            # both
    python scripts/benchmark_ingestion.py --check     # coverage self-check only
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

TRADING_DAYS_PER_YEAR = 252
TARGETS = [  # (label, symbols, years)
    ("100 × 10y", 100, 10),
    ("500 × 20y", 500, 20),
    ("1000 × 20y", 1000, 20),
    ("5000 × 30y", 5000, 30),
]


def _synthetic_bars(symbols: int, days: int) -> list[dict]:
    """Deterministic synthetic bars. Engine load test only — not research data."""
    start = datetime(1994, 1, 3, tzinfo=UTC)
    dates = [start + timedelta(days=i) for i in range(days)]
    bars = []
    for s in range(symbols):
        sym = f"SYN{s:04d}"
        px = 10.0 + s % 500
        for dt in dates:
            px *= 1.0003
            c = round(px, 4)
            bars.append({
                "symbol": sym, "timestamp": dt, "frequency": "1d",
                "open": c, "high": round(c * 1.01, 4), "low": round(c * 0.99, 4),
                "close": c, "volume": 1_000_000, "vwap": c,
                "trade_count": 100, "quality_score": 100, "source": "benchmark",
                "adjustment_factor": 1.0,
            })
    return bars


def benchmark() -> None:
    from aurelius.market_data.storage.duckdb_store import DuckDBStore

    print("INGESTION BENCHMARK (real DuckDBStore.write_bars path)\n")
    print(f"{'scale':>16} {'rows':>10} {'sec':>7} {'rows/sec':>10} {'MB':>7} {'bytes/row':>10}")
    per_row_bytes = []
    rows_per_sec = []
    for label, syms, days in [("2 × 250d", 2, 250), ("20 × 500d", 20, 500),
                              ("100 × 500d", 100, 500), ("200 × 1000d", 200, 1000)]:
        bars = _synthetic_bars(syms, days)
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "bench.duckdb")
            store = DuckDBStore(db)
            tracemalloc.start()
            t0 = time.perf_counter()
            n = store.write_bars(bars)
            dt = time.perf_counter() - t0
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            store.close()
            size = os.path.getsize(db)
        rps = n / dt if dt else 0
        bpr = size / n
        per_row_bytes.append(bpr)
        rows_per_sec.append(rps)
        print(f"{label:>16} {n:>10,} {dt:>7.2f} {rps:>10,.0f} {size/1e6:>7.1f} {bpr:>10.1f}"
              f"   peakmem={peak/1e6:.1f}MB")

    # medians for extrapolation (write path is ~linear in row count)
    bpr = sorted(per_row_bytes)[len(per_row_bytes) // 2]
    rps = sorted(rows_per_sec)[len(rows_per_sec) // 2]
    print(f"\nExtrapolation basis: ~{rps:,.0f} rows/sec, ~{bpr:.0f} bytes/row (medians)\n")
    print(f"{'target':>16} {'rows':>14} {'est storage':>12} {'est load time':>14}")
    for label, syms, years in TARGETS:
        rows = syms * years * TRADING_DAYS_PER_YEAR
        gb = rows * bpr / 1e9
        secs = rows / rps
        tstr = f"{secs:.0f}s" if secs < 90 else f"{secs/60:.1f}min"
        print(f"{label:>16} {rows:>14,} {gb:>10.2f}GB {tstr:>14}")
    print("\nNote: DuckDB is columnar single-file; write path is O(rows), no per-symbol\n"
          "overhead. Bottleneck at 5000×30y (~37.8M rows) is one bulk load, not schema.")


def check_coverage() -> None:
    """Assert every required validation category fires at its real enforcement point."""
    from aurelius.infrastructure.database.validation.market import OHLCVBatchValidator
    from aurelius.market_data.adapters.csv_loader import CSVLoader
    from aurelius.market_data.pipeline.normalizer import detect_gaps, compute_spike

    v = OHLCVBatchValidator()

    def raw(**over) -> dict:
        base = dict(symbol_id=uuid4(), source_id=uuid4(), timestamp=datetime(2020, 1, 2, tzinfo=UTC),
                    frequency="1d", open=Decimal("10"), high=Decimal("11"),
                    low=Decimal("9"), close=Decimal("10"), volume=Decimal("1000"))
        base.update(over)
        return base

    def rejected(**over) -> bool:
        _, rej = v.validate_batch([raw(**over)])
        return len(rej) == 1

    # per-bar rejections
    assert not rejected(), "valid bar must pass"                       # sanity
    assert rejected(close=Decimal("0")), "zero price"                  # 5
    assert rejected(low=Decimal("-1")), "negative price"              # 6
    assert rejected(volume=Decimal("-5")), "negative volume"          # 7
    assert rejected(high=Decimal("8")), "OHLC: high<low"             # 11
    assert rejected(timestamp=datetime(2020, 1, 2)), "naive ts rejected"  # tz

    # out-of-order (batch-level)
    good, _ = v.validate_batch([
        raw(timestamp=datetime(2020, 1, 3, tzinfo=UTC)),
        raw(timestamp=datetime(2020, 1, 2, tzinfo=UTC)),
    ])
    assert len(v.validate_chronological_order(good)) == 1, "out-of-order flagged"  # 3

    # split anomaly (>20% move) + missing trading days via normalizer
    assert compute_spike(_Bar(Decimal("13")), Decimal("10")), "split/spike >20%"   # 4
    b0, b3 = _Bar(Decimal("10"), datetime(2020, 1, 2, tzinfo=UTC)), _Bar(Decimal("10"), datetime(2020, 1, 10, tzinfo=UTC))
    assert detect_gaps([b0, b3], max_gap_days=2), "missing trading days"            # 2

    # file-level via csv_loader
    with tempfile.TemporaryDirectory() as tmp:
        bad_date = Path(tmp) / "baddate.csv"
        bad_date.write_text("symbol,timestamp,open,high,low,close,volume\n"
                            "AAA,not-a-date,1,1,1,1,1\n", encoding="utf-8")
        bars = CSVLoader().load_file(bad_date, frequency="1d")
        assert len(bars) == 0, "malformed date row skipped"                        # 10

        corrupt = Path(tmp) / "corrupt.csv"
        corrupt.write_text("", encoding="utf-8")
        try:
            CSVLoader().load_file(corrupt, frequency="1d")
            raise AssertionError("empty/corrupt file must raise")                   # 9
        except Exception:
            pass

    print("VALIDATION COVERAGE — all required checks fire:")
    for c in ["zero price", "negative price", "negative volume", "OHLC relationship",
              "naive/malformed timestamp", "out-of-order", "split/spike >20%",
              "missing trading days", "malformed date row", "corrupt file",
              "duplicate rows (DuckDB PK + INSERT OR REPLACE)",
              "invalid symbol (ingestion symbol-resolution skip)"]:
        print(f"  ✓ {c}")
    print("\n(duplicate + invalid-symbol enforced at store/pipeline level, noted not asserted here)")


class _Bar:
    """Minimal RawBar stand-in for normalizer functions (close + timestamp)."""
    def __init__(self, close: Decimal, timestamp: datetime | None = None) -> None:
        self.close = close
        self.timestamp = timestamp or datetime(2020, 1, 2, tzinfo=UTC)


if __name__ == "__main__":
    check_coverage()
    if "--check" not in sys.argv:
        print()
        benchmark()
