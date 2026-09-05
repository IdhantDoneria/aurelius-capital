"""SABR stochastic-volatility model (AIDP M19).

Hagan et al. (2002) lognormal implied-vol expansion and a deterministic calibrator. Given a
forward, expiry and a market smile (strikes → implied vols), `calibrate_sabr` fixes β (a market
choice) and fits (α, ρ, ν) with no RNG and no external optimizer: a deterministic grid over
(ρ, ν), α pinned to the ATM vol by 1-D bisection for each grid point, then a local refinement
grid around the best node. Parameters are validated (α>0, β∈[0,1], |ρ|<1, ν>0) — invalid
combinations are never returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def sabr_vol(
    f: float, k: float, t: float, alpha: float, beta: float, rho: float, nu: float
) -> float:
    """Hagan lognormal implied vol. Uses the ATM limit when |f−k| is tiny."""
    if alpha <= 0 or t <= 0 or f <= 0 or k <= 0:
        raise ValueError("sabr_vol needs positive alpha, t, f, k")
    eps = 1e-12
    one_beta = 1.0 - beta
    if abs(f - k) < 1e-9 * max(f, 1.0):  # ATM
        fk_beta = f**one_beta
        term = (
            ((one_beta**2) / 24.0) * alpha**2 / (fk_beta**2)
            + 0.25 * rho * beta * nu * alpha / fk_beta
            + ((2.0 - 3.0 * rho**2) / 24.0) * nu**2
        )
        return (alpha / fk_beta) * (1.0 + term * t)
    logfk = math.log(f / k)
    fk_beta = (f * k) ** (one_beta / 2.0)
    z = (nu / alpha) * fk_beta * logfk
    xz = math.log((math.sqrt(1.0 - 2.0 * rho * z + z * z) + z - rho) / (1.0 - rho))
    if abs(xz) < eps:
        xz = eps
    denom = fk_beta * (1.0 + (one_beta**2) / 24.0 * logfk**2 + (one_beta**4) / 1920.0 * logfk**4)
    term = (
        ((one_beta**2) / 24.0) * alpha**2 / (fk_beta**2)
        + 0.25 * rho * beta * nu * alpha / fk_beta
        + ((2.0 - 3.0 * rho**2) / 24.0) * nu**2
    )
    return (alpha / denom) * (z / xz) * (1.0 + term * t)


def _alpha_from_atm(atm_vol, f, t, beta, rho, nu):
    """Solve α so the SABR ATM vol matches `atm_vol` (bisection — monotone in α)."""

    def g(a):
        return sabr_vol(f, f, t, a, beta, rho, nu) - atm_vol

    lo, hi = 1e-6, 5.0
    glo, ghi = g(lo), g(hi)
    if glo * ghi > 0:
        return max(1e-6, atm_vol * f ** (1.0 - beta))  # fallback initial guess
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        gm = g(mid)
        if abs(gm) < 1e-12:
            return mid
        if (gm > 0) == (glo > 0):
            lo, glo = mid, gm
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class SABRParams:
    alpha: float
    beta: float
    rho: float
    nu: float

    def validate(self) -> list:
        p = []
        if self.alpha <= 0:
            p.append("alpha must be > 0")
        if not 0.0 <= self.beta <= 1.0:
            p.append("beta must be in [0, 1]")
        if not -1.0 < self.rho < 1.0:
            p.append("rho must be in (-1, 1)")
        if self.nu <= 0:
            p.append("nu must be > 0")
        return p

    def vol(self, f, k, t):
        return sabr_vol(f, k, t, self.alpha, self.beta, self.rho, self.nu)


@dataclass(frozen=True)
class SABRCalibration:
    params: SABRParams
    residuals: tuple  # (strike, model_vol - market_vol)
    max_residual: float
    rmse: float


def calibrate_sabr(
    f: float, t: float, strikes, market_vols, *, beta: float = 0.5, refine: bool = True
) -> SABRCalibration:
    """Deterministic (ρ, ν) grid + α-from-ATM fit. `beta` is fixed by the caller (market choice)."""
    strikes = list(strikes)
    market_vols = list(market_vols)
    if len(strikes) != len(market_vols) or not strikes:
        raise ValueError("strikes/market_vols must be non-empty, equal length")
    # ATM target: vol nearest the forward
    atm = min(zip(strikes, market_vols, strict=False), key=lambda kv: abs(kv[0] - f))[1]

    def sse(rho, nu):
        a = _alpha_from_atm(atm, f, t, beta, rho, nu)
        s = 0.0
        for k, mv in zip(strikes, market_vols, strict=False):
            s += (sabr_vol(f, k, t, a, beta, rho, nu) - mv) ** 2
        return s, a

    rhos = [i / 10.0 for i in range(-9, 10)]  # -0.9 .. 0.9
    nus = [0.05 + 0.05 * i for i in range(0, 40)]  # 0.05 .. 2.0
    best = None
    for rho in rhos:
        for nu in nus:
            s, a = sse(rho, nu)
            if best is None or s < best[0]:
                best = (s, rho, nu, a)
    if refine:
        _, rho0, nu0, _ = best
        for rho in [rho0 + d for d in (-0.05, -0.025, 0.0, 0.025, 0.05)]:
            if not -0.999 < rho < 0.999:
                continue
            for nu in [nu0 + d for d in (-0.04, -0.02, 0.0, 0.02, 0.04)]:
                if nu <= 0:
                    continue
                s, a = sse(rho, nu)
                if s < best[0]:
                    best = (s, rho, nu, a)
    _, rho, nu, alpha = best
    params = SABRParams(alpha, beta, rho, nu)
    resid = tuple(
        (k, sabr_vol(f, k, t, alpha, beta, rho, nu) - mv)
        for k, mv in zip(strikes, market_vols, strict=False)
    )
    max_res = max((abs(r) for _, r in resid), default=0.0)
    rmse = math.sqrt(sum(r * r for _, r in resid) / len(resid))
    return SABRCalibration(params, resid, max_res, rmse)
