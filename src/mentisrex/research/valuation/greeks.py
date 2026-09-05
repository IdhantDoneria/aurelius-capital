"""Greeks utilities & finite-difference validation (AIDP M18).

The engine derives Greeks analytically from the pricing inputs; this module provides the
finite-difference cross-check (used by the numerical-validation tests) and the mapping of
portfolio Greeks into the sensitivity inputs M13 consumes. It does NOT recompute risk — M13
remains the risk authority; M18 supplies delta/gamma/vega/rho/duration/DV01/FX exposure.
"""

from __future__ import annotations

from mentisrex.research.valuation import pricing


def fd_delta(is_call, s, k, r, q, vol, t, *, h=1e-4) -> float:
    up = pricing.black_scholes_price(is_call, s * (1 + h), k, r, q, vol, t)
    dn = pricing.black_scholes_price(is_call, s * (1 - h), k, r, q, vol, t)
    return (up - dn) / (2 * s * h)


def fd_gamma(is_call, s, k, r, q, vol, t, *, h=1e-4) -> float:
    ds = s * h
    up = pricing.black_scholes_price(is_call, s + ds, k, r, q, vol, t)
    p0 = pricing.black_scholes_price(is_call, s, k, r, q, vol, t)
    dn = pricing.black_scholes_price(is_call, s - ds, k, r, q, vol, t)
    return (up - 2 * p0 + dn) / (ds * ds)


def fd_vega(is_call, s, k, r, q, vol, t, *, h=1e-4) -> float:
    up = pricing.black_scholes_price(is_call, s, k, r, q, vol + h, t)
    dn = pricing.black_scholes_price(is_call, s, k, r, q, vol - h, t)
    return (up - dn) / (2 * h)


def fd_rho(is_call, s, k, r, q, vol, t, *, h=1e-4) -> float:
    up = pricing.black_scholes_price(is_call, s, k, r + h, q, vol, t)
    dn = pricing.black_scholes_price(is_call, s, k, r - h, q, vol, t)
    return (up - dn) / (2 * h)


def to_m13_risk_inputs(
    portfolio_valuation,
    *,
    duration: float = 0.0,
    dv01: float = 0.0,
    fx_exposure: dict | None = None,
    margin: float = 0.0,
) -> dict:
    """Shape a PortfolioValuation + fixed-income/FX sensitivities into M13's input dict."""
    g = portfolio_valuation.greeks
    return {
        "portfolio_value": portfolio_valuation.base_value,
        "delta": g.delta if g else 0.0,
        "gamma": g.gamma if g else 0.0,
        "vega": g.vega if g else 0.0,
        "rho": g.rho if g else 0.0,
        "duration": duration,
        "dv01": dv01,
        "fx_exposure": fx_exposure or {},
        "margin_requirement": margin,
    }
