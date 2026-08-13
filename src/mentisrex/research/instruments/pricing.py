"""Pricing & Greeks providers (AIDP M17).

Dependency-injected pricing — M17 defines the *interfaces* and ships a deterministic mock,
never a hard-coded valuation. Real Black-Scholes / Monte-Carlo pricers plug in by
implementing `PricingProvider`; the book never assumes one.

Interfaces
  PricingProvider  price(instrument, market) -> per-unit price
  GreeksProvider   greeks(instrument, market) -> Greeks
  YieldProvider    ytm/duration(instrument, price) -> float

`market` is a plain dict of inputs (spot, vol, rate, forward, ...), so the same call
shape serves every asset class and nothing is implicitly sourced.
"""

from __future__ import annotations

import math
from typing import Protocol

from mentisrex.research.instruments.models import Greeks, Instrument, InstrumentType, OptionRight


class PricingProvider(Protocol):
    def price(self, inst: Instrument, market: dict) -> float: ...


class GreeksProvider(Protocol):
    def greeks(self, inst: Instrument, market: dict) -> Greeks: ...


class YieldProvider(Protocol):
    def ytm(self, inst: Instrument, price: float) -> float: ...
    def duration(self, inst: Instrument, price: float) -> float: ...


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class BlackScholesPricer:
    """European Black-Scholes. Deterministic, closed-form; the reference `PricingProvider`.

    `market` keys: spot, vol (annualized), rate (cont. comp.), t (years to expiry).
    """

    def _d1_d2(self, inst: Instrument, m: dict):
        s, k = float(m["spot"]), float(inst.strike)
        vol, r, t = float(m["vol"]), float(m.get("rate", 0.0)), float(m["t"])
        if t <= 0 or vol <= 0:
            return None
        d1 = (math.log(s / k) + (r + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
        return d1, d1 - vol * math.sqrt(t)

    def price(self, inst: Instrument, market: dict) -> float:
        if inst.type is not InstrumentType.OPTION:
            return float(market.get("mark", market.get("spot", 0.0)))
        dd = self._d1_d2(inst, market)
        s, k = float(market["spot"]), float(inst.strike)
        if dd is None:                                   # expired / degenerate → intrinsic
            iv = s - k if inst.right is OptionRight.CALL else k - s
            return max(0.0, iv)
        d1, d2 = dd
        r, t = float(market.get("rate", 0.0)), float(market["t"])
        disc = math.exp(-r * t)
        if inst.right is OptionRight.CALL:
            return s * _norm_cdf(d1) - k * disc * _norm_cdf(d2)
        return k * disc * _norm_cdf(-d2) - s * _norm_cdf(-d1)

    def greeks(self, inst: Instrument, market: dict) -> Greeks:
        if inst.type is not InstrumentType.OPTION:
            return Greeks(delta=1.0)                      # linear instrument
        dd = self._d1_d2(inst, market)
        if dd is None:
            return Greeks()
        d1, d2 = dd
        s, k = float(market["spot"]), float(inst.strike)
        vol, r, t = float(market["vol"]), float(market.get("rate", 0.0)), float(market["t"])
        disc = math.exp(-r * t)
        sqt = math.sqrt(t)
        gamma = _norm_pdf(d1) / (s * vol * sqt)
        vega = s * _norm_pdf(d1) * sqt
        if inst.right is OptionRight.CALL:
            delta = _norm_cdf(d1)
            theta = -(s * _norm_pdf(d1) * vol) / (2 * sqt) - r * k * disc * _norm_cdf(d2)
            rho = k * t * disc * _norm_cdf(d2)
        else:
            delta = _norm_cdf(d1) - 1.0
            theta = -(s * _norm_pdf(d1) * vol) / (2 * sqt) + r * k * disc * _norm_cdf(-d2)
            rho = -k * t * disc * _norm_cdf(-d2)
        return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


class DeterministicMockPricer:
    """Offline, no-math pricer for tests/benchmarks. Options price at intrinsic value,
    everything else at the supplied `mark`/`spot`. Fully deterministic."""

    def price(self, inst: Instrument, market: dict) -> float:
        if inst.type is InstrumentType.OPTION:
            s = float(market.get("spot", 0.0))
            iv = s - inst.strike if inst.right is OptionRight.CALL else inst.strike - s
            return max(0.0, iv)
        return float(market.get("mark", market.get("spot", 0.0)))

    def greeks(self, inst: Instrument, market: dict) -> Greeks:
        if inst.type is InstrumentType.OPTION:
            s = float(market.get("spot", 0.0))
            itm = (s > inst.strike) if inst.right is OptionRight.CALL else (s < inst.strike)
            return Greeks(delta=1.0 if (itm and inst.right is OptionRight.CALL)
                          else (-1.0 if itm else 0.0))
        return Greeks(delta=1.0)


class MockYieldProvider:
    """Trivial deterministic yield/duration provider (flat approximations)."""

    def ytm(self, inst: Instrument, price: float) -> float:
        return float(inst.metadata.get("coupon", 0.0)) * (100.0 / max(price, 1e-9))

    def duration(self, inst: Instrument, price: float) -> float:
        # placeholder: flat modified duration proxy, real math is an injected provider's job
        return float(inst.metadata.get("face", 100.0)) / 100.0


# Extension point: a MonteCarloPricer would implement PricingProvider the same way,
# reading a "paths"/"seed" from `market`. Not implemented in M17 (see docs, limitations).
