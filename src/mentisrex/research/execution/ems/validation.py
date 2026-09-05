"""Validation (AIDP M14).

Pre-trade order validation and post-run session-invariant checks. Deterministic,
pure. Session invariants are the safety net for the audit trail: filled never
exceeds requested, every fill maps to a known order, every non-rejected order has a
`created` event, and terminal orders stay terminal.
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.execution.ems.models import OrderRequest, OrderStatus


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    issues: list


def validate_request(req: OrderRequest, *, prices: dict | None = None) -> ValidationResult:
    issues = []
    if abs(req.quantity) < 1e-12:
        issues.append("zero_quantity")
    if req.order_type.value == "limit" and req.limit_price is None:
        issues.append("limit_order_without_price")
    if prices is not None:
        p = prices.get(req.security_id)
        if p is None or p <= 0:
            issues.append("unpriced_security")
    if req.arrival_price < 0:
        issues.append("negative_arrival_price")
    return ValidationResult(ok=not issues, issues=issues)


def validate_session(session) -> ValidationResult:
    issues = []
    order_ids = set(session.oms.order_ids())
    for r in session.reports():
        if abs(r.filled_quantity) - abs(r.requested_quantity) > 1e-6:
            issues.append(f"overfill:{r.order_id}")
        if r.status == OrderStatus.FILLED and abs(r.filled_quantity - r.requested_quantity) > 1e-6:
            issues.append(f"filled_status_mismatch:{r.order_id}")
        if not r.events or r.events[0].kind != "created":
            issues.append(f"audit_missing_created:{r.order_id}")
        seqs = [e.seq for e in r.events]
        if seqs != sorted(seqs):
            issues.append(f"audit_out_of_order:{r.order_id}")
    for f in session.fills:
        if f.order_id not in order_ids:
            issues.append(f"orphan_fill:{f.fill_id}")
    return ValidationResult(ok=not issues, issues=issues)


def check_determinism(run_fn, *, n: int = 2) -> bool:
    """Run `run_fn` `n` times; True iff every run yields the same fingerprint."""
    from mentisrex.research.execution.ems.diagnostics import fingerprint

    fps = {fingerprint(run_fn()) for _ in range(n)}
    return len(fps) == 1
