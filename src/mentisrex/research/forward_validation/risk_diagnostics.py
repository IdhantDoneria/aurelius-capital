"""Risk diagnostics for forward validation (M24).

Analyzes M13 risk decisions recorded in M23 CycleRecords.
Does NOT re-implement M13 risk rules — reads decisions already made.
"""

from __future__ import annotations

import statistics
from collections import Counter

from mentisrex.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


def analyze_risk_decisions(cycles: list) -> dict:
    """Aggregate risk approval/rejection statistics from CycleRecords."""
    if not cycles:
        return {
            "n_cycles": 0,
            "n_approved": 0,
            "n_rejected": 0,
            "approval_rate": 0.0,
            "rejection_reasons": {},
            "issues": ["no cycle records"],
        }

    def _get(c, attr, default=None):
        if isinstance(c, dict):
            return c.get(attr, default)
        return getattr(c, attr, default)

    n = len(cycles)
    approved = sum(1 for c in cycles if _get(c, "risk_approved", True))
    rejected = n - approved
    approval_rate = approved / n if n > 0 else 0.0

    # aggregate rejection reasons
    reasons: Counter = Counter()
    for c in cycles:
        if not _get(c, "risk_approved", True):
            rd = _get(c, "risk_decision", "") or ""
            reasons[rd or "UNKNOWN"] += 1

    issues = []
    if approval_rate < 0.5:
        issues.append(f"risk rejection rate {1 - approval_rate:.1%} exceeds 50% — "
                      "check M13 limits vs universe/portfolio config")

    return {
        "n_cycles": n,
        "n_approved": approved,
        "n_rejected": rejected,
        "approval_rate": approval_rate,
        "rejection_reasons": dict(reasons),
        "issues": issues,
    }


def build_risk_diagnostics(
    cycles: list,
    *,
    expected_approval_rate: float = 1.0,
    rejection_threshold: float = 0.15,
) -> tuple[dict, list[DiagnosticRecord]]:
    """Produce risk diagnostics dict and DiagnosticRecords."""
    risk_summary = analyze_risk_decisions(cycles)
    records: list[DiagnosticRecord] = []
    n = risk_summary["n_cycles"]
    observed_rate = risk_summary["approval_rate"]

    diff = abs(observed_rate - expected_approval_rate)
    drifted = diff > rejection_threshold

    records.append(make_diagnostic(
        "risk.approval_rate",
        DiscrepancyCategory.RISK_DRIFT,
        DiagnosticSeverity.WARNING if drifted else DiagnosticSeverity.INFO,
        "risk_approval_rate",
        baseline=expected_approval_rate,
        observed=observed_rate,
        threshold=rejection_threshold,
        sample_size=n,
        method="absolute_threshold",
        evidence=(f"approval_rate={observed_rate:.3f} "
                  f"expected={expected_approval_rate:.3f}"),
        status=ValidationStatus.WARNING if drifted else ValidationStatus.VALID,
    ))

    # per-reason diagnostics for non-trivial rejection reasons
    for reason, count in risk_summary.get("rejection_reasons", {}).items():
        records.append(make_diagnostic(
            f"risk.rejection.{reason.lower()[:30]}",
            DiscrepancyCategory.RISK_DRIFT,
            DiagnosticSeverity.INFO,
            "rejection_reason_count",
            observed=float(count),
            sample_size=n,
            method="count",
            evidence=f"reason={reason!r} count={count}",
            status=ValidationStatus.VALID,
        ))

    return risk_summary, records
