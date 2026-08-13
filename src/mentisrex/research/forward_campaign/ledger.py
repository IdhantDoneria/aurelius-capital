"""Forward performance ledger (M25).

Reads sealed ForwardCycleRecords from the campaign's cycles/ directory and
provides a research-facing performance view.

Design constraints:
  - Never mutates sealed records — read-only access.
  - Statistics with insufficient observations are explicitly labelled.
  - Forward data must not leak into research / training pipelines; this ledger
    is locked to the campaign directory and must be imported explicitly.
  - Sharpe requires >= 24 observations for a meaningful estimate; annualized
    return requires >= 12; volatility requires >= 2.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from mentisrex.research.forward_campaign.record import ForwardCycleRecord, CycleStatus


_MIN_SHARPE_OBS = 24       # fewer than this: label as INSUFFICIENT_SAMPLE
_MIN_ANNUAL_OBS = 12       # fewer than this: label annualized return as N/A
_MIN_VOL_OBS = 2           # fewer than this: label volatility as N/A


@dataclass(frozen=True)
class ForwardPerformanceSummary:
    """Computed performance statistics from completed forward cycles.

    Fields labelled INSUFFICIENT_SAMPLE where sample is too small.
    Never fabricates statistics from too-few observations.
    """
    n_forward_cycles: int
    n_successful_cycles: int
    n_skipped_cycles: int
    n_failed_cycles: int

    # returns
    cumulative_return: float
    monthly_returns: list            # list[float], one per successful cycle
    annualized_return: Optional[float]  # None when < _MIN_ANNUAL_OBS cycles
    annualized_return_label: str         # "ESTIMATED" | "INSUFFICIENT_SAMPLE"

    # risk / volatility
    volatility: Optional[float]          # None when < _MIN_VOL_OBS
    volatility_label: str
    sharpe: Optional[float]              # None when < _MIN_SHARPE_OBS
    sharpe_label: str

    # drawdown
    max_drawdown: float

    # execution
    total_orders: int
    total_fills: int
    total_turnover: float
    total_transaction_cost_est: float

    # accounting
    starting_nav: float
    current_nav: float
    realized_pnl: float
    unrealized_pnl: float

    # data quality
    total_observations_accepted: int
    total_observations_rejected: int
    total_pit_violations: int

    first_evaluation_date: Optional[date]
    last_evaluation_date: Optional[date]


class ForwardLedger:
    """Read-only view of sealed forward campaign cycles.

    Loads records from the campaign cycles/ directory. Records are never
    written by this class — only read.
    """

    def __init__(self, campaign_dir: Path) -> None:
        self._cycles_dir = campaign_dir / "cycles"

    # ── public API ────────────────────────────────────────────────────────────

    def list_cycles(self) -> list[ForwardCycleRecord]:
        """All sealed cycles in chronological order."""
        recs = []
        if not self._cycles_dir.exists():
            return recs
        for p in sorted(self._cycles_dir.glob("*.json")):
            try:
                recs.append(ForwardCycleRecord.from_dict(json.loads(p.read_text())))
            except Exception:
                continue
        recs.sort(key=lambda r: (r.evaluation_date or date.min))
        return recs

    def get_cycle(self, cycle_id: str) -> ForwardCycleRecord | None:
        """Return the sealed record for cycle_id, or None if not found."""
        p = self._cycles_dir / f"{cycle_id}.json"
        if not p.exists():
            return None
        try:
            return ForwardCycleRecord.from_dict(json.loads(p.read_text()))
        except Exception:
            return None

    def latest_cycle(self) -> ForwardCycleRecord | None:
        """Most recent successful sealed cycle, or None."""
        cycles = [c for c in self.list_cycles() if c.status == CycleStatus.SUCCESS]
        return cycles[-1] if cycles else None

    def current_nav(self) -> float:
        """NAV from most recent successful cycle, or 0."""
        c = self.latest_cycle()
        return c.ending_nav if c else 0.0

    def current_positions(self) -> dict:
        """Positions dict from most recent successful cycle, or {}."""
        c = self.latest_cycle()
        return dict(c.positions) if c else {}

    def performance_summary(self) -> ForwardPerformanceSummary:
        """Compute performance statistics from all sealed cycles."""
        all_cycles = self.list_cycles()
        success = [c for c in all_cycles if c.status == CycleStatus.SUCCESS]
        skipped = [c for c in all_cycles if c.status == CycleStatus.SKIPPED]
        failed  = [c for c in all_cycles if c.status == CycleStatus.FAILED]

        nav_series = [c.ending_nav for c in success]
        monthly_returns: list[float] = []
        if len(nav_series) >= 2:
            monthly_returns = [
                (nav_series[i] - nav_series[i - 1]) / nav_series[i - 1]
                for i in range(1, len(nav_series))
                if nav_series[i - 1] > 0
            ]

        cumulative = (
            (nav_series[-1] / nav_series[0] - 1.0)
            if len(nav_series) >= 2 and nav_series[0] > 0 else 0.0
        )

        # annualized return
        if len(success) >= _MIN_ANNUAL_OBS:
            ann = (1 + cumulative) ** (12 / len(success)) - 1
            ann_label = "ESTIMATED"
        else:
            ann = None
            ann_label = "INSUFFICIENT_SAMPLE"

        # volatility (monthly)
        if len(monthly_returns) >= _MIN_VOL_OBS:
            vol = statistics.stdev(monthly_returns) * (12 ** 0.5)
            vol_label = "ESTIMATED"
        else:
            vol = None
            vol_label = "INSUFFICIENT_SAMPLE"

        # Sharpe
        if len(monthly_returns) >= _MIN_SHARPE_OBS:
            mu = statistics.mean(monthly_returns)
            sd = statistics.stdev(monthly_returns)
            sharpe: float | None = (mu / sd * (12 ** 0.5)) if sd > 0 else 0.0
            sharpe_label = "ESTIMATED"
        else:
            sharpe = None
            sharpe_label = "INSUFFICIENT_SAMPLE"

        # max drawdown
        mdd = 0.0
        if nav_series:
            peak = nav_series[0]
            for nav in nav_series:
                peak = max(peak, nav)
                dd = (peak - nav) / peak if peak > 0 else 0.0
                mdd = max(mdd, dd)

        last_c = success[-1] if success else None
        first_c = success[0] if success else None

        return ForwardPerformanceSummary(
            n_forward_cycles=len(all_cycles),
            n_successful_cycles=len(success),
            n_skipped_cycles=len(skipped),
            n_failed_cycles=len(failed),
            cumulative_return=cumulative,
            monthly_returns=monthly_returns,
            annualized_return=ann,
            annualized_return_label=ann_label,
            volatility=vol,
            volatility_label=vol_label,
            sharpe=sharpe,
            sharpe_label=sharpe_label,
            max_drawdown=mdd,
            total_orders=sum(c.orders_generated for c in success),
            total_fills=sum(c.fills for c in success),
            total_turnover=sum(c.turnover for c in success),
            total_transaction_cost_est=0.0,  # derived from slippage_bps * fills if needed
            starting_nav=first_c.starting_nav if first_c else 0.0,
            current_nav=last_c.ending_nav if last_c else 0.0,
            realized_pnl=last_c.realized_pnl if last_c else 0.0,
            unrealized_pnl=last_c.unrealized_pnl if last_c else 0.0,
            total_observations_accepted=sum(c.observations_accepted for c in success),
            total_observations_rejected=sum(c.observations_rejected for c in success),
            total_pit_violations=sum(c.pit_violations for c in success),
            first_evaluation_date=first_c.evaluation_date if first_c else None,
            last_evaluation_date=last_c.evaluation_date if last_c else None,
        )
