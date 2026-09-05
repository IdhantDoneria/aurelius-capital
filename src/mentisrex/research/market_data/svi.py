"""SVI volatility parameterization (AIDP M19).

Gatheral's raw SVI total-variance smile:

    w(k) = a + b·( ρ·(k − m) + sqrt((k − m)² + σ²) )          (k = log-moneyness, w = σ_impl²·T)

An alternative to SABR, selectable by dependency injection in the surface calibrator. Calibration
is deterministic: for a fixed (m, σ) the model is **linear** in (a, b·ρ, b), so each grid node is
a closed-form 3×3 least-squares solve; a grid over (m, σ) picks the best. Butterfly (static) no-
arbitrage is checked via Gatheral–Durrleman g(k) ≥ 0; parameters are validated (b ≥ 0, |ρ| < 1,
σ > 0, a + b·σ·sqrt(1−ρ²) ≥ 0 so total variance stays non-negative).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SVIParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def total_variance(self, k: float) -> float:
        return self.a + self.b * (
            self.rho * (k - self.m) + math.sqrt((k - self.m) ** 2 + self.sigma**2)
        )

    def vol(self, k: float, t: float) -> float:
        w = self.total_variance(k)
        if w < 0 or t <= 0:
            raise ValueError(f"non-positive total variance {w} at k={k}")
        return math.sqrt(w / t)

    def validate(self) -> list:
        p = []
        if self.b < 0:
            p.append("b must be >= 0")
        if not -1.0 < self.rho < 1.0:
            p.append("rho must be in (-1, 1)")
        if self.sigma <= 0:
            p.append("sigma must be > 0")
        min_w = self.a + self.b * self.sigma * math.sqrt(max(0.0, 1.0 - self.rho**2))
        if min_w < -1e-12:
            p.append(f"min total variance {min_w:.3g} < 0")
        return p


def durrleman_g(params: SVIParams, k: float) -> float:
    """Gatheral–Durrleman g(k); g(k) >= 0 everywhere == no butterfly (density non-negative)."""
    a, b, rho, m, sig = params.a, params.b, params.rho, params.m, params.sigma
    disc = math.sqrt((k - m) ** 2 + sig**2)
    w = a + b * (rho * (k - m) + disc)
    if w <= 0:
        return -1.0
    wp = b * (rho + (k - m) / disc)  # w'(k)
    wpp = b * sig**2 / (disc**3)  # w''(k)
    term = (1.0 - 0.5 * k * wp / w) ** 2 - 0.25 * wp**2 * (1.0 / w + 0.25) + 0.5 * wpp
    return term


def butterfly_arbitrage(
    params: SVIParams, *, kmin: float = -1.5, kmax: float = 1.5, n: int = 61
) -> list:
    """Return log-moneyness points where g(k) < 0 (butterfly arbitrage)."""
    probs = []
    for i in range(n):
        k = kmin + (kmax - kmin) * i / (n - 1)
        if durrleman_g(params, k) < -1e-9:
            probs.append(f"butterfly arbitrage at k={k:.3f}")
    return probs


@dataclass(frozen=True)
class SVICalibration:
    params: SVIParams
    residuals: tuple  # (k, model_totvar - market_totvar)
    max_residual: float
    rmse: float
    arbitrage: tuple = ()


def _ls_fixed_ms(ks, ws, m, sigma):
    """Closed-form least squares for (a, e=b·ρ, d=b) at fixed (m, σ). Returns (a,b,rho,sse)."""
    # basis: [1, (k-m), sqrt((k-m)^2+sigma^2)]
    import numpy as np

    x = np.array([[1.0, (k - m), math.sqrt((k - m) ** 2 + sigma**2)] for k in ks])
    y = np.array(ws)
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    a, e, d = float(coef[0]), float(coef[1]), float(coef[2])
    b = max(d, 1e-8)
    rho = max(-0.999, min(0.999, e / b))
    resid = x @ coef - y
    return a, b, rho, float(resid @ resid)


def calibrate_svi(log_moneyness, total_variances, *, refine: bool = True) -> SVICalibration:
    """Deterministic (m, σ) grid with a linear LS inner solve. Inputs are total variances (σ²·T)."""
    ks = list(log_moneyness)
    ws = list(total_variances)
    if len(ks) != len(ws) or len(ks) < 3:
        raise ValueError("need >= 3 (log-moneyness, total-variance) points")
    ms = [-0.5 + 0.05 * i for i in range(0, 21)]  # -0.5 .. 0.5
    sigmas = [0.02 + 0.02 * i for i in range(0, 50)]  # 0.02 .. 1.0
    best = None
    for m in ms:
        for sg in sigmas:
            a, b, rho, sse = _ls_fixed_ms(ks, ws, m, sg)
            if best is None or sse < best[-1]:
                best = (a, b, rho, m, sg, sse)
    if refine:
        a, b, rho, m0, s0, _ = best
        for m in [m0 + d for d in (-0.03, -0.015, 0.0, 0.015, 0.03)]:
            for sg in [s0 + d for d in (-0.015, 0.0, 0.015)]:
                if sg <= 0:
                    continue
                a, b, rho, sse = _ls_fixed_ms(ks, ws, m, sg)
                if sse < best[-1]:
                    best = (a, b, rho, m, sg, sse)
    a, b, rho, m, sg, _ = best
    params = SVIParams(a, b, rho, m, sg)
    resid = tuple((k, params.total_variance(k) - w) for k, w in zip(ks, ws, strict=False))
    max_res = max((abs(r) for _, r in resid), default=0.0)
    rmse = math.sqrt(sum(r * r for _, r in resid) / len(resid))
    return SVICalibration(params, resid, max_res, rmse, tuple(butterfly_arbitrage(params)))
