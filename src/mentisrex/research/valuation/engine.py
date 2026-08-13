"""Valuation engine (AIDP M18).

The canonical entry point. `ValuationEngine.value(instrument, snapshot, config)` reproduces a
price + Greeks purely from Instrument + MarketDataSnapshot + ValuationDate + Configuration,
and stamps every result with model name/version and input/market fingerprints (governance).
`PortfolioValuationEngine` values a heterogeneous book and aggregates gross/net/base value,
unrealized P&L, Greeks and the sensitivity inputs M13 consumes.

Dispatch is by M17 `InstrumentType`. Nothing here fetches data — the snapshot is injected and
PIT-validated before use.
"""

from __future__ import annotations

import hashlib
from datetime import date

from mentisrex.research.instruments.models import (
    Instrument,
    InstrumentType,
    OptionRight,
)
from mentisrex.research.valuation import american, bonds, futures, pricing
from mentisrex.research.valuation import swaps as _swaps
from mentisrex.research.valuation import cross_currency as _xccy
from mentisrex.research.valuation.daycount import DayCount, year_fraction
from mentisrex.research.valuation.models import (
    Greeks,
    MarketDataSnapshot,
    PortfolioValuation,
    ValuationConfiguration,
    ValuationResult,
)
from mentisrex.research.valuation.snapshot import validate_pit

MODEL_VERSION = "1.0.0"


class ValuationError(ValueError):
    pass


