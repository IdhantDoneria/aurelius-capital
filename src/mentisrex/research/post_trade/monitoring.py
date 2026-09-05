"""Operational monitoring (AIDP M15).

Rolls the engine's state into an `OperationalHealthReport`: settlement completion,
reconciliation breaks, cash/ledger integrity, and alerts. Pure reads — the operational
dashboard of the post-trade book.
"""

from __future__ import annotations

from mentisrex.research.post_trade.models import (
    OperationalHealthReport,
    SettlementStatus,
    TradeEvent,
)


def ledger_reconciles(engine) -> bool:
    """Position ledger net == M11 holdings, and cash ledger == M11 economic cash."""
    net = engine.position_ledger.net_shares()
    holdings = {s: h.shares for s, h in engine.accounting.state.holdings.items()}
    keys = set(net) | set(holdings)
    pos_ok = all(abs(net.get(k, 0.0) - holdings.get(k, 0.0)) < 1e-6 for k in keys)
    cash_ok = engine.cash_ledger.reconciles(engine.accounting.cash)
    return pos_ok and cash_ok


def operational_health(engine, *, reconciliation_breaks: int = 0) -> OperationalHealthReport:
    insts = engine.settlement.instructions.values()
    total = len(insts) or 1
    n_completed = sum(i.status == SettlementStatus.COMPLETED for i in insts)
    n_failed = sum(i.status == SettlementStatus.FAILED for i in insts)
    cash_ok = engine.cash_ledger.reconciles(engine.accounting.cash)
    ledg_ok = ledger_reconciles(engine)

    alerts = []
    if n_failed:
        alerts.append(f"failed_settlements:{n_failed}")
    if not cash_ok:
        alerts.append("cash_break")
    if not ledg_ok:
        alerts.append("ledger_break")
    if reconciliation_breaks:
        alerts.append(f"reconciliation_breaks:{reconciliation_breaks}")

    return OperationalHealthReport(
        ok=not alerts,
        n_trades=len(engine.log.of_type(TradeEvent)),
        n_failed_settlements=n_failed,
        n_reconciliation_breaks=reconciliation_breaks,
        settlement_completion_rate=n_completed / total,
        cash_reconciles=cash_ok,
        ledger_reconciles=ledg_ok,
        alerts=alerts,
    )
