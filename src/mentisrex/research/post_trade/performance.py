"""Performance attribution (AIDP M15).

Post-trade performance impacts derived from the event log + M11 book. Reuses M11
realized/unrealized P&L; adds the operational attributions the milestone asks for:
turnover, total execution cost, implementation-shortfall proxy, cash drag, and the
dividend / corporate-action contribution to P&L. Pure reads — no re-accounting.
"""

from __future__ import annotations

from mentisrex.research.post_trade.models import (
    CashType,
    CorporateActionEvent,
    TradeEvent,
)


def performance(engine) -> dict:
    trades = engine.trade_ledger.events
    value = engine.accounting.value() or 1.0

    gross_traded = engine.trade_ledger.gross_notional()
    total_cost = sum(e.cost for e in trades)
    realized = engine.accounting.realized_pnl()
    unrealized = engine.accounting.unrealized_pnl()

    dividend_cash = sum(e.amount for e in engine.cash_ledger.events
                        if e.cash_type == CashType.DIVIDEND)
    ca_cash = sum(e.cash_impact for e in engine.log.of_type(CorporateActionEvent))

    return {
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": realized + unrealized,
        "total_cost": total_cost,
        "turnover": gross_traded / value,
        "gross_traded_notional": gross_traded,
        "implementation_shortfall": total_cost,          # cost proxy vs arrival unavailable post-trade
        "cash_drag": engine.accounting.cash / value,
        "dividend_impact": dividend_cash,
        "corporate_action_impact": ca_cash,
        "portfolio_value": engine.accounting.value(),
        "return_on_capital": (engine.accounting.value() - engine.initial_capital) / engine.initial_capital
        if engine.initial_capital else 0.0,
    }


def cost_attribution(engine) -> dict:
    """Total execution cost split trade-by-trade (audit of where cost accrued)."""
    per_trade = {e.trade_id: e.cost for e in engine.log.of_type(TradeEvent) if e.cost}
    return {"total_cost": sum(per_trade.values()), "per_trade": per_trade}
