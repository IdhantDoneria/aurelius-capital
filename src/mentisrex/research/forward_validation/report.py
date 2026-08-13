"""Report assembly for forward validation (M24).

Assembles ForwardValidationReport from ForwardValidationArtifact.
Deterministic: same artifact → same report fingerprint.
"""

from __future__ import annotations

from mentisrex.research.forward_validation.models import (
    ForwardValidationArtifact,
    ForwardValidationReport,
    _fp,
)


def assemble_report(artifact: ForwardValidationArtifact) -> ForwardValidationReport:
    """Build a ForwardValidationReport from a stamped ForwardValidationArtifact."""
    # prefer pre-computed discrepancy list from engine (includes INSUFFICIENT_SAMPLE)
    stored = artifact.metric_results.get("discrepancies")
    if stored is not None:
        discrepancy_categories = stored
    else:
        discrepancy_categories = sorted({
            r.get("category", "")
            for r in artifact.diagnostic_results
            if r.get("severity") in ("WARNING", "ERROR", "CRITICAL")
            and r.get("category")
        })

    # limitations list — always include standard M24 limitations
    limitations = [
        "Corporate action replay through checkpoint is not serialized (M15 limitation).",
        "Partial-fill simulation uses SimulatedBroker fill_ratio without real ADV data.",
        "Intraday scheduling not supported (day-granular only).",
        "No live brokerage connectivity — paper trading only.",
        "Forward observations use M21 open/free data, not institutional feeds.",
        "Statistical metrics are unreliable for INSUFFICIENT or PRELIMINARY samples.",
        "M24 cannot claim alpha or profitability from short forward samples.",
    ]

    report_payload = {
        "strategy_id": artifact.strategy_id,
        "strategy_version": artifact.strategy_version,
        "forward_record_fingerprint": artifact.forward_record_fingerprint,
        "status": artifact.status,
        "artifact_fingerprint": artifact.artifact_fingerprint,
    }

    report = ForwardValidationReport(
        strategy_id=artifact.strategy_id,
        strategy_version=artifact.strategy_version,
        research_artifact_id=artifact.research_artifact_id,
        validation_artifact_id=artifact.validation_artifact_id,
        deployment_manifest_fingerprint=artifact.deployment_manifest_fingerprint,
        analysis_period=artifact.analysis_period,
        sample_size=artifact.analysis_period.get("n_cycles", 0),
        sample_adequacy=artifact.sample_adequacy,
        data_diagnostics=_extract_section(artifact, "data"),
        signal_diagnostics=_extract_section(artifact, "signal"),
        portfolio_diagnostics=_extract_section(artifact, "portfolio"),
        execution_diagnostics=_extract_section(artifact, "execution"),
        risk_diagnostics=_extract_section(artifact, "risk"),
        performance_diagnostics=artifact.metric_results.get("performance", {}),
        backtest_comparison=artifact.metric_results.get("backtest_comparison", {}),
        drift_analysis=artifact.metric_results.get("drift", {}),
        statistical_diagnostics=artifact.metric_results.get("statistical", {}),
        discrepancy_classification=discrepancy_categories,
        limitations=limitations,
        status=artifact.status,
        operational_status=artifact.operational_status,
        economic_status=artifact.economic_status,
        fingerprint=_fp(report_payload),
    )
    return report


def _extract_section(artifact: ForwardValidationArtifact, prefix: str) -> dict:
    """Extract diagnostic records for a category prefix into a summary dict."""
    matching = [
        r for r in artifact.diagnostic_results
        if r.get("category", "").startswith(prefix.upper())
        or r.get("diagnostic_id", "").startswith(prefix)
    ]
    return {
        "n_diagnostics": len(matching),
        "n_critical": sum(1 for r in matching if r.get("severity") == "CRITICAL"),
        "n_error": sum(1 for r in matching if r.get("severity") == "ERROR"),
        "n_warning": sum(1 for r in matching if r.get("severity") == "WARNING"),
        "records": matching,
        **artifact.metric_results.get(prefix, {}),
    }
