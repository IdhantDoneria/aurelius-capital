"""Equal-weight solver (AIDP M10). w_i = 1/N. Ignores μ and Σ by design."""

from __future__ import annotations

import numpy as np

from aurelius.research.portfolio.solvers.base import Solver


class EqualWeightSolver(Solver):
    name = "equal_weight"

    def solve(self, mu: np.ndarray, cov: np.ndarray, *, ctx: dict | None = None) -> np.ndarray:
        n = mu.size
        return np.full(n, 1.0 / n) if n else np.array([])
