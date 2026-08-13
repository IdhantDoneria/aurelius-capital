"""Benchmark the M13 risk engine across 100 / 1000 / 10000 securities.
Measures full assess, VaR, stress, monitoring, memory. Offline, deterministic.

Run: .venv/bin/python scripts/benchmark_risk.py
"""

from __future__ import annotations

import time
import tracemalloc

import numpy as np

from mentisrex.research.risk import (
    RiskEngine,
    RiskEngineConfig,
    RiskLimits,
    historical_var,
    monitor,
    stress_test,
)

RNG = np.random.default_rng(0)


def bench(n, T=252):
    ids = [f"S{i:05d}" for i in range(n)]
    w = {s: 1.0 / n for s in ids}
    R = RNG.normal(0.0004, 0.02, (T, n))              # (T, N) aligned to ids
    adv = {s: 5e7 for s in ids}
    eng = RiskEngine(RiskEngineConfig(limits=RiskLimits(max_position=1.0)))

    tracemalloc.start()
    t0 = time.perf_counter()
    rep = eng.assess(w, returns=R, adv=adv, aum=1e9, portfolio_value=1e9)
    assess_ms = (time.perf_counter() - t0) * 1e3
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rp = R @ np.array(list(w.values()))
    t0 = time.perf_counter()
    for _ in range(10):
        historical_var(rp)
    var_ms = (time.perf_counter() - t0) / 10 * 1e3

    t0 = time.perf_counter()
    for _ in range(10):
        stress_test(w, betas={s: 1.0 for s in ids})
    stress_ms = (time.perf_counter() - t0) / 10 * 1e3

    reps = [rep] * 12
    t0 = time.perf_counter()
    monitor(reps)
    mon_ms = (time.perf_counter() - t0) * 1e3

    print(f"N={n:>6}: assess={assess_ms:8.2f}ms  VaR={var_ms:6.3f}ms  "
          f"stress={stress_ms:7.2f}ms  monitor(12)={mon_ms:6.2f}ms  "
          f"peak_mem={peak/1e6:7.1f}MB  decision={rep.decision.value}")


if __name__ == "__main__":
    for n in (100, 1000, 10000):
        bench(n)
