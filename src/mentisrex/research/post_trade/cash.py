"""Cash management (AIDP M15).

A settlement-aware view over the reused M11 economic cash: splits it into settled
(available) vs pending (restricted), tracks obligations, and reconciles against M11.
No second cash accounting — every figure is derived from the `CashLedger` flow list,
which mirrors M11's economic cash flow for flow.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.post_trade.models import CashReport


def cash_report(engine, as_of: date | None = None) -> CashReport:
    cl = engine.cash_ledger
    return CashReport(
        as_of=as_of,
        economic_cash=cl.economic_balance(),
        settled_cash=cl.settled_balance(),
        available_cash=cl.available(),
        restricted_cash=cl.restricted(),
        pending_inflows=cl.pending_inflows(),
        pending_outflows=cl.pending_outflows(),
        reconciles=cl.reconciles(engine.accounting.cash))


def settlement_obligations(engine) -> dict:
    """Net cash owed (−) / due (+) per settlement date, from pending instructions."""
    out: dict = {}
    for inst in engine.settlement.pending():
        key = inst.settle_date
        out[key] = out.get(key, 0.0) + inst.cash_amount
    return out
