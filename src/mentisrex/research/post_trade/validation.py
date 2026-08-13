"""Validation (AIDP M15).

Engine-invariant checks (the safety net for the audit trail) and single-input
validation. Deterministic, pure.
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.post_trade import monitoring
from mentisrex.research.post_trade.models import SettlementStatus


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    issues: list


def validate_engine(engine) -> ValidationResult:
    issues = []
    if not engine.cash_ledger.reconciles(engine.accounting.cash):
        issues.append("cash_ledger_break")
    if not monitoring.ledger_reconciles(engine):
        issues.append("ledger_break")

    seqs = [e.seq for e in engine.log.events]
    if seqs != sorted(seqs):
        issues.append("event_log_out_of_order")
    if len(set(seqs)) != len(seqs):
        issues.append("event_log_duplicate_seq")

    # every completed instruction must carry a settlement record
    for iid, inst in engine.settlement.instructions.items():
        if inst.status == SettlementStatus.COMPLETED and iid not in engine.settlement.records:
            issues.append(f"settled_without_record:{iid}")

    # M11 double-entry cash ledger must still reconcile
    if not engine.accounting.state.ledger.reconciles():
        issues.append("m11_ledger_break")
    return ValidationResult(ok=not issues, issues=issues)


def validate_fill(security_id: str, quantity: float, price: float) -> ValidationResult:
    issues = []
    if abs(quantity) < 1e-12:
        issues.append("zero_quantity")
    if price < 0:
        issues.append("negative_price")
    if not security_id:
        issues.append("missing_security")
    return ValidationResult(ok=not issues, issues=issues)


def check_determinism(run_fn, *, n: int = 2) -> bool:
    from mentisrex.research.post_trade.diagnostics import fingerprint
    return len({fingerprint(run_fn()) for _ in range(n)}) == 1
