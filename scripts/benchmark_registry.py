"""Benchmark the experiment registry at scale (AIDP M7).

Seeds N experiments (lineage capture off — no 100k git subprocesses), then times
insert throughput, single-experiment lookup, search, and comparison.

Run: python scripts/benchmark_registry.py [N]   (default 100,000)
Target: lookup < 20 ms.
"""

from __future__ import annotations

import sys
import time

from aurelius.research.experiment_registry import ExperimentRegistry, RegistryStore
from aurelius.research.experiment_registry import lineage


def run(n: int = 100_000) -> None:
    reg = ExperimentRegistry(store=RegistryStore(":memory:"))
    dv = lineage.dataset_versions(prices=100, fundamentals=50, insiders=20, universe=10,
                                  securitymaster=10, feature_registry_version="fr1")

    t0 = time.perf_counter()
    ids = []
    for i in range(n):
        exp = reg.start_experiment(
            f"exp{i}", parameters={"lookback": 252, "top": i % 100, "seed": i},
            features=["market_cap", "roe", "close"], dataset_versions=dict(dv, prices_version=i),
            random_seed=i, capture_runtime=False)
        reg.finish_experiment(exp, metrics={"Sharpe": (i % 30) / 10, "CAGR": (i % 20) / 100})
        ids.append(exp.experiment_id)
    insert_s = time.perf_counter() - t0

    mid = ids[n // 2]
    t1 = time.perf_counter()
    reg.load(mid)
    lookup_ms = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    reg.search(name="exp500", limit=10)
    search_ms = (time.perf_counter() - t2) * 1000

    t3 = time.perf_counter()
    reg.compare(ids[0], ids[-1])
    compare_ms = (time.perf_counter() - t3) * 1000

    reg.close()
    print(f"experiments: {n:,}")
    print(f"  insert (start+finish):  {insert_s:7.2f} s   ({2*n/insert_s:,.0f} ops/s)")
    print(f"  lookup:                 {lookup_ms:7.2f} ms  (target < 20 ms)")
    print(f"  search:                 {search_ms:7.2f} ms")
    print(f"  compare:                {compare_ms:7.2f} ms")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 100_000)
