"""Solver interface (AIDP M10).

Dependency-injection seam: the engine depends on this ABC, never on a concrete
optimizer (scipy / cvxpy / analytic). A solver maps (expected returns, covariance,
context) → a raw weight vector; constraint enforcement happens downstream so
solvers stay pure and comparable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Solver(ABC):
    name: str = "solver"

    @abstractmethod
    def solve(self, mu: np.ndarray, cov: np.ndarray, *, ctx: dict | None = None) -> np.ndarray:
        """Return an (unconstrained) weight vector. Constraint projection is applied
        by the engine afterwards."""


def pinv(cov: np.ndarray) -> np.ndarray:
    """Moore-Penrose pseudo-inverse — robust to a singular / ill-conditioned Σ."""
    return np.linalg.pinv(cov)


def l1_normalize(w: np.ndarray) -> np.ndarray:
    """Normalize to gross exposure 1 (Σ|w| = 1). Zero vector → equal weight."""
    s = np.abs(w).sum()
    if s <= 0:
        return np.full(w.size, 1.0 / max(w.size, 1))
    return w / s
