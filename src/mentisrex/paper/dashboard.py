"""Performance dashboard — a live snapshot of the running paper account.

Reuses the Phase-4 PerformanceCalculator on the engine's wall-clock equity curve,
so live metrics are computed the exact same way as backtest metrics (Sharpe, max
drawdown, ...). One definition of performance across backtest and paper is the
whole reason those numbers are comparable.

build_snapshot() -> dict for programmatic use / a web UI.
render_text()   -> a monospace panel for a terminal.
"""

from __future__ import annotations

from mentisrex.backtesting.analytics.performance import PerformanceCalculator
from mentisrex.paper.broker import PaperBroker
from mentisrex.paper.engine import TradingEngine


def build_snapshot(engine: TradingEngine, broker: PaperBroker) -> dict:
    acc = broker.account()
    metrics = (
        PerformanceCalculator().compute(
            engine.equity_curve,
            fills=None,
            initial_capital=engine.equity_curve[0].equity if engine.equity_curve else 0.0,
        )
        if len(engine.equity_curve) >= 2
        else None
    )
    return {
        "account": acc,
        "health": engine.health_snapshot(),
        "performance": {
            "total_return": metrics.total_return if metrics else 0.0,
            "sharpe": metrics.sharpe_ratio if metrics else 0.0,
            "max_drawdown": metrics.max_drawdown if metrics else 0.0,
            "volatility": metrics.annualized_volatility if metrics else 0.0,
        },
    }


def render_text(engine: TradingEngine, broker: PaperBroker) -> str:
    s = build_snapshot(engine, broker)
    a, h, p = s["account"], s["health"], s["performance"]
    lines = [
        "== PAPER TRADING DASHBOARD ==",
        f"equity        : {float(a['equity']):>14,.2f}",
        f"cash          : {float(a['cash']):>14,.2f}",
        f"unrealized P&L: {float(a['unrealized_pnl']):>14,.2f}",
        f"realized P&L  : {float(a['realized_pnl']):>14,.2f}",
        f"positions     : {a['positions']}",
        f"open orders   : {a['open_orders']}",
        "-- performance --",
        f"total return  : {p['total_return']:>8.2%}",
        f"sharpe        : {p['sharpe']:>8.2f}",
        f"max drawdown  : {p['max_drawdown']:>8.2%}",
        "-- health --",
        f"ticks/fills   : {h['ticks']} / {h['fills']}",
        f"rejects/errors: {h['rejects']} / {h['errors']}",
        f"restarts      : {h['restarts']}   running={h['running']}",
    ]
    return "\n".join(lines)
