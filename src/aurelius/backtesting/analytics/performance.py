"""PerformanceCalculator — institutional-grade risk and return metrics.

All formulas use annualized conventions (252 trading days).

Equity curve → returns:
  r_t = equity[t] / equity[t-1] - 1

Sharpe: (mean_return - rf_daily) / std_return x sqrt(252)
Sortino: uses only downside returns (r < 0) in denominator
Max Drawdown: max((peak - current) / peak) across the full series
Calmar: CAGR / abs(max_drawdown)
Profit Factor: gross_profit / gross_loss from all closed fills

Win rate and profit factor are computed from the fill history:
  pair consecutive fills (buy then sell, or short then cover)
  → realized P&L per round-trip trade
"""

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EquityPoint:
    timestamp: datetime
    equity: float


@dataclass
class RoundTrip:
    """A complete open+close cycle."""

    symbol: str
    side: str  # "long" or "short"
    entry_time: datetime
    exit_time: datetime
    quantity: float
    entry_price: float
    exit_price: float
    pnl: float  # net of commission and slippage

    @property
    def holding_days(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 86400


@dataclass
class PerformanceMetrics:
    # Returns
    total_return: float = 0.0
    cagr: float = 0.0

    # Risk
    annualized_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0  # e.g. -0.15 means 15% below peak
    calmar_ratio: float = 0.0

    # Trading
    num_trades: int = 0
    win_rate: float = 0.0
    avg_holding_period_days: float = 0.0
    annual_turnover: float = 0.0
    profit_factor: float = 0.0

    # Series
    equity_curve: list[EquityPoint] = field(default_factory=list)
    drawdown_series: list[tuple[datetime, float]] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    round_trips: list[RoundTrip] = field(default_factory=list)


class PerformanceCalculator:
    def __init__(self, risk_free_rate: float = 0.05, trading_days: int = 252) -> None:
        self._rf = risk_free_rate
        self._td = trading_days

    def compute(
        self,
        equity_curve: list[EquityPoint],
        fills: list | None = None,
        initial_capital: float = 1_000_000.0,
    ) -> PerformanceMetrics:
        if len(equity_curve) < 2:
            return PerformanceMetrics(equity_curve=equity_curve)

        equities = [p.equity for p in equity_curve]
        timestamps = [p.timestamp for p in equity_curve]

        daily_returns = [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))]
        avg_nav = statistics.mean(equities)

        metrics = PerformanceMetrics(
            equity_curve=equity_curve,
            daily_returns=daily_returns,
        )

        # ── returns ──────────────────────────────────────────────────────────
        metrics.total_return = equities[-1] / equities[0] - 1

        days = max((timestamps[-1] - timestamps[0]).days, 1)
        years = days / 365.25
        if years > 0:
            metrics.cagr = (equities[-1] / equities[0]) ** (1.0 / years) - 1

        # ── risk ─────────────────────────────────────────────────────────────
        if len(daily_returns) > 1:
            std = statistics.stdev(daily_returns)
            metrics.annualized_volatility = std * math.sqrt(self._td)

            rf_daily = (1 + self._rf) ** (1.0 / self._td) - 1
            excess = [r - rf_daily for r in daily_returns]
            excess_std = statistics.stdev(excess)
            if excess_std > 0:
                metrics.sharpe_ratio = statistics.mean(excess) / excess_std * math.sqrt(self._td)

            # Sortino — downside deviation only
            downside_sq = statistics.mean(min(r, 0.0) ** 2 for r in daily_returns)
            if downside_sq > 0:
                metrics.sortino_ratio = (
                    (statistics.mean(daily_returns) - rf_daily)
                    / math.sqrt(downside_sq)
                    * math.sqrt(self._td)
                )

        # ── drawdown ─────────────────────────────────────────────────────────
        peak = equities[0]
        max_dd = 0.0
        dd_series: list[tuple[datetime, float]] = []
        for ts, eq in zip(timestamps, equities, strict=True):
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak if peak > 0 else 0.0
            dd_series.append((ts, dd))
            if dd < max_dd:
                max_dd = dd

        metrics.max_drawdown = max_dd
        metrics.drawdown_series = dd_series

        if max_dd < 0:
            metrics.calmar_ratio = metrics.cagr / abs(max_dd)

        # ── trade metrics from fills ──────────────────────────────────────────
        if fills:
            round_trips, turnover = self._reconstruct_trades(fills, avg_nav, years)
            metrics.round_trips = round_trips
            metrics.num_trades = len(round_trips)
            metrics.annual_turnover = turnover

            if round_trips:
                wins = [t for t in round_trips if t.pnl > 0]
                losses = [t for t in round_trips if t.pnl <= 0]
                metrics.win_rate = len(wins) / len(round_trips)
                metrics.avg_holding_period_days = statistics.mean(
                    t.holding_days for t in round_trips
                )
                gross_profit = sum(t.pnl for t in wins)
                gross_loss = abs(sum(t.pnl for t in losses))
                metrics.profit_factor = (
                    gross_profit / gross_loss if gross_loss > 0 else float("inf")
                )

        return metrics

    def _reconstruct_trades(
        self,
        fills: list,
        avg_nav: float,
        years: float,
    ) -> tuple[list[RoundTrip], float]:
        """Match buys to sells (FIFO) to produce round-trip trades."""
        from collections import defaultdict, deque

        from aurelius.backtesting.events.types import Side

        open_lots: dict[str, deque] = defaultdict(deque)
        round_trips: list[RoundTrip] = []
        total_notional = 0.0

        for fill in fills:
            qty = float(fill.quantity)
            price = float(fill.fill_price)
            commission = float(fill.commission)
            total_notional += qty * price

            if fill.side == Side.BUY:
                open_lots[fill.symbol].append(
                    {
                        "qty": qty,
                        "price": price,
                        "time": fill.timestamp,
                        "commission": commission / qty,
                    }
                )
            else:  # SELL — close long lots FIFO
                remaining = qty
                while remaining > 0 and open_lots[fill.symbol]:
                    lot = open_lots[fill.symbol][0]
                    close_qty = min(remaining, lot["qty"])
                    pnl = (
                        (price - lot["price"]) * close_qty
                        - lot["commission"] * close_qty
                        - (commission / qty) * close_qty
                    )
                    round_trips.append(
                        RoundTrip(
                            symbol=fill.symbol,
                            side="long",
                            entry_time=lot["time"],
                            exit_time=fill.timestamp,
                            quantity=close_qty,
                            entry_price=lot["price"],
                            exit_price=price,
                            pnl=pnl,
                        )
                    )
                    lot["qty"] -= close_qty
                    if lot["qty"] <= 0:
                        open_lots[fill.symbol].popleft()
                    remaining -= close_qty

        annual_turnover = (total_notional / avg_nav / max(years, 1)) if avg_nav > 0 else 0.0
        return round_trips, annual_turnover
