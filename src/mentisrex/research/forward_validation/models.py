"""M24 forward validation — immutable domain models.

All core objects are frozen dataclasses fingerprinted with blake2b (same as M7/M22/M23).
Timestamps are excluded from fingerprint payloads so fingerprints are deterministic.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── helpers ────────────────────────────────────────────────────────────────────

def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _fp(obj: Any) -> str:
    return hashlib.blake2b(_canonical(obj).encode(), digest_size=16).hexdigest()


# ── classification enumerations ────────────────────────────────────────────────

class ValidationStatus(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    IN_PROGRESS = "IN_PROGRESS"
    VALID = "VALID"
    WARNING = "WARNING"
    DIVERGENT = "DIVERGENT"
    FAILED = "FAILED"
    INVALID = "INVALID"


class OperationalStatus(str, Enum):
    OPERATIONALLY_VALID = "OPERATIONALLY_VALID"
    OPERATIONALLY_INVALID = "OPERATIONALLY_INVALID"
    OPERATIONALLY_INCONCLUSIVE = "OPERATIONALLY_INCONCLUSIVE"


class EconomicStatus(str, Enum):
    ECONOMICALLY_CONCLUSIVE = "ECONOMICALLY_CONCLUSIVE"
    ECONOMICALLY_INCONCLUSIVE = "ECONOMICALLY_INCONCLUSIVE"


class SampleAdequacy(str, Enum):
    INSUFFICIENT = "INSUFFICIENT"    # < 20 observations
    PRELIMINARY = "PRELIMINARY"      # 20–62 (~1 month daily)
    MEANINGFUL = "MEANINGFUL"        # 63–251
    EXTENDED = "EXTENDED"            # ≥ 252 (≈ 1 year daily)


class DiscrepancyCategory(str, Enum):
    DATA_DRIFT = "DATA_DRIFT"
    SIGNAL_DRIFT = "SIGNAL_DRIFT"
    UNIVERSE_DRIFT = "UNIVERSE_DRIFT"
    PORTFOLIO_DRIFT = "PORTFOLIO_DRIFT"
    EXECUTION_DRIFT = "EXECUTION_DRIFT"
    COST_DRIFT = "COST_DRIFT"
    RISK_DRIFT = "RISK_DRIFT"
    ACCOUNTING_DRIFT = "ACCOUNTING_DRIFT"
    TIMING_DRIFT = "TIMING_DRIFT"
    IMPLEMENTATION_DIVERGENCE = "IMPLEMENTATION_DIVERGENCE"
    STATISTICAL_NOISE = "STATISTICAL_NOISE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    UNKNOWN = "UNKNOWN"


class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ── diagnostic record ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DiagnosticRecord:
    """Machine-readable single diagnostic finding."""
    diagnostic_id: str
    category: str               # DiscrepancyCategory value
    severity: str               # DiagnosticSeverity value
    metric: str
    baseline: float | None      # research/expected value
    observed: float | None      # forward/paper value
    difference: float | None    # observed - baseline
    threshold: float | None
    sample_size: int
    method: str
    evidence: str
    status: str                 # ValidationStatus value
    fingerprint: str = ""

    def to_dict(self) -> dict:
        return {
            "diagnostic_id": self.diagnostic_id,
            "category": self.category,
            "severity": self.severity,
            "metric": self.metric,
            "baseline": self.baseline,
            "observed": self.observed,
            "difference": self.difference,
            "threshold": self.threshold,
            "sample_size": self.sample_size,
            "method": self.method,
            "evidence": self.evidence,
            "status": self.status,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DiagnosticRecord:
        return cls(**{k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(cls)}})


def _ev(x: Any) -> str:
    """Extract plain string from enum member or return str(x).

    Use .value for Enum types to avoid Python 3.12's 'ClassName.MEMBER' repr.
    """
    return x.value if hasattr(x, "value") else str(x)


def make_diagnostic(
    diagnostic_id: str,
    category: DiscrepancyCategory | str,
    severity: DiagnosticSeverity | str,
    metric: str,
    *,
    baseline: float | None = None,
    observed: float | None = None,
    threshold: float | None = None,
    sample_size: int = 0,
    method: str = "threshold",
    evidence: str = "",
    status: ValidationStatus | str = ValidationStatus.VALID,
) -> DiagnosticRecord:
    difference = (observed - baseline) if (observed is not None and baseline is not None) else None
    payload = {
        "diagnostic_id": diagnostic_id,
        "metric": metric,
        "baseline": baseline,
        "observed": observed,
        "difference": difference,
    }
    return DiagnosticRecord(
        diagnostic_id=diagnostic_id,
        category=_ev(category),
        severity=_ev(severity),
        metric=metric,
        baseline=baseline,
        observed=observed,
        difference=difference,
        threshold=threshold,
        sample_size=sample_size,
        method=method,
        evidence=evidence,
        status=_ev(status),
        fingerprint=_fp(payload),
    )


# ── forward validation artifact ───────────────────────────────────────────────

@dataclass(frozen=True)
class ForwardValidationArtifact:
    """Immutable, deterministically fingerprinted forward-validation artifact (M24).

    Consumable by research pipelines, audit systems, and the M24 report layer.
    Fingerprint excludes recorded_at so the same analysis inputs always produce
    the same fingerprint.
    """
    artifact_id: str
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str
    deployment_manifest_fingerprint: str
    forward_record_fingerprint: str
    research_artifact_id: str
    validation_artifact_id: str
    analysis_period: dict        # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "n_cycles": N}
    data_sources: list           # list[str] — mode labels
    data_fingerprints: dict      # {source: fingerprint}
    comparison_configuration: dict
    diagnostic_configuration: dict
    metric_results: dict
    diagnostic_results: list     # list[DiagnosticRecord.to_dict()]
    warnings: list               # list[str]
    failures: list               # list[str]
    status: str                  # ValidationStatus
    operational_status: str      # OperationalStatus
    economic_status: str         # EconomicStatus
    sample_adequacy: str         # SampleAdequacy
    artifact_fingerprint: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ForwardValidationArtifact:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def verify_fingerprint(self) -> bool:
        """Return True if artifact_fingerprint matches current content."""
        payload = _fingerprint_payload(self)
        return self.artifact_fingerprint == _fp(payload)


def _fingerprint_payload(artifact: ForwardValidationArtifact) -> dict:
    """Deterministic payload for fingerprinting — excludes artifact_fingerprint itself."""
    return {
        "artifact_id": artifact.artifact_id,
        "strategy_id": artifact.strategy_id,
        "strategy_version": artifact.strategy_version,
        "strategy_fingerprint": artifact.strategy_fingerprint,
        "forward_record_fingerprint": artifact.forward_record_fingerprint,
        "analysis_period": artifact.analysis_period,
        "metric_results": artifact.metric_results,
        "status": artifact.status,
        "operational_status": artifact.operational_status,
        "economic_status": artifact.economic_status,
        "sample_adequacy": artifact.sample_adequacy,
        "diagnostic_results": artifact.diagnostic_results,
    }


def stamp_artifact(artifact: ForwardValidationArtifact) -> ForwardValidationArtifact:
    """Return new artifact with computed artifact_fingerprint."""
    payload = _fingerprint_payload(artifact)
    fp = _fp(payload)
    return dataclasses.replace(artifact, artifact_fingerprint=fp)


# ── forward validation report ─────────────────────────────────────────────────

@dataclass(frozen=True)
class ForwardValidationReport:
    """Human-and-machine-readable forward validation report (M24).

    Assembles all diagnostic sections into one structured object.
    Fingerprint is computed from the artifact_fingerprint so the report
    and artifact are linked.
    """
    strategy_id: str
    strategy_version: str
    research_artifact_id: str
    validation_artifact_id: str
    deployment_manifest_fingerprint: str
    analysis_period: dict
    sample_size: int
    sample_adequacy: str
    data_diagnostics: dict
    signal_diagnostics: dict
    portfolio_diagnostics: dict
    execution_diagnostics: dict
    risk_diagnostics: dict
    performance_diagnostics: dict
    backtest_comparison: dict
    drift_analysis: dict
    statistical_diagnostics: dict
    discrepancy_classification: list   # list[str] — DiscrepancyCategory values
    limitations: list                  # list[str]
    status: str
    operational_status: str
    economic_status: str
    fingerprint: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ForwardValidationReport:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
