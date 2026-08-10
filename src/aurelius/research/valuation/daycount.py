"""Day-count conventions (AIDP M18).

Year-fraction between two dates under the common institutional conventions. Shared by
curves, bonds and swaps so no module hard-codes ACT/365. Deterministic, calendar-free
(business-day calendars are a documented limitation — see docs).
"""

from __future__ import annotations

from datetime import date
from enum import Enum


class DayCount(str, Enum):
    ACT_365 = "ACT/365"
    ACT_360 = "ACT/360"
    THIRTY_360 = "30/360"
    ACT_ACT = "ACT/ACT"


def year_fraction(start: date, end: date, convention: DayCount = DayCount.ACT_365) -> float:
    if end < start:
        raise ValueError(f"end {end} before start {start}")
    days = (end - start).days
    if convention is DayCount.ACT_365:
        return days / 365.0
    if convention is DayCount.ACT_360:
        return days / 360.0
    if convention is DayCount.ACT_ACT:
        return days / 365.25
    if convention is DayCount.THIRTY_360:
        d1 = min(start.day, 30)
        d2 = min(end.day, 30) if d1 == 30 else end.day
        return ((end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)) / 360.0
    raise ValueError(f"unknown day-count {convention}")


class Compounding(str, Enum):
    CONTINUOUS = "continuous"
    ANNUAL = "annual"
    SIMPLE = "simple"
    SEMIANNUAL = "semiannual"


def discount_factor(zero_rate: float, t: float, compounding: Compounding = Compounding.CONTINUOUS) -> float:
    """Discount factor for a zero rate over year-fraction `t`."""
    import math
    if t < 0:
        raise ValueError("t must be >= 0")
    if compounding is Compounding.CONTINUOUS:
        return math.exp(-zero_rate * t)
    if compounding is Compounding.SIMPLE:
        return 1.0 / (1.0 + zero_rate * t)
    if compounding is Compounding.ANNUAL:
        return (1.0 + zero_rate) ** (-t)
    if compounding is Compounding.SEMIANNUAL:
        return (1.0 + zero_rate / 2.0) ** (-2.0 * t)
    raise ValueError(f"unknown compounding {compounding}")


def zero_from_df(df: float, t: float, compounding: Compounding = Compounding.CONTINUOUS) -> float:
    """Invert `discount_factor`: recover the zero rate from a discount factor."""
    import math
    if df <= 0:
        raise ValueError("discount factor must be > 0")
    if t <= 0:
        return 0.0
    if compounding is Compounding.CONTINUOUS:
        return -math.log(df) / t
    if compounding is Compounding.SIMPLE:
        return (1.0 / df - 1.0) / t
    if compounding is Compounding.ANNUAL:
        return df ** (-1.0 / t) - 1.0
    if compounding is Compounding.SEMIANNUAL:
        return 2.0 * (df ** (-1.0 / (2.0 * t)) - 1.0)
    raise ValueError(f"unknown compounding {compounding}")
