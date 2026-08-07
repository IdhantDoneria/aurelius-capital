"""Benchmark the research execution platform (AIDP M8).

Isolates platform overhead from strategy cost by using a trivial executor, then
times: single-run overhead, batch throughput, artifact generation, event logging,
and scheduler sweep throughput.

Run: python scripts/benchmark_execution.py [N]   (default 500 runs)
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta

from aurelius.backtesting.analytics.performance import EquityPoint, PerformanceMetrics, RoundTrip
from aurelius.research.execution import ResearchRunner, RunConfiguration
from aurelius.research.execution.artifact_manager import ArtifactManager
from aurelius.research.execution.event_log import EventLog
from aurelius.research.experiment_registry import ExperimentRegistry, RegistryStore, lineage


def _pm():
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    curve = [EquityPoint(t0 + timedelta(days=i), 1e6 * (1 + 0.001 * i)) for i in range(60)]
    rets = [curve[i].equity / curve[i - 1].equity - 1 for i in range(1, len(curve))]
    rts = [RoundTrip("AAA", "long", t0, t0 + timedelta(days=5), 100, 100.0, 110.0, 1000.0)]
    return PerformanceMetrics(cagr=0.4, sharpe_ratio=1.5, max_drawdown=-0.05, num_trades=1,
                              equity_curve=curve, drawdown_series=[(p.timestamp, 0.0) for p in curve],
                              daily_returns=rets, round_trips=rts)


class _Report:
    metrics = _pm()


def _executor(session):
    return _Report()


def run(n: int = 500) -> None:
    dv = lineage.dataset_versions(prices=100, fundamentals=50, insiders=20, universe=10,
                                  securitymaster=10, feature_registry_version="fr1")
    tmp = tempfile.mkdtemp()

    def cfg(i):
        return RunConfiguration(name=f"e{i}", parameters={"lookback": i}, features=["market_cap"],
                                dataset_versions=dv, random_seed=i, executor=_executor,
                                artifacts_dir=f"{tmp}/e{i}")

    runner = ResearchRunner(registry=ExperimentRegistry(store=RegistryStore(":memory:")))

    # single-run overhead
    t = time.perf_counter()
    runner.run(cfg(0))
    single_ms = (time.perf_counter() - t) * 1000

    # batch overhead
    t = time.perf_counter()
    runner.batch([cfg(i) for i in range(1, n)])
    batch_s = time.perf_counter() - t

    # artifact generation alone
    s = runner.run(cfg(n + 1))
    t = time.perf_counter()
    for _ in range(100):
        ArtifactManager(f"{tmp}/art").write_all(s)
    artifact_ms = (time.perf_counter() - t) * 1000 / 100

    # logging overhead
    log = EventLog()
    t = time.perf_counter()
    for i in range(10_000):
        log.emit("bench", stage="RUNNING", i=i)
    log_us = (time.perf_counter() - t) * 1e6 / 10_000

    # scheduler sweep throughput
    base = cfg(0)
    t = time.perf_counter()
    sessions = runner.scheduler.parameter_sweep(base, {"a": list(range(10)), "b": list(range(10))})
    sweep_s = time.perf_counter() - t

    runner.registry.close()
    print(f"runs: {n}")
    print(f"  single run overhead:    {single_ms:8.2f} ms")
    print(f"  batch throughput:       {(n-1)/batch_s:8.1f} runs/s  ({batch_s:.2f}s for {n-1})")
    print(f"  artifact generation:    {artifact_ms:8.2f} ms  (9 files + hashes + verify)")
    print(f"  event logging:          {log_us:8.2f} us/event")
    print(f"  scheduler sweep:        {len(sessions)/sweep_s:8.1f} runs/s  ({len(sessions)} configs)")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 500)
