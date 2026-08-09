"""AIDP M15 post-trade benchmarks — deterministic, offline.

Measures event-processing / settlement / reconciliation / serialization throughput and
peak memory for 10k and 100k trades, and a ~1M lifecycle-event run.

Run: `uv run python scripts/benchmark_m15_post_trade.py`
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date

from aurelius.research import post_trade as PT
from aurelius.research.post_trade import serialization

T0 = date(2026, 1, 5)          # a Monday
UNIVERSE = 1000                # cycle names so holdings stay bounded, events scale with N


def _bench(n_trades: int, *, serialize: bool = True) -> dict:
    eng = PT.PostTradeEngine(1e12, settlement_config=PT.SettlementConfig(default_days=2))

    tracemalloc.start()
    t0 = time.perf_counter()
    for i in range(n_trades):
        eng.book_fill(security_id=f"S{i % UNIVERSE}", quantity=10.0,
                      price=100.0 + (i % 50), cost=1.0, trade_date=T0)
    t_book = time.perf_counter() - t0

    t0 = time.perf_counter()
    eng.settle(date(2026, 1, 9))               # settle everything due
    t_settle = time.perf_counter() - t0

    t0 = time.perf_counter()
    recon = PT.reconcile(eng)
    t_recon = time.perf_counter() - t0

    t_ser = 0.0
    if serialize:
        t0 = time.perf_counter()
        _ = serialization.to_json(eng)
        t_ser = time.perf_counter() - t0

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    n_events = len(eng.log)
    return {"trades": n_trades, "events": n_events,
            "book_s": t_book, "trades_per_s": n_trades / t_book,
            "settle_s": t_settle, "recon_s": t_recon, "ser_s": t_ser,
            "events_per_s": n_events / (t_book + t_settle), "peak_mb": peak / 1e6,
            "recon_ok": recon.ok}


def main() -> None:
    rows = [_bench(10_000), _bench(100_000)]
    rows.append(_bench(340_000, serialize=False))     # ~1M+ lifecycle events
    hdr = f"{'trades':>9} {'events':>10} {'book_s':>8} {'trd/s':>10} {'evt/s':>10} " \
          f"{'settle_s':>9} {'recon_s':>8} {'ser_s':>7} {'peakMB':>8} {'ok':>4}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['trades']:>9,} {r['events']:>10,} {r['book_s']:>8.3f} {r['trades_per_s']:>10,.0f} "
              f"{r['events_per_s']:>10,.0f} {r['settle_s']:>9.3f} {r['recon_s']:>8.3f} "
              f"{r['ser_s']:>7.2f} {r['peak_mb']:>8.1f} {str(r['recon_ok']):>4}")
    assert all(r["recon_ok"] for r in rows), "benchmark must reconcile"


if __name__ == "__main__":
    main()
