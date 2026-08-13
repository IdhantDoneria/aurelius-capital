"""Cross-currency swap valuation (AIDP M18).

Values a fixed-fixed cross-currency swap: two legs in two currencies, each discounted on its
own curve, then translated to a base currency via the injected M16 FX provider. FX conversion
is delegated to M16 (`snapshot.fx_rate` / `fx_provider.rate`), never re-implemented.

Convention: you RECEIVE `recv_leg` and PAY `pay_leg`; principals exchange at start and
maturity (standard XCCY). Base value = PV(receive) − PV(pay), both in base currency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mentisrex.research.valuation import swaps as _swaps
from mentisrex.research.valuation.daycount import DayCount, year_fraction


@dataclass(frozen=True)
class CrossCurrencyLeg:
    notional: float
    rate: float
    currency: str
    pay_dates: tuple
    start: date
    day_count: DayCount = DayCount.ACT_360
    exchange_principal: bool = True


def _leg_pv(leg: CrossCurrencyLeg, disc_curve) -> float:
    """PV of a fixed leg in its own currency, including principal exchange if set."""
    spec = _swaps.SwapSpec(leg.notional, leg.rate, leg.pay_dates, leg.start,
                           day_count=leg.day_count, currency=leg.currency)
    pv = _swaps.fixed_leg_pv(spec, disc_curve)
    if leg.exchange_principal and leg.pay_dates:
        t_mat = year_fraction(disc_curve.ref_date, leg.pay_dates[-1], disc_curve.day_count)
        pv += leg.notional * disc_curve.discount(t_mat)     # principal redemption at maturity
        pv -= leg.notional * disc_curve.discount(0.0)       # principal paid at start (t≈0)
    return pv


def value(recv_leg: CrossCurrencyLeg, pay_leg: CrossCurrencyLeg, recv_curve, pay_curve,
          fx_provider, base_currency: str, *, as_of: date | None = None) -> dict:
    """Base-currency NPV of the XCCY swap plus per-currency PVs and FX exposure."""
    pv_recv = _leg_pv(recv_leg, recv_curve)                 # in recv currency
    pv_pay = _leg_pv(pay_leg, pay_curve)                    # in pay currency
    recv_base = pv_recv * fx_provider.rate(recv_leg.currency, base_currency, as_of=as_of)
    pay_base = pv_pay * fx_provider.rate(pay_leg.currency, base_currency, as_of=as_of)
    return {
        "base_npv": recv_base - pay_base,
        "recv_pv": pv_recv, "recv_currency": recv_leg.currency, "recv_base": recv_base,
        "pay_pv": pv_pay, "pay_currency": pay_leg.currency, "pay_base": pay_base,
        # FX exposure: base-value sensitivity is the notional PV in each foreign currency
        "fx_exposure": {recv_leg.currency: recv_base, pay_leg.currency: -pay_base},
    }
