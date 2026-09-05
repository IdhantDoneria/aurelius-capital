"""Business-day calendar engine (AIDP M19).

Reusable, injectable calendars — the M18 deferred item "business-day calendars & holiday roll".
Weekend mask + injected holiday sets, the standard roll conventions, and business-day offsets,
all delegating to `numpy.busday_*` (the same mechanism M15 settlement already uses) so dates are
a deterministic pure function of inputs. Sample US/UK/India holiday sets are provided; exhaustive
vendor holiday history is an injected extension (see docs). Calendars are meant to be *injected*
into schedule building — no valuation module hard-codes an exchange's holidays.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from enum import StrEnum

import numpy as np


class RollConvention(StrEnum):
    NONE = "none"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    MODIFIED_PRECEDING = "modified_preceding"


_ROLL = {
    RollConvention.NONE: "raise",
    RollConvention.FOLLOWING: "forward",
    RollConvention.MODIFIED_FOLLOWING: "modifiedfollowing",
    RollConvention.PRECEDING: "backward",
    RollConvention.MODIFIED_PRECEDING: "modifiedpreceding",
}


class BusinessCalendar(ABC):
    """Weekend + holiday aware calendar. Concrete subclasses expose a numpy weekmask + holiday
    array; all date arithmetic routes through numpy busday functions for determinism."""

    name: str = "calendar"

    @property
    @abstractmethod
    def weekmask(self) -> str: ...  # "1111100" == Mon-Fri business days

    @property
    @abstractmethod
    def holidays(self) -> np.ndarray: ...  # datetime64[D] array

    def is_business_day(self, d: date) -> bool:
        return bool(
            np.is_busday(np.datetime64(d, "D"), weekmask=self.weekmask, holidays=self.holidays)
        )

    def is_holiday(self, d: date) -> bool:
        # a weekday that is not a business day == a holiday
        wd = np.is_busday(np.datetime64(d, "D"), weekmask=self.weekmask)
        return bool(wd) and not self.is_business_day(d)

    def adjust(self, d: date, roll: RollConvention = RollConvention.MODIFIED_FOLLOWING) -> date:
        roll = RollConvention(roll)
        if roll is RollConvention.NONE and not self.is_business_day(d):
            raise ValueError(f"{d} is not a business day on {self.name} (roll=none)")
        out = np.busday_offset(
            np.datetime64(d, "D"),
            0,
            roll=_ROLL[roll],
            weekmask=self.weekmask,
            holidays=self.holidays,
        )
        return out.astype("O")

    def add_business_days(self, d: date, n: int) -> date:
        roll = "forward" if n >= 0 else "backward"
        out = np.busday_offset(
            np.datetime64(d, "D"), n, roll=roll, weekmask=self.weekmask, holidays=self.holidays
        )
        return out.astype("O")

    def business_days_between(self, start: date, end: date) -> int:
        return int(
            np.busday_count(
                np.datetime64(start, "D"),
                np.datetime64(end, "D"),
                weekmask=self.weekmask,
                holidays=self.holidays,
            )
        )


class WeekendCalendar(BusinessCalendar):
    """Weekends only — no holidays. The generic default when no holiday set is injected."""

    def __init__(self, *, weekmask: str = "1111100", name: str = "weekend") -> None:
        self._weekmask = weekmask
        self._holidays = np.array([], dtype="datetime64[D]")
        self.name = name

    @property
    def weekmask(self) -> str:
        return self._weekmask

    @property
    def holidays(self) -> np.ndarray:
        return self._holidays


class HolidayCalendar(BusinessCalendar):
    """Weekend mask + an injected set of holiday dates."""

    def __init__(self, holidays, *, weekmask: str = "1111100", name: str = "custom") -> None:
        self._weekmask = weekmask
        self._holidays = np.array(sorted({_as_iso(h) for h in holidays}), dtype="datetime64[D]")
        self.name = name

    @property
    def weekmask(self) -> str:
        return self._weekmask

    @property
    def holidays(self) -> np.ndarray:
        return self._holidays


class JointCalendar(BusinessCalendar):
    """Union of several calendars' holidays (a date is a business day only if it is in *all*)."""

    def __init__(self, calendars, *, name: str = "joint") -> None:
        cals = list(calendars)
        if not cals:
            raise ValueError("JointCalendar needs at least one calendar")
        self._weekmask = cals[0].weekmask
        hol = set()
        for c in cals:
            hol.update(np.datetime_as_string(c.holidays))
        self._holidays = np.array(sorted(hol), dtype="datetime64[D]")
        self.name = name

    @property
    def weekmask(self) -> str:
        return self._weekmask

    @property
    def holidays(self) -> np.ndarray:
        return self._holidays


def _as_iso(h) -> str:
    return h.isoformat() if isinstance(h, date) else str(h)


# ── sample holiday sets (injected, not authoritative — see docs limitations) ──
# Representative fixed + observed holidays 2024-2026 for the three requested centers.

_US = [
    "2024-01-01",
    "2024-01-15",
    "2024-02-19",
    "2024-05-27",
    "2024-06-19",
    "2024-07-04",
    "2024-09-02",
    "2024-11-28",
    "2024-12-25",
    "2025-01-01",
    "2025-01-20",
    "2025-02-17",
    "2025-05-26",
    "2025-06-19",
    "2025-07-04",
    "2025-09-01",
    "2025-11-27",
    "2025-12-25",
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
]
_UK = [
    "2024-01-01",
    "2024-03-29",
    "2024-04-01",
    "2024-05-06",
    "2024-05-27",
    "2024-08-26",
    "2024-12-25",
    "2024-12-26",
    "2025-01-01",
    "2025-04-18",
    "2025-04-21",
    "2025-05-05",
    "2025-05-26",
    "2025-08-25",
    "2025-12-25",
    "2025-12-26",
    "2026-01-01",
    "2026-04-03",
    "2026-04-06",
    "2026-05-04",
    "2026-05-25",
    "2026-08-31",
    "2026-12-25",
    "2026-12-28",
]
_IN = [
    "2024-01-26",
    "2024-03-25",
    "2024-08-15",
    "2024-10-02",
    "2024-11-01",
    "2024-12-25",
    "2025-01-26",
    "2025-03-14",
    "2025-08-15",
    "2025-10-02",
    "2025-10-21",
    "2025-12-25",
    "2026-01-26",
    "2026-03-04",
    "2026-08-15",
    "2026-10-02",
    "2026-11-08",
    "2026-12-25",
]


def us_calendar() -> HolidayCalendar:
    return HolidayCalendar(_US, name="US")


def uk_calendar() -> HolidayCalendar:
    return HolidayCalendar(_UK, name="UK")


def india_calendar() -> HolidayCalendar:
    return HolidayCalendar(_IN, name="IN")


_NAMED = {
    "US": us_calendar,
    "UK": uk_calendar,
    "IN": india_calendar,
    "INDIA": india_calendar,
    "WEEKEND": WeekendCalendar,
}


def calendar(name: str) -> BusinessCalendar:
    """Look up a built-in calendar by name (US/UK/IN/WEEKEND)."""
    key = name.upper()
    if key not in _NAMED:
        raise KeyError(f"unknown calendar {name!r}; known: {sorted(_NAMED)}")
    return _NAMED[key]()
