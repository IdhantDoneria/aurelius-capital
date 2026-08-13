"""Post-trade reconciliation (AIDP M15).

Cross-checks the internal book of record against upstream/broker truth across five
faces: execution records, portfolio state, broker state, settlement records, cash
records. Detects missing/duplicate/incorrect trades, cash mismatch, unsettled
positions, and failed settlements. Every finding is an auditable difference dict.

Reuses the M11/M12 truth where possible — this layer only diffs; it never re-accounts.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.post_trade.models import ReconciliationReport, SettlementStatus


def _diff(category, security_id, internal, external, severity="warning") -> dict:
    return {"category": category, "security_id": security_id, "internal": internal,
            "external": external, "delta": internal - external, "severity": severity}


def reconcile(engine, *, broker_account=None, execution_fills=None, as_of: date | None = None,
              cash_tol: float = 1e-6, qty_tol: float = 1e-6) -> ReconciliationReport:
    diffs: list = []

    # ── cash: post-trade ledger vs M11 economic cash ──
    econ_ledger = engine.cash_ledger.economic_balance()
    econ_m11 = engine.accounting.cash
    if abs(econ_ledger - econ_m11) > cash_tol:
        diffs.append(_diff("cash_mismatch", None, econ_ledger, econ_m11, "critical"))

    # ── positions: M11 book vs broker account ──
    holdings = engine.accounting.state.holdings
    if broker_account is not None:
        ext = broker_account.positions
        for sid in sorted(set(holdings) | set(ext)):
            iq = holdings[sid].shares if sid in holdings else 0.0
            eq = ext[sid].quantity if sid in ext else 0.0
            if abs(iq - eq) > qty_tol:
                cat = ("missing_trade" if eq == 0 else "unsettled_position" if iq == 0
                       else "incorrect_quantity")
                diffs.append(_diff(cat, sid, iq, eq, "critical"))
        if abs(broker_account.cash - econ_m11) > max(cash_tol, 1.0):
            diffs.append(_diff("cash_mismatch", None, econ_m11, broker_account.cash, "warning"))

    # ── execution: booked trades vs execution fill record (missing/duplicate) ──
    if execution_fills is not None:
        booked = {e.source_fill_id for e in engine.trade_ledger.events if e.source_fill_id}
        exec_ids = {getattr(f, "fill_id", None) for f in execution_fills}
        exec_ids.discard(None)
        for _fid in sorted(exec_ids - booked):
            diffs.append(_diff("missing_trade", None, 0.0, 1.0, "critical"))
        seen, dupes = set(), []
        for e in engine.trade_ledger.events:
            if e.source_fill_id and e.source_fill_id in seen:
                dupes.append(e.source_fill_id)
            seen.add(e.source_fill_id)
        for _ in dupes:
            diffs.append(_diff("duplicate_trade", None, 1.0, 0.0, "critical"))

    # ── settlement failures ──
    for inst in engine.settlement.instructions.values():
        if inst.status == SettlementStatus.FAILED:
            diffs.append(_diff("failed_settlement", inst.security_id, inst.cash_amount, 0.0, "critical"))

    n_settled = sum(1 for i in engine.settlement.instructions.values()
                    if i.status == SettlementStatus.COMPLETED)
    categories: dict = {}
    for d in diffs:
        categories[d["category"]] = categories.get(d["category"], 0) + 1
    return ReconciliationReport(
        as_of=as_of, ok=not diffs, differences=diffs, n_trades=engine.trade_ledger.n_trades,
        n_settled=n_settled, cash_diff=econ_ledger - econ_m11, categories=categories)
