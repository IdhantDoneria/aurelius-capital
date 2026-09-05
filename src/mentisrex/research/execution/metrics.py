"""Metric engine (AIDP M8).

Does NOT re-derive what the backtester already computed. It takes the certified
`PerformanceMetrics` (Sharpe/Sortino/Calmar/CAGR/vol/drawdown/turnover/win-rate/
profit-factor from an earlier milestone `PerformanceCalculator`) and *extends* it with the
institutional metrics that layer needs — distribution shape, tail behaviour,
benchmark-relative alpha/beta/IR, trade statistics. Pure functions over the
already-produced return/trade series.
"""

from __future__ import annotations

import math
import statistics
from typing import Any


def _moment(xs: list[float], k: int, mean: float) -> float:
    return sum((x - mean) ** k for x in xs) / len(xs)


def compute_metrics(
    pm: Any,
    *,
    benchmark_returns: list[float] | None = None,
    trading_days: int = 252,
    risk_free: float = 0.05,
) -> dict[str, float]:
    """Full metric set. `pm` is a backtester PerformanceMetrics; `benchmark_returns`
    are daily benchmark returns aligned to pm.daily_returns (optional → alpha/beta/
    IR are None)."""
    r = list(pm.daily_returns or [])
    rts = list(pm.round_trips or [])
    pnls = [t.pnl for t in rts]

    out: dict[str, float] = {
        # ── reused from the certified calculator (not recomputed) ──
        "Sharpe": pm.sharpe_ratio,
        "Sortino": pm.sortino_ratio,
        "Calmar": pm.calmar_ratio,
        "CAGR": pm.cagr,
        "AnnualizedReturn": pm.cagr,
        "TotalReturn": pm.total_return,
        "Volatility": pm.annualized_volatility,
        "MaxDrawdown": pm.max_drawdown,
        "Turnover": pm.annual_turnover,
        "AverageHoldingPeriod": pm.avg_holding_period_days,
        "WinRate": pm.win_rate,
        "ProfitFactor": pm.profit_factor,
        "NumTrades": float(pm.num_trades),
    }

    # ── distribution shape ──
    if len(r) >= 2:
        mean = statistics.mean(r)
        sd = statistics.pstdev(r)
        out["HitRate"] = sum(1 for x in r if x > 0) / len(r)
        if sd > 0:
            out["Skew"] = _moment(r, 3, mean) / sd**3
            out["Kurtosis"] = _moment(r, 4, mean) / sd**4 - 3.0  # excess
        else:
            out["Skew"] = out["Kurtosis"] = 0.0
        out["TailRatio"] = _tail_ratio(r)
    else:
        out["HitRate"] = out["Skew"] = out["Kurtosis"] = out["TailRatio"] = 0.0

    # ── drawdown-based ──
    dd = [d for _, d in (pm.drawdown_series or [])]
    out["UlcerIndex"] = math.sqrt(statistics.mean([d * d for d in dd])) if dd else 0.0
    out["RecoveryFactor"] = (pm.total_return / abs(pm.max_drawdown)) if pm.max_drawdown < 0 else 0.0

    # ── exposure: fraction of the sample with capital at work ──
    out["Exposure"] = _exposure(pm)

    # ── trade statistics ──
    if pnls:
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        out["AverageTrade"] = statistics.mean(pnls)
        out["Expectancy"] = statistics.mean(pnls)  # currency expectancy per trade
        out["LargestWin"] = max(pnls)
        out["LargestLoss"] = min(pnls)
        out["AverageWin"] = statistics.mean(wins) if wins else 0.0
        out["AverageLoss"] = statistics.mean(losses) if losses else 0.0
    else:
        for k in (
            "AverageTrade",
            "Expectancy",
            "LargestWin",
            "LargestLoss",
            "AverageWin",
            "AverageLoss",
        ):
            out[k] = 0.0

    # ── benchmark-relative ──
    alpha, beta, ir = _benchmark_relative(r, benchmark_returns, trading_days, risk_free)
    out["Alpha"], out["Beta"], out["InformationRatio"] = alpha, beta, ir
    return out


def _tail_ratio(r: list[float]) -> float:
    s = sorted(r)
    n = len(s)
    p95 = s[min(n - 1, int(0.95 * n))]
    p05 = s[max(0, int(0.05 * n))]
    return abs(p95) / abs(p05) if p05 != 0 else 0.0


def _exposure(pm: Any) -> float:
    """Share of trading days with an open position, from round-trip intervals over
    the equity-curve span. No positions → 0."""
    curve = pm.equity_curve or []
    rts = pm.round_trips or []
    if not curve or not rts:
        return 0.0
    days = {p.timestamp.date() for p in curve}
    if not days:
        return 0.0
    held = set()
    for t in rts:
        entry = getattr(t, "entry_time", None) or getattr(t, "entry", None)
        exit_ = getattr(t, "exit_time", None) or getattr(t, "exit", None)
        if entry is None or exit_ is None:
            continue
        held |= {d for d in days if entry.date() <= d <= exit_.date()}
    return len(held) / len(days)


def _benchmark_relative(r, bench, td, rf):
    if not bench or len(bench) < 2 or len(r) < 2:
        return None, None, None
    n = min(len(r), len(bench))
    r, bench = r[:n], bench[:n]
    var_b = statistics.pvariance(bench)
    if var_b == 0:
        return None, None, None
    mr, mb = statistics.mean(r), statistics.mean(bench)
    cov = sum((r[i] - mr) * (bench[i] - mb) for i in range(n)) / n
    beta = cov / var_b
    rf_daily = (1 + rf) ** (1.0 / td) - 1
    alpha = ((mr - rf_daily) - beta * (mb - rf_daily)) * td  # annualized
    active = [r[i] - bench[i] for i in range(n)]
    te = statistics.pstdev(active)
    ir = (statistics.mean(active) / te * math.sqrt(td)) if te > 0 else None
    return alpha, beta, ir
