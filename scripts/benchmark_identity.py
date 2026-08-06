"""Benchmark SecurityMaster resolution at institutional universe scale (Phase 2).

Registers N securities, then times:
  - batch resolve_universe of the whole universe as-of a date (the research path)
  - per-call resolve_as_of latency (the incidental-lookup path)

Run: python scripts/benchmark_identity.py [N]
"""

from __future__ import annotations

import sys
import time
from datetime import date

from aurelius.market_data.identity import Security, SecurityMaster, make_security_id


def run(n: int = 100_000) -> None:
    sm = SecurityMaster(":memory:")
    first = date(2000, 1, 1)
    t0 = time.perf_counter()
    # Bulk-load via direct inserts (register() is row-at-a-time; backfill scale test
    # cares about resolution latency, so seed fast).
    rows = []
    hist = []
    for i in range(n):
        tk = f"T{i:06d}"
        sid = make_security_id(isin=None, figi=None, ticker=tk, exchange="XNAS", first_date=first)
        rows.append((sid, tk, "XNAS"))
        hist.append((sid, tk, "XNAS", "2000-01-01", "9999-12-31", "seed", "bench"))
    with sm._conn() as conn:  # noqa: SLF001 — benchmark seeding
        conn.executemany(
            "INSERT OR REPLACE INTO security_master (security_id, ticker, exchange, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', now(), now())", rows)
        conn.executemany(
            "INSERT OR REPLACE INTO security_identity_history "
            "(security_id, ticker, exchange, valid_from, valid_to, reason, source) VALUES (?,?,?,?,?,?,?)", hist)
    seed_s = time.perf_counter() - t0

    universe = [f"T{i:06d}" for i in range(n)]
    t1 = time.perf_counter()
    resolved = sm.resolve_universe(universe, date(2010, 1, 1))
    batch_s = time.perf_counter() - t1
    assert len(resolved) == n

    sample = universe[:: max(1, n // 1000)]  # ~1000 point lookups
    t2 = time.perf_counter()
    for tk in sample:
        sm.resolve_as_of(tk, date(2010, 1, 1))
    per_call_us = (time.perf_counter() - t2) / len(sample) * 1e6

    sm.close()
    print(f"N={n:,}")
    print(f"  seed:            {seed_s:6.3f}s")
    print(f"  resolve_universe {n:,} as-of: {batch_s*1000:7.1f} ms ({n/batch_s/1e6:.1f}M/s)")
    print(f"  resolve_as_of point latency:  {per_call_us:7.1f} us/call")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 100_000)
