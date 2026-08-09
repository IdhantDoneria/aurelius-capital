"""Covariance engine (AIDP M13) — dependency-injected estimators.

Reuses the M10 estimators (`SampleCovariance`, `DiagonalCovariance`,
`ShrinkageCovariance`) rather than re-implementing them, and adds an EWMA
(RiskMetrics) estimator and a factor-covariance interface. `make_covariance`
selects one by name for DI.
"""

from __future__ import annotations

import numpy as np

# reuse — do not duplicate the M10 estimators
from aurelius.research.portfolio.optimizer import (
    CovarianceEstimator,
    DiagonalCovariance,
    SampleCovariance,
    ShrinkageCovariance,
)


class EWMACovariance(CovarianceEstimator):
    """Exponentially-weighted covariance (RiskMetrics). λ=0.94 daily default —
    weights recent observations more, tracking regime shifts."""

    def __init__(self, lam: float = 0.94) -> None:
        self.lam = lam

    def estimate(self, returns):
        X = np.asarray(returns, dtype=float)
        T, _ = X.shape
        Xc = X - X.mean(axis=0)
        w = self.lam ** np.arange(T - 1, -1, -1)       # oldest→newest weight
        w /= w.sum()
        return (Xc * w[:, None]).T @ Xc


class FactorCovariance(CovarianceEstimator):
    """Σ = B F Bᵀ + D — factor-model covariance. Needs a factor-return matrix to
    fit loadings B and factor covariance F; without one it falls back to the
    injected base estimator (documented interface, honest fallback)."""

    def __init__(self, factor_returns=None, base: CovarianceEstimator | None = None) -> None:
        self.factor_returns = factor_returns
        self.base = base or DiagonalCovariance()

    def estimate(self, returns):
        X = np.asarray(returns, dtype=float)
        if self.factor_returns is None:
            return self.base.estimate(X)
        F = np.asarray(self.factor_returns, dtype=float)
        # OLS loadings B (N×K), residual (specific) variance D
        B, *_ = np.linalg.lstsq(F, X, rcond=None)       # (K, N)
        B = B.T                                         # (N, K)
        resid = X - F @ B.T
        Fcov = np.cov(F, rowvar=False)
        D = np.diag(np.var(resid, axis=0, ddof=1))
        return B @ np.atleast_2d(Fcov) @ B.T + D


_ESTIMATORS = {
    "sample": SampleCovariance,
    "diagonal": DiagonalCovariance,
    "shrinkage": ShrinkageCovariance,
    "ewma": EWMACovariance,
    "factor": FactorCovariance,
}


def make_covariance(kind: str = "shrinkage", **kw) -> CovarianceEstimator:
    if kind not in _ESTIMATORS:
        raise ValueError(f"unknown covariance estimator {kind!r}; choices: {sorted(_ESTIMATORS)}")
    return _ESTIMATORS[kind](**kw)
