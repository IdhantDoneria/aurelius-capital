"""Arbitrage diagnostics (AIDP M18).

Deterministic no-arbitrage / consistency checks over curves, surfaces, FX and option prices.
Each returns a list of problems (empty == consistent). These are the guardrails the
validator and tests lean on; they diagnose, they do not fix.
"""

from __future__ import annotations

from mentisrex.research.valuation import fx as _fx
from mentisrex.research.valuation import pricing


def negative_discount_factors(curve, tenors=None) -> list:
    tenors = tenors or curve.tenors
    return [f"{curve.curve_id}: DF({t}) <= 0" for t in tenors if curve.discount(t) <= 0]


def curve_discontinuities(
    curve, *, step: float = 0.25, tmax: float = 30.0, jump_tol: float = 0.05
) -> list:
    """Flag large jumps in the zero rate between adjacent sample points."""
    problems, t, prev = [], step, None
    while t <= tmax:
        z = curve.zero_rate(t)
        if prev is not None and abs(z - prev) > jump_tol:
            problems.append(f"{curve.curve_id}: zero-rate jump {prev:.4g}->{z:.4g} near t={t}")
        prev, t = z, t + step
    return problems


def fx_reciprocal(fx_provider, pairs, *, as_of=None, tol: float = 1e-9) -> list:
    return [
        f"FX reciprocal violated for {b}/{q}"
        for b, q in pairs
        if not _fx.reciprocal_consistent(fx_provider, b, q, as_of=as_of, tol=tol)
    ]


def put_call_parity(s, k, r, q, vol, t, *, tol: float = 1e-6) -> list:
    import math

    c = pricing.black_scholes_price(True, s, k, r, q, vol, t)
    p = pricing.black_scholes_price(False, s, k, r, q, vol, t)
    lhs = c - p
    rhs = s * math.exp(-q * t) - k * math.exp(-r * t)
    return [] if abs(lhs - rhs) < tol else [f"put-call parity off by {lhs - rhs:.3g}"]


def option_bounds(price, is_call, s, k, r, q, t, *, tol: float = 1e-6) -> list:
    """European no-arbitrage bounds: intrinsic-of-forwards <= price <= discounted spot/strike."""
    import math

    df_s, df_k = math.exp(-q * t), math.exp(-r * t)
    if is_call:
        lo, hi = max(0.0, s * df_s - k * df_k), s * df_s
    else:
        lo, hi = max(0.0, k * df_k - s * df_s), k * df_k
    problems = []
    if price < lo - tol:
        problems.append(f"option price {price:.6g} below lower bound {lo:.6g}")
    if price > hi + tol:
        problems.append(f"option price {price:.6g} above upper bound {hi:.6g}")
    return problems


def calendar_spread(surface, strike, t_short, t_long) -> list:
    """Total variance should be non-decreasing in maturity at a fixed strike."""
    if t_long <= t_short:
        return ["calendar: t_long must exceed t_short"]
    v_s = surface.vol(strike, t_short) ** 2 * t_short
    v_l = surface.vol(strike, t_long) ** 2 * t_long
    return [] if v_l >= v_s - 1e-9 else [f"calendar-spread arbitrage at K={strike}"]


def negative_prices(results) -> list:
    return [f"{r.instrument_id}: negative price {r.price:.6g}" for r in results if r.price < 0]


def vol_surface_consistency(surface) -> list:
    return surface.validate()
