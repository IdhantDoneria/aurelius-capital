"""Validation report quality / completeness check (AIDP M9).

Verifies a ValidationReport is well-formed and self-consistent before it's trusted
as the deployment gate.
"""

from __future__ import annotations

from mentisrex.research.validation.report import VERDICTS, ValidationReport


def check(report: ValidationReport) -> dict:
    issues: list[str] = []
    if report.overall_verdict not in VERDICTS:
        issues.append(f"invalid_verdict:{report.overall_verdict}")
    if not (0.0 <= report.confidence_score <= 100.0):
        issues.append("confidence_score_out_of_range")
    if report.overall_verdict == "REJECT" and not report.critical_failures:
        issues.append("reject_without_reason")
    if report.overall_verdict == "PASS" and report.critical_failures:
        issues.append("pass_with_critical_failures")
    if not report.manifest_hash:
        issues.append("missing_manifest_hash")
    if (
        report.component_scores
        and abs(sum(report.score_contributions.values()) - report.research_score) > 1e-6
    ):
        issues.append("contributions_do_not_sum_to_score")
    return {"ok": not issues, "issues": issues, "verdict": report.overall_verdict}
