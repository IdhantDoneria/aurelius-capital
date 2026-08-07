"""Simulation validation (AIDP M11).

Two layers: (1) accounting/consistency checks native to the simulation — ledger
reconciliation, portfolio value reconciliation, position accounting, leverage,
NaN-free equity; (2) M9 integration — `to_performance_metrics` adapts the
realized equity curve + trades into a PerformanceMetrics so the M9
ResearchValidator can render its deployment verdict on the *simulated* track record.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np

from aurelius.backtesting.analytics.performance import EquityPoint as PerfEquityPoint
from aurelius.backtesting.analytics.performance import PerformanceMetrics, RoundTrip


def validate_simulation(result, *, allow_short: bool = False, max_leverage: float = 1.05) -> dict:
    checks: dict = {}
    diag = result.diagnostics
    values = [e.value for e in result.equity_curve]

    final_value = values[-1] if values else 0.0
    # tiny negative cash from cost rounding on a fully-invested target is not a
    # violation; flag only a material overdraft (>1% of value = real leverage).
    cash = diag.get("final_cash", 0.0)
    checks["ledger_consistency"] = {"ok": bool(diag.get("ledger_reconciles"))}
    checks["cash_consistency"] = {"ok": cash >= -0.01 * final_value or allow_short,
                                  "final_cash": cash}
    checks["portfolio_accounting"] = {
        "ok": all(v == v and v > 0 for v in values),   # positive, no NaN
        "min_value": min(values) if values else 0.0}
    max_gross = result.exposure_report.max_gross
    checks["leverage"] = {"ok": max_gross <= max_leverage + 1e-6, "max_gross": max_gross}
    checks["position_accounting"] = {
        "ok": allow_short or all(s.short_exposure <= 1e-9 for s in result.snapshots)}
    checks["turnover"] = {"annualized": result.turnover_report.annualized_turnover}
    checks["costs"] = {"total": result.cost_report.total_cost,
                       "drag_annualized": result.cost_report.cost_drag_annualized}
    checks["capacity"] = {"signal": result.capacity_report.capacity_signal,
                          "max_participation": result.capacity_report.max_participation}
    checks["concentration"] = {
        "max_largest_weight": max((r.largest_weight for r in result.risk_timeline), default=0.0)}
    checks["ok"] = all(c.get("ok", True) for c in checks.values() if isinstance(c, dict))
    return checks


def to_performance_metrics(result) -> PerformanceMetrics:
    """Adapt a SimulationResult into a backtester PerformanceMetrics so M9 can
    validate the simulated track record without rerunning anything."""
    eq = result.equity_curve
    base = datetime(2000, 1, 1, tzinfo=UTC)
    curve = [PerfEquityPoint(base + timedelta(days=i), p.value) for i, p in enumerate(eq)]
    vals = [p.value for p in eq]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))] if len(vals) > 1 else []
    peak, dd = (vals[0] if vals else 0.0), []
    for i, v in enumerate(vals):
        peak = max(peak, v)
        dd.append((curve[i].timestamp, (v - peak) / peak if peak else 0.0))
    rts = [RoundTrip(t.security_id, "long" if t.quantity > 0 else "short",
                     base, base + timedelta(days=1), abs(t.quantity), t.price, t.price, -t.cost)
           for t in result.trades]
    s = result.summary
    return PerformanceMetrics(
        total_return=s.total_return, cagr=s.cagr, annualized_volatility=s.volatility,
        sharpe_ratio=s.sharpe, sortino_ratio=s.sortino, max_drawdown=s.max_drawdown,
        calmar_ratio=s.calmar, num_trades=len(rts), annual_turnover=s.annualized_turnover,
        avg_holding_period_days=s.avg_holding_days, equity_curve=curve,
        drawdown_series=dd, daily_returns=rets, round_trips=rts)
