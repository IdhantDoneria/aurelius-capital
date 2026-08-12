"""Portfolio diagnostics for forward validation (M24).

Compares target portfolio weights against actual paper portfolio weights.
Does NOT reimplement M10 portfolio construction or M11 accounting.
Consumes weight_history provided by the caller.

weight_history format:
  list[{"as_of": date_str, "target": {sid: weight}, "actual": {sid: weight},
        "cash": float, "gross_exposure": float}]
"""

from __future__ import annotations

import statistics

from aurelius.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


def _max_abs_weight_diff(target: dict, actual: dict) -> float:
    all_keys = set(target) | set(actual)
    if not all_keys:
        return 0.0
    return max(abs(actual.get(k, 0.0) - target.get(k, 0.0)) for k in all_keys)


def analyze_portfolio_drift(weight_history: list[dict]) -> dict:
    """Compute target-vs-actual weight drift statistics.

    Returns dict with per-cycle drift summary and aggregate statistics.
    """
    if not weight_history:
        return {
            "analyzed": False,
            "n_cycles": 0,
            "avg_max_weight_drift": 0.0,
            "max_weight_drift_ever": 0.0,
            "issues": ["no weight history provided"],
        }

    drifts = []
    for entry in weight_history:
        target = entry.get("target", {})
        actual = entry.get("actual", {})
        d = _max_abs_weight_diff(target, actual)
        drifts.append(d)

    avg_drift = statistics.mean(drifts) if drifts else 0.0
    max_drift = max(drifts) if drifts else 0.0

    issues = []
    if max_drift > 0.20:
        issues.append(f"max weight drift {max_drift:.1%} exceeds 20% threshold")
    elif avg_drift > 0.10:
        issues.append(f"avg weight drift {avg_drift:.1%} exceeds 10% threshold")

    return {
        "analyzed": True,
        "n_cycles": len(weight_history),
        "avg_max_weight_drift": avg_drift,
        "max_weight_drift_ever": max_drift,
        "issues": issues,
    }


def analyze_turnover(weight_history: list[dict]) -> dict:
    """Estimate portfolio turnover from weight_history (change in target weights)."""
    if len(weight_history) < 2:
        return {"n_rebalances": 0, "avg_turnover": 0.0, "max_turnover": 0.0}

    turnovers = []
    for i in range(1, len(weight_history)):
        prev = weight_history[i - 1].get("target", {})
        curr = weight_history[i].get("target", {})
        all_keys = set(prev) | set(curr)
        if not all_keys:
            turnovers.append(0.0)
            continue
        turnover = sum(abs(curr.get(k, 0.0) - prev.get(k, 0.0)) for k in all_keys) / 2
        turnovers.append(turnover)

    return {
        "n_rebalances": len(turnovers),
        "avg_turnover": statistics.mean(turnovers) if turnovers else 0.0,
        "max_turnover": max(turnovers) if turnovers else 0.0,
    }


def build_portfolio_diagnostics(
    weight_history: list[dict] | None,
    cycles: list,
    *,
    drift_threshold: float = 0.10,
) -> tuple[dict, list[DiagnosticRecord]]:
    """Produce portfolio diagnostics dict and DiagnosticRecords."""
    records: list[DiagnosticRecord] = []
    wh = weight_history or []

    drift_summary = analyze_portfolio_drift(wh)
    turnover_summary = analyze_turnover(wh)

    n = len(cycles)

    if drift_summary.get("analyzed"):
        avg_drift = drift_summary["avg_max_weight_drift"]
        max_drift = drift_summary["max_weight_drift_ever"]
        drifted = avg_drift > drift_threshold

        records.append(make_diagnostic(
            "portfolio.weight_drift",
            DiscrepancyCategory.PORTFOLIO_DRIFT,
            DiagnosticSeverity.WARNING if drifted else DiagnosticSeverity.INFO,
            "avg_max_weight_drift",
            observed=avg_drift,
            threshold=drift_threshold,
            sample_size=n,
            method="absolute_threshold",
            evidence=(f"avg_weight_drift={avg_drift:.3f} "
                      f"max_drift={max_drift:.3f} threshold={drift_threshold:.2f}"),
            status=ValidationStatus.WARNING if drifted else ValidationStatus.VALID,
        ))

    # position count from cycles
    position_counts = []
    for c in cycles:
        # estimate from n_signals if we don't have position data
        ns = c.get("n_signals") if isinstance(c, dict) else getattr(c, "n_signals", None)
        if ns is not None:
            position_counts.append(ns)

    result = {
        **drift_summary,
        "turnover": turnover_summary,
        "avg_position_count": (statistics.mean(position_counts) if position_counts else None),
    }
    return result, records
