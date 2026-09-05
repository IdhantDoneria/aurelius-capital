"""Rebalance scheduling and injectable clock (AIDP M23).

Deterministic: no wall-clock reads in replay/simulation mode. The Clock is
injected so tests and replay pass a fixed datetime; only PAPER_LIVE_FEED
mode uses the real clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


class Clock:
    """Real-time clock. Inject a FixedClock in tests / replay."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def today(self) -> date:
        return datetime.now(timezone.utc).date()


@dataclass(frozen=True)
class FixedClock:
    """Deterministic clock for tests and replay. Returns a constant datetime."""
    fixed: datetime

    def now(self) -> datetime:
        return self.fixed

    def today(self) -> date:
        return self.fixed.date()


VALID_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "quarterly", "event_driven"})


class RebalanceScheduler:
    """Determines whether a strategy is due for evaluation given a snapshot date.

    Rules:
      daily        — any snapshot with as_of > last_eval_date
      weekly       — at least 7 calendar days since last evaluation
      monthly      — calendar month has advanced
      quarterly    — calendar quarter has advanced
      event_driven — never automatically; caller must trigger externally

    First evaluation (last_eval_date is None) is always due.
    """

    def is_due(self, spec, runtime_state, snapshot_date: date) -> bool:
        freq = getattr(spec, "rebalance_frequency", "daily")
        last: date | None = getattr(runtime_state, "last_eval_date", None)

        if last is None:
            return True

        if freq == "daily":
            return snapshot_date > last
        if freq == "weekly":
            return (snapshot_date - last).days >= 7
        if freq == "monthly":
            return (snapshot_date.year, snapshot_date.month) > (last.year, last.month)
        if freq == "quarterly":
            return (snapshot_date.year, _quarter(snapshot_date)) > (last.year, _quarter(last))
        if freq == "event_driven":
            return False
        # unknown frequency: treat as daily
        return snapshot_date > last

    def next_due(self, spec, runtime_state) -> date | None:
        """Best-effort next evaluation date given last eval. None if unknown."""
        from datetime import timedelta
        freq = getattr(spec, "rebalance_frequency", "daily")
        last: date | None = getattr(runtime_state, "last_eval_date", None)
        if last is None:
            return None
        if freq == "daily":
            return last + timedelta(days=1)
        if freq == "weekly":
            return last + timedelta(days=7)
        if freq == "monthly":
            # first day of next month
            m = last.month + 1
            y = last.year + (1 if m > 12 else 0)
            m = m if m <= 12 else 1
            return date(y, m, 1)
        if freq == "quarterly":
            # first day of next quarter
            q = _quarter(last)
            next_q_month = (q * 3 + 1) % 12 or 12
            next_q_year = last.year + (1 if q == 4 else 0)
            return date(next_q_year, next_q_month, 1)
        return None


def _quarter(d: date) -> int:
    return (d.month - 1) // 3 + 1
