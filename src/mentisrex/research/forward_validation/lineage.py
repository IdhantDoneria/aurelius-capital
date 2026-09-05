"""Forward validation lineage (M24).

Builds a lineage chain from research artifact to forward paper evidence.
Does NOT create a parallel research registry — reads from existing M22
StrategySpecification fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


@dataclass(frozen=True)
class LineageChain:
    """Immutable lineage record linking research to forward evidence."""

    research_artifact_id: str
    validation_artifact_id: str
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str
    deployment_manifest_fingerprint: str
    forward_record_fingerprint: str
    cycle_count: int
    lineage_fingerprint: str = ""

    def to_dict(self) -> dict:
        import dataclasses

        return dataclasses.asdict(self)


def build_lineage(
    spec,  # M22 StrategySpecification
    forward_record,  # M23 ForwardPerformanceRecord
    validation_report: dict | None,
    *,
    deployment_manifest_fingerprint: str = "",
) -> tuple[LineageChain, list[DiagnosticRecord]]:
    """Build lineage chain and detect any lineage mismatches.

    Returns (LineageChain, list_of_DiagnosticRecord).
    """
    from mentisrex.research.forward_validation.models import _fp

    records: list[DiagnosticRecord] = []

    strategy_id = getattr(spec, "strategy_id", "")
    strategy_version = getattr(spec, "version", "")
    strategy_fingerprint = (
        getattr(spec, "configuration_fingerprint", "") or getattr(spec, "fingerprint", lambda: "")()
    )
    research_artifact_id = getattr(spec, "research_artifact_id", "") or ""
    validation_artifact_id = getattr(spec, "validation_artifact_id", "") or ""

    # validate lineage consistency between spec and forward_record
    fr_sid = getattr(forward_record, "strategy_id", "")
    fr_ver = getattr(forward_record, "strategy_version", "")
    fr_fp = getattr(forward_record, "strategy_fingerprint", "")

    if fr_sid and fr_sid != strategy_id:
        records.append(
            make_diagnostic(
                "lineage.strategy_id_mismatch",
                DiscrepancyCategory.IMPLEMENTATION_DIVERGENCE,
                DiagnosticSeverity.CRITICAL,
                "strategy_id",
                sample_size=0,
                method="equality_check",
                evidence=(
                    f"spec.strategy_id={strategy_id!r} forward_record.strategy_id={fr_sid!r}"
                ),
                status=ValidationStatus.INVALID,
            )
        )

    if fr_ver and fr_ver != strategy_version:
        records.append(
            make_diagnostic(
                "lineage.version_mismatch",
                DiscrepancyCategory.IMPLEMENTATION_DIVERGENCE,
                DiagnosticSeverity.ERROR,
                "strategy_version",
                sample_size=0,
                method="equality_check",
                evidence=(
                    f"spec.version={strategy_version!r} forward_record.strategy_version={fr_ver!r}"
                ),
                status=ValidationStatus.FAILED,
            )
        )

    if fr_fp and strategy_fingerprint and fr_fp != strategy_fingerprint:
        records.append(
            make_diagnostic(
                "lineage.fingerprint_mismatch",
                DiscrepancyCategory.IMPLEMENTATION_DIVERGENCE,
                DiagnosticSeverity.ERROR,
                "strategy_fingerprint",
                sample_size=0,
                method="fingerprint_comparison",
                evidence=(
                    f"spec fingerprint={strategy_fingerprint[:16]!r} "
                    f"forward_record fingerprint={fr_fp[:16]!r}"
                ),
                status=ValidationStatus.FAILED,
            )
        )

    # validation report linkage check
    if validation_report and validation_artifact_id:
        vr_hash = validation_report.get("manifest_hash", "")
        if vr_hash and vr_hash != validation_artifact_id:
            records.append(
                make_diagnostic(
                    "lineage.validation_artifact_mismatch",
                    DiscrepancyCategory.IMPLEMENTATION_DIVERGENCE,
                    DiagnosticSeverity.WARNING,
                    "validation_artifact_id",
                    sample_size=0,
                    method="fingerprint_comparison",
                    evidence=(
                        f"spec.validation_artifact_id={validation_artifact_id[:16]!r} "
                        f"validation_report.manifest_hash={vr_hash[:16]!r}"
                    ),
                    status=ValidationStatus.WARNING,
                )
            )

    # forward_record fingerprint
    cycles = getattr(forward_record, "cycles", [])
    fwd_fp_payload = {
        "strategy_id": fr_sid or strategy_id,
        "strategy_version": fr_ver or strategy_version,
        "n_cycles": len(cycles),
        "cycle_ids": [getattr(c, "cycle_id", "") for c in cycles],
    }
    fwd_fp = _fp(fwd_fp_payload)

    lineage_payload = {
        "research_artifact_id": research_artifact_id,
        "validation_artifact_id": validation_artifact_id,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "strategy_fingerprint": strategy_fingerprint,
        "forward_record_fingerprint": fwd_fp,
    }

    chain = LineageChain(
        research_artifact_id=research_artifact_id,
        validation_artifact_id=validation_artifact_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        strategy_fingerprint=strategy_fingerprint,
        deployment_manifest_fingerprint=deployment_manifest_fingerprint,
        forward_record_fingerprint=fwd_fp,
        cycle_count=len(cycles),
        lineage_fingerprint=_fp(lineage_payload),
    )
    return chain, records
