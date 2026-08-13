"""Session diagnostics (AIDP M12).

A flat, deterministic dict summarising the internal book and the run — the M12
analogue of the M11 `SimulationResult.diagnostics`. Cheap health snapshot for
logging/artifacts; the authoritative checks live in `validation.py`.
"""

from __future__ import annotations


def diagnostics(session) -> dict:
    st = session.book.state
    recs = session.reconciliations
    return {
        "n_syncs": len(session.sync_events),
        "n_trades": len(session.trades),
        "ledger_reconciles": st.ledger.reconciles(),
        "final_cash": st.cash,
        "final_value": st.total_value(),
        "realized_pnl": st.realized_pnl_total,
        "unrealized_pnl": st.unrealized_pnl(),
        "total_cost": session.total_cost,
        "n_reconciled": sum(1 for r in recs if r.ok),
        "n_breaks": sum(1 for r in recs if not r.ok),
        "break_categories": _merge_categories(recs),
        "fingerprint": session.fingerprint(),
    }


def _merge_categories(recs) -> dict:
    out: dict = {}
    for r in recs:
        for k, v in r.categories.items():
            out[k] = out.get(k, 0) + v
    return out
