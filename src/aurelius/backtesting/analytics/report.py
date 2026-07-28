"""BacktestReport — structured, reproducible experiment record.

Every field needed to reproduce a backtest is included:
  - strategy name + parameters
  - data version (feed description)
  - engine config (costs, limits, capital)
  - performance metrics
  - equity curve (for visualization)
  - trade log (for forensic analysis)

to_dict() produces a JSON-serializable dict for storage in ExperimentRun.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aurelius.backtesting.analytics.performance import PerformanceMetrics


@dataclass
class BacktestReport:
    # Identity
    strategy_name: str
    strategy_parameters: dict[str, Any]
    run_id: str

    # Data
    symbols: list[str]
    start_date: str  # ISO format
    end_date: str
    total_bars: int
    data_source: str = "unknown"

    # Config snapshot (subset for display)
    initial_capital: float = 1_000_000.0
    commission_rate_bps: float = 10.0
    spread_bps: float = 5.0
    slippage_bps: float = 10.0

    # Metrics
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)

    # Status
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None

    # ── summary display ───────────────────────────────────────────────────────

    def summary(self) -> str:
        m = self.metrics
        return (
            f"{'═' * 60}\n"
            f"  Backtest: {self.strategy_name}\n"
            f"  Period:   {self.start_date} → {self.end_date}\n"
            f"  Capital:  ${self.initial_capital:,.0f}\n"
            f"{'─' * 60}\n"
            f"  Total Return:    {m.total_return:+.2%}\n"
            f"  CAGR:            {m.cagr:+.2%}\n"
            f"  Sharpe Ratio:    {m.sharpe_ratio:.3f}\n"
            f"  Sortino Ratio:   {m.sortino_ratio:.3f}\n"
            f"  Max Drawdown:    {m.max_drawdown:.2%}\n"
            f"  Calmar Ratio:    {m.calmar_ratio:.3f}\n"
            f"  Volatility:      {m.annualized_volatility:.2%}\n"
            f"{'─' * 60}\n"
            f"  Trades:          {m.num_trades}\n"
            f"  Win Rate:        {m.win_rate:.1%}\n"
            f"  Profit Factor:   {m.profit_factor:.2f}\n"
            f"  Avg Hold Period: {m.avg_holding_period_days:.1f} days\n"
            f"  Annual Turnover: {m.annual_turnover:.1f}x\n"
            f"{'═' * 60}"
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for storage."""
        m = self.metrics
        return {
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "strategy_parameters": self.strategy_parameters,
            "symbols": self.symbols,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_bars": self.total_bars,
            "data_source": self.data_source,
            "config": {
                "initial_capital": self.initial_capital,
                "commission_rate_bps": self.commission_rate_bps,
                "spread_bps": self.spread_bps,
                "slippage_bps": self.slippage_bps,
            },
            "metrics": {
                "total_return": m.total_return,
                "cagr": m.cagr,
                "annualized_volatility": m.annualized_volatility,
                "sharpe_ratio": m.sharpe_ratio,
                "sortino_ratio": m.sortino_ratio,
                "max_drawdown": m.max_drawdown,
                "calmar_ratio": m.calmar_ratio,
                "num_trades": m.num_trades,
                "win_rate": m.win_rate,
                "avg_holding_period_days": m.avg_holding_period_days,
                "annual_turnover": m.annual_turnover,
                "profit_factor": m.profit_factor,
            },
            "completed_at": self.completed_at.isoformat(),
            "error": self.error,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)
