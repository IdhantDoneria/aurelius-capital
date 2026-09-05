"""Risk-parity solver (AIDP M10).

Equal risk contribution: choose w so RC_i = w_i·(Σw)_i is equal across assets. No
closed form under long-only, so the standard multiplicative fixed-point iteration
(Spinu 2013 / Chaves et al. 2011) is used; deterministic from a fixed start.
Includes a Hierarchical Risk Parity (HRP) extension point.

Reference: Chaves, Hsu, Li, Shakernia (2011) "Risk Parity Portfolio vs. Other
Asset Allocation Heuristics".
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.portfolio.solvers.base import Solver


class RiskParitySolver(Solver):
    name = "risk_parity"

    def __init__(self, *, max_iter: int = 1000, tol: float = 1e-10) -> None:
        self._max_iter = max_iter
        self._tol = tol

    def solve(self, mu, cov, *, ctx=None):
        n = mu.size
        if n == 0:
            return np.array([])
        budget = np.full(n, 1.0 / n)  # equal risk budget
        w = 1.0 / np.sqrt(np.clip(np.diag(cov), 1e-12, None))
        w = w / w.sum()
        for _ in range(self._max_iter):
            rc = w * (cov @ w)  # risk contribution RC_i = w_i(Σw)_i
            rc = np.where(np.abs(rc) < 1e-15, 1e-15, rc)
            # sqrt-damped multiplicative update — stable (undamped ratio oscillates
            # and can pin weights at 0); converges to equal risk contribution.
            w_new = w * np.sqrt(budget / rc)
            w_new = w_new / w_new.sum()
            if np.max(np.abs(w_new - w)) < self._tol:
                w = w_new
                break
            w = w_new
        return w


class HierarchicalRiskParitySolver(Solver):
    """HRP (López de Prado 2016) extension point. Not implemented — falls back to
    plain risk parity with a metadata note so the caller knows. Implement by
    clustering the correlation matrix and recursively bisecting risk budgets."""

    name = "hrp"

    def solve(self, mu, cov, *, ctx=None):
        if ctx is not None:
            ctx["hrp_fallback"] = "HRP not implemented; used risk parity (see docs)"
        return RiskParitySolver().solve(mu, cov, ctx=ctx)
