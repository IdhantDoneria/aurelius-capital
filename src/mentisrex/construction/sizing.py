"""Position sizing — turn an alpha view + risk estimates into portfolio weights.

Three schemes, increasing in how much they trust the covariance estimate. Alpha
sets the *sign* (long/short) of each weight; the scheme sets the *magnitude*.
Names with zero alpha are dropped.

Schemes & math (w_i is fraction of NAV; sign from alpha):
  equal_weight:       |w_i| = 1/N over selected names. Trusts nothing about risk.
  volatility_target:  |w_i| ∝ 1/sigma_i (inverse-vol), then scale the book so the
                      portfolio vol hits sigma_target: w *= sigma_target / sqrt(wᵀΣw).
  risk_parity:        choose w so each name's risk contribution is equal,
                      RC_i = w_i (Σw)_i / (wᵀΣw) = 1/N. Solved by fixed-point
                      iteration (no closed form for a full Σ).

Assumptions:
  - equal_weight: none about risk — its strength is estimation-error immunity.
  - vol_target / risk_parity: sigma_i and Σ are stable and forward-looking.

Limitations / when each fails:
  - equal_weight: equal *capital* != equal *risk*; a high-vol name dominates P&L.
  - volatility_target: ignores correlation in the per-name step, so a book of
    correlated low-vol names understates true portfolio vol; the target scale
    can then imply large leverage. Vol regime shifts break the sigma forecast.
  - risk_parity: piles into the lowest-vol assets and levers them up; a bad Σ
    (near-singular, correlated cluster) makes contributions meaningless. No
    return view at all — pure risk allocation.
"""

from __future__ import annotations

import math

import numpy as np


def _signs(alphas: dict[str, float]) -> dict[str, float]:
    return {s: math.copysign(1.0, a) for s, a in alphas.items() if a != 0.0}


def equal_weight(alphas: dict[str, float]) -> dict[str, float]:
    signs = _signs(alphas)
    n = len(signs)
    if n == 0:
        return {}
    return {s: sign / n for s, sign in signs.items()}


def volatility_target(
    alphas: dict[str, float],
    vols: dict[str, float],
    target_vol: float = 0.10,
    cov: tuple[list[str], np.ndarray] | None = None,
) -> dict[str, float]:
    """Inverse-vol weights scaled to a target annualized portfolio vol.

    If a full covariance is supplied it is used for the portfolio-vol scaling
    (captures correlation); otherwise the sqrt(sum) assumes independence.
    """
    signs = _signs(alphas)
    inv = {s: 1.0 / vols[s] for s in signs if vols.get(s, 0.0) > 0}
    tot = sum(inv.values())
    if tot == 0:
        return {}
    w = {s: signs[s] * inv[s] / tot for s in inv}

    port_vol = _portfolio_vol(w, vols, cov)
    if port_vol > 0:
        scale = target_vol / port_vol
        w = {s: wi * scale for s, wi in w.items()}
    return w


def risk_parity(
    symbols: list[str], cov: np.ndarray, alphas: dict[str, float], iters: int = 1000
) -> dict[str, float]:
    """Equal-risk-contribution weights via fixed-point iteration.

    Update w_i <- w_i * sqrt(target_RC / RC_i) then renormalize; converges for a
    well-conditioned PSD Sigma. ponytail: iteration cap, no convergence proof for
    pathological Sigma — check optimize.condition_number first.
    """
    n = len(symbols)
    if n == 0:
        return {}
    w = np.full(n, 1.0 / n)
    for _ in range(iters):
        sigma_w = cov @ w
        rc = w * sigma_w
        total = rc.sum()
        if total <= 0:
            break
        target = total / n
        w = w * np.sqrt(target / np.maximum(rc, 1e-12))
        w = np.clip(w, 1e-9, None)
        w /= w.sum()
    signs = _signs(alphas)
    return {s: float(w[i]) * signs.get(s, 1.0) for i, s in enumerate(symbols)}


def _portfolio_vol(
    w: dict[str, float], vols: dict[str, float], cov: tuple[list[str], np.ndarray] | None
) -> float:
    if cov is not None:
        syms, sigma = cov
        vec = np.array([w.get(s, 0.0) for s in syms])
        return math.sqrt(max(0.0, float(vec @ sigma @ vec)))
    # No covariance -> assume independence: Var = sum(w_i^2 * sigma_i^2).
    return math.sqrt(sum((wi * vols.get(s, 0.0)) ** 2 for s, wi in w.items()))
