"""Deployment readiness validator (AIDP M22).

Checks all preconditions before a strategy may be transitioned to DEPLOYABLE or PAPER.
Returns a machine-readable ReadinessReport — never silently approves an incomplete strategy.
"""

from __future__ import annotations

from datetime import datetime

from mentisrex.research.strategy_deployment.models import (
    ReadinessReport,
    StrategySpecification,
    StrategyType,
    _DEPLOYABLE_VERDICTS,
    _PAPER_VERDICTS,
)


_DEPLOYABLE_CHECKS = [
    "research_artifact_exists",
    "validation_artifact_exists",
    "validation_status_permits_deployment",
    "strategy_version_present",
    "configuration_fingerprint_present",
    "universe_definition_present",
    "portfolio_construction_config_present",
    "risk_config_present",
    "execution_config_present",
    "cost_assumptions_explicit",
    "base_currency_defined",
    "capital_assumption_positive",
    "rebalance_frequency_valid",
    "signal_definition_present",
    "feature_definition_present",
    "no_provider_access_flags",
    "strategy_type_consistent",
]

_VALID_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly"}


class ReadinessValidator:

    def validate(self, spec: StrategySpecification, *,
                 permit_experimental: bool = False) -> ReadinessReport:
        checks: dict[str, bool] = {}
        issues: list[str] = []
        warnings: list[str] = []

        is_experimental = spec.strategy_type == StrategyType.EXPERIMENTAL_PAPER
        required_verdicts = _PAPER_VERDICTS if is_experimental else _DEPLOYABLE_VERDICTS

        # ── research lineage ──────────────────────────────────────────────────
        checks["research_artifact_exists"] = bool(spec.research_artifact_id)
        if not checks["research_artifact_exists"]:
            issues.append("research_artifact_id is missing — no research lineage")

        checks["validation_artifact_exists"] = bool(spec.validation_artifact_id)
        if not checks["validation_artifact_exists"]:
            issues.append("validation_artifact_id is missing — no validation evidence")

        # ── validation gate ───────────────────────────────────────────────────
        checks["validation_status_permits_deployment"] = (
            spec.validation_status in required_verdicts
        )
        if not checks["validation_status_permits_deployment"]:
            issues.append(
                f"validation_status={spec.validation_status!r} does not permit deployment. "
                f"Required one of: {sorted(required_verdicts)}"
            )
        if is_experimental and spec.validation_status not in _DEPLOYABLE_VERDICTS:
            warnings.append(
                f"EXPERIMENTAL PAPER strategy: validation_status={spec.validation_status!r}. "
                "This strategy must never be confused with a validated deployable strategy."
            )

        # ── version / fingerprint ─────────────────────────────────────────────
        checks["strategy_version_present"] = bool(spec.version)
        if not checks["strategy_version_present"]:
            issues.append("strategy version is empty")

        checks["configuration_fingerprint_present"] = bool(spec.configuration_fingerprint)
        if not checks["configuration_fingerprint_present"]:
            warnings.append("configuration_fingerprint is empty — run make_spec() to stamp it")

        # ── universe & data ───────────────────────────────────────────────────
        checks["universe_definition_present"] = bool(spec.universe_definition)
        if not checks["universe_definition_present"]:
            issues.append("universe_definition is empty — cannot determine tradeable universe")

        # ── portfolio construction ────────────────────────────────────────────
        checks["portfolio_construction_config_present"] = bool(spec.portfolio_construction_config)
        if not checks["portfolio_construction_config_present"]:
            issues.append("portfolio_construction_config is empty")

        # ── risk ──────────────────────────────────────────────────────────────
        checks["risk_config_present"] = bool(spec.risk_config)
        if not checks["risk_config_present"]:
            issues.append("risk_config is empty — risk checks cannot run without limits")

        # ── execution ─────────────────────────────────────────────────────────
        checks["execution_config_present"] = bool(spec.execution_config)
        if not checks["execution_config_present"]:
            warnings.append("execution_config is empty — M14 defaults will be used")

        # ── cost assumptions (must be explicit; empty = reject) ───────────────
        checks["cost_assumptions_explicit"] = bool(spec.transaction_cost_assumption)
        if not checks["cost_assumptions_explicit"]:
            issues.append(
                "transaction_cost_assumption is empty — cost assumptions must be explicit. "
                "Set to {'commission': 0} to acknowledge zero-cost assumption."
            )

        # ── currency ──────────────────────────────────────────────────────────
        checks["base_currency_defined"] = bool(spec.base_currency)
        if not checks["base_currency_defined"]:
            issues.append("base_currency is empty")

        # ── capital ───────────────────────────────────────────────────────────
        checks["capital_assumption_positive"] = spec.capital_assumption > 0
        if not checks["capital_assumption_positive"]:
            issues.append(f"capital_assumption={spec.capital_assumption} — must be > 0")

        # ── rebalance frequency ───────────────────────────────────────────────
        checks["rebalance_frequency_valid"] = spec.rebalance_frequency in _VALID_FREQUENCIES
        if not checks["rebalance_frequency_valid"]:
            issues.append(
                f"rebalance_frequency={spec.rebalance_frequency!r} is not valid. "
                f"Must be one of {sorted(_VALID_FREQUENCIES)}"
            )

        # ── signal / feature logic ────────────────────────────────────────────
        checks["signal_definition_present"] = bool(spec.signal_definition)
        if not checks["signal_definition_present"]:
            issues.append("signal_definition is empty — no signal generation config")

        checks["feature_definition_present"] = bool(spec.feature_definition)
        if not checks["feature_definition_present"]:
            warnings.append("feature_definition is empty — strategy logic must handle raw snapshot directly")

        # ── no provider access flags (checked by convention in execution_config) ─
        # Strategies must not set provider_access=True; M21 providers are upstream.
        no_provider = not spec.execution_config.get("direct_provider_access", False)
        checks["no_provider_access_flags"] = no_provider
        if not no_provider:
            issues.append(
                "execution_config.direct_provider_access=True is not allowed. "
                "Strategy runtime must consume MarketDataSnapshot, not fetch data."
            )

        # ── type consistency ──────────────────────────────────────────────────
        checks["strategy_type_consistent"] = spec.strategy_type in (
            StrategyType.VALIDATED_DEPLOYABLE, StrategyType.EXPERIMENTAL_PAPER
        )
        if not checks["strategy_type_consistent"]:
            issues.append(f"strategy_type={spec.strategy_type!r} is not a valid StrategyType")

        # ── experimental: must not be confused with validated ─────────────────
        if (is_experimental and not permit_experimental
                and spec.strategy_type == StrategyType.EXPERIMENTAL_PAPER):
            warnings.append(
                "EXPERIMENTAL PAPER strategy submitted for readiness check. "
                "Pass permit_experimental=True to allow this."
            )

        ready = len(issues) == 0
        verdict = "READY" if ready else "NOT_READY"
        return ReadinessReport(
            ready=ready,
            verdict=verdict,
            checks=checks,
            issues=issues,
            warnings=warnings,
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            validated_at=datetime.utcnow(),
        )
