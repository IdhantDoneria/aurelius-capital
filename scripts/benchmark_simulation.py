"""Benchmark the portfolio simulation engine (AIDP M11).

Simulates a multi-year daily timeline with monthly rebalancing across increasing
universe sizes and reports runtime, throughput (security-days/s), and peak memory.

Run: python scripts/benchmark_simulation.py [days]   (default 504 ≈ 2y)
"""

from __future__ import annotations

import sys
import time
import tracemalloc
from datetime import date, timedelta

import numpy as np

from aurelius.research.portfolio.costs import TransactionCostModel
from aurelius.research.simulation import (
    CostExecutionModel,
    PortfolioSimulationEngine,
    RebalancePolicy,
    SimulationConfig,
    SizingConfig,
    calendar_dates,
)


def _bench(n: int, days: int) -> dict:
    ids = [f"S{i:06d}" for i in range(n)]
    t0 = date(2018, 1, 1)
    timeline = [t0 + timedelta(days=i) for i in range(days)]
    idx = {d: i for i, d in enumerate(timeline)}
    rng = np.random.default_rng(0)
    paths = {s: 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, days)) for s in ids}
    tw = {s: 1.0 / n for s in ids}

    def price(sid, d):
        i = idx.get(d)
        return float(paths[sid][i]) if i is not None else None

    def target(d):
        return tw

    eng = PortfolioSimulationEngine(
        config=SimulationConfig(initial_capital=1e9, sizing=SizingConfig(min_trade_notional=100)),
        execution_model=CostExecutionModel(TransactionCostModel()),
        policy=RebalancePolicy(explicit_dates=calendar_dates(timeline, "monthly")))

    tracemalloc.start()
    t = time.perf_counter()
    res = eng.run(timeline, target, price, adv_provider=lambda s, d: 1e8)
    dt = time.perf_counter() - t
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sec_days = n * days
    return {"n": n, "runtime_s": dt, "throughput": sec_days / dt, "peak_mb": peak / 1e6,
            "rebalances": res.summary.n_rebalances, "trades": len(res.trades),
            "cagr": res.summary.cagr}


def run(days: int = 504) -> None:
    print(f"timeline: {days} trading days, monthly rebalance")
    print(f"{'N':>7} {'runtime':>10} {'sec-days/s':>14} {'peak MB':>10} {'trades':>10} {'cagr':>8}")
    for n in (100, 500, 1000, 5000, 10000):
        r = _bench(n, days)
        print(f"{r['n']:>7} {r['runtime_s']:>9.2f}s {r['throughput']:>14,.0f} "
              f"{r['peak_mb']:>10.1f} {r['trades']:>10,} {r['cagr']:>8.3f}")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 504)
