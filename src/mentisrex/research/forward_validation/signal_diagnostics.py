"""Signal distribution diagnostics for forward validation (M24).

Compares research/backtest signal distributions against forward paper signals.
Does NOT re-run the strategy logic or re-evaluate any signals. Consumes
pre-computed signal_history provided by the caller.

signal_history format:
  list[{"as_of": date_str, "n_signals": int, "mean": float, "stdev": float,
        "min": float, "max": float, "long_count": int, "short_count": int}]

All of these are optional. Missing keys are handled gracefully.
"""

from __future__ import annotations

import statistics

from mentisrex.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


def _safe_mean(xs: list[float]) -> float:
    return statistics.mean(xs) if xs else 0.0


def _safe_stdev(xs: list[float]) -> float:
    return statistics.stdev(xs) if len(xs) >= 2 else 0.0


def analyze_signal_distribution(
    signal_history: list[dict],
) -> dict:
    """Aggregate forward signal statistics from per-cycle signal_history entries."""
    if not signal_history:
        return {"analyzed": False, "n_cycles": 0, "issues": ["no signal history provided"]}

    n_signals_per_cycle = [e.get("n_signals", 0) for e in signal_history]
    means = [e["mean"] for e in signal_history if "mean" in e]
    stdevs = [e["stdev"] for e in signal_history if "stdev" in e]
    long_counts = [e.get("long_count", 0) for e in signal_history]
    short_counts = [e.get("short_count", 0) for e in signal_history]

    return {
        "analyzed": True,
        "n_cycles": len(signal_history),
        "avg_n_signals": _safe_mean([float(x) for x in n_signals_per_cycle]),
        "signal_mean": _safe_mean(means),
        "signal_stdev": _safe_mean(stdevs),
        "signal_mean_stdev": _safe_stdev(means),  # stability of mean across cycles
        "avg_long_count": _safe_mean([float(x) for x in long_counts]),
        "avg_short_count": _safe_mean([float(x) for x in short_counts]),
        "zero_signal_cycles": sum(1 for x in n_signals_per_cycle if x == 0),
        "issues": [],
    }


def compare_signal_distributions(
    research_stats: dict,
    forward_stats: dict,
    *,
    sample_size: int = 0,
    mean_z_threshold: float = 2.0,
) -> tuple[dict, list[DiagnosticRecord]]:
    """Compare research vs forward signal distribution statistics.

    Returns (summary_dict, list_of_diagnostics).
    """
    records: list[DiagnosticRecord] = []

    if not forward_stats.get("analyzed", False):
        return {"compared": False, "reason": "no forward signal history"}, records

    if not research_stats:
        return {"compared": False, "reason": "no research signal statistics provided"}, records

    # mean comparison
    r_mean = research_stats.get("signal_mean", 0.0)
    f_mean = forward_stats.get("signal_mean", 0.0)
    pooled_sd = max(research_stats.get("signal_stdev", 0.0),
                    forward_stats.get("signal_stdev", 0.0), 1e-8)
    mean_z = abs(f_mean - r_mean) / pooled_sd if pooled_sd > 0 else 0.0
    mean_drifted = mean_z > mean_z_threshold

    records.append(make_diagnostic(
        "signal.distribution.mean",
        DiscrepancyCategory.SIGNAL_DRIFT,
        DiagnosticSeverity.WARNING if mean_drifted else DiagnosticSeverity.INFO,
        "signal_mean",
        baseline=r_mean,
        observed=f_mean,
        threshold=mean_z_threshold,
        sample_size=sample_size,
        method="z_score",
        evidence=f"z={mean_z:.3f} threshold={mean_z_threshold:.1f}",
        status=ValidationStatus.WARNING if mean_drifted else ValidationStatus.VALID,
    ))

    # signal count comparison
    r_avg_n = research_stats.get("avg_n_signals", 0.0)
    f_avg_n = forward_stats.get("avg_n_signals", 0.0)
    n_rel_diff = abs(f_avg_n - r_avg_n) / max(r_avg_n, 1.0)
    n_drifted = n_rel_diff > 0.20

    records.append(make_diagnostic(
        "signal.distribution.count",
        DiscrepancyCategory.SIGNAL_DRIFT,
        DiagnosticSeverity.WARNING if n_drifted else DiagnosticSeverity.INFO,
        "avg_n_signals",
        baseline=r_avg_n,
        observed=f_avg_n,
        threshold=0.20,
        sample_size=sample_size,
        method="relative_threshold",
        evidence=f"rel_diff={n_rel_diff:.3f}",
        status=ValidationStatus.WARNING if n_drifted else ValidationStatus.VALID,
    ))

    return {
        "compared": True,
        "research_mean": r_mean,
        "forward_mean": f_mean,
        "mean_z_score": mean_z,
        "mean_drift_detected": mean_drifted,
        "research_avg_n_signals": r_avg_n,
        "forward_avg_n_signals": f_avg_n,
        "n_signals_drift_detected": n_drifted,
    }, records


def check_signal_consistency(
    research_expected_signals: dict,
    forward_signals: dict,
    *,
    snapshot_fingerprint: str = "",
) -> DiagnosticRecord:
    """Implementation-consistency check: same spec + same snapshot → same signals.

    research_expected_signals and forward_signals are {security_id: float} dicts.
    Returns CRITICAL if any security shows a meaningful signal discrepancy.
    """
    if not research_expected_signals or not forward_signals:
        return make_diagnostic(
            "signal.consistency.check",
            DiscrepancyCategory.IMPLEMENTATION_DIVERGENCE,
            DiagnosticSeverity.INFO,
            "signal_consistency",
            sample_size=0,
            method="deterministic_comparison",
            evidence="insufficient data for consistency check",
            status=ValidationStatus.VALID,
        )

    mismatches = []
    for sid, expected in research_expected_signals.items():
        observed = forward_signals.get(sid)
        if observed is None:
            mismatches.append(f"{sid}: missing in forward")
        elif abs(observed - expected) > 1e-6:
            mismatches.append(f"{sid}: expected={expected:.6f} observed={observed:.6f}")

    if mismatches:
        return make_diagnostic(
            "signal.consistency.check",
            DiscrepancyCategory.IMPLEMENTATION_DIVERGENCE,
            DiagnosticSeverity.CRITICAL,
            "signal_consistency",
            sample_size=len(research_expected_signals),
            method="deterministic_comparison",
            evidence=f"divergence on {len(mismatches)} security(ies): {mismatches[:3]}",
            status=ValidationStatus.INVALID,
        )

    return make_diagnostic(
        "signal.consistency.check",
        DiscrepancyCategory.IMPLEMENTATION_DIVERGENCE,
        DiagnosticSeverity.INFO,
        "signal_consistency",
        sample_size=len(research_expected_signals),
        method="deterministic_comparison",
        evidence="all signals consistent with research implementation",
        status=ValidationStatus.VALID,
    )
