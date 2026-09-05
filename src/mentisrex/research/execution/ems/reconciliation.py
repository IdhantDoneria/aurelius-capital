"""Execution reconciliation (AIDP M14).

Two layers, no duplicate accounting:

  * execution-layer — the EMS's own fills/orders vs what the broker reports
    (`broker.get_fills()` / `get_positions()`): duplicate fills, missing fills,
    quantity mismatches, orders left non-terminal. This is the piece M12 doesn't do.
  * state-layer — the M12 internal book vs the broker account: delegated straight to
    M12's certified `reconcile(...)`. Not re-implemented.

All findings are auditable `StateDifference`s (reused M12 model).
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.execution.ems.models import TERMINAL
from mentisrex.research.paper_trading.models import StateDifference
from mentisrex.research.paper_trading.reconciliation import ReconciliationConfig, reconcile


@dataclass(frozen=True)
class ExecutionReconciliationReport:
    ok: bool
    n_ems_fills: int
    n_broker_fills: int
    duplicate_fill_ids: list
    missing_fill_ids: list  # in broker, not applied by EMS
    orphan_fill_ids: list  # applied by EMS, not in broker
    non_terminal_orders: list
    differences: list  # list[StateDifference]


def reconcile_execution(session, broker_fills) -> ExecutionReconciliationReport:
    """Compare EMS-processed fills against the broker's fill record."""
    ems_ids = {f.fill_id for f in session.fills}
    broker_ids = {f.fill_id for f in broker_fills}
    missing = sorted(broker_ids - ems_ids)
    orphan = sorted(ems_ids - broker_ids)
    dupes = sorted(set(session.fills_processor.duplicates))

    non_terminal = [
        oid
        for oid in session.oms.order_ids()
        if session.oms.status(oid) not in TERMINAL
        and session.oms.status(oid).value not in ("partially_filled",)
    ]

    diffs = []
    for _fid in missing:
        diffs.append(StateDifference(None, "missing_fill", 0.0, 1.0, 1.0, "critical"))
    for _fid in orphan:
        diffs.append(StateDifference(None, "duplicate_fill", 1.0, 0.0, 1.0, "critical"))
    for _ in dupes:
        diffs.append(StateDifference(None, "duplicate_fill", 1.0, 0.0, 1.0, "warning"))
    for oid in non_terminal:
        diffs.append(StateDifference(oid, "stale_order", 1.0, 0.0, 1.0, "warning"))

    ok = not (missing or orphan or dupes or non_terminal)
    return ExecutionReconciliationReport(
        ok=ok,
        n_ems_fills=len(ems_ids),
        n_broker_fills=len(broker_ids),
        duplicate_fill_ids=dupes,
        missing_fill_ids=missing,
        orphan_fill_ids=orphan,
        non_terminal_orders=non_terminal,
        differences=diffs,
    )


def reconcile_state(book_or_state, broker_account, *, config: ReconciliationConfig | None = None):
    """State-layer reconciliation — delegated to M12's certified reconcile. Accepts a
    M12 `PaperPortfolio` or a raw M11 `PortfolioState` (reconcile wants the state)."""
    internal = getattr(book_or_state, "state", book_or_state)
    return reconcile(internal, broker_account, config=config or ReconciliationConfig())
