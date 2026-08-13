"""Concrete execution algorithms (AIDP M14).

Immediate, TWAP, VWAP, POV. Each produces a deterministic `ExecutionSchedule` from
the parent order + `MarketInfo` via the shared `scheduler` slicing math. VWAP is the
"interface" the milestone calls for: it slices against an injected volume profile
(default U-shape) — swap in a real forecast and the algo is unchanged. POV needs an
expected per-interval volume; absent it, it degrades to a single slice and says so.
"""

from __future__ import annotations

from mentisrex.research.execution.ems import scheduler
from mentisrex.research.execution.ems.algorithms import ExecutionAlgorithm, register
from mentisrex.research.execution.ems.orders import DEFAULT_VWAP_PROFILE


@register
class ImmediateExecution(ExecutionAlgorithm):
    """One child = the whole order, executed now. Market/limit/stop route here."""
    name = "immediate"

    def schedule(self, order, market):
        return scheduler.uniform_schedule(order.order_id, order.quantity, 1, algo=self.name)


@register
class TWAP(ExecutionAlgorithm):
    """Time-weighted: split evenly across `n_slices` equal time buckets."""
    name = "twap"

    def __init__(self, n_slices: int = 5) -> None:
        self.n_slices = max(1, int(n_slices))

    def schedule(self, order, market):
        return scheduler.uniform_schedule(order.order_id, order.quantity, self.n_slices, algo=self.name)


@register
class VWAP(ExecutionAlgorithm):
    """Volume-weighted: slice proportional to a volume profile. Uses the per-name
    profile in `market.volume_profile` if present, else the default U-shape."""
    name = "vwap"

    def __init__(self, profile=None) -> None:
        self.profile = list(profile) if profile else None

    def schedule(self, order, market):
        profile = self.profile or getattr(market, "volume_profile", None) or DEFAULT_VWAP_PROFILE
        return scheduler.profile_schedule(order.order_id, order.quantity, profile, algo=self.name)


@register
class POV(ExecutionAlgorithm):
    """Participation-of-volume: take `participation_rate` of each interval's expected
    volume until filled. Interval volume comes from `market.interval_volume[sid]`."""
    name = "pov"

    def __init__(self, participation_rate: float = 0.10, max_slices: int = 100) -> None:
        self.participation_rate = participation_rate
        self.max_slices = max_slices

    def schedule(self, order, market):
        vol = getattr(market, "interval_volume", {}).get(order.security_id, 0.0)
        return scheduler.pov_schedule(order.order_id, order.quantity, vol,
                                      self.participation_rate, max_slices=self.max_slices,
                                      algo=self.name)
