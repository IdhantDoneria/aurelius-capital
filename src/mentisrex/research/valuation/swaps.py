"""Interest-rate swap valuation (AIDP M18).

Discount-curve valuation of vanilla fixed-vs-float IRS: fixed leg PV, floating leg PV (from
projected forwards on a projection curve), NPV, par swap rate, DV01 and cash-flow projection.
Deterministic. Discounting and projection curves are injected (single-curve if the same
object is passed for both). Currency swaps compose two of these + FX (see `cross_currency`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mentisrex.research.valuation.daycount import DayCount, year_fraction


@dataclass(frozen=True)
class SwapSpec:
    notional: float
    fixed_rate: float
    pay_dates: tuple                       # payment dates, increasing
    start: date
    pay_fixed: bool = True                 # True: pay fixed / receive float
    day_count: DayCount = DayCount.ACT_360
    currency: str = "USD"


def _accruals(start: date, pay_dates, dc: DayCount) -> list:
    prev, out = start, []
    for d in pay_dates:
        out.append((prev, d, year_fraction(prev, d, dc)))
        prev = d
    return out


def fixed_leg_pv(spec: SwapSpec, disc_curve) -> float:
    pv = 0.0
    for _, d, tau in _accruals(spec.start, spec.pay_dates, spec.day_count):
        df = disc_curve.discount(year_fraction(disc_curve.ref_date, d, disc_curve.day_count))
        pv += spec.fixed_rate * tau * spec.notional * df
    return pv


def floating_leg_pv(spec: SwapSpec, disc_curve, proj_curve) -> float:
    pv = 0.0
    for s, d, tau in _accruals(spec.start, spec.pay_dates, spec.day_count):
        t1 = year_fraction(proj_curve.ref_date, s, proj_curve.day_count)
        t2 = year_fraction(proj_curve.ref_date, d, proj_curve.day_count)
        fwd = proj_curve.forward_rate(max(t1, 1e-9), t2) if t2 > t1 else 0.0
        df = disc_curve.discount(year_fraction(disc_curve.ref_date, d, disc_curve.day_count))
        pv += fwd * tau * spec.notional * df
    return pv


def npv(spec: SwapSpec, disc_curve, proj_curve=None) -> float:
    """Swap NPV from the payer's perspective (pay fixed → receive float)."""
    proj_curve = proj_curve or disc_curve
    fixed = fixed_leg_pv(spec, disc_curve)
    floating = floating_leg_pv(spec, disc_curve, proj_curve)
    val = floating - fixed                                  # receive float, pay fixed
    return val if spec.pay_fixed else -val


def annuity(spec: SwapSpec, disc_curve) -> float:
    a = 0.0
    for _, d, tau in _accruals(spec.start, spec.pay_dates, spec.day_count):
        a += tau * disc_curve.discount(
            year_fraction(disc_curve.ref_date, d, disc_curve.day_count))
    return a * spec.notional


def par_rate(spec: SwapSpec, disc_curve, proj_curve=None) -> float:
    """The fixed rate that sets NPV to zero."""
    proj_curve = proj_curve or disc_curve
    floating = floating_leg_pv(spec, disc_curve, proj_curve)
    ann = annuity(spec, disc_curve)
    return floating / ann if ann else 0.0


def dv01(spec: SwapSpec, disc_curve, proj_curve=None) -> float:
    """PV change per 1bp parallel shift — via the fixed annuity (standard swap DV01)."""
    return annuity(spec, disc_curve) * 1e-4


def cash_flow_projection(spec: SwapSpec, disc_curve, proj_curve=None) -> list:
    """Per-period (pay_date, fixed_amount, float_amount, df) projection."""
    proj_curve = proj_curve or disc_curve
    out = []
    for s, d, tau in _accruals(spec.start, spec.pay_dates, spec.day_count):
        t1 = year_fraction(proj_curve.ref_date, s, proj_curve.day_count)
        t2 = year_fraction(proj_curve.ref_date, d, proj_curve.day_count)
        fwd = proj_curve.forward_rate(max(t1, 1e-9), t2) if t2 > t1 else 0.0
        df = disc_curve.discount(year_fraction(disc_curve.ref_date, d, disc_curve.day_count))
        out.append((d, spec.fixed_rate * tau * spec.notional,
                    fwd * tau * spec.notional, df))
    return out
