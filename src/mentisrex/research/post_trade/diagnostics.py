"""Diagnostics & fingerprint (AIDP M15).

Compact scalar summary + a stable content hash — the determinism anchor. Two runs of
identical inputs must produce the same fingerprint. Mirrors M12–M14.
"""

from __future__ import annotations

import hashlib

from mentisrex.research.post_trade.models import (
    CorporateActionEvent,
    SettlementStatus,
    TradeEvent,
)
from mentisrex.research.post_trade.performance import performance as _performance


def diagnostics(engine) -> dict:
    perf = _performance(engine)
    insts = engine.settlement.instructions.values()
    return {
        "n_events": len(engine.log),
        "n_trades": len(engine.log.of_type(TradeEvent)),
        "n_corporate_actions": len(engine.log.of_type(CorporateActionEvent)),
        "n_settlements_completed": sum(i.status == SettlementStatus.COMPLETED for i in insts),
        "n_settlements_pending": sum(i.status == SettlementStatus.PENDING for i in insts),
        "n_settlements_failed": sum(i.status == SettlementStatus.FAILED for i in insts),
        "n_positions": len(engine.accounting.state.holdings),
        "economic_cash": round(engine.cash_ledger.economic_balance(), 6),
        "settled_cash": round(engine.cash_ledger.settled_balance(), 6),
        "portfolio_value": round(engine.accounting.value(), 6),
        "realized_pnl": round(perf["realized_pnl"], 6),
        "unrealized_pnl": round(perf["unrealized_pnl"], 6),
        "dividend_impact": round(perf["dividend_impact"], 6),
        "corporate_action_impact": round(perf["corporate_action_impact"], 6),
    }


def fingerprint(engine) -> str:
    d = diagnostics(engine)
    payload = "|".join(f"{k}={d[k]}" for k in sorted(d))
    return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()
