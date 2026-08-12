"""Drift detection for forward validation (M24).

Detects structural drift between research/backtest baselines and forward
paper-trading observations. Produces DiagnosticRecord objects.

Does NOT re-implement M12/M13 risk engines. Consumes metrics already
computed from CycleRecords and strategy specifications.
"""

from __future__ import annotations

import math
import statistics

from aurelius.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


# ── drift result ───────────────────────────────────────────────────────────────

class DriftResult:
    """Collection of drift diagnostics for one category."""

    def __init__(self, category: DiscrepancyCategory | str) -> None:
        self.category = str(category)
        self.records: list[DiagnosticRecord] = []

    def add(self, record: DiagnosticRecord) -> None:
        self.records.append(record)

    def has_critical(self) -> bool:
        return any(r.severity == DiagnosticSeverity.CRITICAL for r in self.records)

    def has_error(self) -> bool:
        return any(r.severity in (DiagnosticSeverity.ERROR,
                                  DiagnosticSeverity.CRITICAL) for r in self.records)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "n_diagnostics": len(self.records),
            "has_critical": self.has_critical(),
            "has_error": self.has_error(),
            "records": [r.to_dict() for r in self.records],
        }


# ── generic metric drift ───────────────────────────────────────────────────────

def detect_metric_drift(
    metric: str,
    category: DiscrepancyCategory | str,
    baseline: float,
    observed: float,
    *,
    relative_threshold: float = 0.20,   # 20% relative change
    absolute_threshold: float | None = None,
    sample_size: int = 0,
    method: str = "threshold",
) -> DiagnosticRecord:
    """Detect drift for a single numeric metric.

    Uses relative threshold by default; absolute_threshold overrides for
    metrics where relative comparison is ill-defined (e.g., Sharpe ≈ 0).
    """
    if baseline == 0.0:
        # avoid division by zero; use absolute difference instead
        diff = abs(observed - baseline)
        threshold = absolute_threshold if absolute_threshold is not None else 0.10
        drifted = diff > threshold
    else:
        rel_diff = abs((observed - baseline) / baseline)
        threshold = relative_threshold
        drifted = rel_diff > threshold

    severity = (DiagnosticSeverity.WARNING if drifted
                else DiagnosticSeverity.INFO)
    status = (ValidationStatus.WARNING if drifted
              else ValidationStatus.VALID)

    return make_diagnostic(
        diagnostic_id=f"drift.{category}.{metric}".replace(" ", "_").lower(),
        category=category,
        severity=severity,
        metric=metric,
        baseline=baseline,
        observed=observed,
        threshold=threshold,
        sample_size=sample_size,
        method=method,
        evidence=(f"baseline={baseline:.4f} observed={observed:.4f} "
                  f"threshold={threshold:.2%}"),
        status=status,
    )


# ── execution drift ────────────────────────────────────────────────────────────

def execution_drift(
    expected_fill_rate: float,
    observed_fill_rate: float,
    *,
    sample_size: int = 0,
    threshold: float = 0.10,   # 10% absolute fill-rate gap
) -> DiagnosticRecord:
    diff = abs(observed_fill_rate - expected_fill_rate)
    drifted = diff > threshold
    return make_diagnostic(
        diagnostic_id="drift.execution.fill_rate",
        category=DiscrepancyCategory.EXECUTION_DRIFT,
        severity=DiagnosticSeverity.WARNING if drifted else DiagnosticSeverity.INFO,
        metric="fill_rate",
        baseline=expected_fill_rate,
        observed=observed_fill_rate,
        threshold=threshold,
        sample_size=sample_size,
        method="absolute_threshold",
        evidence=(f"expected_fill_rate={expected_fill_rate:.3f} "
                  f"observed={observed_fill_rate:.3f} diff={diff:.3f}"),
        status=ValidationStatus.WARNING if drifted else ValidationStatus.VALID,
    )


# ── cost drift ────────────────────────────────────────────────────────────────

def cost_drift(
    planned_slippage_bps: float,
    observed_slippage_proxy: float,
    *,
    sample_size: int = 0,
    threshold_bps: float = 5.0,
) -> DiagnosticRecord:
    diff = abs(observed_slippage_proxy - planned_slippage_bps)
    drifted = diff > threshold_bps
    return make_diagnostic(
        diagnostic_id="drift.cost.slippage_bps",
        category=DiscrepancyCategory.COST_DRIFT,
        severity=DiagnosticSeverity.WARNING if drifted else DiagnosticSeverity.INFO,
        metric="slippage_bps",
        baseline=planned_slippage_bps,
        observed=observed_slippage_proxy,
        threshold=threshold_bps,
        sample_size=sample_size,
        method="absolute_bps",
        evidence=(f"planned={planned_slippage_bps:.1f}bps "
                  f"observed_proxy={observed_slippage_proxy:.1f}bps"),
        status=ValidationStatus.WARNING if drifted else ValidationStatus.VALID,
    )


# ── risk drift ────────────────────────────────────────────────────────────────

