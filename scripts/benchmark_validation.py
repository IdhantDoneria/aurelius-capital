"""Benchmark the validation framework (AIDP Phase 9).

Times the individual heavy stages (bootstrap, Monte Carlo) and the full
ResearchValidator pass, reports peak memory, and demonstrates local parallel
scalability across independent experiments (thread pool — the resampling is
numpy-bound and releases the GIL).

Run: python scripts/benchmark_validation.py [n_returns] [n_boot]
"""

from __future__ import annotations

import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import numpy as np

from aurelius.backtesting.analytics.performance import EquityPoint, PerformanceMetrics, RoundTrip
from aurelius.research.validation import ResearchValidator, ValidationConfig
from aurelius.research.validation import bootstrap, monte_carlo
from aurelius.research.validation.significance import sharpe


def _pm(n, seed=1):
    rng = np.random.default_rng(seed)
    rets = list(rng.normal(0.0008, 0.01, n))
    t0 = datetime(2015, 1, 1, tzinfo=UTC)
    eq = [1e6]
    for r in rets:
        eq.append(eq[-1] * (1 + r))
    curve = [EquityPoint(t0 + timedelta(days=i), eq[i]) for i in range(len(eq))]
    peak, dd = eq[0], []
    for i, e in enumerate(eq):
        peak = max(peak, e)
        dd.append((curve[i].timestamp, (e - peak) / peak))
    rts = [RoundTrip("A", "long", t0, t0 + timedelta(days=5), 100, 100.0, 110.0, 900.0)]
    return PerformanceMetrics(cagr=0.15, annualized_volatility=0.16, num_trades=1,
                              annual_turnover=2.0, avg_holding_period_days=5,
                              equity_curve=curve, drawdown_series=dd, daily_returns=rets, round_trips=rts)


class _E:
    experiment_id = "B"; fingerprint = "f"; git_commit = "c"; random_seed = 1
    dataset_versions = {"feature_registry_version": "fr1"}; features = ["market_cap"]
    artifacts: list = []; metrics: dict = {}


def run(n: int = 1000, n_boot: int = 2000) -> None:
    import tempfile
    rets = _pm(n).daily_returns

    t = time.perf_counter()
    bootstrap.bootstrap_distribution(rets, sharpe, n_samples=n_boot, method="stationary", seed=0)
    boot_ms = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    monte_carlo.monte_carlo(rets, sharpe, n_samples=n_boot, seed=0)
    mc_ms = (time.perf_counter() - t) * 1000

    v = ResearchValidator(config=ValidationConfig(bootstrap_samples=n_boot,
                          monte_carlo_samples=n_boot, permutation_samples=n_boot, n_trials=10))
    # timing WITHOUT tracemalloc (tracemalloc traces every alloc → ~10x slowdown)
    with tempfile.TemporaryDirectory() as d:
        v.validate(_E(), _pm(n), artifacts_dir=d)          # warm-up
        t = time.perf_counter()
        v.validate(_E(), _pm(n), artifacts_dir=d)
        full_ms = (time.perf_counter() - t) * 1000
    # memory measured in a separate traced pass
    tracemalloc.start()
    with tempfile.TemporaryDirectory() as d:
        v.validate(_E(), _pm(n), artifacts_dir=d)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # local parallel scalability over K independent validations
    K = 8
    def one(_):
        import tempfile as tf
        with tf.TemporaryDirectory() as d:
            v.validate(_E(), _pm(n), artifacts_dir=d)
    t = time.perf_counter()
    for _ in range(K):
        one(0)
    serial = time.perf_counter() - t
    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(one, range(K)))
    parallel = time.perf_counter() - t

    print(f"n_returns={n}  n_boot={n_boot}")
    print(f"  bootstrap:            {boot_ms:8.1f} ms")
    print(f"  monte carlo:          {mc_ms:8.1f} ms")
    print(f"  full validation:      {full_ms:8.1f} ms")
    print(f"  peak memory:          {peak/1e6:8.2f} MB")
    print(f"  {K} validations serial:  {serial:6.2f}s   4-thread: {parallel:6.2f}s   speedup {serial/parallel:.2f}x")


if __name__ == "__main__":
    a = sys.argv
    run(int(a[1]) if len(a) > 1 else 1000, int(a[2]) if len(a) > 2 else 2000)
