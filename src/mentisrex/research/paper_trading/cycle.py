"""Cycle records and forward performance accumulation (AIDP M23).

CycleRecord — one immutable, fingerprinted record per strategy evaluation cycle.
ForwardPerformanceRecord — accumulates cycles into an auditable performance history.
PerformanceMetrics — computed from the accumulated cycle records.

No new P&L engine. All values are read from M12 PaperPortfolio / M11 PortfolioState
after each evaluation cycle and stored here for research.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class CycleRecord:
    """Immutable record of one evaluation/execution cycle for one strategy."""
    cycle_id: str
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str
    as_of: date
    snapshot_fingerprint: str
    evaluation_fingerprint: str
    evaluation_id: str

    # portfolio state after this cycle
    portfolio_value: float
    nav: float
    cash: float
    realized_pnl: float
    unrealized_pnl: float

    # execution
    n_orders: int
    n_fills: int
    reconciled: bool
    risk_approved: bool
    risk_decision: str = ""
    n_signals: int = 0

    recorded_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "as_of": self.as_of.isoformat(),
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "evaluation_fingerprint": self.evaluation_fingerprint,
            "evaluation_id": self.evaluation_id,
            "portfolio_value": self.portfolio_value,
            "nav": self.nav,
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "n_orders": self.n_orders,
            "n_fills": self.n_fills,
            "reconciled": self.reconciled,
            "risk_approved": self.risk_approved,
            "risk_decision": self.risk_decision,
            "n_signals": self.n_signals,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> CycleRecord:
        return cls(
            cycle_id=d["cycle_id"],
            strategy_id=d["strategy_id"],
            strategy_version=d["strategy_version"],
            strategy_fingerprint=d["strategy_fingerprint"],
            as_of=date.fromisoformat(d["as_of"]),
            snapshot_fingerprint=d["snapshot_fingerprint"],
            evaluation_fingerprint=d["evaluation_fingerprint"],
            evaluation_id=d["evaluation_id"],
            portfolio_value=d["portfolio_value"],
            nav=d.get("nav", d["portfolio_value"]),
            cash=d["cash"],
            realized_pnl=d["realized_pnl"],
            unrealized_pnl=d["unrealized_pnl"],
            n_orders=d["n_orders"],
            n_fills=d["n_fills"],
            reconciled=d["reconciled"],
            risk_approved=d["risk_approved"],
            risk_decision=d.get("risk_decision", ""),
            n_signals=d.get("n_signals", 0),
            recorded_at=datetime.fromisoformat(d["recorded_at"]) if d.get("recorded_at") else datetime.utcnow(),
        )


@dataclass(frozen=True)
class PerformanceMetrics:
    n_cycles: int
    total_return: float
    max_drawdown: float
    realized_pnl: float
    unrealized_pnl: float
    final_nav: float
    avg_daily_return: float
    volatility: float
    sharpe: float
    total_orders: int
    total_fills: int
    fill_rate: float
    risk_approval_rate: float
    total_n_signals: int


@dataclass(frozen=True)
class PaperBacktestComparison:
    """Comparison of research/backtest assumptions vs paper-trading realized results."""
    strategy_id: str
    strategy_version: str

    # capital
    research_capital: float
    paper_initial_nav: float
    paper_final_nav: float

    # returns
    paper_total_return: float

    # execution quality
    fill_rate: float
    risk_approval_rate: float

    # signals
    avg_n_signals: float

    # drawdown
    max_drawdown: float

    notes: list = field(default_factory=list)


class ForwardPerformanceRecord:
    """Accumulated paper performance history for one strategy.

    Immutable once built from cycles. Methods compute derived metrics.
    """

    def __init__(self,
                 strategy_id: str,
                 strategy_version: str,
                 strategy_fingerprint: str,
                 cycles: list) -> None:
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.strategy_fingerprint = strategy_fingerprint
        self.cycles: list[CycleRecord] = list(cycles)

    @property
    def n_cycles(self) -> int:
        return len(self.cycles)

    def fingerprint(self) -> str:
        from mentisrex.research.strategy_deployment.models import _fp
        return _fp({
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "n_cycles": len(self.cycles),
            "cycle_ids": [c.cycle_id for c in self.cycles],
        })

    def nav_series(self) -> list[tuple[date, float]]:
        return [(r.as_of, r.nav) for r in self.cycles]

    def daily_returns(self) -> list[float]:
        navs = [r.nav for r in self.cycles]
        if len(navs) < 2:
            return []
        return [(navs[i] - navs[i - 1]) / navs[i - 1]
                for i in range(1, len(navs))
                if navs[i - 1] > 0]

    def total_return(self) -> float:
        if len(self.cycles) < 2:
            return 0.0
        first_nav = self.cycles[0].nav
        last_nav = self.cycles[-1].nav
        return (last_nav / first_nav - 1.0) if first_nav > 0 else 0.0

    def max_drawdown(self) -> float:
        navs = [r.nav for r in self.cycles]
        if not navs:
            return 0.0
        peak = navs[0]
        mdd = 0.0
        for nav in navs:
            peak = max(peak, nav)
            dd = (peak - nav) / peak if peak > 0 else 0.0
            mdd = max(mdd, dd)
        return mdd

    def sharpe(self, periods_per_year: int = 252) -> float:
        rets = self.daily_returns()
        if len(rets) < 2:
            return 0.0
        mu = statistics.mean(rets)
        sd = statistics.stdev(rets)
        return (mu / sd * (periods_per_year ** 0.5)) if sd > 0 else 0.0

    def volatility(self, periods_per_year: int = 252) -> float:
        rets = self.daily_returns()
        if len(rets) < 2:
            return 0.0
        sd = statistics.stdev(rets)
        return sd * (periods_per_year ** 0.5)

    def metrics(self, periods_per_year: int = 252) -> PerformanceMetrics:
        rets = self.daily_returns()
        n = len(self.cycles)
        total_orders = sum(r.n_orders for r in self.cycles)
        total_fills = sum(r.n_fills for r in self.cycles)
        risk_approved = sum(1 for r in self.cycles if r.risk_approved)
        final_nav = self.cycles[-1].nav if self.cycles else 0.0
        realized_pnl = self.cycles[-1].realized_pnl if self.cycles else 0.0
        unrealized_pnl = self.cycles[-1].unrealized_pnl if self.cycles else 0.0
        total_sigs = sum(r.n_signals for r in self.cycles)

        avg_ret = statistics.mean(rets) if rets else 0.0
        vol = (statistics.stdev(rets) * (periods_per_year ** 0.5)) if len(rets) >= 2 else 0.0
        sd = statistics.stdev(rets) if len(rets) >= 2 else 0.0
        sharpe = (avg_ret / sd * (periods_per_year ** 0.5)) if sd > 0 else 0.0

        return PerformanceMetrics(
            n_cycles=n,
            total_return=self.total_return(),
            max_drawdown=self.max_drawdown(),
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            final_nav=final_nav,
            avg_daily_return=avg_ret,
            volatility=vol,
            sharpe=sharpe,
            total_orders=total_orders,
            total_fills=total_fills,
            fill_rate=(total_fills / total_orders if total_orders > 0 else 0.0),
            risk_approval_rate=(risk_approved / n if n > 0 else 0.0),
            total_n_signals=total_sigs,
        )

    def paper_backtest_comparison(self, research_capital: float) -> PaperBacktestComparison:
        m = self.metrics()
        return PaperBacktestComparison(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            research_capital=research_capital,
            paper_initial_nav=self.cycles[0].nav if self.cycles else 0.0,
            paper_final_nav=self.cycles[-1].nav if self.cycles else 0.0,
            paper_total_return=m.total_return,
            fill_rate=m.fill_rate,
            risk_approval_rate=m.risk_approval_rate,
            avg_n_signals=(m.total_n_signals / m.n_cycles if m.n_cycles > 0 else 0.0),
            max_drawdown=m.max_drawdown,
            notes=["paper trading using M21 open/free data — not equivalent to institutional feeds"],
        )
