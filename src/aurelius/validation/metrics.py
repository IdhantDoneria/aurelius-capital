"""Extended performance metrics beyond PerformanceCalculator baseline.

MetricsCalculator.compute_extended() takes an existing PerformanceMetrics
(from backtesting.analytics.performance) and adds:
  VaR/CVaR (historical), skewness, excess kurtosis, average drawdown,
  recovery time, expectancy, tail ratio, capacity estimate, TC/slippage drag.

All math is stdlib-only (no numpy/scipy).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from aurelius.backtesting.analytics.performance import PerformanceMetrics


@dataclass
class ExtendedMetrics:
    # ── base metrics (carried from PerformanceMetrics) ────────────────────────
    total_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    num_trades: int
    win_rate: float
    profit_factor: float
    annual_turnover: float
    avg_holding_period_days: float

    # ── tail risk ─────────────────────────────────────────────────────────────
    var_95: float  # 1-day 95% historical VaR (negative → loss)
    var_99: float  # 1-day 99% historical VaR
    cvar_95: float  # Expected shortfall at 95% confidence
    skewness: float  # Negative = left-tail heavy (bad for strategies)
    excess_kurtosis: float  # >0 = fat tails vs normal

    # ── drawdown analysis ─────────────────────────────────────────────────────
    avg_drawdown: float  # Mean drawdown depth across full history
    recovery_time_days: float  # Mean calendar days to recover from troughs

    # ── trade quality ─────────────────────────────────────────────────────────
    expectancy: float  # avg_win * win_rate - avg_loss * loss_rate (per trade)
    tail_ratio: float  # |95th pct return| / |5th pct return|; >1 means right tail

    # ── cost analysis ─────────────────────────────────────────────────────────
    tc_drag_bps: float  # annual TC drag in bps (from turnover * commission)
    slippage_drag_bps: float  # annual slippage drag in bps (from turnover * slippage)

    # ── capacity ─────────────────────────────────────────────────────────────
    capacity_estimate_mm: float  # rough AUM capacity in $M; -1 if cannot estimate


def _percentile(sorted_data: list[float], p: float) -> float:
    """p in [0,1]. Linear interpolation on sorted array."""
    n = len(sorted_data)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_data[0]
    idx = p * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return sorted_data[lo] + (idx - lo) * (sorted_data[hi] - sorted_data[lo])


def _skewness(data: list[float]) -> float:
    n = len(data)
    if n < 3:
        return 0.0
    m = statistics.mean(data)
    s = statistics.stdev(data)
    if s == 0:
        return 0.0
    return sum((x - m) ** 3 for x in data) / (n * s**3)


def _excess_kurtosis(data: list[float]) -> float:
    n = len(data)
    if n < 4:
        return 0.0
    m = statistics.mean(data)
    s = statistics.stdev(data)
    if s == 0:
        return 0.0
    return sum((x - m) ** 4 for x in data) / (n * s**4) - 3.0


def _recovery_time_days(dd_series: list[tuple]) -> float:
    """Mean calendar days from drawdown trough to recovery (equity back to prior peak)."""
    # dd_series: list[(timestamp, drawdown_fraction)] from PerformanceMetrics.drawdown_series
    if not dd_series:
        return 0.0
    recovery_durations: list[float] = []
    in_drawdown = False
    trough_ts = None
    for ts, dd in dd_series:
        if dd < -0.001 and not in_drawdown:
            in_drawdown = True
            trough_ts = ts
        elif dd >= -0.001 and in_drawdown:
            if trough_ts is not None:
                days = (ts - trough_ts).days
                recovery_durations.append(float(days))
            in_drawdown = False
            trough_ts = None
    return statistics.mean(recovery_durations) if recovery_durations else 0.0


class MetricsCalculator:
    def __init__(
        self,
        commission_rate: float = 0.001,  # 10 bps/side = 0.001 * 10000 = 10 bps
        slippage_bps: float = 10.0,
        trading_days: int = 252,
        avg_daily_volume_mm: float = -1.0,  # -1 means unknown
        max_fill_pct_adv: float = 0.20,
    ) -> None:
        self._commission = commission_rate
        self._slip_bps = slippage_bps
        self._td = trading_days
        self._adv_mm = avg_daily_volume_mm
        self._max_fill = max_fill_pct_adv

    def compute_extended(self, base: PerformanceMetrics) -> ExtendedMetrics:
        dr = base.daily_returns
        sorted_dr = sorted(dr)
        n = len(sorted_dr)

        # VaR / CVaR (historical, 1-day)
        var_95 = _percentile(sorted_dr, 0.05) if n > 0 else 0.0
        var_99 = _percentile(sorted_dr, 0.01) if n > 0 else 0.0
        tail_count_95 = max(1, int(0.05 * n))
        cvar_95 = statistics.mean(sorted_dr[:tail_count_95]) if sorted_dr else 0.0

        # Skew / kurtosis
        skew = _skewness(dr) if n >= 3 else 0.0
        kurt = _excess_kurtosis(dr) if n >= 4 else 0.0

        # Average drawdown
        dd_values = [dd for _, dd in base.drawdown_series]
        avg_dd = statistics.mean(dd_values) if dd_values else 0.0

        # Recovery time
        rec_time = _recovery_time_days(base.drawdown_series)

        # Expectancy from round trips
        rt = base.round_trips
        if rt:
            wins = [t.pnl for t in rt if t.pnl > 0]
            losses = [t.pnl for t in rt if t.pnl <= 0]
            wr = len(wins) / len(rt)
            avg_win = statistics.mean(wins) if wins else 0.0
            avg_loss = abs(statistics.mean(losses)) if losses else 0.0
            expectancy = wr * avg_win - (1 - wr) * avg_loss
        else:
            expectancy = 0.0

        # Tail ratio: 95th pct / abs(5th pct) of daily returns
        if n > 0:
            p95 = _percentile(sorted_dr, 0.95)
            p05 = abs(_percentile(sorted_dr, 0.05))
            tail_ratio = p95 / p05 if p05 > 0 else float("inf")
        else:
            tail_ratio = 0.0

        # Cost drag (approximate from turnover)
        # annual TC drag: turnover * commission_rate * 2 (round-trip) * 10000 bps
        tc_drag_bps = base.annual_turnover * float(self._commission) * 2.0 * 10_000.0
        slip_drag_bps = base.annual_turnover * (self._slip_bps / 10_000.0) * 2.0 * 10_000.0

        # Capacity estimate: daily capacity = ADV * max_fill_pct
        # Strategy capacity ≈ daily_capacity / daily_turnover_fraction
        if self._adv_mm > 0 and base.annual_turnover > 0:
            daily_turn_frac = base.annual_turnover / self._td
            daily_capacity_mm = self._adv_mm * self._max_fill
            capacity_mm = daily_capacity_mm / daily_turn_frac if daily_turn_frac > 0 else -1.0
        else:
            capacity_mm = -1.0

        return ExtendedMetrics(
            total_return=base.total_return,
            cagr=base.cagr,
            annualized_volatility=base.annualized_volatility,
            sharpe_ratio=base.sharpe_ratio,
            sortino_ratio=base.sortino_ratio,
            max_drawdown=base.max_drawdown,
            calmar_ratio=base.calmar_ratio,
            num_trades=base.num_trades,
            win_rate=base.win_rate,
            profit_factor=base.profit_factor,
            annual_turnover=base.annual_turnover,
            avg_holding_period_days=base.avg_holding_period_days,
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            skewness=skew,
            excess_kurtosis=kurt,
            avg_drawdown=avg_dd,
            recovery_time_days=rec_time,
            expectancy=expectancy,
            tail_ratio=tail_ratio,
            tc_drag_bps=tc_drag_bps,
            slippage_drag_bps=slip_drag_bps,
            capacity_estimate_mm=capacity_mm,
        )
