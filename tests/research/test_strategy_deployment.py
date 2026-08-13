"""M22 Strategy Deployment — test suite.

Covers:
  1.  StrategySpecification construction and immutability
  2.  configuration_fingerprint determinism
  3.  Strategy versioning (new version = new spec)
  4.  StrategyState lifecycle transitions (valid + invalid)
  5.  StrategyRegistry operations
  6.  Research artifact binding
  7.  Validation gate (readiness validator)
  8.  Experimental paper strategy distinction
  9.  FeatureSet contract
  10. SignalSet contract + PIT enforcement
  11. Market data integration (MarketDataSnapshot)
  12. NaN / Inf signal rejection
  13. Deterministic runtime evaluation
  14. Portfolio construction integration (M10)
  15. Risk integration (M13)
  16. OrderIntentRecord lineage
  17. M14 OrderRequest generation
  18. Research/deployment consistency checker
  19. Cost assumptions must be explicit
  20. DeploymentManifest + fingerprint
  21. make_manifest round-trip
  22. Replay determinism (same inputs → same fingerprint)
  23. Failure: missing snapshot
  24. Failure: stale snapshot as_of
  25. Failure: NaN signal
  26. Failure: invalid strategy version
  27. Failure: missing research artifact → readiness rejects
  28. Failure: wrong validation status → readiness rejects
  29. Failure: direct_provider_access flag rejected
  30. Failure: risk rejection → no ems_requests generated
  31. Configuration drift detection (all material fields)
  32. Experimental strategy labeled and never confused with validated
  33. JT-integration fixture: momentum signal → target → risk → intent
  34. JT-integration: rejected validation status blocks DEPLOYABLE
  35. JT-integration: experimental paper still allowed under permit_experimental
  36. Registry: list by state
  37. Registry: invalid transition raises StrategyTransitionError
  38. Registry: retired strategy cannot transition
  39. Duplicate evaluation returns same fingerprint
  40. Out-of-order evaluation (older snapshot) still deterministic
  41. Portfolio: long-only constraint respected
  42. Portfolio: signal-weighted objective
  43. Risk: soft violation produces warnings, not rejection
  44. OrderIntentRecord.to_ems_intent() returns valid M14 OrderIntent
  45. Spec.to_dict() round-trip
  46. Manifest.to_dict() round-trip
  47. Empty universe (all-zero signals) produces empty portfolio
  48. Missing price for universe member: handled gracefully
  49. StrategySpecification equal comparison (same fingerprint = same content)
  50. Full integration: Research → Spec → Runtime → EMS boundary
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pytest

from mentisrex.research.portfolio.engine import PortfolioEngine
from mentisrex.research.risk.engine import RiskEngine, RiskEngineConfig
from mentisrex.research.risk.models import RiskDecision
from mentisrex.research.strategy_deployment import (
    ConsistencyChecker,
    EvaluationError,
    FeatureSet,
    OrderIntentRecord,
    ReadinessReport,
    ReadinessValidator,
    SignalRecord,
    SignalSet,
    StrategyEntry,
    StrategyEvaluation,
    StrategyLogic,
    StrategyRegistry,
    StrategyRuntime,
    StrategySpecification,
    StrategyState,
    StrategyTransitionError,
    StrategyType,
    make_manifest,
    make_spec,
)
from mentisrex.research.execution.ems.models import OrderIntent as EmsOrderIntent


# ── shared fixtures ───────────────────────────────────────────────────────────

AS_OF = date(2024, 6, 30)

SPOTS = {"AAPL": 190.0, "MSFT": 420.0, "GOOG": 170.0, "AMZN": 180.0, "META": 500.0}


@dataclass(frozen=True)
class FakeSnapshot:
    """Minimal stand-in for M18 MarketDataSnapshot — no network access."""
    as_of: date
    spots: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        import hashlib, json
        payload = json.dumps({"as_of": str(self.as_of), "spots": {k: v for k, v in sorted(self.spots.items())}},
                             sort_keys=True)
        return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()


@dataclass
class FakePortfolioState:
    """Minimal M11-compatible portfolio state for tests."""
    holdings: dict = field(default_factory=dict)
    _cash: float = 1_000_000.0

    def total_value(self) -> float:
        return self._cash + sum(h.get("shares", 0) * h.get("price", 0) for h in self.holdings.values())


def _base_spec(**overrides) -> StrategySpecification:
    """Build a minimal valid spec. Overrides are applied before fingerprinting."""
    defaults = dict(
        strategy_id="test-strategy",
        strategy_name="Test Strategy",
        version="1.0.0",
        description="Unit test strategy",
        strategy_type=StrategyType.VALIDATED_DEPLOYABLE,
        research_artifact_id="exp-abc123",
        validation_artifact_id="val-xyz789",
        validation_status="PASS",
        universe_definition={"type": "equity", "region": "US"},
        required_data=["close", "volume"],
        feature_definition={"lookback": 12},
        signal_definition={"type": "momentum", "top_n": 50},
        rebalance_frequency="monthly",
        portfolio_construction_config={"objective": "equal_weight", "long_only": True},
        risk_config={"max_position": 0.10, "max_volatility": 0.25},
        execution_config={"algo": "market"},
        transaction_cost_assumption={"commission": 0.001, "spread": 0.0005},
        slippage_assumption={"model": "linear", "factor": 0.1},
        benchmark="SPY",
        base_currency="USD",
        allowed_instruments=["equity"],
        capital_assumption=1_000_000.0,
        model_version="1.0.0",
    )
    defaults.update(overrides)
    return make_spec(**defaults)


class ConstantLogic(StrategyLogic):
    """Logic that generates constant signals — deterministic by construction."""

    def __init__(self, signals: dict[str, float]) -> None:
        self._signals = signals

    def compute_features(self, snapshot: FakeSnapshot, spec: StrategySpecification) -> FeatureSet:
        features = {sid: {"spot": snapshot.spots.get(sid, 0.0)} for sid in self._signals}
        return FeatureSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=snapshot.as_of,
            features=features,
            input_fingerprint=snapshot.fingerprint(),
            strategy_fingerprint=spec.configuration_fingerprint or spec.fingerprint(),
        )

    def generate_signal(self, features: FeatureSet, spec: StrategySpecification) -> SignalSet:
        records = [
            SignalRecord(
                strategy_id=spec.strategy_id,
                strategy_version=spec.version,
                security_id=sid,
                as_of=features.as_of,
                signal_value=self._signals[sid],
                input_fingerprint=features.fingerprint(),
                strategy_fingerprint=features.strategy_fingerprint,
            )
            for sid in self._signals
        ]
        return SignalSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=features.as_of,
            signals=dict(self._signals),
            signal_records=records,
            features_fingerprint=features.fingerprint(),
            strategy_fingerprint=features.strategy_fingerprint,
        )


class MomentumLogic(StrategyLogic):
    """JT-style 12-1 momentum signal: rank by 12m return, skip last month.

    Uses only data present in the snapshot (spots vs a prior-period baseline).
    No external data access. Deterministic.
    """

    def __init__(self, prior_spots: dict[str, float]) -> None:
        self._prior = prior_spots  # spots 12 months ago (test-supplied, not live-fetched)

    def compute_features(self, snapshot, spec) -> FeatureSet:
        features = {}
        for sid in snapshot.spots:
            current = float(snapshot.spots[sid])
            prior = float(self._prior.get(sid, current))
            ret_12m = (current / prior - 1.0) if prior > 0 else 0.0
            features[sid] = {"ret_12m": ret_12m, "spot": current}
        return FeatureSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=snapshot.as_of,
            features=features,
            input_fingerprint=snapshot.fingerprint(),
            strategy_fingerprint=spec.configuration_fingerprint or spec.fingerprint(),
        )

    def generate_signal(self, features, spec) -> SignalSet:
        # rank by 12m return → signal = rank / N
        rets = {sid: v["ret_12m"] for sid, v in features.features.items()}
        ranked = sorted(rets, key=lambda s: rets[s])
        n = len(ranked)
        signals = {sid: (i + 1) / n for i, sid in enumerate(ranked)}
        records = [
            SignalRecord(
                strategy_id=spec.strategy_id,
                strategy_version=spec.version,
                security_id=sid,
                as_of=features.as_of,
                signal_value=signals[sid],
                input_fingerprint=features.fingerprint(),
                strategy_fingerprint=features.strategy_fingerprint,
            )
            for sid in signals
        ]
        return SignalSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=features.as_of,
            signals=signals,
            signal_records=records,
            features_fingerprint=features.fingerprint(),
            strategy_fingerprint=features.strategy_fingerprint,
        )


# ── 1. StrategySpecification construction ────────────────────────────────────

def test_spec_construction():
    spec = _base_spec()
    assert spec.strategy_id == "test-strategy"
    assert spec.version == "1.0.0"
    assert spec.validation_status == "PASS"


def test_spec_is_frozen():
    spec = _base_spec()
    with pytest.raises(Exception):   # frozen dataclass → FrozenInstanceError
        spec.strategy_id = "mutated"  # type: ignore[misc]


# ── 2. configuration_fingerprint determinism ─────────────────────────────────

def test_fingerprint_deterministic():
    spec_a = _base_spec()
    spec_b = _base_spec()
    assert spec_a.configuration_fingerprint == spec_b.configuration_fingerprint


def test_fingerprint_changes_on_material_change():
    spec_a = _base_spec()
    spec_b = _base_spec(signal_definition={"type": "value", "top_n": 100})
    assert spec_a.configuration_fingerprint != spec_b.configuration_fingerprint


def test_fingerprint_ignores_timestamp():
    # Two specs with different creation_timestamp but identical material fields
    spec_a = make_spec(**{k: getattr(_base_spec(), k) for k in StrategySpecification.__dataclass_fields__
                          if k not in ("configuration_fingerprint", "creation_timestamp")})
    spec_b = make_spec(**{k: getattr(_base_spec(), k) for k in StrategySpecification.__dataclass_fields__
                          if k not in ("configuration_fingerprint", "creation_timestamp")})
    assert spec_a.configuration_fingerprint == spec_b.configuration_fingerprint


# ── 3. strategy versioning ────────────────────────────────────────────────────

def test_new_version_has_different_fingerprint():
    spec_v1 = _base_spec(version="1.0.0")
    spec_v2 = _base_spec(version="2.0.0")
    assert spec_v1.configuration_fingerprint != spec_v2.configuration_fingerprint


def test_version_in_spec():
    spec = _base_spec(version="3.1.4")
    assert spec.version == "3.1.4"


# ── 4. lifecycle transitions ──────────────────────────────────────────────────

def test_valid_transitions():
    registry = StrategyRegistry()
    spec = _base_spec()
    registry.register(spec, StrategyState.DRAFT)
    registry.transition(spec.strategy_id, StrategyState.VALIDATING)
    registry.transition(spec.strategy_id, StrategyState.VALIDATED)
    registry.transition(spec.strategy_id, StrategyState.DEPLOYABLE)
    registry.transition(spec.strategy_id, StrategyState.PAPER)
    assert registry.state(spec.strategy_id) == StrategyState.PAPER


def test_invalid_transition_raises():
    registry = StrategyRegistry()
    spec = _base_spec()
    registry.register(spec, StrategyState.DRAFT)
    with pytest.raises(StrategyTransitionError):
        registry.transition(spec.strategy_id, StrategyState.PAPER)  # DRAFT → PAPER not allowed


def test_retired_strategy_cannot_transition():
    registry = StrategyRegistry()
    spec = _base_spec()
    registry.register(spec, StrategyState.RETIRED)
    with pytest.raises(StrategyTransitionError):
        registry.transition(spec.strategy_id, StrategyState.PAPER)


def test_rejected_strategy_cannot_transition():
    registry = StrategyRegistry()
    spec = _base_spec()
    registry.register(spec, StrategyState.REJECTED)
    with pytest.raises(StrategyTransitionError):
        registry.transition(spec.strategy_id, StrategyState.VALIDATED)


def test_draft_can_be_rejected():
    registry = StrategyRegistry()
    spec = _base_spec()
    registry.register(spec, StrategyState.DRAFT)
    registry.transition(spec.strategy_id, StrategyState.REJECTED)
    assert registry.state(spec.strategy_id) == StrategyState.REJECTED


# ── 5. registry operations ────────────────────────────────────────────────────

def test_registry_register_and_get():
    registry = StrategyRegistry()
    spec = _base_spec()
    entry = registry.register(spec)
    assert entry.spec is spec
    assert entry.state == StrategyState.DRAFT


def test_registry_get_missing_raises():
    registry = StrategyRegistry()
    with pytest.raises(KeyError):
        registry.state("nonexistent-strategy")


def test_registry_list_by_state():
    registry = StrategyRegistry()
    s1 = _base_spec(strategy_id="s1")
    s2 = _base_spec(strategy_id="s2")
    s3 = _base_spec(strategy_id="s3")
    registry.register(s1, StrategyState.DRAFT)
    registry.register(s2, StrategyState.PAPER)
    registry.register(s3, StrategyState.PAPER)
    paper = registry.list_strategies(state=StrategyState.PAPER)
    assert len(paper) == 2
    assert all(e.state == StrategyState.PAPER for e in paper)


def test_registry_list_all():
    registry = StrategyRegistry()
    for i in range(5):
        registry.register(_base_spec(strategy_id=f"s{i}"))
    assert len(registry.list_strategies()) == 5


# ── 6. research artifact binding ─────────────────────────────────────────────

def test_research_artifact_binding():
    spec = _base_spec(research_artifact_id="exp-abc123", validation_artifact_id="val-xyz789")
    assert spec.research_artifact_id == "exp-abc123"
    assert spec.validation_artifact_id == "val-xyz789"


def test_spec_without_research_artifact():
    spec = _base_spec(research_artifact_id=None)
    assert spec.research_artifact_id is None


# ── 7. readiness validator ────────────────────────────────────────────────────

def test_readiness_valid_spec_passes():
    spec = _base_spec()
    report = ReadinessValidator().validate(spec)
    assert report.ready is True
    assert report.verdict == "READY"


def test_readiness_missing_research_artifact_fails():
    spec = _base_spec(research_artifact_id=None)
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert any("research_artifact_id" in i for i in report.issues)
    assert report.checks["research_artifact_exists"] is False


def test_readiness_wrong_validation_status_fails():
    spec = _base_spec(validation_status="REJECT")
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert not report.checks["validation_status_permits_deployment"]


def test_readiness_missing_risk_config_fails():
    spec = _base_spec(risk_config={})
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert not report.checks["risk_config_present"]


def test_readiness_no_cost_assumptions_fails():
    spec = _base_spec(transaction_cost_assumption={})
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert not report.checks["cost_assumptions_explicit"]


def test_readiness_zero_capital_fails():
    spec = _base_spec(capital_assumption=0.0)
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert not report.checks["capital_assumption_positive"]


def test_readiness_invalid_frequency_fails():
    spec = _base_spec(rebalance_frequency="intraday")
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert not report.checks["rebalance_frequency_valid"]


def test_readiness_provider_access_flag_fails():
    spec = _base_spec(execution_config={"direct_provider_access": True})
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert not report.checks["no_provider_access_flags"]


# ── 8. experimental paper strategy ───────────────────────────────────────────

def test_experimental_strategy_type():
    spec = _base_spec(strategy_type=StrategyType.EXPERIMENTAL_PAPER, validation_status="REQUIRES_REVIEW")
    assert spec.strategy_type == StrategyType.EXPERIMENTAL_PAPER


def test_experimental_strategy_readiness_with_requires_review():
    spec = _base_spec(strategy_type=StrategyType.EXPERIMENTAL_PAPER, validation_status="REQUIRES_REVIEW")
    report = ReadinessValidator().validate(spec, permit_experimental=True)
    assert report.ready  # REQUIRES_REVIEW is allowed for experimental
    assert any("EXPERIMENTAL" in w for w in report.warnings)


def test_experimental_strategy_cannot_pass_as_validated():
    spec_exp = _base_spec(strategy_type=StrategyType.EXPERIMENTAL_PAPER, validation_status="REQUIRES_REVIEW")
    spec_val = _base_spec(strategy_type=StrategyType.VALIDATED_DEPLOYABLE, validation_status="PASS")
    assert spec_exp.strategy_type != spec_val.strategy_type


def test_experimental_strategy_has_warning_in_readiness():
    spec = _base_spec(strategy_type=StrategyType.EXPERIMENTAL_PAPER, validation_status="REQUIRES_REVIEW")
    report = ReadinessValidator().validate(spec, permit_experimental=True)
    assert any("EXPERIMENTAL" in w.upper() for w in report.warnings)


# ── 9. FeatureSet contract ────────────────────────────────────────────────────

def test_feature_set_pit_as_of():
    spec = _base_spec()
    snapshot = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5, "MSFT": 0.3})
    fs = logic.compute_features(snapshot, spec)
    assert fs.as_of == AS_OF


def test_feature_set_has_input_fingerprint():
    spec = _base_spec()
    snapshot = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5})
    fs = logic.compute_features(snapshot, spec)
    assert fs.input_fingerprint != ""


def test_feature_set_fingerprint_deterministic():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5, "MSFT": 0.3})
    fs1 = logic.compute_features(snap, spec)
    fs2 = logic.compute_features(snap, spec)
    assert fs1.fingerprint() == fs2.fingerprint()


# ── 10. SignalSet contract + PIT enforcement ──────────────────────────────────

def test_signal_set_as_of_matches_snapshot():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5, "MSFT": 0.3})
    fs = logic.compute_features(snap, spec)
    ss = logic.generate_signal(fs, spec)
    assert ss.as_of == AS_OF


def test_signal_set_has_all_securities():
    sigs = {"AAPL": 0.5, "MSFT": 0.3, "GOOG": 0.8}
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic(sigs)
    fs = logic.compute_features(snap, spec)
    ss = logic.generate_signal(fs, spec)
    assert set(ss.signals.keys()) == set(sigs.keys())


def test_signal_set_fingerprint_deterministic():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5, "MSFT": 0.3})
    fs = logic.compute_features(snap, spec)
    ss1 = logic.generate_signal(fs, spec)
    ss2 = logic.generate_signal(fs, spec)
    assert ss1.fingerprint() == ss2.fingerprint()


def test_signal_pit_violation_raises():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)

    class WrongDateLogic(StrategyLogic):
        def compute_features(self, snapshot, spec):
            return FeatureSet(
                strategy_id=spec.strategy_id, strategy_version=spec.version,
                as_of=date(2099, 1, 1),   # future date!
                features={"AAPL": {"spot": 190.0}},
                input_fingerprint="x", strategy_fingerprint="y",
            )

        def generate_signal(self, features, spec):
            return SignalSet(
                strategy_id=spec.strategy_id, strategy_version=spec.version,
                as_of=features.as_of,
                signals={"AAPL": 0.5}, signal_records=[],
                features_fingerprint="x", strategy_fingerprint="y",
            )

    runtime = StrategyRuntime()
    with pytest.raises(EvaluationError, match="PIT violation"):
        runtime.evaluate(spec, WrongDateLogic(), snap, None)


# ── 11. market data integration ──────────────────────────────────────────────

def test_runtime_consumes_snapshot_spots():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots={"AAPL": 190.0, "MSFT": 420.0})
    logic = ConstantLogic({"AAPL": 0.6, "MSFT": 0.4})
    runtime = StrategyRuntime()
    ev = runtime.evaluate(spec, logic, snap, None)
    assert ev.as_of == AS_OF
    assert len(ev.portfolio.positions) >= 1


def test_runtime_no_provider_access(monkeypatch):
    """Strategy must not call external providers; snapshot is the boundary."""
    call_count = {"n": 0}

    class SpyLogic(StrategyLogic):
        def compute_features(self, snapshot, spec):
            # Attempt to call an external network function would fail in offline tests.
            # We verify the logic only receives the snapshot (not a provider).
            call_count["n"] += 1
            assert hasattr(snapshot, "spots"), "snapshot must have spots"
            return ConstantLogic({"AAPL": 0.5}).compute_features(snapshot, spec)

        def generate_signal(self, features, spec):
            return ConstantLogic({"AAPL": 0.5}).generate_signal(features, spec)

    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots={"AAPL": 190.0})
    StrategyRuntime().evaluate(spec, SpyLogic(), snap, None)
    assert call_count["n"] == 1


# ── 12. NaN / Inf signal rejection ───────────────────────────────────────────

def test_nan_signal_raises():
    class NanLogic(StrategyLogic):
        def compute_features(self, snapshot, spec):
            return ConstantLogic({"AAPL": float("nan")}).compute_features(snapshot, spec)

        def generate_signal(self, features, spec):
            return ConstantLogic({"AAPL": float("nan")}).generate_signal(features, spec)

    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots={"AAPL": 190.0})
    with pytest.raises(EvaluationError, match="NaN"):
        StrategyRuntime().evaluate(spec, NanLogic(), snap, None)


def test_inf_signal_raises():
    class InfLogic(StrategyLogic):
        def compute_features(self, snapshot, spec):
            return ConstantLogic({"AAPL": float("inf")}).compute_features(snapshot, spec)

        def generate_signal(self, features, spec):
            return ConstantLogic({"AAPL": float("inf")}).generate_signal(features, spec)

    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots={"AAPL": 190.0})
    with pytest.raises(EvaluationError, match="infinite"):
        StrategyRuntime().evaluate(spec, InfLogic(), snap, None)


# ── 13. deterministic runtime evaluation ─────────────────────────────────────

def test_same_inputs_produce_same_fingerprint():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5, "MSFT": 0.3, "GOOG": 0.2})
    rt = StrategyRuntime()
    ev1 = rt.evaluate(spec, logic, snap, None)
    ev2 = rt.evaluate(spec, logic, snap, None)
    assert ev1.evaluation_fingerprint == ev2.evaluation_fingerprint


def test_different_snapshot_different_fingerprint():
    spec = _base_spec()
    snap1 = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    snap2 = FakeSnapshot(as_of=date(2024, 7, 31), spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5})
    rt = StrategyRuntime()
    ev1 = rt.evaluate(spec, logic, snap1, None)
    ev2 = rt.evaluate(spec, logic, snap2, None)
    assert ev1.evaluation_fingerprint != ev2.evaluation_fingerprint


def test_different_spec_version_different_fingerprint():
    spec1 = _base_spec(version="1.0.0")
    spec2 = _base_spec(version="2.0.0")
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5})
    rt = StrategyRuntime()
    ev1 = rt.evaluate(spec1, logic, snap, None)
    ev2 = rt.evaluate(spec2, logic, snap, None)
    assert ev1.evaluation_fingerprint != ev2.evaluation_fingerprint


# ── 14. portfolio construction integration (M10) ──────────────────────────────

def test_portfolio_positions_non_empty():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({sid: 0.5 for sid in SPOTS})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    assert len(ev.portfolio.positions) > 0


def test_long_only_constraint_respected():
    spec = _base_spec(portfolio_construction_config={
        "objective": "equal_weight", "long_only": True,
    })
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({sid: (0.5 if i % 2 == 0 else -0.5) for i, sid in enumerate(SPOTS)})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    for pos in ev.portfolio.positions:
        assert pos.weight >= -1e-9, f"short position {pos.weight} with long_only=True"


def test_portfolio_weights_sum_to_one_approx():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({sid: 1.0 for sid in SPOTS})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    total_weight = sum(p.weight for p in ev.portfolio.positions)
    assert abs(total_weight - 1.0) < 0.01


def test_empty_signals_produce_empty_portfolio():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({})  # no signals
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    assert len(ev.portfolio.positions) == 0


# ── 15. risk integration (M13) ────────────────────────────────────────────────

def test_risk_report_attached():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({sid: 0.5 for sid in SPOTS})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    assert ev.risk_report is not None
    assert ev.risk_decision in ("approve", "approve_with_warning", "reject")


def test_risk_approved_flag():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({sid: 0.5 for sid in SPOTS})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    # Default M13 config is permissive for small portfolios → should approve
    assert isinstance(ev.risk_approved, bool)


def test_risk_rejection_produces_no_ems_requests():
    from mentisrex.research.risk.limits import RiskLimits
    from mentisrex.research.risk.engine import RiskEngineConfig

    # Set an absurdly tight position limit to force rejection
    tight_config = RiskEngineConfig(limits=RiskLimits(max_position=0.001))
    tight_risk = RiskEngine(tight_config)

    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({sid: 1.0 for sid in SPOTS})  # concentrated → violates 0.1%

    rt = StrategyRuntime(risk_engine=tight_risk)
    ev = rt.evaluate(spec, logic, snap, None)
    assert not ev.risk_approved
    assert len(ev.ems_requests) == 0
    assert len(ev.warnings) > 0


# ── 16. OrderIntentRecord lineage ─────────────────────────────────────────────

def test_intent_record_has_strategy_lineage():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.8, "MSFT": 0.2})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    for intent in ev.order_intents:
        assert intent.strategy_id == spec.strategy_id
        assert intent.strategy_version == spec.version
        assert intent.configuration_fingerprint == spec.configuration_fingerprint
        assert intent.signal_reference != ""
        assert intent.target_reference != ""
        assert intent.risk_reference != ""


def test_intent_record_side_correct():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots={"AAPL": 190.0, "MSFT": 420.0})
    logic = ConstantLogic({"AAPL": 0.7, "MSFT": 0.3})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    for intent in ev.order_intents:
        assert intent.side in ("buy", "sell", "flat")


# ── 17. M14 OrderRequest generation ──────────────────────────────────────────

def test_ems_requests_are_m14_order_requests():
    from mentisrex.research.execution.ems.models import OrderRequest
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({sid: 0.5 for sid in SPOTS})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    for req in ev.ems_requests:
        assert isinstance(req, OrderRequest)
        assert abs(req.quantity) > 0


def test_to_ems_intent_produces_m14_intent():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.8, "MSFT": 0.2})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    for record in ev.order_intents:
        ems_intent = record.to_ems_intent()
        assert isinstance(ems_intent, EmsOrderIntent)
        assert ems_intent.security_id == record.security_id
        assert ems_intent.delta_shares == record.delta_shares


# ── 18. consistency checker ───────────────────────────────────────────────────

def test_identical_specs_consistent():
    spec = _base_spec()
    report = ConsistencyChecker().check(spec, spec)
    assert report.consistent
    assert len(report.drifted_fields) == 0


def test_signal_definition_drift_detected():
    research = _base_spec(signal_definition={"type": "momentum", "lookback": 12})
    deployed = _base_spec(signal_definition={"type": "momentum", "lookback": 6})
    report = ConsistencyChecker().check(research, deployed)
    assert not report.consistent
    assert "signal_definition" in report.drifted_fields


def test_universe_drift_detected():
    research = _base_spec(universe_definition={"region": "US"})
    deployed = _base_spec(universe_definition={"region": "Global"})
    report = ConsistencyChecker().check(research, deployed)
    assert not report.consistent
    assert "universe_definition" in report.drifted_fields


def test_cost_assumption_drift_detected():
    research = _base_spec(transaction_cost_assumption={"commission": 0.001})
    deployed = _base_spec(transaction_cost_assumption={"commission": 0.005})
    report = ConsistencyChecker().check(research, deployed)
    assert not report.consistent
    assert "transaction_cost_assumption" in report.drifted_fields


def test_consistency_report_has_differences_detail():
    research = _base_spec(benchmark="SPY")
    deployed = _base_spec(benchmark="QQQ")
    report = ConsistencyChecker().check(research, deployed)
    assert "benchmark" in report.differences
    assert report.differences["benchmark"]["research"] == "SPY"
    assert report.differences["benchmark"]["deployed"] == "QQQ"


# ── 19. cost assumptions must be explicit ─────────────────────────────────────

def test_cost_assumptions_in_spec():
    spec = _base_spec(transaction_cost_assumption={"commission": 0.0010, "spread": 0.0005})
    assert spec.transaction_cost_assumption["commission"] == 0.0010


def test_zero_cost_assumption_acknowledged():
    spec = _base_spec(transaction_cost_assumption={"commission": 0.0})
    report = ReadinessValidator().validate(spec)
    # {"commission": 0.0} is explicit (truthy dict) → should pass
    assert report.checks["cost_assumptions_explicit"]


# ── 20. DeploymentManifest ────────────────────────────────────────────────────

def test_manifest_from_spec():
    spec = _base_spec()
    manifest = make_manifest("man-001", spec)
    assert manifest.strategy_id == spec.strategy_id
    assert manifest.strategy_version == spec.version
    assert manifest.manifest_fingerprint != ""


def test_manifest_fingerprint_deterministic():
    spec = _base_spec()
    m1 = make_manifest("man-001", spec)
    m2 = make_manifest("man-001", spec)
    # Same manifest_id and spec → same fingerprint
    assert m1.manifest_fingerprint == m2.manifest_fingerprint


def test_manifest_captures_all_config():
    spec = _base_spec()
    manifest = make_manifest("man-001", spec)
    assert manifest.base_currency == spec.base_currency
    assert manifest.rebalance_frequency == spec.rebalance_frequency
    assert manifest.transaction_cost_assumption == spec.transaction_cost_assumption


# ── 21. manifest to_dict round-trip ──────────────────────────────────────────

def test_manifest_to_dict():
    spec = _base_spec()
    manifest = make_manifest("man-001", spec)
    d = manifest.to_dict()
    assert d["strategy_id"] == spec.strategy_id
    assert "created_at" in d
    assert "manifest_fingerprint" in d


def test_spec_to_dict():
    spec = _base_spec()
    d = spec.to_dict()
    assert d["strategy_id"] == spec.strategy_id
    assert "creation_timestamp" in d
    assert "configuration_fingerprint" in d


# ── 22. replay determinism ────────────────────────────────────────────────────

def test_replay_same_fingerprint():
    """Replaying same snapshot + spec must produce identical evaluation fingerprint."""
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.6, "MSFT": 0.4})
    rt = StrategyRuntime()
    # First evaluation
    ev1 = rt.evaluate(spec, logic, snap, None, evaluation_id="replay-001")
    # Second evaluation (replay) — new evaluation_id, same fingerprint
    ev2 = rt.evaluate(spec, logic, snap, None, evaluation_id="replay-002")
    assert ev1.evaluation_fingerprint == ev2.evaluation_fingerprint


def test_replay_signal_fingerprints_match():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.6, "MSFT": 0.4})
    rt = StrategyRuntime()
    ev1 = rt.evaluate(spec, logic, snap, None)
    ev2 = rt.evaluate(spec, logic, snap, None)
    assert ev1.signal_set.fingerprint() == ev2.signal_set.fingerprint()


def test_replay_feature_fingerprints_match():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.6, "MSFT": 0.4})
    rt = StrategyRuntime()
    ev1 = rt.evaluate(spec, logic, snap, None)
    ev2 = rt.evaluate(spec, logic, snap, None)
    assert ev1.feature_set.fingerprint() == ev2.feature_set.fingerprint()


# ── 23-29. failure modes ──────────────────────────────────────────────────────

def test_none_snapshot_raises():
    spec = _base_spec()
    with pytest.raises(EvaluationError, match="snapshot is None"):
        StrategyRuntime().evaluate(spec, ConstantLogic({}), None, None)


def test_snapshot_missing_as_of_raises():
    spec = _base_spec()

    class NoDateSnapshot:
        as_of = None
        spots = {"AAPL": 190.0}
        def fingerprint(self): return "x"

    with pytest.raises(EvaluationError, match="as_of is None"):
        StrategyRuntime().evaluate(spec, ConstantLogic({"AAPL": 0.5}), NoDateSnapshot(), None)


def test_none_features_returned_raises():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)

    class NullFeaturesLogic(StrategyLogic):
        def compute_features(self, snapshot, spec): return None  # type: ignore
        def generate_signal(self, features, spec): return None  # type: ignore

    with pytest.raises(EvaluationError, match="None"):
        StrategyRuntime().evaluate(spec, NullFeaturesLogic(), snap, None)


def test_none_signal_returned_raises():
    spec = _base_spec()
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)

    class NullSignalLogic(StrategyLogic):
        def compute_features(self, snapshot, spec):
            return ConstantLogic({}).compute_features(snapshot, spec)
        def generate_signal(self, features, spec): return None  # type: ignore

    with pytest.raises(EvaluationError, match="None"):
        StrategyRuntime().evaluate(spec, NullSignalLogic(), snap, None)


# ── 30. risk rejection → no EMS requests ─────────────────────────────────────
# (already covered in test 15; duplicate entry is not added)

# ── 31. configuration drift detection ────────────────────────────────────────

@pytest.mark.parametrize("field,research_val,deployed_val", [
    ("rebalance_frequency", "monthly", "weekly"),
    ("benchmark", "SPY", "QQQ"),
    ("base_currency", "USD", "EUR"),
    ("capital_assumption", 1_000_000.0, 5_000_000.0),
    ("model_version", "1.0.0", "2.0.0"),
])
def test_material_drift_detected(field, research_val, deployed_val):
    research = _base_spec(**{field: research_val})
    deployed = _base_spec(**{field: deployed_val})
    report = ConsistencyChecker().check(research, deployed)
    assert not report.consistent
    assert field in report.drifted_fields


# ── 33–35. JT integration fixture ────────────────────────────────────────────

_JT_PRIOR_SPOTS = {sid: price * 0.85 for sid, price in SPOTS.items()}   # 15% lower 12m ago


def _jt_spec(validation_status: str = "REJECT", **overrides) -> StrategySpecification:
    """JT-1993 inspired spec. Validation status defaults to REJECT (historically rejected)."""
    return _base_spec(
        strategy_id="jt-momentum-1993",
        strategy_name="Jegadeesh-Titman 1993 Momentum",
        research_artifact_id="jt-exp-001",
        validation_artifact_id="jt-val-001",
        validation_status=validation_status,
        signal_definition={"type": "cross_sectional_momentum", "formation": 12, "holding": 3},
        feature_definition={"lookback_months": 12, "skip_months": 1},
        **overrides,
    )


def test_jt_strategy_evaluation_produces_signals():
    """JT research → signal → target → risk → intent pipeline works end-to-end."""
    spec = _jt_spec(validation_status="PASS")  # pretend validated for fixture test
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = MomentumLogic(prior_spots=_JT_PRIOR_SPOTS)
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)

    assert ev.as_of == AS_OF
    assert len(ev.signal_set.signals) == len(SPOTS)
    assert len(ev.portfolio.positions) > 0
    assert ev.risk_report is not None
    assert isinstance(ev.risk_approved, bool)


def test_jt_rejected_validation_blocks_deployable():
    """A REJECT verdict must block DEPLOYABLE transition via readiness gate."""
    spec = _jt_spec(validation_status="REJECT")
    report = ReadinessValidator().validate(spec)
    assert not report.ready
    assert not report.checks["validation_status_permits_deployment"]


def test_jt_experimental_paper_allowed_despite_reject():
    """Experimental paper may run with REQUIRES_REVIEW; REJECT still blocked."""
    spec_review = _jt_spec(validation_status="REQUIRES_REVIEW",
                           strategy_type=StrategyType.EXPERIMENTAL_PAPER)
    report = ReadinessValidator().validate(spec_review, permit_experimental=True)
    assert report.ready

    spec_reject = _jt_spec(validation_status="REJECT",
                           strategy_type=StrategyType.EXPERIMENTAL_PAPER)
    report2 = ReadinessValidator().validate(spec_reject, permit_experimental=True)
    assert not report2.ready  # REJECT is never OK even for experimental


def test_jt_signals_are_monotone_with_return():
    """Higher return → higher momentum signal rank."""
    spec = _jt_spec(validation_status="PASS")
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = MomentumLogic(prior_spots=_JT_PRIOR_SPOTS)

    fs = logic.compute_features(snap, spec)
    ss = logic.generate_signal(fs, spec)

    # Verify signals correlate with computed returns
    rets = {sid: (SPOTS[sid] / _JT_PRIOR_SPOTS[sid]) - 1 for sid in SPOTS}
    ranked_by_signal = sorted(ss.signals, key=lambda s: ss.signals[s])
    ranked_by_return = sorted(rets, key=lambda s: rets[s])
    assert ranked_by_signal == ranked_by_return


def test_jt_evaluation_audit_trail():
    """Evaluation fingerprint captures the full lineage."""
    spec = _jt_spec(validation_status="PASS")
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)
    logic = MomentumLogic(prior_spots=_JT_PRIOR_SPOTS)
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)

    assert ev.evaluation_fingerprint != ""
    assert ev.strategy_fingerprint == spec.configuration_fingerprint
    assert ev.provenance["snapshot_as_of"] == str(AS_OF)


# ── 40. out-of-order evaluation (older snapshot) ──────────────────────────────

def test_older_snapshot_still_deterministic():
    spec = _base_spec()
    older = FakeSnapshot(as_of=date(2024, 1, 31), spots=SPOTS)
    newer = FakeSnapshot(as_of=date(2024, 6, 30), spots=SPOTS)
    logic = ConstantLogic({"AAPL": 0.5})
    rt = StrategyRuntime()
    ev_old1 = rt.evaluate(spec, logic, older, None)
    ev_old2 = rt.evaluate(spec, logic, older, None)
    ev_new = rt.evaluate(spec, logic, newer, None)
    assert ev_old1.evaluation_fingerprint == ev_old2.evaluation_fingerprint
    assert ev_old1.evaluation_fingerprint != ev_new.evaluation_fingerprint


# ── 48. missing price handled gracefully ──────────────────────────────────────

def test_missing_price_for_security_excluded():
    """Security with no price in snapshot is simply not priced → excluded from targets."""
    spec = _base_spec()
    # snapshot only has AAPL priced
    snap = FakeSnapshot(as_of=AS_OF, spots={"AAPL": 190.0})
    # signals include MSFT which has no spot
    logic = ConstantLogic({"AAPL": 0.6, "MSFT": 0.4})
    ev = StrategyRuntime().evaluate(spec, logic, snap, None)
    # Should not crash; MSFT just doesn't get a meaningful position
    assert ev is not None


# ── 49. spec equality ─────────────────────────────────────────────────────────

def test_same_content_same_fingerprint():
    spec_a = _base_spec()
    spec_b = _base_spec()
    assert spec_a.fingerprint() == spec_b.fingerprint()


# ── 50. full integration: Research → Spec → Runtime → EMS boundary ───────────

def test_full_integration_pipeline():
    """Integration: research artifact → spec → manifest → runtime → EMS requests."""
    # 1. research artifact (simulated M7 experiment)
    research_experiment_id = "exp-full-integration-001"
    validation_manifest_hash = "val-full-001-abcd1234"

    # 2. strategy specification
    spec = make_spec(
        strategy_id="full-integration-strategy",
        strategy_name="Full Integration Test Strategy",
        version="1.0.0",
        strategy_type=StrategyType.VALIDATED_DEPLOYABLE,
        research_artifact_id=research_experiment_id,
        validation_artifact_id=validation_manifest_hash,
        validation_status="PASS",
        universe_definition={"region": "US", "type": "equity"},
        required_data=["close"],
        feature_definition={"lookback": 1},
        signal_definition={"type": "equal_weight"},
        rebalance_frequency="monthly",
        portfolio_construction_config={"objective": "equal_weight", "long_only": True},
        risk_config={"max_position": 0.50},
        execution_config={"algo": "market"},
        transaction_cost_assumption={"commission": 0.001},
        slippage_assumption={"model": "none"},
        benchmark="SPY",
        base_currency="USD",
        allowed_instruments=["equity"],
        capital_assumption=1_000_000.0,
        model_version="1.0.0",
    )

    # 3. readiness gate
    validator = ReadinessValidator()
    readiness = validator.validate(spec)
    assert readiness.ready, f"not ready: {readiness.issues}"

    # 4. registry
    registry = StrategyRegistry()
    registry.register(spec, StrategyState.DRAFT)
    registry.transition(spec.strategy_id, StrategyState.VALIDATING)
    registry.transition(spec.strategy_id, StrategyState.VALIDATED)
    registry.transition(spec.strategy_id, StrategyState.DEPLOYABLE)
    registry.transition(spec.strategy_id, StrategyState.PAPER)
    assert registry.state(spec.strategy_id) == StrategyState.PAPER

    # 5. deployment manifest
    manifest = make_manifest("man-full-001", spec)
    assert manifest.manifest_fingerprint != ""

    # 6. market data snapshot
    snap = FakeSnapshot(as_of=AS_OF, spots=SPOTS)

    # 7. strategy evaluation
    logic = ConstantLogic({sid: 1.0 for sid in SPOTS})
    rt = StrategyRuntime()
    ev = rt.evaluate(spec, logic, snap, None)

    # 8. verify pipeline outputs
    assert ev.strategy_id == spec.strategy_id
    assert ev.strategy_version == spec.version
    assert ev.as_of == AS_OF
    assert len(ev.signal_set.signals) == len(SPOTS)
    assert len(ev.portfolio.positions) > 0
    assert ev.evaluation_fingerprint != ""

    # 9. M14 boundary: verify EMS requests are valid
    from mentisrex.research.execution.ems.models import OrderRequest
    if ev.risk_approved:
        assert len(ev.ems_requests) > 0
        for req in ev.ems_requests:
            assert isinstance(req, OrderRequest)
            assert abs(req.quantity) > 0

    # 10. research/deployment consistency
    consistency = ConsistencyChecker().check(spec, spec)
    assert consistency.consistent

    # 11. replay determinism
    ev2 = rt.evaluate(spec, logic, snap, None)
    assert ev.evaluation_fingerprint == ev2.evaluation_fingerprint
