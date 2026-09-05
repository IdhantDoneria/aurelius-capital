"""Optimizer wiring: covariance & expected-return abstractions + the DI optimizer
(AIDP M10).

The engine never hard-codes a solver, a covariance estimator, or an expected-return
model — all three are injectable interfaces. Concrete, working implementations are
provided; Black-Litterman and Bayesian return models are interfaces with documented
extension points.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from mentisrex.research.portfolio.constraints import ConstraintSet
from mentisrex.research.portfolio.solvers.base import Solver

# ── covariance estimators ───────────────────────────────────────────────────────


class CovarianceEstimator(ABC):
    @abstractmethod
    def estimate(self, returns: np.ndarray) -> np.ndarray:
        """returns: (T, N) matrix → (N, N) covariance."""


class SampleCovariance(CovarianceEstimator):
    def estimate(self, returns):
        return np.cov(np.asarray(returns, dtype=float), rowvar=False)


class DiagonalCovariance(CovarianceEstimator):
    """Variances only — assumes zero cross-correlation (conservative, well-conditioned)."""

    def estimate(self, returns):
        var = np.var(np.asarray(returns, dtype=float), axis=0, ddof=1)
        return np.diag(var)


class ShrinkageCovariance(CovarianceEstimator):
    """Ledoit-Wolf-style linear shrinkage toward a scaled-identity target:
    Σ̂ = (1−δ)·S + δ·μ̄·I, with δ auto-estimated when not given.

    Reference: Ledoit & Wolf (2004) "A well-conditioned estimator for large-
    dimensional covariance matrices"."""

    def __init__(self, delta: float | None = None) -> None:
        self._delta = delta

    def estimate(self, returns):
        X = np.asarray(returns, dtype=float)
        T, N = X.shape
        S = np.cov(X, rowvar=False)
        mu = np.trace(S) / N
        target = mu * np.eye(N)
        if self._delta is not None:
            delta = self._delta
        else:
            Xc = X - X.mean(axis=0)
            # LW intensity estimate (toward identity target)
            phi = sum(np.sum((np.outer(Xc[t], Xc[t]) - S) ** 2) for t in range(T)) / T**2
            gamma = np.linalg.norm(S - target, "fro") ** 2
            delta = float(np.clip(phi / gamma, 0.0, 1.0)) if gamma > 0 else 0.0
        return (1 - delta) * S + delta * target


# ── expected-return models ──────────────────────────────────────────────────────


class ExpectedReturnModel(ABC):
    @abstractmethod
    def estimate(self, signal: np.ndarray, **ctx) -> np.ndarray: ...


class SignalExpectedReturns(ExpectedReturnModel):
    """Cross-sectionally standardize a signal into an expected-return vector:
    μ = z(signal)·scale. Keeps alpha generation (the signal) separate from
    construction (this mapping)."""

    def __init__(self, scale: float = 0.05) -> None:
        self._scale = scale

    def estimate(self, signal, **ctx):
        s = np.asarray(signal, dtype=float)
        sd = s.std()
        z = (s - s.mean()) / sd if sd > 0 else np.zeros_like(s)
        return z * self._scale


class BlackLittermanModel(ExpectedReturnModel):
    """Black-Litterman interface (extension point). Full implementation needs market
    equilibrium weights, a risk-aversion coefficient, and a views matrix (P, Q, Ω);
    absent those it returns the prior (equilibrium/signal) unchanged with a note."""

    def estimate(self, signal, **ctx):
        note = ctx.get("_notes")
        if isinstance(note, dict):
            note["black_litterman"] = "not implemented — returned prior (see docs)"
        return np.asarray(signal, dtype=float)


class BayesianExpectedReturns(ExpectedReturnModel):
    """Bayesian shrinkage of the signal toward the cross-sectional mean (grand-mean
    prior), shrinkage τ ∈ [0,1]. A concrete, if simple, Bayesian estimator."""

    def __init__(self, tau: float = 0.5) -> None:
        self._tau = tau

    def estimate(self, signal, **ctx):
        s = np.asarray(signal, dtype=float)
        return (1 - self._tau) * s + self._tau * s.mean()


# ── DI optimizer ────────────────────────────────────────────────────────────────


class Optimizer:
    """Binds a Solver to a ConstraintSet. `optimize` solves then projects into the
    feasible set — the single place solver output meets constraints."""

    def __init__(self, solver: Solver, constraints: ConstraintSet | None = None) -> None:
        self.solver = solver
        self.constraints = constraints or ConstraintSet()

    def optimize(self, expected_returns, covariance, *, ctx: dict | None = None):
        raw = self.solver.solve(
            np.asarray(expected_returns, dtype=float), np.asarray(covariance, dtype=float), ctx=ctx
        )
        return self.constraints.enforce(raw)
