"""Closed-form option pricing (AIDP M18).

Production Black-Scholes (spot + continuous dividend yield) and Black-76 (options on a
forward/future), with a consistent Greek set (delta, gamma, theta, vega, rho, vanna, volga)
derived from the same inputs, plus implied-vol inversion. Pure functions of explicit inputs
— spot/forward, strike, rate, dividend yield, vol, time, right — nothing is sourced
implicitly. All quantities are per-unit (per share / per index point); the engine scales by
contract size.

No-arbitrage behaviour is a tested invariant: put-call parity, monotonicity, non-negativity,
and the European bounds all hold to deterministic tolerance.
"""

from __future__ import annotations

import math

SQRT2PI = math.sqrt(2.0 * math.pi)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


def _intrinsic(is_call: bool, s: float, k: float) -> float:
    return max(0.0, s - k) if is_call else max(0.0, k - s)


# ── Black-Scholes (spot, dividend yield q) ───────────────────────────────────


def _d1_d2(s: float, k: float, r: float, q: float, vol: float, t: float):
    if s <= 0 or k <= 0:
        raise ValueError("spot and strike must be > 0")
    if t <= 0 or vol <= 0:
        return None
    v = vol * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * vol * vol) * t) / v
    return d1, d1 - v


def black_scholes_price(
    is_call: bool, s: float, k: float, r: float, q: float, vol: float, t: float
) -> float:
    dd = _d1_d2(s, k, r, q, vol, t)
    if dd is None:  # expiry / zero-vol → discounted intrinsic
        disc_s = s * math.exp(-q * max(t, 0.0))
        disc_k = k * math.exp(-r * max(t, 0.0))
        return _intrinsic(is_call, disc_s, disc_k)
    d1, d2 = dd
    df_s, df_k = math.exp(-q * t), math.exp(-r * t)
    if is_call:
        return s * df_s * norm_cdf(d1) - k * df_k * norm_cdf(d2)
    return k * df_k * norm_cdf(-d2) - s * df_s * norm_cdf(-d1)


def black_scholes_greeks(
    is_call: bool, s: float, k: float, r: float, q: float, vol: float, t: float
) -> dict:
    """Per-unit Greeks. vega/theta/rho are per 1.00 (not per 1%); the engine may rescale."""
    dd = _d1_d2(s, k, r, q, vol, t)
    if dd is None:
        # degenerate: delta is the discounted digital, everything else ~0
        itm = (s > k) if is_call else (s < k)
        return {
            "delta": (1.0 if (itm and is_call) else (-1.0 if itm and not is_call else 0.0)),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
            "vanna": 0.0,
            "volga": 0.0,
        }
    d1, d2 = dd
    sqt = math.sqrt(t)
    df_s, df_k = math.exp(-q * t), math.exp(-r * t)
    nd1 = norm_pdf(d1)
    gamma = df_s * nd1 / (s * vol * sqt)
    vega = s * df_s * nd1 * sqt
    vanna = -df_s * nd1 * d2 / vol
    volga = vega * d1 * d2 / vol
    if is_call:
        delta = df_s * norm_cdf(d1)
        theta = (
            -s * df_s * nd1 * vol / (2 * sqt)
            - r * k * df_k * norm_cdf(d2)
            + q * s * df_s * norm_cdf(d1)
        )
        rho = k * t * df_k * norm_cdf(d2)
    else:
        delta = -df_s * norm_cdf(-d1)
        theta = (
            -s * df_s * nd1 * vol / (2 * sqt)
            + r * k * df_k * norm_cdf(-d2)
            - q * s * df_s * norm_cdf(-d1)
        )
        rho = -k * t * df_k * norm_cdf(-d2)
    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
        "vanna": vanna,
        "volga": volga,
    }


# ── Black-76 (option on a forward/future F) ──────────────────────────────────


def black76_price(is_call: bool, f: float, k: float, r: float, vol: float, t: float) -> float:
    df = math.exp(-r * max(t, 0.0))
    if t <= 0 or vol <= 0:
        return df * _intrinsic(is_call, f, k)
    v = vol * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * vol * vol * t) / v
    d2 = d1 - v
    if is_call:
        return df * (f * norm_cdf(d1) - k * norm_cdf(d2))
    return df * (k * norm_cdf(-d2) - f * norm_cdf(-d1))


def black76_greeks(is_call: bool, f: float, k: float, r: float, vol: float, t: float) -> dict:
    """Black-76 = Black-Scholes with S→F and q=r (so S·e^{-qT} == F·e^{-rT})."""
    return black_scholes_greeks(is_call, f, k, r, r, vol, t)


# ── implied volatility ───────────────────────────────────────────────────────


def implied_vol(
    is_call: bool,
    price: float,
    s: float,
    k: float,
    r: float,
    q: float,
    t: float,
    *,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> float:
    """Invert Black-Scholes for vol via bisection (robust, deterministic)."""
    intrinsic = math.exp(-q * t) * s - math.exp(-r * t) * k
    lo_bound = max(0.0, intrinsic if is_call else -intrinsic)
    if price <= lo_bound + 1e-12:
        return 0.0
    lo, hi = 1e-6, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        pm = black_scholes_price(is_call, s, k, r, q, mid, t)
        if abs(pm - price) < tol:
            return mid
        if pm > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
