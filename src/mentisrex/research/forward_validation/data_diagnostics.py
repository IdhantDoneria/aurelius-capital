"""Data quality diagnostics for forward validation (M24).

Analyzes the snapshot stream received by M23 for completeness, ordering,
staleness, and provenance integrity.

Does NOT re-implement M20 quality rules. Consumes M23 cycle metadata and
optional snapshot_metadata dicts provided by the caller.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


def analyze_snapshot_coverage(
    cycle_dates: list[date],
    *,
    expected_frequency: str = "daily",
) -> dict:
    """Check for gaps, duplicates, and out-of-order delivery in cycle dates.

    Returns a structured dict consumed by the engine and report modules.
    """
    n = len(cycle_dates)
    if n == 0:
        return {
            "snapshot_count": 0,
            "duplicate_count": 0,
            "gap_count": 0,
            "out_of_order_count": 0,
            "first_date": None,
            "last_date": None,
            "coverage_ratio": 0.0,
            "status": ValidationStatus.INSUFFICIENT_DATA.value,
            "issues": ["no snapshots observed"],
        }

    sorted_dates = sorted(cycle_dates)
    duplicates = n - len(set(cycle_dates))
    out_of_order = sum(
        1 for i in range(1, n) if cycle_dates[i] < cycle_dates[i - 1]
    )

    # gap detection: count calendar days between first and last and compare
    span_days = (sorted_dates[-1] - sorted_dates[0]).days + 1
    if expected_frequency == "daily":
        expected_n = span_days  # simplistic (ignores weekends/holidays)
        gaps = max(0, expected_n - n)
    elif expected_frequency == "weekly":
        expected_n = span_days // 7
        gaps = max(0, expected_n - n)
    else:
        gaps = 0
        expected_n = n

    coverage_ratio = n / max(expected_n, 1)
    issues = []
    if duplicates > 0:
        issues.append(f"{duplicates} duplicate snapshot(s) detected")
    if out_of_order > 0:
        issues.append(f"{out_of_order} out-of-order snapshot(s) detected")
    if gaps > 0 and expected_frequency in ("daily", "weekly"):
        issues.append(f"{gaps} expected snapshot(s) missing (approx)")

    status = ValidationStatus.VALID.value
    if out_of_order > 0:
        status = ValidationStatus.INVALID.value
    elif duplicates > 0 or gaps > expected_n * 0.10:
        status = ValidationStatus.WARNING.value

    return {
        "snapshot_count": n,
        "duplicate_count": duplicates,
        "gap_count": gaps,
        "out_of_order_count": out_of_order,
        "first_date": str(sorted_dates[0]) if sorted_dates else None,
        "last_date": str(sorted_dates[-1]) if sorted_dates else None,
        "coverage_ratio": coverage_ratio,
        "expected_n": expected_n,
        "status": status,
        "issues": issues,
    }


def analyze_snapshot_metadata(
    snapshot_metadata: list[dict],
) -> dict:
    """Analyze optional per-snapshot metadata for staleness, source changes, etc.

    snapshot_metadata entries may contain:
      {"as_of": date, "source": str, "stale": bool, "fields_missing": list}
    """
    if not snapshot_metadata:
        return {"analyzed": False, "issues": []}

    stale_count = sum(1 for m in snapshot_metadata if m.get("stale", False))
    missing_fields = sum(
        len(m.get("fields_missing", [])) for m in snapshot_metadata
    )
    sources = {m.get("source", "unknown") for m in snapshot_metadata}
    source_changes = len(sources) > 1

    issues = []
    if stale_count > 0:
        issues.append(f"{stale_count} stale snapshot(s)")
    if missing_fields > 0:
        issues.append(f"{missing_fields} missing field(s) across snapshots")
    if source_changes:
        issues.append(f"data source changed mid-run: {sorted(sources)}")

    return {
        "analyzed": True,
        "n_snapshots": len(snapshot_metadata),
        "stale_count": stale_count,
        "missing_fields_total": missing_fields,
        "sources_seen": sorted(sources),
        "source_change_detected": source_changes,
        "issues": issues,
    }


def build_data_diagnostics(
    cycle_dates: list[date],
    *,
    expected_frequency: str = "daily",
    snapshot_metadata: list[dict] | None = None,
) -> tuple[dict, list[DiagnosticRecord]]:
    """Produce data diagnostics dict and list of DiagnosticRecords."""
    coverage = analyze_snapshot_coverage(cycle_dates, expected_frequency=expected_frequency)
    meta = analyze_snapshot_metadata(snapshot_metadata or [])

    records: list[DiagnosticRecord] = []
    n = coverage["snapshot_count"]

    if coverage["out_of_order_count"] > 0:
        records.append(make_diagnostic(
            "data.ordering",
            DiscrepancyCategory.DATA_DRIFT,
            DiagnosticSeverity.ERROR,
            "snapshot_ordering",
            observed=float(coverage["out_of_order_count"]),
            threshold=0.0,
            sample_size=n,
            method="ordering_check",
            evidence=f"{coverage['out_of_order_count']} out-of-order delivery(ies)",
            status=ValidationStatus.INVALID,
        ))

    if coverage["duplicate_count"] > 0:
        records.append(make_diagnostic(
            "data.duplicates",
            DiscrepancyCategory.DATA_DRIFT,
            DiagnosticSeverity.WARNING,
            "duplicate_snapshots",
            observed=float(coverage["duplicate_count"]),
            threshold=0.0,
            sample_size=n,
            method="fingerprint_check",
            evidence=f"{coverage['duplicate_count']} duplicate snapshots (idempotency gate should handle these)",
            status=ValidationStatus.WARNING,
        ))

    if meta.get("stale_count", 0) > 0:
        records.append(make_diagnostic(
            "data.staleness",
            DiscrepancyCategory.DATA_DRIFT,
            DiagnosticSeverity.WARNING,
            "stale_snapshots",
            observed=float(meta["stale_count"]),
            threshold=0.0,
            sample_size=n,
            method="staleness_flag",
            evidence=f"{meta['stale_count']} stale snapshots in metadata",
            status=ValidationStatus.WARNING,
        ))

    if meta.get("source_change_detected", False):
        records.append(make_diagnostic(
            "data.source_change",
            DiscrepancyCategory.DATA_DRIFT,
            DiagnosticSeverity.WARNING,
            "data_source_provenance",
            observed=None,
            threshold=None,
            sample_size=n,
            method="provenance_check",
            evidence=f"sources changed mid-run: {meta.get('sources_seen', [])}",
            status=ValidationStatus.WARNING,
        ))

    result = {**coverage, "metadata_analysis": meta}
    return result, records
