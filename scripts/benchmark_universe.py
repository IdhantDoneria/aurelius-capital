"""Benchmark PIT universe reconstruction (AIDP Phase 4).

Seeds N securities (a fraction delisted at random dates), then times
universe_as_of at a historical date — the survivorship-free constituent query.

Run: python scripts/benchmark_universe.py [N]
"""

from __future__ import annotations

import sys
import time
from datetime import date

from aurelius.market_data.delistings import DelistingEvent, DelistingStore
from aurelius.market_data.identity import Security, SecurityMaster, make_security_id
from aurelius.market_data.universe import UniverseEngine


def run(n: int = 50_000) -> None:
    sm = SecurityMaster(":memory:")
    dl = DelistingStore(":memory:")
    first = date(1990, 1, 1)

    t0 = time.perf_counter()
    hist_rows = []
    for i in range(n):
        tk = f"S{i:06d}"
        sid = make_security_id(isin=None, figi=None, ticker=tk, exchange="XNAS", first_date=first)
        # ~30% delisted at a spread of dates (valid_to closed), rest open.
        valid_to = "2005-01-01" if i % 10 < 3 else "9999-12-31"
        hist_rows.append((sid, tk, "XNAS", "1990-01-01", valid_to, "seed", "bench"))
    with sm._conn() as conn:  # noqa: SLF001 — benchmark seeding
        conn.executemany(
            "INSERT OR REPLACE INTO security_master (security_id, ticker, exchange, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', now(), now())", [(r[0], r[1], r[2]) for r in hist_rows])
        conn.executemany(
            "INSERT OR REPLACE INTO security_identity_history "
            "(security_id, ticker, exchange, valid_from, valid_to, reason, source) VALUES (?,?,?,?,?,?,?)", hist_rows)
    seed_s = time.perf_counter() - t0

    eng = UniverseEngine(sm, delisting_store=dl)
    t1 = time.perf_counter()
    snap = eng.universe_as_of(date(2000, 6, 30))
    build_ms = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    snap2 = eng.universe_as_of(date(2000, 6, 30), with_exclusions=True)
    excl_ms = (time.perf_counter() - t2) * 1000

    sm.close()
    dl.close()
    print(f"N={n:,} securities")
    print(f"  seed:                        {seed_s:6.2f}s")
    print(f"  universe_as_of:              {build_ms:7.1f} ms  ({snap.security_count:,} live)")
    print(f"  universe_as_of +exclusions:  {excl_ms:7.1f} ms  ({len(snap2.exclusions):,} excluded)")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 50_000)
