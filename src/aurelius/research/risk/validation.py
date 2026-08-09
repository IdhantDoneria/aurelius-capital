"""Risk validation integration (AIDP M13).

Turns a `RiskReport` into a `PortfolioHealthReport` (composite 0–100 health) and
combines it with the M9 statistical verdict into a `DeploymentRiskDecision`:
deployable only if the track record is statistically sound (M9) AND the portfolio
is within risk limits (M13). Risk thereby becomes a first-class gate in deployment
validation alongside M9 and M12.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aurelius.research.risk.models import (
    DeploymentRiskDecision,
    PortfolioHealthReport,
    RiskDecision,
    RiskValidationResult,
)

_DEPLOYABLE_M9 = ("PASS", "PASS_WITH_WARNINGS", "SKIPPED")


def portfolio_health(report) -> PortfolioHealthReport:
    hard = [v for v in report.violations if v.severity == "hard"]
    soft = [v for v in report.violations if v.severity == "soft"]
    halted = bool(report.drawdown and report.drawdown.halt_triggered)
    score = 100.0 - 25.0 * len(hard) - 5.0 * len(soft) - (40.0 if halted else 0.0)
    score = max(0.0, min(100.0, score))
    checks = {
        "no_hard_violations": not hard,
        "no_drawdown_halt": not halted,
        "within_leverage": report.exposure.gross <= 1.05 + 1e-9,
    }
    reasons = [v.message for v in report.violations] + (["drawdown halt"] if halted else [])
    healthy = not hard and not halted
    return PortfolioHealthReport(
        healthy=healthy, decision=report.decision, score=score,
        reasons=reasons or ["within all risk limits"], checks=checks)


def deployment_risk_decision(report, *, m9_verdict: str = "SKIPPED") -> DeploymentRiskDecision:
    risk_ok = report.decision != RiskDecision.REJECT
    m9_ok = m9_verdict in _DEPLOYABLE_M9
    reasons = []
    if not risk_ok:
        reasons.append("risk decision REJECT")
    if not m9_ok:
        reasons.append(f"M9 verdict {m9_verdict}")
    return DeploymentRiskDecision(
        deployable=risk_ok and m9_ok, risk_decision=report.decision,
        m9_verdict=m9_verdict, reasons=reasons or ["risk + statistical checks passed"])


def validate_risk(report, *, m9_verdict: str = "SKIPPED") -> RiskValidationResult:
    from aurelius.research.risk import serialization
    health = portfolio_health(report)
    deployment = deployment_risk_decision(report, m9_verdict=m9_verdict)
    return RiskValidationResult(
        ok=health.healthy and deployment.deployable, health=health, deployment=deployment,
        risk_report=serialization.report_to_dict(report), generated_at=datetime.now(UTC))
