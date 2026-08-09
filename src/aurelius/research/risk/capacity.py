"""Capacity analytics (AIDP M13).

Strategy dollar-capacity estimate: the AUM at which the least-liquid required
position first exceeds its ADV-participation budget. Complements the M11 capacity
report (which measures realized-trade participation) by asking the forward question
— how much money can this weight vector hold before liquidity binds.
"""

from __future__ import annotations

from aurelius.research.risk.models import CapacityReport


def capacity_report(weights: dict, adv: dict, *, aum: float,
                    participation_limit: float = 0.10) -> CapacityReport:
    """Capacity = min over names of (participation_limit · ADV / |weight|).
    Utilization = aum / capacity."""
    binding = float("inf")
    for sid, w in (weights or {}).items():
        if w == 0:
            continue
        v = adv.get(sid, 0.0)
        if v and v > 0:
            binding = min(binding, participation_limit * v / abs(w))
    capacity = 0.0 if binding == float("inf") else binding
    util = (aum / capacity) if capacity > 0 else float("inf")
    signal = ("ok" if util <= 0.5 else "warning" if util <= 1.0 else "critical")
    return CapacityReport(capacity_usd=capacity, aum_usd=aum,
                          utilization=float(min(util, 1e9)), capacity_signal=signal)
