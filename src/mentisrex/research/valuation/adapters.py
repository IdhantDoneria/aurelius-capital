"""M17 provider adapters (AIDP M18).

Production implementations of the M17 dependency-injection seams
(`PricingProvider` / `GreeksProvider` / `YieldProvider`): M18 replaces M17's deterministic
stubs so an M17 `InstrumentBook` can request real price / NPV / Greeks / yield / duration.

These consume the M17 `market` dict (spot, vol, rate, div_yield, t) so they drop straight in
where `BlackScholesPricer` / `MockYieldProvider` were used — no M17 code changes required.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.instruments.models import Greeks as M17Greeks
from mentisrex.research.instruments.models import Instrument, InstrumentType, OptionRight
from mentisrex.research.valuation import american, bonds, futures, pricing


class M18Pricer:
    """M17 `PricingProvider` + `GreeksProvider` backed by M18 closed forms / binomial tree.

    `market` keys: spot, vol, rate (default 0), div_yield (default 0), t, and for American
    exercise `american=True` (+ optional `steps`).
    """

    def price(self, inst: Instrument, market: dict) -> float:
        if inst.type is InstrumentType.OPTION:
            return self._option_price(inst, market)
        if inst.type is InstrumentType.FUTURE:
            return futures.fair_value(
                float(market["spot"]),
                float(market.get("rate", 0.0)),
                float(market.get("div_yield", 0.0)),
                float(market.get("t", 0.0)),
            )
        # equity / forward / bond: mark or spot passthrough (bonds use the yield adapter)
        return float(market.get("mark", market.get("spot", 0.0)))

    def _option_price(self, inst, market):
        s, k = float(market["spot"]), float(inst.strike)
        r, q = float(market.get("rate", 0.0)), float(market.get("div_yield", 0.0))
        vol, t = float(market["vol"]), float(market.get("t", 0.0))
        is_call = inst.right is OptionRight.CALL
        if market.get("american"):
            return american.crr_price(
                is_call, s, k, r, q, vol, t, steps=int(market.get("steps", 200))
            )
        return pricing.black_scholes_price(is_call, s, k, r, q, vol, t)

    def greeks(self, inst: Instrument, market: dict) -> M17Greeks:
        if inst.type is not InstrumentType.OPTION:
            return M17Greeks(delta=1.0)  # linear instrument
        s, k = float(market["spot"]), float(inst.strike)
        r, q = float(market.get("rate", 0.0)), float(market.get("div_yield", 0.0))
        vol, t = float(market["vol"]), float(market.get("t", 0.0))
        is_call = inst.right is OptionRight.CALL
        if market.get("american"):
            g = american.crr_greeks(
                is_call, s, k, r, q, vol, t, steps=int(market.get("steps", 200))
            )
        else:
            g = pricing.black_scholes_greeks(is_call, s, k, r, q, vol, t)
        return M17Greeks(
            delta=g["delta"], gamma=g["gamma"], theta=g["theta"], vega=g["vega"], rho=g["rho"]
        )


class M18YieldProvider:
    """M17 `YieldProvider` backed by M18 bond analytics (YTM + modified duration)."""

    def __init__(self, *, settle: date | None = None) -> None:
        self.settle = settle

    def _spec(self, inst: Instrument) -> bonds.BondSpec:
        md = inst.metadata
        return bonds.BondSpec(
            face=float(md.get("face", 100.0)),
            coupon=float(md.get("coupon", 0.0)),
            frequency=int(md.get("frequency", 2)),
            maturity=inst.expiry,
            issue=md.get("issue"),
        )

    def ytm(self, inst: Instrument, price: float) -> float:
        settle = self.settle or date.today()
        return bonds.yield_to_maturity(self._spec(inst), price, settle)

    def duration(self, inst: Instrument, price: float) -> float:
        settle = self.settle or date.today()
        spec = self._spec(inst)
        y = bonds.yield_to_maturity(spec, price, settle)
        return bonds.modified_duration(spec, y, settle)
