"""Yield curves (AIDP M18).

`ZeroCurve` (zero rates by tenor), `DiscountCurve` (discount factors by tenor) and
`ForwardCurve` (instantaneous/period forwards). All immutable, deterministic, with explicit
interpolation + extrapolation policy, day-count and compounding conventions injected. A
`ZeroCurve` is the primary object; `DiscountCurve`/`ForwardCurve` are derived views.

Invariants (checked by `validate`): DF(0)=1, DF(T)>0, tenors strictly increasing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from aurelius.research.valuation import interpolation as interp
from aurelius.research.valuation.daycount import (
    Compounding,
    DayCount,
    discount_factor,
    year_fraction,
    zero_from_df,
)


@dataclass(frozen=True)
class ZeroCurve:
    """Zero (spot) rates by tenor in years. Interpolates linearly in zero-rate space."""
    curve_id: str
    ref_date: date
    tenors: tuple                  # increasing year-fractions
    zeros: tuple                   # zero rates, same length
    compounding: Compounding = Compounding.CONTINUOUS
    day_count: DayCount = DayCount.ACT_365
    extrap: interp.Extrapolation = interp.Extrapolation.FLAT
    currency: str = "USD"

    def __post_init__(self):
        if len(self.tenors) != len(self.zeros) or not self.tenors:
            raise ValueError("tenors/zeros must be non-empty and equal length")
        if list(self.tenors) != sorted(self.tenors) or len(set(self.tenors)) != len(self.tenors):
            raise ValueError("tenors must be strictly increasing")

    def zero_rate(self, t: float) -> float:
        return interp.linear(list(self.tenors), list(self.zeros), t, extrap=self.extrap)

    def discount(self, t: float) -> float:
        if t <= 0:
            return 1.0
        return discount_factor(self.zero_rate(t), t, self.compounding)

    def discount_to(self, d: date) -> float:
        return self.discount(year_fraction(self.ref_date, d, self.day_count))

    def forward_rate(self, t1: float, t2: float) -> float:
        """Simple-compounded forward rate between t1 and t2 implied by discount factors."""
        if t2 <= t1:
            raise ValueError("t2 must be > t1")
        df1, df2 = self.discount(t1), self.discount(t2)
        return (df1 / df2 - 1.0) / (t2 - t1)

    def as_discount_curve(self) -> "DiscountCurve":
        dfs = tuple(self.discount(t) for t in self.tenors)
        return DiscountCurve(self.curve_id, self.ref_date, self.tenors, dfs,
                             self.compounding, self.day_count, self.extrap, self.currency)

    def validate(self) -> list:
        problems = []
        for t in self.tenors:
            if self.discount(t) <= 0:
                problems.append(f"{self.curve_id}: DF({t}) <= 0")
        return problems

    def fingerprint(self) -> str:
        parts = [self.curve_id, str(self.ref_date), self.compounding.value, self.day_count.value]
        parts += [f"{t:.8g}:{z:.10g}" for t, z in zip(self.tenors, self.zeros)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


@dataclass(frozen=True)
class DiscountCurve:
    """Discount factors by tenor. Interpolates log-linearly (piecewise-flat forwards)."""
    curve_id: str
    ref_date: date
    tenors: tuple
    dfs: tuple
    compounding: Compounding = Compounding.CONTINUOUS
    day_count: DayCount = DayCount.ACT_365
    extrap: interp.Extrapolation = interp.Extrapolation.FLAT
    currency: str = "USD"

    def __post_init__(self):
        if len(self.tenors) != len(self.dfs) or not self.tenors:
            raise ValueError("tenors/dfs must be non-empty and equal length")
        if any(df <= 0 for df in self.dfs):
            raise ValueError("all discount factors must be > 0")

    def discount(self, t: float) -> float:
        if t <= 0:
            return 1.0
        return interp.log_linear(list(self.tenors), list(self.dfs), t, extrap=self.extrap)

    def discount_to(self, d: date) -> float:
        return self.discount(year_fraction(self.ref_date, d, self.day_count))

    def zero_rate(self, t: float) -> float:
        if t <= 0:
            return 0.0
        return zero_from_df(self.discount(t), t, self.compounding)

    def forward_rate(self, t1: float, t2: float) -> float:
        if t2 <= t1:
            raise ValueError("t2 must be > t1")
        return (self.discount(t1) / self.discount(t2) - 1.0) / (t2 - t1)

    def validate(self) -> list:
        problems = []
        prev = 1.0
        for t, df in zip(self.tenors, self.dfs):
            if df <= 0:
                problems.append(f"{self.curve_id}: DF({t}) <= 0")
            if df > prev + 1e-9:
                problems.append(f"{self.curve_id}: non-monotone DF at {t} (implies negative fwd)")
            prev = df
        return problems

    def fingerprint(self) -> str:
        parts = [self.curve_id, str(self.ref_date)]
        parts += [f"{t:.8g}:{d:.12g}" for t, d in zip(self.tenors, self.dfs)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


@dataclass(frozen=True)
class ForwardCurve:
    """Forward prices/rates by tenor (e.g. equity forwards, FX forward points, index level)."""
    curve_id: str
    ref_date: date
    tenors: tuple
    forwards: tuple
    extrap: interp.Extrapolation = interp.Extrapolation.FLAT
    day_count: DayCount = DayCount.ACT_365

    def forward(self, t: float) -> float:
        return interp.linear(list(self.tenors), list(self.forwards), t, extrap=self.extrap)

    def forward_to(self, d: date) -> float:
        return self.forward(year_fraction(self.ref_date, d, self.day_count))

    def fingerprint(self) -> str:
        parts = [self.curve_id, str(self.ref_date)]
        parts += [f"{t:.8g}:{f:.10g}" for t, f in zip(self.tenors, self.forwards)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


def flat_curve(curve_id: str, ref_date: date, rate: float, *, currency: str = "USD",
               compounding: Compounding = Compounding.CONTINUOUS,
               day_count: DayCount = DayCount.ACT_365) -> ZeroCurve:
    """A flat zero curve — the deterministic default when only one rate is known."""
    return ZeroCurve(curve_id, ref_date, (0.25, 1.0, 5.0, 30.0),
                     (rate, rate, rate, rate), compounding, day_count, currency=currency)