def risk_drift(
    expected_approval_rate: float,
    observed_approval_rate: float,
    *,
    sample_size: int = 0,
    threshold: float = 0.15,
) -> DiagnosticRecord:
    diff = abs(observed_approval_rate - expected_approval_rate)
    drifted = diff > threshold
    return make_diagnostic(
        diagnostic_id="drift.risk.approval_rate",
        category=DiscrepancyCategory.RISK_DRIFT,
        severity=DiagnosticSeverity.WARNING if drifted else DiagnosticSeverity.INFO,
        metric="risk_approval_rate",
        baseline=expected_approval_rate,
        observed=observed_approval_rate,
        threshold=threshold,
        sample_size=sample_size,
        method="absolute_threshold",
        evidence=(f"expected={expected_approval_rate:.3f} "
                  f"observed={observed_approval_rate:.3f}"),
        status=ValidationStatus.WARNING if drifted else ValidationStatus.VALID,
    )


# ── signal drift ──────────────────────────────────────────────────────────────

def signal_drift(
    baseline_mean: float,
    forward_mean: float,
    baseline_stdev: float,
    forward_stdev: float,
    *,
    sample_size: int = 0,
    z_threshold: float = 2.0,
) -> DriftResult:
    """Detect distributional shift in signal values using Z-score-like comparison.

    Compares means and volatilities of the signal distribution. Uses a
    threshold-based approach (not a formal hypothesis test) since signal
    data format is strategy-specific.
    """
    result = DriftResult(DiscrepancyCategory.SIGNAL_DRIFT)

    # mean shift
    pooled_sd = max(baseline_stdev, forward_stdev, 1e-8)
    mean_z = abs(forward_mean - baseline_mean) / pooled_sd if pooled_sd > 0 else 0.0
    mean_drifted = mean_z > z_threshold

    result.add(make_diagnostic(
        diagnostic_id="drift.signal.mean",
        category=DiscrepancyCategory.SIGNAL_DRIFT,
        severity=DiagnosticSeverity.WARNING if mean_drifted else DiagnosticSeverity.INFO,
        metric="signal_mean",
        baseline=baseline_mean,
        observed=forward_mean,
        threshold=z_threshold,
        sample_size=sample_size,
        method="z_score",
        evidence=f"z={mean_z:.2f} threshold={z_threshold:.1f}",
        status=ValidationStatus.WARNING if mean_drifted else ValidationStatus.VALID,
    ))

    # volatility ratio
    vol_ratio = (forward_stdev / baseline_stdev) if baseline_stdev > 0 else 1.0
    vol_drifted = vol_ratio > 2.0 or vol_ratio < 0.5

    result.add(make_diagnostic(
        diagnostic_id="drift.signal.volatility",
        category=DiscrepancyCategory.SIGNAL_DRIFT,
        severity=DiagnosticSeverity.WARNING if vol_drifted else DiagnosticSeverity.INFO,
        metric="signal_volatility_ratio",
        baseline=baseline_stdev,
        observed=forward_stdev,
        threshold=2.0,
        sample_size=sample_size,
        method="vol_ratio",
        evidence=f"vol_ratio={vol_ratio:.3f}",
        status=ValidationStatus.WARNING if vol_drifted else ValidationStatus.VALID,
    ))

    return result


# ── timing drift / PIT violation ─────────────────────────────────────────────

def detect_pit_violation(
    signal_date: object,
    snapshot_date: object,
    *,
    sample_size: int = 0,
) -> DiagnosticRecord | None:
    """Return a CRITICAL diagnostic if signal_date > snapshot_date (future data leak)."""
    try:
        if signal_date > snapshot_date:
            return make_diagnostic(
                diagnostic_id="pit.violation.signal_date",
                category=DiscrepancyCategory.TIMING_DRIFT,
                severity=DiagnosticSeverity.CRITICAL,
                metric="signal_vs_snapshot_date",
                baseline=None,
                observed=None,
                threshold=None,
                sample_size=sample_size,
                method="date_comparison",
                evidence=(f"signal_date={signal_date} > snapshot_date={snapshot_date} "
                          "— potential look-ahead bias"),
                status=ValidationStatus.INVALID,
            )
    except TypeError:
        pass
    return None


def detect_snapshot_ordering(dates: list) -> DiagnosticRecord | None:
    """Detect out-of-order snapshot delivery. Returns ERROR diagnostic if found."""
    for i in range(1, len(dates)):
        if dates[i] < dates[i - 1]:
            return make_diagnostic(
                diagnostic_id="pit.ordering.snapshot",
                category=DiscrepancyCategory.TIMING_DRIFT,
                severity=DiagnosticSeverity.ERROR,
                metric="snapshot_ordering",
                baseline=None,
                observed=None,
                threshold=None,
                sample_size=len(dates),
                method="ordering_check",
                evidence=(f"out-of-order snapshot at index {i}: "
                          f"{dates[i - 1]} followed by {dates[i]}"),
                status=ValidationStatus.INVALID,
            )
    return None
