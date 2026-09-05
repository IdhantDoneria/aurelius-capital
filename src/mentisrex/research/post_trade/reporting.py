"""Reporting (AIDP M15).

Builds the operational report set from the engine state: settlement, cash, ledger,
corporate-action, operational-health, and the daily composite `PostTradeReport`. Pure
reads over the reused book — reports are frozen and dated for a point-in-time record.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.post_trade import cash as cash_mod
from mentisrex.research.post_trade import monitoring, reconciliation
from mentisrex.research.post_trade.models import (
    CorporateActionEvent,
    CorporateActionReport,
    LedgerReport,
    PostTradeReport,
    TradeEvent,
)


def settlement_report(engine, as_of: date | None = None):
    return engine.settlement.report(as_of)


def cash_report(engine, as_of: date | None = None):
    return cash_mod.cash_report(engine, as_of)


def ledger_report(engine) -> LedgerReport:
    return LedgerReport(
        n_trade_events=len(engine.log.of_type(TradeEvent)),
        n_position_events=len(engine.position_ledger.events),
        n_cash_events=len(engine.cash_ledger.events),
        net_cash_flow=engine.trade_ledger.net_cash_flow(),
        gross_traded_notional=engine.trade_ledger.gross_notional(),
        reconciles=monitoring.ledger_reconciles(engine),
    )


def corporate_action_report(engine) -> CorporateActionReport:
    evs = engine.log.of_type(CorporateActionEvent)
    by_type: dict = {}
    for e in evs:
        by_type[e.action_type] = by_type.get(e.action_type, 0) + 1
    return CorporateActionReport(
        n_actions=len(evs), total_cash_impact=sum(e.cash_impact for e in evs), by_type=by_type
    )


def post_trade_report(
    engine, *, as_of: date | None = None, broker_account=None, execution_fills=None
) -> PostTradeReport:
    recon = reconciliation.reconcile(
        engine, broker_account=broker_account, execution_fills=execution_fills, as_of=as_of
    )
    health = monitoring.operational_health(
        engine, reconciliation_breaks=0 if recon.ok else len(recon.differences)
    )
    return PostTradeReport(
        as_of=as_of,
        portfolio_value=engine.accounting.value(),
        settled_cash=engine.cash_ledger.settled_balance(),
        realized_pnl=engine.accounting.realized_pnl(),
        unrealized_pnl=engine.accounting.unrealized_pnl(),
        n_positions=len(engine.accounting.state.holdings),
        settlement=settlement_report(engine, as_of),
        cash=cash_report(engine, as_of),
        ledger=ledger_report(engine),
        corporate_actions=corporate_action_report(engine),
        health=health,
        reconciliation=recon,
    )
