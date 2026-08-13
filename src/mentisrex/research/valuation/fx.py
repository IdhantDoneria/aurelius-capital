"""FX valuation (AIDP M18).

Spot, forward and cross-rate valuation that REUSES the M16 `FXRateProvider` — it does not
fork FX conversion. Adds covered-interest-parity forward rates, forward points, and FX
forward contract valuation on top of the injected M16 provider and M18 curves.
"""

from __future__ import annotations

import math


def spot_rate(fx_provider, base: str, quote: str, *, as_of=None) -> float:
    """Delegate to M16 — the single source of FX conversion."""
    return fx_provider.rate(base, quote, as_of=as_of)


def forward_rate(spot: float, r_base: float, r_quote: float, t: float) -> float:
    """Covered interest parity: F = S · e^{(r_quote - r_base)·T} (quote per base)."""
    return spot * math.exp((r_quote - r_base) * max(t, 0.0))


def forward_points(spot: float, forward: float) -> float:
    return forward - spot


def cross_rate(fx_provider, base: str, quote: str, pivot: str, *, as_of=None) -> float:
    """Cross rate via a pivot currency, using M16 resolution."""
    return (fx_provider.rate(base, pivot, as_of=as_of)
            * fx_provider.rate(pivot, quote, as_of=as_of))


def fx_forward_value(notional_base: float, contracted_rate: float, market_forward: float,
                     quote_discount: float) -> float:
    """PV (in quote currency) of a forward to buy `notional_base` of base at `contracted_rate`.

    Value = notional_base · (market_forward − contracted_rate) · DF_quote(T).
    """
    return notional_base * (market_forward - contracted_rate) * quote_discount


def reciprocal_consistent(fx_provider, base: str, quote: str, *, as_of=None,
                          tol: float = 1e-9) -> bool:
    """rate(A,B)·rate(B,A) == 1 — the M16 no-arbitrage FX invariant."""
    r = fx_provider.rate(base, quote, as_of=as_of) * fx_provider.rate(quote, base, as_of=as_of)
    return abs(r - 1.0) < tol
