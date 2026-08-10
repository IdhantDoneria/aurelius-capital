"""Futures / forward fair value (AIDP M18).

Cost-of-carry fair value F = S·e^{(r-q)·T} (equity index / dividend-paying underlyings),
basis, implied financing rate and expiry convergence. Deterministic, pure functions.
Contract multiplier is applied by the engine, not here (these are per-unit prices).
"""

from __future__ import annotations

import math


def fair_value(spot: float, rate: float, div_yield: float, t: float) -> float:
    """Cost-of-carry forward/future fair value. At t=0 it converges to spot."""
    if spot <= 0:
        raise ValueError("spot must be > 0")
    return spot * math.exp((rate - div_yield) * max(t, 0.0))


def basis(futures_price: float, spot: float) -> float:
    """Futures minus spot (positive = contango)."""
    return futures_price - spot


def implied_financing(futures_price: float, spot: float, div_yield: float, t: float) -> float:
    """Rate implied by an observed futures price given spot + dividend yield."""
    if spot <= 0 or futures_price <= 0 or t <= 0:
        raise ValueError("need positive spot, futures and t")
    return math.log(futures_price / spot) / t + div_yield


def converges_at_expiry(spot: float, rate: float, div_yield: float, tol: float = 1e-9) -> bool:
    """Fair value at t=0 equals spot (the expiry-convergence invariant)."""
    return abs(fair_value(spot, rate, div_yield, 0.0) - spot) < tol