class ValuationEngine:
    def __init__(self, *, validate_pit_on_value: bool = True) -> None:
        self.validate_pit_on_value = validate_pit_on_value

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _tte(self, inst: Instrument, as_of: date) -> float:
        if inst.expiry is None:
            return 0.0
        if inst.expiry <= as_of:
            return 0.0
        return year_fraction(as_of, inst.expiry, DayCount.ACT_365)

    def _rate(self, snap: MarketDataSnapshot, currency: str, t: float, assumptions: dict) -> float:
        curve = snap.rates.get(currency)
        if curve is None:
            assumptions["rate_source"] = "none→0"
            return 0.0
        assumptions["rate_source"] = getattr(curve, "curve_id", currency)
        return curve.zero_rate(max(t, 1e-9))

    def _input_fp(self, inst: Instrument, config: ValuationConfiguration, extra: dict) -> str:
        parts = [inst.instrument_id, inst.type.value, config.fingerprint()]
        parts += [f"{k}={extra[k]}" for k in sorted(extra)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()

    # ── single-instrument valuation ─────────────────────────────────────────────
    def value(self, inst: Instrument, snap: MarketDataSnapshot,
              config: ValuationConfiguration | None = None, *, quantity: float = 1.0,
              cost_basis: float | None = None) -> ValuationResult:
        config = config or ValuationConfiguration()
        if self.validate_pit_on_value:
            probs = validate_pit(snap, max_staleness_days=config.max_staleness_days)
            if probs:
                raise ValuationError(f"PIT validation failed: {probs[0]}")

        t = self._tte(inst, snap.as_of)
        assumptions: dict = {"t": round(t, 8)}
        greeks = None

        if inst.type is InstrumentType.EQUITY:
            price = snap.spot(inst.instrument_id)
            model = "equity.spot"

        elif inst.type is InstrumentType.FUTURE:
            under = inst.underlying or inst.metadata.get("underlying") or inst.instrument_id
            spot = snap.spot(under)
            r = self._rate(snap, inst.currency, t, assumptions)
            q = snap.dividend_yield(under)
            price = futures.fair_value(spot, r, q, t)
            assumptions.update(spot=spot, rate=r, div_yield=q, basis=price - spot)
            model = "futures.cost_of_carry"

        elif inst.type is InstrumentType.OPTION:
            price, greeks, model = self._value_option(inst, snap, config, t, assumptions)

        elif inst.type is InstrumentType.BOND:
            price, model = self._value_bond(inst, snap, t, assumptions)

        elif inst.type is InstrumentType.FORWARD:
            price, model = self._value_forward(inst, snap, t, assumptions)

        elif inst.type is InstrumentType.SWAP:
            # swaps need a full schedule spec — use value_swap(); generic path marks flat.
            price = float(inst.metadata.get("npv", 0.0))
            assumptions["note"] = "swap: use value_swap() with curves for NPV"
            model = "swap.stub"

        else:
            raise ValuationError(f"unsupported instrument type {inst.type}")

        cs = inst.contract_size
        market_value = price * quantity * cs
        base_value = self._to_base(market_value, inst.currency, snap, config)
        pnl = 0.0 if cost_basis is None else (price - cost_basis) * quantity * cs

        return ValuationResult(
            instrument_id=inst.instrument_id, valuation_date=snap.as_of, price=price,
            market_value=market_value, currency=inst.currency, base_value=base_value,
            model_name=model, model_version=MODEL_VERSION,
            input_fingerprint=self._input_fp(inst, config, assumptions),
            market_data_fingerprint=snap.fingerprint(), quantity=quantity, pnl=pnl,
            greeks=greeks, assumptions=assumptions)

    def _value_option(self, inst, snap, config, t, assumptions):
        under = inst.underlying
        if under is None:
            raise ValuationError(f"option {inst.instrument_id} has no underlying")
        spot = snap.spot(under)
        k = inst.strike
        r = self._rate(snap, inst.currency, t, assumptions)
        q = snap.dividend_yield(under)
        surf = snap.vol_surfaces.get(under)
        if surf is None:
            raise ValuationError(f"no vol surface for underlying {under!r}")
        vol = surf.vol(k, max(t, 1e-9))
        is_call = inst.right is OptionRight.CALL
        assumptions.update(spot=spot, strike=k, rate=r, div_yield=q, vol=vol)

        if config.option_model == "binomial":
            price = american.crr_price(is_call, spot, k, r, q, vol, t, steps=config.american_steps)
            g = american.crr_greeks(is_call, spot, k, r, q, vol, t, steps=config.american_steps)
            model = "option.binomial_crr"
        elif config.option_model == "black_76":
            f = futures.fair_value(spot, r, q, t)
            price = pricing.black76_price(is_call, f, k, r, vol, t)
            g = pricing.black76_greeks(is_call, f, k, r, vol, t)
            model = "option.black_76"
        else:
            price = pricing.black_scholes_price(is_call, spot, k, r, q, vol, t)
            g = pricing.black_scholes_greeks(is_call, spot, k, r, q, vol, t)
            model = "option.black_scholes"
        return price, Greeks(**{k2: g.get(k2, 0.0) for k2 in
                               ("delta", "gamma", "theta", "vega", "rho", "vanna", "volga")}), model

    def _value_bond(self, inst, snap, t, assumptions):
        md = inst.metadata
        spec = bonds.BondSpec(
            face=float(md.get("face", 100.0)), coupon=float(md.get("coupon", 0.0)),
            frequency=int(md.get("frequency", 2)), maturity=inst.expiry,
            issue=md.get("issue"))
        curve = snap.rates.get(inst.currency)
        if curve is not None:
            dirty = bonds.price_from_curve(spec, curve, snap.as_of)
            assumptions["bond_method"] = "curve_dcf"
        elif "ytm" in md:
            dirty = bonds.dirty_price_from_yield(spec, float(md["ytm"]), snap.as_of)
            assumptions["bond_method"] = "ytm"
        else:
            raise ValuationError(f"bond {inst.instrument_id}: need a {inst.currency} curve or ytm")
        # per-unit price is per 100 face; contract_size = face/100 folds face back in
        assumptions["accrued"] = bonds.accrued_interest(spec, snap.as_of)
        return dirty, "bond.dcf"

    def _value_forward(self, inst, snap, t, assumptions):
        under = inst.underlying or inst.metadata.get("underlying") or inst.instrument_id
        if under in snap.spots:
            spot = snap.spot(under)
            r = self._rate(snap, inst.currency, t, assumptions)
            q = snap.dividend_yield(under)
            price = futures.fair_value(spot, r, q, t)
            assumptions.update(spot=spot, rate=r, div_yield=q)
            return price, "forward.cost_of_carry"
        if inst.instrument_id in snap.forwards:
            return snap.forward(inst.instrument_id), "forward.quoted"
        raise ValuationError(f"forward {inst.instrument_id}: no spot for {under} or quoted forward")

    def _to_base(self, amount: float, currency: str, snap: MarketDataSnapshot,
                 config: ValuationConfiguration) -> float:
        if currency == config.base_currency:
            return amount
        return amount * snap.fx_rate(currency, config.base_currency)

    # ── swaps (need explicit schedule specs) ─────────────────────────────────────
    def value_swap(self, inst_id: str, spec: _swaps.SwapSpec, disc_curve, proj_curve=None, *,
                   snap: MarketDataSnapshot, config: ValuationConfiguration | None = None,
                   quantity: float = 1.0) -> ValuationResult:
        config = config or ValuationConfiguration()
        npv = _swaps.npv(spec, disc_curve, proj_curve)
        base = self._to_base(npv * quantity, spec.currency, snap, config)
        assumptions = {"par_rate": _swaps.par_rate(spec, disc_curve, proj_curve),
                       "dv01": _swaps.dv01(spec, disc_curve, proj_curve)}
        return ValuationResult(
            instrument_id=inst_id, valuation_date=snap.as_of, price=npv,
            market_value=npv * quantity, currency=spec.currency, base_value=base,
            model_name="swap.discount_curve", model_version=MODEL_VERSION,
            input_fingerprint=hashlib.blake2b(
                f"{inst_id}|{spec.fixed_rate}|{disc_curve.fingerprint()}".encode(),
                digest_size=8).hexdigest(),
            market_data_fingerprint=snap.fingerprint(), quantity=quantity, assumptions=assumptions)

    def value_cross_currency(self, inst_id: str, recv_leg, pay_leg, recv_curve, pay_curve, *,
                             snap: MarketDataSnapshot,
                             config: ValuationConfiguration | None = None) -> ValuationResult:
        config = config or ValuationConfiguration()
        res = _xccy.value(recv_leg, pay_leg, recv_curve, pay_curve, snap.fx_provider,
                          config.base_currency, as_of=snap.as_of)
        return ValuationResult(
            instrument_id=inst_id, valuation_date=snap.as_of, price=res["base_npv"],
            market_value=res["base_npv"], currency=config.base_currency,
            base_value=res["base_npv"], model_name="xccy_swap.dual_curve",
            model_version=MODEL_VERSION,
            input_fingerprint=hashlib.blake2b(
                f"{inst_id}|{recv_curve.fingerprint()}|{pay_curve.fingerprint()}".encode(),
                digest_size=8).hexdigest(),
            market_data_fingerprint=snap.fingerprint(),
            assumptions={"fx_exposure": res["fx_exposure"], "recv_base": res["recv_base"],
                         "pay_base": res["pay_base"]})


class PortfolioValuationEngine:
    """Values a heterogeneous portfolio and aggregates for reporting + M13 risk."""

    def __init__(self, engine: ValuationEngine | None = None) -> None:
        self.engine = engine or ValuationEngine()

    def value(self, positions: list, snap: MarketDataSnapshot,
              config: ValuationConfiguration | None = None) -> PortfolioValuation:
        """`positions`: list of (Instrument, quantity, cost_basis|None)."""
        config = config or ValuationConfiguration()
        results, greeks = [], Greeks()
        gross = net = base = upnl = 0.0
        for inst, qty, cost in positions:
            res = self.engine.value(inst, snap, config, quantity=qty, cost_basis=cost)
            results.append(res)
            gross += abs(res.base_value)
            net += res.base_value
            base += res.base_value
            upnl += res.pnl
            if res.greeks is not None:
                greeks = greeks + res.greeks.scale(qty * inst.contract_size)
        risk_inputs = {"portfolio_value": base, "gross_value": gross, "net_value": net,
                       "delta": greeks.delta, "gamma": greeks.gamma, "vega": greeks.vega,
                       "rho": greeks.rho, "theta": greeks.theta}
        return PortfolioValuation(
            valuation_date=snap.as_of, base_currency=config.base_currency,
            gross_market_value=gross, net_market_value=net, base_value=base,
            unrealized_pnl=upnl, results=results, greeks=greeks, risk_inputs=risk_inputs,
            market_data_fingerprint=snap.fingerprint())
