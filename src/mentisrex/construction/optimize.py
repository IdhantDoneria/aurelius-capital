"""Portfolio optimization — turn a covariance matrix (and optionally expected
returns) into weights. numpy only; no scipy, so constrained problems use a
projected-gradient solver rather than a QP library.

Covariance is the whole game here: every method is a function of Sigma, and every
failure mode is an estimation-error-in-Sigma story.

Methods & math:
  min_variance:  min wᵀΣw  s.t. 1ᵀw = 1.  Closed form w = Σ⁻¹1 / (1ᵀΣ⁻¹1).
  max_sharpe:    tangency portfolio w ∝ Σ⁻¹μ, renormalized to sum 1.
  constrained:   min wᵀΣw with box (lo<=w_i<=hi) + sum(w)=1, projected gradient.

Assumptions (all methods):
  - Σ is the *true* forward covariance. It is not — it is a noisy sample estimate.
  - Returns are (roughly) elliptically distributed so variance captures risk.
  - max_sharpe additionally assumes μ is known; it almost never is.

Limitations / when it fails:
  - Σ singular or ill-conditioned -> Σ⁻¹ explodes -> extreme, unstable weights.
    We use the pseudo-inverse so the call *returns* instead of throwing, but the
    output is only as trustworthy as Σ's conditioning. Check condition number.
  - min_variance ignores returns entirely: it will happily 100%-weight the
    lowest-vol asset even with zero/negative expected return.
  - max_sharpe is an "error maximizer" (Michaud): tiny μ errors -> huge weight
    swings, frequent large shorts. Shrink μ/Σ or prefer min_variance in practice.
  - projected gradient finds the global optimum only because min-variance is
    convex; a non-convex objective would need a real solver.
"""

from __future__ import annotations

import numpy as np


def sample_covariance(
    returns: dict[str, list[float]],
) -> tuple[list[str], np.ndarray]:
    """Sample covariance of aligned return series. Returns (symbols, Sigma).

    Series are right-aligned to the shortest length so all are the same T.
    """
    syms = [s for s, r in returns.items() if len(r) >= 2]
    if len(syms) < 1:
        return [], np.zeros((0, 0))
    t = min(len(returns[s]) for s in syms)
    mat = np.array([returns[s][-t:] for s in syms], dtype=float)
    # rowvar=True: each row is a variable (asset). ddof=1 -> unbiased sample cov.
    cov = np.cov(mat, ddof=1) if t > 1 else np.zeros((len(syms), len(syms)))
    return syms, np.atleast_2d(cov)


def min_variance(cov: np.ndarray) -> np.ndarray:
    """Global minimum-variance weights. w = Σ⁻¹1 / (1ᵀΣ⁻¹1)."""
    n = cov.shape[0]
    inv = np.linalg.pinv(cov)  # pinv: survive a singular Sigma
    ones = np.ones(n)
    denom = ones @ inv @ ones
    if abs(denom) < 1e-15:
        return np.full(n, 1.0 / n)  # degenerate -> equal weight fallback
    return (inv @ ones) / denom


def max_sharpe(mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Tangency portfolio w ∝ Σ⁻¹μ, renormalized. Guards a non-positive sum."""
    inv = np.linalg.pinv(cov)
    raw = inv @ mu
    s = raw.sum()
    if abs(s) < 1e-15:
        return min_variance(cov)  # μ carries no usable signal -> min-var
    return raw / s


def constrained_min_variance(
    cov: np.ndarray,
    lo: float = 0.0,
    hi: float = 1.0,
    iters: int = 2000,
    step: float | None = None,
) -> np.ndarray:
    """min wᵀΣw s.t. lo<=w_i<=hi and sum(w)=1, via projected gradient descent.

    Convex objective + convex feasible set -> converges to the global optimum.
    ponytail: fixed step / iteration cap, no line search. Fine for the small
    (tens of names) covariance matrices this framework builds; raise iters or
    add a real QP if you optimize thousands of names.
    """
    n = cov.shape[0]
    w = np.full(n, 1.0 / n)
    # Step from the spectral norm keeps gradient descent stable (1/L, L=2*lambda_max).
    if step is None:
        lam = float(np.linalg.eigvalsh(cov).max()) if n else 1.0
        step = 1.0 / (2 * lam) if lam > 0 else 1.0
    for _ in range(iters):
        grad = 2 * cov @ w
        w = _project_box_simplex(w - step * grad, lo, hi)
    return w


def _project_box_simplex(v: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Project v onto {lo<=w<=hi, sum(w)=1} by bisecting the sum on a shift tau.

    clip(v - tau, lo, hi) is monotone decreasing in tau; find tau s.t. sum == 1.
    """
    n = len(v)
    if n * lo > 1 + 1e-9 or n * hi < 1 - 1e-9:
        return np.full(n, 1.0 / n)  # infeasible box -> equal weight
    a, b = float(v.min()) - hi, float(v.max()) - lo
    for _ in range(100):
        tau = (a + b) / 2
        s = np.clip(v - tau, lo, hi).sum()
        if s > 1:
            a = tau
        else:
            b = tau
    return np.clip(v - (a + b) / 2, lo, hi)


def condition_number(cov: np.ndarray) -> float:
    """max/min eigenvalue. High (>~1e3) = Sigma is unreliable, weights untrustworthy."""
    if cov.shape[0] == 0:
        return 0.0
    ev = np.linalg.eigvalsh(cov)
    lo = float(ev.min())
    return float("inf") if lo <= 0 else float(ev.max() / lo)
