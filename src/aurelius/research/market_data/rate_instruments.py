"""Canonical interest-rate instruments (AIDP M19).

The market quotes a curve is bootstrapped from: deposits, OIS, FRAs, rate futures, par swaps,
government bonds and basis swaps. Conventions (day-count, compounding, payment frequency,
settlement lag, calendar) are **injected per instrument**, never assumed universal — the M18
deferred item said as much. Instruments are immutable; each knows its maturity and, for
price-quoted futures, its implied rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from aurelius.research.valuation.daycount import Compounding, DayCount


class InstrumentKind(str, Enum):
    DEPOSIT = "deposit"
    OIS = "ois"
    FRA = "fra"
    FUTURE = "future"
    SWAP = "swap"
    GOV_BOND = "gov_bond"
    BASIS_SWAP = "basis_swap"


@dataclass(frozen=True)
class RateConvention:
    day_count: DayCount = DayCount.ACT_360
    compounding: Compounding = Compounding.SIMPLE
    frequency: int = 2                    # coupon payments per year (swaps/bonds)
    settlement_lag: int = 2               # business days
    calendar_name: str = "US"


@dataclass(frozen=True)
class RateInstrument:
    """A single calibration instrument. `quote` is a rate (decimal) except futures, where it is a
    price (100 - rate*100). `start`/`tenor` are in years; maturity == start + tenor."""
    kind: InstrumentKind
    tenor: float                          # years from start to maturity
    quote: float
    convention: RateConvention = field(default_factory=RateConvention)
    start: float = 0.0                    # years from valuation date (FRAs/futures)
    label: str = ""
    currency: str = "USD"

    def maturity_years(self) -> float:
        return self.start + self.tenor

    def implied_rate(self) -> float:
        """Rate the instrument locks. Futures price 100·(1-rate) -> rate; else the quote is a rate."""
        if self.kind is InstrumentKind.FUTURE:
            return (100.0 - self.quote) / 100.0
        return self.quote

    def name(self) -> str:
        return self.label or f"{self.kind.value}@{self.maturity_years():.4g}y"


# ── convenience constructors ──────────────────────────────────────────────────

def deposit(tenor: float, rate: float, *, convention=None, currency="USD", label="") -> RateInstrument:
    return RateInstrument(InstrumentKind.DEPOSIT, tenor, rate,
                          convention or RateConvention(), 0.0, label, currency)


def ois(tenor: float, rate: float, *, convention=None, currency="USD", label="") -> RateInstrument:
    return RateInstrument(InstrumentKind.OIS, tenor, rate,
                          convention or RateConvention(frequency=1), 0.0, label, currency)


def fra(start: float, end: float, rate: float, *, convention=None, currency="USD", label="") -> RateInstrument:
    return RateInstrument(InstrumentKind.FRA, end - start, rate,
                          convention or RateConvention(), start, label, currency)


def rate_future(start: float, price: float, *, length: float = 0.25, convention=None,
                currency="USD", label="") -> RateInstrument:
    return RateInstrument(InstrumentKind.FUTURE, length, price,
                          convention or RateConvention(), start, label, currency)


def swap(tenor: float, rate: float, *, frequency: int = 2, convention=None,
         currency="USD", label="") -> RateInstrument:
    conv = convention or RateConvention(frequency=frequency)
    return RateInstrument(InstrumentKind.SWAP, tenor, rate, conv, 0.0, label, currency)
