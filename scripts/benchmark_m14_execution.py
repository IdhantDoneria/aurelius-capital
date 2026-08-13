"""AIDP M14 execution benchmarks — deterministic, offline.

Measures order-processing / routing / execution-simulation throughput and peak
memory for:
  * 100 / 1,000 / 10,000 parent market orders end-to-end through the EMS
  * one parent order fanned out to 100,000 child slices (TWAP)

Run: `uv run python scripts/benchmark_m14_execution.py`
"""

from __future__ import annotations

import time
import tracemalloc

from mentisrex.research.execution import ems as E
from mentisrex.research.execution.ems.orders import MarketInfo


def _prices(n):
    return {f"S{i}": 10.0 + (i % 500) for i in range(n)}


def _bench_parent_orders(n: int) -> dict:
    prices = _prices(n)
    market = MarketInfo(prices=prices, adv={s: 1e7 for s in prices})
    reqs = [E.market_order(f"o{i}", f"S{i}", 10, arrival_price=prices[f"S{i}"]) for i in range(n)]
    broker = E.MockExecutionBroker(initial_cash=1e12)
    engine = E.EMS(E.ExecutionRouter({"b": broker}))

    tracemalloc.start()
    t0 = time.perf_counter()
    sess = engine.execute(reqs, market)
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    m = E.metrics(sess)
    return {"scenario": f"{n} parent orders", "n": n, "seconds": dt,
            "orders_per_sec": n / dt, "us_per_order": dt / n * 1e6,
            "n_fills": m.n_fills, "fill_rate": m.fill_rate, "peak_mb": peak / 1e6}


def _bench_child_fanout(n_children: int) -> dict:
    prices = {"AAA": 100.0}
    market = MarketInfo(prices=prices, adv={"AAA": 1e12})
    broker = E.MockExecutionBroker(initial_cash=1e15)
    engine = E.EMS(E.ExecutionRouter({"b": broker}), config=E.ExecutionConfig(twap_slices=n_children))
    req = E.twap_order("big", "AAA", float(n_children), arrival_price=100.0)

    tracemalloc.start()
    t0 = time.perf_counter()
    sess = engine.execute([req], market)
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    m = E.metrics(sess)
    return {"scenario": f"{n_children} child orders (1 TWAP parent)", "n": n_children,
            "seconds": dt, "orders_per_sec": n_children / dt, "us_per_order": dt / n_children * 1e6,
            "n_fills": m.n_fills, "fill_rate": m.fill_rate, "peak_mb": peak / 1e6}


def main() -> None:
    rows = [_bench_parent_orders(n) for n in (100, 1_000, 10_000)]
    rows.append(_bench_child_fanout(100_000))
    print(f"{'scenario':<40} {'sec':>8} {'ord/s':>12} {'us/ord':>9} {'fills':>8} {'peakMB':>8}")
    print("-" * 92)
    for r in rows:
        print(f"{r['scenario']:<40} {r['seconds']:>8.3f} {r['orders_per_sec']:>12,.0f} "
              f"{r['us_per_order']:>9.2f} {r['n_fills']:>8,} {r['peak_mb']:>8.1f}")
    assert all(abs(r["fill_rate"] - 1.0) < 1e-9 for r in rows), "benchmark fills must be complete"


if __name__ == "__main__":
    main()
