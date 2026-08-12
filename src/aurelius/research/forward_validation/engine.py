"""Forward Validation Engine (M24).

The main orchestrator: consumes M23 ForwardPerformanceRecord + M22
StrategySpecification + optional M9 ValidationReport and backtest results,
then produces a ForwardValidationArtifact and ForwardValidationReport.

Does NOT:
  - modify strategy parameters
  - automatically promote or retire strategies
  - change capital allocation
  - fetch market data from any external source
  - re-run backtests or create a second backtesting engine
  - re-implement M10/M11/M12/M13/M14 logic
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

from aurelius.research.forward_validation.comparison import (
    build_comparison,
    classify_discrepancies,
)
from aurelius.research.forward_validation.data_diagnostics import build_data_diagnostics
from aurelius.research.forward_validation.drift import (
    detect_metric_drift,
    detect_pit_violation,
    detect_snapshot_ordering,
)
from aurelius.research.forward_validation.execution_diagnostics import build_execution_diagnostics
from aurelius.research.forward_validation.lineage import build_lineage
from aurelius.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    EconomicStatus,
    ForwardValidationArtifact,
    OperationalStatus,
    SampleAdequacy,
    ValidationStatus,
    _fp,
    make_diagnostic,
    stamp_artifact,
)
from aurelius.research.forward_validation.portfolio_diagnostics import build_portfolio_diagnostics
from aurelius.research.forward_validation.report import assemble_report
from aurelius.research.forward_validation.risk_diagnostics import build_risk_diagnostics
from aurelius.research.forward_validation.signal_diagnostics import (
    analyze_signal_distribution,
    compare_signal_distributions,
)
from aurelius.research.forward_validation.statistics import (
    AnnualizedMetrics,
    bootstrap_mean_ci,
    compute_annualized,
    return_distribution_summary,
    rolling_sharpe,
    rolling_volatility,
    sample_adequacy,
)


@dataclass
class EngineConfig:
    periods_per_year: int = 252
    rolling_window: int = 20
    fill_rate_threshold: float = 0.10
    drift_threshold: float = 0.10
    rejection_threshold: float = 0.15
    expected_fill_rate: float = 1.0
    expected_approval_rate: float = 1.0
    bootstrap_samples: int = 200
    bootstrap_seed: int = 0


class ForwardValidationEngine:
    """M24 forward validation orchestrator.

    Produces ForwardValidationArtifact — the immutable, fingerprinted record
    of one forward-validation analysis run.

    IMPORTANT: This engine is observational only.
    It does NOT modify strategy parameters, promote strategies, retire strategies,
    change capital allocation, or make any automated deployment decisions.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self._config = config or EngineConfig()

    # ── main entry point ──────────────────────────────────────────────────────

    def analyze(
        self,
        forward_record,              # M23 ForwardPerformanceRecord
        spec,                        # M22 StrategySpecification
        *,
        validation_report: dict | None = None,    # M9 ValidationReport.to_dict()
        backtest_results: dict | None = None,      # caller-supplied backtest metrics
        snapshot_metadata: list[dict] | None = None,
        weight_history: list[dict] | None = None,
        signal_history: list[dict] | None = None,
        research_signal_stats: dict | None = None,
        deployment_manifest_fingerprint: str = "",
    ) -> ForwardValidationArtifact:
        """Produce a ForwardValidationArtifact from M23 forward records.

        Same inputs → same artifact_fingerprint (deterministic).
        Does NOT modify spec or forward_record.
        """
        cfg = self._config
        cycles = getattr(forward_record, "cycles", [])
        n = len(cycles)

        # ── 1. lineage ─────────────────────────────────────────────────────
        lineage_chain, lineage_records = build_lineage(
            spec, forward_record, validation_report,
            deployment_manifest_fingerprint=deployment_manifest_fingerprint,
        )

        # ── 2. cycle dates and data diagnostics ───────────────────────────
        cycle_dates = [
            (getattr(c, "as_of") if not isinstance(c, dict) else date.fromisoformat(str(c["as_of"])))
            for c in cycles
        ]
        rebalance_freq = getattr(spec, "rebalance_frequency", "daily") or "daily"
        data_diag, data_records = build_data_diagnostics(
            cycle_dates,
            expected_frequency=rebalance_freq,
            snapshot_metadata=snapshot_metadata,
        )

        # ── 3. snapshot ordering / PIT checks ─────────────────────────────
        timing_records: list[DiagnosticRecord] = []
        ordering_rec = detect_snapshot_ordering(cycle_dates)
        if ordering_rec:
            timing_records.append(ordering_rec)

        # ── 4. signal diagnostics ─────────────────────────────────────────
        fwd_signal_stats = analyze_signal_distribution(signal_history or [])
        signal_comparison, signal_records = compare_signal_distributions(
            research_signal_stats or {},
            fwd_signal_stats,
            sample_size=n,
        )
        # supplement with n_signals from cycles
        n_signals_from_cycles = sum(
            (getattr(c, "n_signals", 0) if not isinstance(c, dict) else c.get("n_signals", 0))
            for c in cycles
        )
        fwd_signal_stats["total_n_signals_from_cycles"] = n_signals_from_cycles

        # ── 5. execution diagnostics ──────────────────────────────────────
        slippage_bps = 0.0
        tca = getattr(spec, "transaction_cost_assumption", {}) or {}
        if isinstance(tca, dict):
            slippage_bps = float(tca.get("slippage_bps", 0.0))

        exec_diag, exec_records = build_execution_diagnostics(
            cycles,
            expected_fill_rate=cfg.expected_fill_rate,
            spec_slippage_bps=slippage_bps,
            fill_rate_threshold=cfg.fill_rate_threshold,
        )

        # ── 6. portfolio diagnostics ──────────────────────────────────────
        portfolio_diag, portfolio_records = build_portfolio_diagnostics(
            weight_history, cycles,
            drift_threshold=cfg.drift_threshold,
        )

        # ── 7. risk diagnostics ───────────────────────────────────────────
        risk_diag, risk_records = build_risk_diagnostics(
            cycles,
            expected_approval_rate=cfg.expected_approval_rate,
            rejection_threshold=cfg.rejection_threshold,
        )

        # ── 8. performance metrics ────────────────────────────────────────
        nav_series = getattr(forward_record, "nav_series", lambda: [])()
        ann = compute_annualized(nav_series, cfg.periods_per_year)
        daily_rets = getattr(forward_record, "daily_returns", lambda: [])()
        dist = return_distribution_summary(daily_rets)

        # rolling (only if enough data)
        rolling_vol = []
        rolling_sh = []
        if len(daily_rets) >= cfg.rolling_window:
            rolling_vol = rolling_volatility(daily_rets, cfg.rolling_window, cfg.periods_per_year)
            rolling_sh = rolling_sharpe(daily_rets, cfg.rolling_window, cfg.periods_per_year)

        # bootstrap CI for mean return
        ci_lo, ci_hi = (0.0, 0.0)
        if daily_rets:
            ci_lo, ci_hi = bootstrap_mean_ci(
                daily_rets,
                n_samples=cfg.bootstrap_samples,
                seed=cfg.bootstrap_seed,
            )

        fwd_metrics = getattr(forward_record, "metrics", lambda: None)()
        perf_diag = {
            "n_cycles": n,
            "total_return": ann.annualized_return,   # annualized
            "paper_total_return": fwd_metrics.total_return if fwd_metrics else 0.0,
            "volatility": ann.volatility,
            "sharpe": ann.sharpe,
            "sortino": ann.sortino,
            "max_drawdown": ann.max_drawdown,
            "fill_rate": fwd_metrics.fill_rate if fwd_metrics else 0.0,
            "risk_approval_rate": fwd_metrics.risk_approval_rate if fwd_metrics else 0.0,
            "total_orders": fwd_metrics.total_orders if fwd_metrics else 0,
            "total_fills": fwd_metrics.total_fills if fwd_metrics else 0,
            "avg_daily_return": fwd_metrics.avg_daily_return if fwd_metrics else 0.0,
            "return_distribution": dist,
            "rolling_volatility": rolling_vol,
            "rolling_sharpe": rolling_sh,
            "bootstrap_ci_mean_return": [ci_lo, ci_hi],
            "annualized_metrics_reliable": ann.reliable,
        }

        # ── 9. backtest comparison ────────────────────────────────────────
        adequacy_str = sample_adequacy(n)
        forward_metric_dict = {
            "total_return": fwd_metrics.total_return if fwd_metrics else 0.0,
            "max_drawdown": ann.max_drawdown,
            "sharpe": ann.sharpe,
            "volatility": ann.volatility,
            "fill_rate": fwd_metrics.fill_rate if fwd_metrics else 0.0,
            "n_cycles": n,
        }
        comparison_diag, comparison_records = build_comparison(
            backtest_results or {},
            forward_metric_dict,
            sample_adequacy=adequacy_str.value,
        )

        # ── 10. drift detection ───────────────────────────────────────────
        drift_records: list[DiagnosticRecord] = []
        if backtest_results:
            for metric in ("sharpe", "volatility", "max_drawdown"):
                b_val = backtest_results.get(metric)
                f_val = forward_metric_dict.get(metric)
                if b_val is not None and f_val is not None:
                    drift_records.append(detect_metric_drift(
                        metric,
                        DiscrepancyCategory.SIGNAL_DRIFT if metric == "sharpe"
                        else DiscrepancyCategory.PORTFOLIO_DRIFT,
                        b_val, f_val,
                        relative_threshold=0.30,
                        sample_size=n,
                    ))

        drift_diag = {
            "n_drift_records": len(drift_records),
            "has_drift": any(
                r.severity in ("WARNING", "ERROR", "CRITICAL")
                for r in drift_records
            ),
        }

        # ── 11. aggregate all records ─────────────────────────────────────
        all_records: list[DiagnosticRecord] = (
            lineage_records
            + data_records
            + timing_records
            + signal_records
            + exec_records
            + portfolio_records
            + risk_records
            + comparison_records
            + drift_records
        )

        # ── 12. determine status ──────────────────────────────────────────
        has_critical = any(r.severity == "CRITICAL" for r in all_records)
        has_error = any(r.severity == "ERROR" for r in all_records)
        has_warning = any(r.severity == "WARNING" for r in all_records)

        warnings = [r.evidence for r in all_records if r.severity == "WARNING"]
        failures = [r.evidence for r in all_records if r.severity in ("ERROR", "CRITICAL")]

        if n < 20:
            status = "INSUFFICIENT_DATA"
        elif has_critical:
            status = "INVALID"
        elif has_error:
            status = "FAILED"
        elif drift_diag["has_drift"] and backtest_results:
            status = "DIVERGENT"
        elif has_warning:
            status = "WARNING"
        else:
            status = "VALID"

        # operational status
        if has_critical or has_error:
            op_status = "OPERATIONALLY_INVALID"
        elif n < 20:
            op_status = "OPERATIONALLY_INCONCLUSIVE"
        else:
            op_status = "OPERATIONALLY_VALID"

        # economic status
        econ_status = (
            "ECONOMICALLY_CONCLUSIVE"
            if adequacy_str.value in ("MEANINGFUL", "EXTENDED") and ann.reliable
            else "ECONOMICALLY_INCONCLUSIVE"
        )

        # ── 13. discrepancy classification ────────────────────────────────
        discrepancies = classify_discrepancies(
            data_diag, fwd_signal_stats, exec_diag,
            portfolio_diag, risk_diag, comparison_diag, all_records,
        )

        # ── 14. analysis period ───────────────────────────────────────────
        analysis_period = {
            "start": str(cycle_dates[0]) if cycle_dates else "",
            "end": str(cycle_dates[-1]) if cycle_dates else "",
            "n_cycles": n,
        }

        # ── 15. artifact fingerprint payload ─────────────────────────────
        artifact_id = _fp({
            "strategy_id": lineage_chain.strategy_id,
            "strategy_version": lineage_chain.strategy_version,
            "strategy_fingerprint": lineage_chain.strategy_fingerprint,
            "forward_record_fingerprint": lineage_chain.forward_record_fingerprint,
            "n_cycles": n,
        })

        metric_results = {
            "performance": perf_diag,
            "backtest_comparison": comparison_diag,
            "drift": drift_diag,
            "statistical": {
                "return_distribution": dist,
                "bootstrap_ci_mean_return": [ci_lo, ci_hi],
                "rolling_sharpe_available": len(rolling_sh) > 0,
                "rolling_volatility_available": len(rolling_vol) > 0,
            },
            "data": data_diag,
            "signal": {**fwd_signal_stats, "comparison": signal_comparison},
            "execution": exec_diag,
            "portfolio": portfolio_diag,
            "risk": risk_diag,
            "lineage": lineage_chain.to_dict(),
            "discrepancies": discrepancies,
        }

        artifact = ForwardValidationArtifact(
            artifact_id=artifact_id,
            strategy_id=lineage_chain.strategy_id,
            strategy_version=lineage_chain.strategy_version,
            strategy_fingerprint=lineage_chain.strategy_fingerprint,
            deployment_manifest_fingerprint=deployment_manifest_fingerprint,
            forward_record_fingerprint=lineage_chain.forward_record_fingerprint,
            research_artifact_id=lineage_chain.research_artifact_id,
            validation_artifact_id=lineage_chain.validation_artifact_id,
            analysis_period=analysis_period,
            data_sources=[cfg_mode for cfg_mode in ["SIMULATION"]],  # informational
            data_fingerprints={"cycle_records": lineage_chain.forward_record_fingerprint},
            comparison_configuration={"backtest_provided": bool(backtest_results)},
            diagnostic_configuration={
                "periods_per_year": cfg.periods_per_year,
                "rolling_window": cfg.rolling_window,
                "drift_threshold": cfg.drift_threshold,
                "fill_rate_threshold": cfg.fill_rate_threshold,
            },
            metric_results=metric_results,
            diagnostic_results=[r.to_dict() for r in all_records],
            warnings=warnings,
            failures=failures,
            status=status,
            operational_status=op_status,
            economic_status=econ_status,
            sample_adequacy=adequacy_str.value,
        )

        return stamp_artifact(artifact)

    # ── report convenience method ─────────────────────────────────────────────

    def report(self, artifact: ForwardValidationArtifact):
        """Assemble a ForwardValidationReport from a stamped artifact."""
        return assemble_report(artifact)
