"""Benchmark the portfolio engine at scale (AIDP M10).

Times construction across objectives on a large universe. Covariance for N=10,000 is
kept diagonal (a dense N×N sample covariance is 800 MB and O(N³) to invert — not a
realistic single-desk portfolio); the dense mean-variance path is timed at a
tractable N to document its actual cost.

Run: python scripts/benchmark_portfolio.py [N]   (default 10,000)
"""

from __future__ import annotations

import sys
import time
import tracemalloc

import numpy as np

from aurelius.research.portfolio import ConstraintSet, Objective, PortfolioEngine, TransactionCostModel


def run(n: int = 10_000) -> None:
    rng = np.random.default_rng(0)
    ids = [f"S{i:06d}" for i in range(n)]
    signals = {s: float(v) for s, v in zip(ids, rng.normal(size=n))}
    vols = np.clip(rng.normal(0.2, 0.05, n), 0.05, None)          # per-name annual vol
    prices = {s: 10.0 + float(rng.random()) * 490 for s in ids}
    current = {s: 0.0 for s in ids}
    adv = {s: 1e7 for s in ids}
    eng = PortfolioEngine()
    cm = TransactionCostModel()
    c = ConstraintSet(max_position_weight=0.02, long_only=True, gross_exposure=1.0,
                      max_adv_participation=0.1)

    print(f"universe: {n:,} securities (diagonal covariance)")
    tracemalloc.start()
    for obj in (Objective.EQUAL_WEIGHT, Objective.MIN_VARIANCE, Objective.RISK_PARITY,
                Objective.MAX_DIVERSIFICATION):
        t = time.perf_counter()
        p = eng.construct(signals, ids, c, obj, vols=vols, prices=prices,
                          current_weights=current, cost_model=cm, adv=adv, capital=1e9)
        dt = (time.perf_counter() - t) * 1000
        _ = p.diagnostics["effective_holdings"]
        print(f"  {obj.value:20s} {dt:8.1f} ms  gross={p.gross_exposure:.3f} "
              f"maxw={max(abs(x.weight) for x in p.positions):.4f} eff={p.diagnostics['effective_holdings']:.0f}")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  peak memory:         {peak/1e6:8.1f} MB")

    # dense mean-variance (full Σ) at a tractable size — document actual cost
    m = 800
    R = rng.normal(0.0005, 0.01, size=(500, m))
    cov = np.cov(R, rowvar=False)
    sig2 = {f"D{i}": float(v) for i, v in enumerate(rng.normal(size=m))}
    ids2 = list(sig2)
    t = time.perf_counter()
    eng.construct(sig2, ids2, ConstraintSet(max_position_weight=0.05), Objective.MAX_SHARPE, covariance=cov)
    print(f"  dense max_sharpe (N={m}, full Σ): {(time.perf_counter()-t)*1000:.1f} ms (O(N^3) pinv)")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 10_000)
