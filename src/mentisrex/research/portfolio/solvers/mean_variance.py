"""Mean-variance family solvers (AIDP M10).

Closed-form analytic optima (no scipy/cvxpy): Max-Sharpe (tangency), Min-Variance,
and Tracking-Error. All use the pseudo-inverse of Σ for robustness. Long/short
sign is whatever the optimum implies; the constraint engine enforces long-only,
bounds, and leverage afterward.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.portfolio.solvers.base import Solver, l1_normalize, pinv


class MaxSharpeSolver(Solver):
    """w ∝ Σ⁻¹ μ — the tangency portfolio. Sensitive to μ estimation error."""

    name = "max_sharpe"

    def solve(self, mu, cov, *, ctx=None):
        w = pinv(cov) @ mu
        return l1_normalize(w)


class MinVarianceSolver(Solver):
    """w ∝ Σ⁻¹ 1 — the global minimum-variance portfolio. Ignores μ."""

    name = "min_variance"

    def solve(self, mu, cov, *, ctx=None):
        ones = np.ones(mu.size)
        w = pinv(cov) @ ones
        return l1_normalize(w)


class TrackingErrorSolver(Solver):
    """Minimize active variance around a benchmark b, tilted toward μ:
    w = b + λ·Σ⁻¹μ, with λ scaled to a tracking-error budget. Without a benchmark
    it reduces to Max-Sharpe."""

    name = "tracking_error"

    def solve(self, mu, cov, *, ctx=None):
        ctx = ctx or {}
        b = ctx.get("benchmark_weights")
        te_budget = float(ctx.get("tracking_error_budget", 0.05))
        if b is None:
            return l1_normalize(pinv(cov) @ mu)
        b = np.asarray(b, dtype=float)
        tilt = pinv(cov) @ mu
        denom = np.sqrt(max(tilt @ cov @ tilt, 1e-16))
        w = b + te_budget * tilt / denom  # active tilt scaled to the TE budget
        return l1_normalize(w)
