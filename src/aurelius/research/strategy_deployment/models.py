"""M22 Strategy Deployment — immutable domain models.

All objects are frozen dataclasses. Every mutable book lives in the downstream
systems (M11 PortfolioState, M12 PaperTradingSession). M22 only produces
evidence artifacts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


# ── helpers ───────────────────────────────────────────────────────────────────

def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _fp(obj: Any) -> str:
    return hashlib.blake2b(_canonical(obj).encode(), digest_size=16).hexdigest()


# ── strategy lifecycle ────────────────────────────────────────────────────────

class StrategyState(str, Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATED = "validated"
    DEPLOYABLE = "deployable"
    PAPER = "paper"
    SUSPENDED = "suspended"
    RETIRED = "retired"
    REJECTED = "rejected"


# Permitted state transitions. REQUIRES_REVIEW is not a standalone state; it is
# represented as VALIDATED with a warning in the validation report.
ALLOWED_TRANSITIONS: dict[StrategyState, set[StrategyState]] = {
    StrategyState.DRAFT:       {StrategyState.VALIDATING, StrategyState.REJECTED},
    StrategyState.VALIDATING:  {StrategyState.VALIDATED, StrategyState.REJECTED},
    StrategyState.VALIDATED:   {StrategyState.DEPLOYABLE, StrategyState.REJECTED},
    StrategyState.DEPLOYABLE:  {StrategyState.PAPER, StrategyState.SUSPENDED, StrategyState.RETIRED},
    StrategyState.PAPER:       {StrategyState.SUSPENDED, StrategyState.RETIRED},
    StrategyState.SUSPENDED:   {StrategyState.PAPER, StrategyState.RETIRED},
    StrategyState.RETIRED:     set(),
    StrategyState.REJECTED:    set(),
}

# Verdicts from M9 that permit DEPLOYABLE transition
_DEPLOYABLE_VERDICTS = {"PASS", "PASS_WITH_WARNINGS"}
_PAPER_VERDICTS = {"PASS", "PASS_WITH_WARNINGS", "REQUIRES_REVIEW"}  # experimental paper


# ── strategy type ─────────────────────────────────────────────────────────────

class StrategyType(str, Enum):
    VALIDATED_DEPLOYABLE = "validated_deployable"
    EXPERIMENTAL_PAPER = "experimental_paper"


# ── core specification ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategySpecification:
    """Immutable, versioned strategy contract.

    One object per (strategy_id, version). Any material change must produce a
    new version; the old spec is never mutated.
    """
    strategy_id: str
    strategy_name: str
    version: str                          # semver string, e.g. "1.0.0"
    description: str = ""
    strategy_type: str = StrategyType.VALIDATED_DEPLOYABLE

    # research lineage
    research_artifact_id: str | None = None       # M7 experiment_id
    validation_artifact_id: str | None = None     # M9 manifest_hash
    validation_status: str = "UNVALIDATED"        # M9 verdict string

    # universe & data
    universe_definition: dict = field(default_factory=dict)
    required_data: list = field(default_factory=list)    # list[str] — field names needed
    data_requirements: dict = field(default_factory=dict)

    # signal logic
    feature_definition: dict = field(default_factory=dict)   # config for compute_features
    signal_definition: dict = field(default_factory=dict)    # config for generate_signal

    # execution schedule
    rebalance_frequency: str = "monthly"          # daily | weekly | monthly

    # construction / risk / execution config (pass through to M10/M13/M14)
    portfolio_construction_config: dict = field(default_factory=dict)
    risk_config: dict = field(default_factory=dict)
    execution_config: dict = field(default_factory=dict)

    # cost assumptions (never hard-coded; always explicit)
    transaction_cost_assumption: dict = field(default_factory=dict)  # commission, spread, …
    slippage_assumption: dict = field(default_factory=dict)

    # portfolio metadata
    benchmark: str | None = None
    base_currency: str = "USD"
    allowed_instruments: list = field(default_factory=list)
    capital_assumption: float = 0.0
    capacity_assumption: dict = field(default_factory=dict)

    # provenance
    model_version: str = "0.0.0"
    dependency_versions: dict = field(default_factory=dict)
    creation_timestamp: datetime = field(default_factory=datetime.utcnow)

    # content fingerprint — set by make_spec(), never by the caller
    configuration_fingerprint: str = ""

    def fingerprint(self) -> str:
        """Deterministic content hash of all material fields (excludes timestamp)."""
        material = {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "strategy_type": self.strategy_type,
            "universe_definition": self.universe_definition,
            "required_data": sorted(self.required_data),
            "feature_definition": self.feature_definition,
            "signal_definition": self.signal_definition,
            "rebalance_frequency": self.rebalance_frequency,
            "portfolio_construction_config": self.portfolio_construction_config,
            "risk_config": self.risk_config,
            "execution_config": self.execution_config,
            "transaction_cost_assumption": self.transaction_cost_assumption,
            "slippage_assumption": self.slippage_assumption,
            "benchmark": self.benchmark,
            "base_currency": self.base_currency,
            "allowed_instruments": sorted(self.allowed_instruments),
            "capital_assumption": self.capital_assumption,
            "model_version": self.model_version,
            "validation_status": self.validation_status,
        }
        return _fp(material)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["creation_timestamp"] = self.creation_timestamp.isoformat()
        return d


def make_spec(**kwargs) -> StrategySpecification:
    """Build a StrategySpecification and stamp its configuration_fingerprint."""
    tmp = StrategySpecification(**kwargs)
    fp = tmp.fingerprint()
    # frozen dataclass: must reconstruct with the fingerprint populated
    return StrategySpecification(**{**kwargs, "configuration_fingerprint": fp})


# ── feature & signal sets ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class FeatureSet:
    """Output of compute_features() — one row per security."""
    strategy_id: str
    strategy_version: str
    as_of: date
    features: dict                        # security_id -> {feature_name: value}
    input_fingerprint: str                # hash of snapshot identity
    strategy_fingerprint: str
    computed_at: datetime = field(default_factory=datetime.utcnow)

    def fingerprint(self) -> str:
        return _fp({
            "strategy_id": self.strategy_id,
            "version": self.strategy_version,
            "as_of": str(self.as_of),
            "input": self.input_fingerprint,
            "strategy": self.strategy_fingerprint,
            "n_securities": len(self.features),
        })


@dataclass(frozen=True)
class SignalRecord:
    """Single-security signal with full provenance."""
    strategy_id: str
    strategy_version: str
    security_id: str
    as_of: date
    signal_value: float
    metadata: dict = field(default_factory=dict)
    input_fingerprint: str = ""           # features fingerprint this was generated from
    strategy_fingerprint: str = ""


@dataclass(frozen=True)
class SignalSet:
    """Output of generate_signal() — one signal per security."""
    strategy_id: str
    strategy_version: str
    as_of: date
    signals: dict                         # security_id -> float
    signal_records: list                  # list[SignalRecord]
    features_fingerprint: str
    strategy_fingerprint: str
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def fingerprint(self) -> str:
        return _fp({
            "strategy_id": self.strategy_id,
            "version": self.strategy_version,
            "as_of": str(self.as_of),
            "features": self.features_fingerprint,
            "strategy": self.strategy_fingerprint,
            "n_signals": len(self.signals),
        })


# ── M22-level order intent (rich lineage wrapper over M14's minimal OrderIntent) ─

@dataclass(frozen=True)
class OrderIntentRecord:
    """Portfolio-level intent with full research→signal→target→risk lineage.

    This is NOT a replacement for M14's OrderRequest. After validation, the caller
    converts these via intents_from_target() / build_requests() from
    aurelius.research.execution.ems.orders.
    """
    intent_id: str
    strategy_id: str
    strategy_version: str
    security_id: str
    side: str                             # buy | sell | flat
    delta_shares: float
    target_weight: float
    reference_price: float
    generated_at: datetime
    reason: str = ""
    signal_reference: str = ""            # signals fingerprint
    target_reference: str = ""            # portfolio fingerprint
    risk_reference: str = ""             # risk report fingerprint
    configuration_fingerprint: str = ""

    def to_ems_intent(self):
        """Produce the M14 OrderIntent consumed by EMS/OMS."""
        from aurelius.research.execution.ems.models import OrderIntent as EmsIntent
        return EmsIntent(security_id=self.security_id, delta_shares=self.delta_shares)


# ── strategy evaluation (full snapshot of one runtime.evaluate() call) ────────

@dataclass(frozen=True)
class StrategyEvaluation:
    """Deterministic output of one StrategyRuntime.evaluate() call.

    Same strategy + same snapshot + same portfolio state + same config
    must always produce the same evaluation_fingerprint.
    """
    evaluation_id: str
    strategy_id: str
    strategy_version: str
    as_of: date
    feature_set: FeatureSet
    signal_set: SignalSet
    portfolio: object                     # M10 Portfolio
    risk_report: object                   # M13 RiskReport
    order_intents: list                   # list[OrderIntentRecord]
    ems_requests: list                    # list[M14 OrderRequest] — execution-ready
    evaluation_fingerprint: str
    provenance: dict = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=datetime.utcnow)
    strategy_fingerprint: str = ""
    risk_approved: bool = False
    risk_decision: str = ""
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


# ── deployment manifest ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeploymentManifest:
    """Sufficient to reconstruct the strategy runtime for any historical snapshot.

    Every field is deterministic. A manifest fingerprint is the hash of all fields
    except manifest_fingerprint itself.
    """
    manifest_id: str
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str
    research_artifact_id: str | None
    validation_artifact_id: str | None
    validation_status: str
    base_currency: str
    benchmark: str | None
    capital_assumption: float
    rebalance_frequency: str
    universe_definition: dict
    data_requirements: dict
    required_data: list
    portfolio_construction_config: dict
    risk_config: dict
    execution_config: dict
    transaction_cost_assumption: dict
    slippage_assumption: dict
    model_version: str
    dependency_versions: dict
    created_at: datetime
    manifest_fingerprint: str = ""

    def fingerprint(self) -> str:
        d = asdict(self)
        d.pop("manifest_fingerprint", None)
        d.pop("created_at", None)   # operational timestamp is not material content
        return _fp(d)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


def make_manifest(manifest_id: str, spec: StrategySpecification) -> DeploymentManifest:
    """Build a DeploymentManifest from a StrategySpecification."""
    tmp = DeploymentManifest(
        manifest_id=manifest_id,
        strategy_id=spec.strategy_id,
        strategy_version=spec.version,
        strategy_fingerprint=spec.configuration_fingerprint or spec.fingerprint(),
        research_artifact_id=spec.research_artifact_id,
        validation_artifact_id=spec.validation_artifact_id,
        validation_status=spec.validation_status,
        base_currency=spec.base_currency,
        benchmark=spec.benchmark,
        capital_assumption=spec.capital_assumption,
        rebalance_frequency=spec.rebalance_frequency,
        universe_definition=spec.universe_definition,
        data_requirements=spec.data_requirements,
        required_data=list(spec.required_data),
        portfolio_construction_config=spec.portfolio_construction_config,
        risk_config=spec.risk_config,
        execution_config=spec.execution_config,
        transaction_cost_assumption=spec.transaction_cost_assumption,
        slippage_assumption=spec.slippage_assumption,
        model_version=spec.model_version,
        dependency_versions=dict(spec.dependency_versions),
        created_at=datetime.utcnow(),
    )
    fp = tmp.fingerprint()
    return DeploymentManifest(**{**asdict(tmp), "created_at": tmp.created_at, "manifest_fingerprint": fp})


# ── readiness report ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReadinessReport:
    """Machine-readable output of ReadinessValidator.validate()."""
    ready: bool
    verdict: str                          # READY | NOT_READY
    checks: dict                          # check_name -> bool
    issues: list                          # list[str] — human-readable failures
    warnings: list = field(default_factory=list)
    strategy_id: str = ""
    strategy_version: str = ""
    validated_at: datetime = field(default_factory=datetime.utcnow)


# ── consistency report ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConsistencyReport:
    """Output of ConsistencyChecker — detects research/deployment config drift."""
    consistent: bool
    drifted_fields: list                  # list[str] — field names that differ
    differences: dict                     # field -> {research: …, deployed: …}
    strategy_id: str = ""
    checked_at: datetime = field(default_factory=datetime.utcnow)
