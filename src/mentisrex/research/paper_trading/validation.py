"""Validation integration (AIDP M12).

Three reports, all built by *reusing* prior milestones:

* StateConsistencyReport  — M11 ledger reconciliation + M12 reconciliation status
                            + worst drift. Native accounting/consistency layer.
* M9 ValidationReport     — the realized paper track record is adapted into a
                            certified PerformanceMetrics (reusing M11's
                            `to_performance_metrics`) and passed to the M9
                            ResearchValidator. No metric math re-implemented.
* DeploymentReadinessReport — combines the two: deployable only if statistically
                            sound (M9) AND internally/externally consistent (M12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from mentisrex.research.paper_trading.models import (
    DeploymentReadinessReport,
    PaperTradingValidationResult,
    StateConsistencyReport,
)
from mentisrex.research.simulation.performance import build_summary
from mentisrex.research.simulation.validation import to_performance_metrics


@dataclass(frozen=True)
class _PerfInput:
    """Minimal shim exposing exactly what M11 `to_performance_metrics` reads."""
    equity_curve: list
    trades: list
    summary: object


def state_consistency(session) -> StateConsistencyReport:
    issues = []
    ledger_ok = session.book.state.ledger.reconciles()
    if not ledger_ok:
        issues.append("internal ledger does not reconcile")
    last = session.reconciliations[-1] if session.reconciliations else None
    rec_ok = bool(last and last.ok)
    unreconciled = [r for r in session.reconciliations if not r.ok]
    if unreconciled:
        issues.append(f"{len(unreconciled)}/{len(session.reconciliations)} ticks had breaks")
    max_drift = max((d.max_weight_drift for d in session.drifts), default=0.0)
    ok = ledger_ok and not unreconciled
    return StateConsistencyReport(ok=ok, ledger_reconciles=ledger_ok,
                                  reconciliation_ok=rec_ok, max_drift=max_drift, issues=issues)


def deployment_readiness(m9_verdict: str, m9_score: float,
                         consistency: StateConsistencyReport) -> DeploymentReadinessReport:
    checks = {
        "statistically_sound": m9_verdict in ("PASS", "PASS_WITH_WARNINGS"),
        "state_consistent": consistency.ok,
        "ledger_reconciles": consistency.ledger_reconciles,
    }
    reasons = [k for k, v in checks.items() if not v]
    ready = all(checks.values())
    return DeploymentReadinessReport(
        ready=ready, verdict=m9_verdict, score=m9_score,
        reasons=reasons or ["all checks passed"], checks=checks)


def validate_session(session, *, validator=None, experiment=None) -> PaperTradingValidationResult:
    """Full M12 validation. `validator`: an M9 ResearchValidator (injected). If
    absent, the M9 layer is skipped and only state consistency is reported."""
    consistency = state_consistency(session)
    values = [e.value for e in session.equity_curve]
    n_years = max((session.equity_curve[-1].date - session.equity_curve[0].date).days / 365.25, 1e-9) \
        if len(session.equity_curve) > 1 else 1e-9
    summary = build_summary(values or [session.config.initial_capital], n_rebalances=len(session.trades),
                            annualized_turnover=0.0, avg_holding_days=0.0,
                            total_cost=session.total_cost, cost_drag_annualized=0.0,
                            periods=session.config.periods_per_year, n_years=n_years)

    m9_dict, verdict, score = {}, "SKIPPED", 0.0
    if validator is not None:
        pm = to_performance_metrics(_PerfInput(session.equity_curve, session.trades, summary))
        rep = validator.validate(experiment or _StubExp(), pm)
        verdict, score = rep.overall_verdict, rep.research_score
        m9_dict = {"verdict": verdict, "score": score,
                   "confidence": rep.confidence_score,
                   "recommendation": rep.deployment_recommendation,
                   "warnings": rep.warnings, "critical_failures": rep.critical_failures}

    deployment = deployment_readiness(verdict, score, consistency)
    ok = consistency.ok and (validator is None or deployment.ready)
    return PaperTradingValidationResult(ok=ok, validation=m9_dict, consistency=consistency,
                                        deployment=deployment, generated_at=datetime.now(UTC))


class _StubExp:
    experiment_id = "paper-session"
    name = "paper-session"
    metrics: dict = {}
    parameters: dict = {}
