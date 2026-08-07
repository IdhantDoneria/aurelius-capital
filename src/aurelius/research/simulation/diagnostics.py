"""Diagnostic log assembly (AIDP Phase 11). Structured logs derived from a
SimulationResult — trade / cash / rebalance / cost logs + warnings."""

from __future__ import annotations


def build_logs(result) -> dict:
    warnings = []
    if not result.diagnostics.get("ledger_reconciles", True):
        warnings.append("ledger_did_not_reconcile")
    if result.capacity_report.capacity_signal == "high":
        warnings.append("high_capacity_utilisation")
    if result.turnover_report.annualized_turnover > 10:
        warnings.append("excessive_turnover")
    if result.drawdown_report.max_drawdown < -0.5:
        warnings.append("severe_drawdown")

    return {
        "trade_log": [{"date": t.date.isoformat() if t.date else None, "security_id": t.security_id,
                       "qty": t.quantity, "price": t.price, "cost": t.cost} for t in result.trades],
        "rebalance_log": [{"date": r.date.isoformat(), "n_trades": r.n_trades,
                           "turnover": r.turnover, "cost": r.total_cost} for r in result.rebalance_events],
        "cost_log": {"total": result.cost_report.total_cost,
                     "bps_of_traded": result.cost_report.cost_bps_of_traded},
        "cash_log": {"final_cash": result.diagnostics.get("final_cash"),
                     "reconciles": result.diagnostics.get("ledger_reconciles")},
        "warnings": warnings,
    }
