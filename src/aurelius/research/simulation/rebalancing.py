"""Rebalance scheduling for the simulation (AIDP M11).

Reuses the M10 RebalanceRule (calendar / threshold / volatility / hybrid) —
no duplicate policy logic — and adds calendar-date generation over a timeline. The
engine calls `due()` per date.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.portfolio.rebalancing import RebalanceRule

_FREQ = {"daily": 1, "weekly": 7, "monthly": 1, "quarterly": 3, "annual": 12}


def calendar_dates(timeline: list[date], frequency: str = "monthly") -> set[date]:
    """Pick rebalance dates from a timeline: first trading day of each period."""
    if frequency == "daily":
        return set(timeline)
    if frequency == "weekly":
        seen, out = set(), set()
        for d in timeline:
            key = d.isocalendar()[:2]
            if key not in seen:
                seen.add(key)
                out.add(d)
        return out
    step = _FREQ.get(frequency, 1)                 # months per period
    seen, out = set(), set()
    for d in timeline:
        key = (d.year, (d.month - 1) // step)
        if key not in seen:
            seen.add(key)
            out.add(d)
    return out


class RebalancePolicy:
    """Wraps a M10 RebalanceRule; `due` decides at a given date."""

    def __init__(self, rule: RebalanceRule | None = None, *, explicit_dates: set | None = None) -> None:
        self.rule = rule
        self.explicit = explicit_dates

    def due(self, *, as_of: date, last: date | None, current=None, target=None,
            prev_risk=None, current_risk=None) -> bool:
        if self.explicit is not None:
            return as_of in self.explicit
        if self.rule is None:
            return True
        return self.rule.should_rebalance(current=current, target=target, last_rebalance=last,
                                          as_of=as_of, prev_risk=prev_risk, current_risk=current_risk)
