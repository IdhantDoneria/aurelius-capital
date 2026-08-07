"""Performance analytics from the realized equity curve (AIDP M11).

Pure numpy over the portfolio-value series produced by the simulation. Reuses the
M9 Sharpe definition; computes the rest (Sortino, Calmar, Omega, drawdowns,
trade stats) locally. No look-ahead — everything is a function of realized values.
"""

from __future__ import annotations

import math

import numpy as np

from aurelius.research.simulation.models import (
    DrawdownReport,
    SimulationSummary,
)
from aurelius.research.validation.significance import sharpe as _sharpe

TRADING_DAYS = 252


def returns_from_values(values) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    if v.size < 2:
        return np.array([])
    return v[1:] / v[:-1] - 1.0


def drawdown(values) -> DrawdownReport:
    v = np.asarray(values, dtype=float)
    if v.size < 2:
        return DrawdownReport(0.0, 0.0, 0.0, 0.0)
    peak = np.maximum.accumulate(v)
    dd = (v - peak) / peak
    underwater = dd < -1e-12
    # recovery: longest run underwater
    max_run = run = 0
    for u in underwater:
        run = run + 1 if u else 0
        max_run = max(max_run, run)
    neg = dd[dd < 0]
    return DrawdownReport(
        max_drawdown=float(dd.min()),
        avg_drawdown=float(neg.mean()) if neg.size else 0.0,
        max_recovery_days=float(max_run),
        time_underwater_frac=float(underwater.mean()))


def performance_metrics(values, *, periods: int = TRADING_DAYS, n_years: float | None = None) -> dict:
    v = np.asarray(values, dtype=float)
    if v.size < 2:
        return {"total_return": 0.0, "cagr": 0.0, "volatility": 0.0, "sharpe": 0.0,
                "sortino": 0.0, "calmar": 0.0, "omega": 0.0, "hit_rate": 0.0,
                "profit_factor": 0.0, "gain_loss_ratio": 0.0,
                "max_drawdown": 0.0, "avg_drawdown": 0.0}
    r = returns_from_values(v)
    total_return = float(v[-1] / v[0] - 1.0)
    years = n_years if n_years else max(v.size / periods, 1e-9)
    cagr = float((v[-1] / v[0]) ** (1.0 / years) - 1.0) if v[0] > 0 else 0.0
    vol = float(r.std(ddof=1) * math.sqrt(periods)) if r.size > 1 else 0.0
    dd = drawdown(v)
    pos, neg = r[r > 0], r[r < 0]
    downside = math.sqrt(float((np.minimum(r, 0.0) ** 2).mean())) if r.size else 0.0
    return {
        "total_return": total_return,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": _sharpe(r, periods) if r.size > 1 else 0.0,
        "sortino": float(r.mean() / downside * math.sqrt(periods)) if downside > 0 else 0.0,
        "calmar": float(cagr / abs(dd.max_drawdown)) if dd.max_drawdown < 0 else 0.0,
        "omega": float(pos.sum() / abs(neg.sum())) if neg.sum() != 0 else float("inf") if pos.sum() > 0 else 0.0,
        "hit_rate": float((r > 0).mean()),
        "profit_factor": float(pos.sum() / abs(neg.sum())) if neg.size else float("inf") if pos.size else 0.0,
        "gain_loss_ratio": float(pos.mean() / abs(neg.mean())) if neg.size and pos.size else 0.0,
        "max_drawdown": dd.max_drawdown,
        "avg_drawdown": dd.avg_drawdown,
    }


def build_summary(values, *, n_rebalances: int, annualized_turnover: float,
                  avg_holding_days: float, total_cost: float, cost_drag_annualized: float,
                  periods: int = TRADING_DAYS, n_years: float | None = None) -> SimulationSummary:
    m = performance_metrics(values, periods=periods, n_years=n_years)
    v = np.asarray(values, dtype=float)
    return SimulationSummary(
        total_return=m["total_return"], cagr=m["cagr"], volatility=m["volatility"],
        sharpe=m["sharpe"], sortino=m["sortino"], calmar=m["calmar"], omega=m["omega"],
        max_drawdown=m["max_drawdown"], avg_drawdown=m["avg_drawdown"],
        hit_rate=m["hit_rate"], profit_factor=m["profit_factor"],
        gain_loss_ratio=m["gain_loss_ratio"], annualized_turnover=annualized_turnover,
        avg_holding_days=avg_holding_days, total_cost=total_cost,
        cost_drag_annualized=cost_drag_annualized, final_value=float(v[-1]) if v.size else 0.0,
        n_rebalances=n_rebalances, n_periods=int(v.size))
