"""Rebalancing rules (AIDP M10).

Decide *when* to rebalance: calendar, weight-drift threshold, volatility-triggered,
or a hybrid. Pure decision functions over the current vs target weights and dates —
they never construct a portfolio, only gate construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

_FREQ_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 91}


@dataclass(frozen=True)
class RebalanceRule:
    mode: str = "calendar"                 # calendar | threshold | volatility | hybrid
    frequency: str = "monthly"
    drift_threshold: float = 0.05          # max |w - target| before a threshold rebalance
    vol_change_threshold: float = 0.25     # relative risk change trigger

    def should_rebalance(self, *, current=None, target=None, last_rebalance: date | None = None,
                         as_of: date | None = None, prev_risk: float | None = None,
                         current_risk: float | None = None) -> bool:
        cal = self._calendar_due(last_rebalance, as_of)
        thr = self._drift_exceeded(current, target)
        vol = self._vol_triggered(prev_risk, current_risk)
        if self.mode == "calendar":
            return cal
        if self.mode == "threshold":
            return thr
        if self.mode == "volatility":
            return vol
        if self.mode == "hybrid":
            return cal or thr               # calendar cadence OR a big drift
        return cal

    def _calendar_due(self, last, as_of) -> bool:
        if last is None or as_of is None:
            return True
        return (as_of - last).days >= _FREQ_DAYS.get(self.frequency, 30)

    def _drift_exceeded(self, current, target) -> bool:
        if current is None or target is None:
            return True
        c, t = np.asarray(current, dtype=float), np.asarray(target, dtype=float)
        n = min(c.size, t.size)
        return bool(np.max(np.abs(c[:n] - t[:n])) >= self.drift_threshold) if n else True

    def _vol_triggered(self, prev, cur) -> bool:
        if prev is None or cur is None or prev <= 0:
            return False
        return abs(cur - prev) / prev >= self.vol_change_threshold
