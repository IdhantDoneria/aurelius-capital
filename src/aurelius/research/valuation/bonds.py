"""Fixed-income analytics (AIDP M18).

Clean/dirty price, accrued interest, coupon cash flows, YTM (Newton with bisection
fallback), Macaulay & modified duration, convexity, DV01 and discount-curve DCF valuation.
Deterministic. Prices are per 100 face unless noted. Supports zero-coupon and fixed-coupon
bonds at arbitrary frequency; day-count is injected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aurelius.research.valuation.daycount import DayCount, year_fraction


@dataclass(frozen=True)
class BondSpec:
    """A fixed-coupon (or zero-coupon) bond, quoted per 100 face."""
    face: float = 100.0
    coupon: float = 0.0                    # annual coupon rate (0.04 = 4%)
    frequency: int = 2                     # coupons/year (0 => zero-coupon)
    issue: date | None = None
    maturity: date | None = None
    day_count: DayCount = DayCount.THIRTY_360


def coupon_dates(spec: BondSpec) -> list:
    if spec.maturity is None or spec.frequency <= 0:
        return [spec.maturity] if spec.maturity else []
    step = 12 // spec.frequency
    # walk backwards from maturity so the final date lands exactly on maturity
    dates, d = [], spec.maturity
    start = spec.issue or date(spec.maturity.year - 30, spec.maturity.month, 1)
    while d > start:
        dates.append(d)
        month = d.month - 1 - step
        year = d.year + month // 12
        d = date(year, month % 12 + 1, min(d.day, 28))
    return sorted(dates)


def cash_flows(spec: BondSpec) -> list:
    """(date, amount per 100 face) — coupons plus principal at maturity."""
    dts = coupon_dates(spec)
    if not dts:
        return []
    cpn = spec.coupon / spec.frequency * 100.0 if spec.frequency > 0 else 0.0
    flows = [(d, cpn) for d in dts]
    d_last, a_last = flows[-1]
    flows[-1] = (d_last, a_last + 100.0)                    # redeem principal
    return flows


def accrued_interest(spec: BondSpec, settle: date) -> float:
    if spec.frequency <= 0 or spec.coupon == 0:
        return 0.0
    dts = coupon_dates(spec)
    prev = spec.issue or dts[0]
    nxt = dts[-1]
    for d in dts:
        if d <= settle:
            prev = d
        else:
            nxt = d
            break
    if settle <= prev:
        return 0.0
    frac = year_fraction(prev, settle, spec.day_count) / year_fraction(prev, nxt, spec.day_count)
    cpn = spec.coupon / spec.frequency * 100.0
    return cpn * frac


def _period_exponents(spec: BondSpec, settle: date) -> list:
    """Discount exponents (in coupon periods) for each future cash flow — actual/actual ICMA.

    The k-th future coupon discounts by (w + k-1) periods, where w is the fraction of the
    current period still remaining. On a coupon date w == 1, so exponents are 1,2,3,… and a
    bond yielding its coupon prices exactly at par (the identity the tests assert)."""
    dts = coupon_dates(spec)
    future = [d for d in dts if d > settle]
    if not future:
        return []
    nxt = future[0]
    prev_candidates = [d for d in dts if d <= settle]
    if prev_candidates:
        prev = prev_candidates[-1]
    else:
        # settle before first coupon: step back one period from the next coupon
        step = 12 // (spec.frequency or 1)
        month = nxt.month - 1 - step
        prev = date(nxt.year + month // 12, month % 12 + 1, min(nxt.day, 28))
    period = year_fraction(prev, nxt, spec.day_count) or 1.0
    w = year_fraction(settle, nxt, spec.day_count) / period
    return [w + i for i in range(len(future))]


def dirty_price_from_yield(spec: BondSpec, ytm: float, settle: date) -> float:
    """PV of remaining cash flows discounted at `ytm` (per 100 face) — the dirty price."""
    flows = [(d, a) for d, a in cash_flows(spec) if d > settle]
    m = spec.frequency if spec.frequency > 0 else 1
    exps = _period_exponents(spec, settle) if spec.frequency > 0 else \
        [year_fraction(settle, d, DayCount.ACT_365) for d, _ in flows]
    pv = 0.0
    for (d, a), e in zip(flows, exps):
        pv += a / (1.0 + ytm / m) ** e
    return pv


def clean_price_from_yield(spec: BondSpec, ytm: float, settle: date) -> float:
    return dirty_price_from_yield(spec, ytm, settle) - accrued_interest(spec, settle)


def yield_to_maturity(spec: BondSpec, clean_price: float, settle: date, *,
                      tol: float = 1e-10, max_iter: int = 100) -> float:
    """Solve for YTM from a clean price. Bisection — robust and deterministic."""
    target = clean_price + accrued_interest(spec, settle)
    lo, hi = -0.5, 2.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        pv = dirty_price_from_yield(spec, mid, settle)
        if abs(pv - target) < tol:
            return mid
        if pv > target:                                    # price too high → yield too low
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def macaulay_duration(spec: BondSpec, ytm: float, settle: date) -> float:
    flows = [(d, a) for d, a in cash_flows(spec) if d > settle]
    m = spec.frequency if spec.frequency > 0 else 1
    exps = _period_exponents(spec, settle) if spec.frequency > 0 else \
        [m * year_fraction(settle, d, DayCount.ACT_365) for d, _ in flows]
    pv_total = twt = 0.0
    for (d, a), e in zip(flows, exps):
        t = e / m                                          # time in years (periods / freq)
        pv = a / (1.0 + ytm / m) ** e
        pv_total += pv
        twt += t * pv
    return twt / pv_total if pv_total else 0.0


def modified_duration(spec: BondSpec, ytm: float, settle: date) -> float:
    m = spec.frequency if spec.frequency > 0 else 1
    return macaulay_duration(spec, ytm, settle) / (1.0 + ytm / m)


def convexity(spec: BondSpec, ytm: float, settle: date) -> float:
    flows = [(d, a) for d, a in cash_flows(spec) if d > settle]
    m = spec.frequency if spec.frequency > 0 else 1
    exps = _period_exponents(spec, settle) if spec.frequency > 0 else \
        [m * year_fraction(settle, d, DayCount.ACT_365) for d, _ in flows]
    pv_total = cx = 0.0
    for (d, a), e in zip(flows, exps):
        t = e / m
        pv = a / (1.0 + ytm / m) ** e
        pv_total += pv
        cx += t * (t + 1.0 / m) * pv
    return cx / (pv_total * (1.0 + ytm / m) ** 2) if pv_total else 0.0


def dv01(spec: BondSpec, ytm: float, settle: date) -> float:
    """Dollar value of 1bp — price change per 100 face for a 1bp yield move."""
    up = dirty_price_from_yield(spec, ytm + 1e-4, settle)
    dn = dirty_price_from_yield(spec, ytm - 1e-4, settle)
    return (dn - up) / 2.0


def price_from_curve(spec: BondSpec, curve, settle: date) -> float:
    """Dirty price by discounting cash flows on a ZeroCurve/DiscountCurve (DCF valuation)."""
    pv = 0.0
    for d, a in cash_flows(spec):
        if d > settle:
            pv += a * curve.discount(year_fraction(settle, d, DayCount.ACT_365))
    return pv
