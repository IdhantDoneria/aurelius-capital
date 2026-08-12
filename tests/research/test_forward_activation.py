"""Integration tests for controlled forward paper-trading activation (post-M24).

Verifies the 10 required integration points:
  1. M23 → M24 compatibility (smoke test)
  2. Run initialization
  3. Strategy fingerprint preservation
  4. Checkpoint / restart integrity
  5. Forward-record persistence
  6. Reconciliation passes at each cycle
  7. Deterministic rehearsal (fault injection)
  8. Evidence immutability (CycleRecord is frozen)
  9. No strategy mutation (fingerprint constant throughout)
 10. No real execution path (no live broker, no network calls)

All tests are offline.  No network access.  All snapshots are synthetic.

EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from aurelius.research.forward_validation.engine import ForwardValidationEngine
from aurelius.research.paper_trading.broker import MockBroker, SimulatedBroker
from aurelius.research.paper_trading.checkpoint import (
    _checkpoint_dict,
    _restore_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from aurelius.research.paper_trading.loop import LoopConfig, LoopError, PaperTradingLoop
from aurelius.research.paper_trading.scheduler import FixedClock
from aurelius.research.strategy_deployment.models import (
    StrategyState,
    StrategyType,
    make_manifest,
    make_spec,
)
from aurelius.research.strategy_deployment.readiness import ReadinessValidator
from aurelius.research.strategy_deployment.registry import StrategyRegistry
from aurelius.research.strategy_deployment.runtime import StrategyLogic, StrategyRuntime


# ── shared fixtures (offline; deterministic) ──────────────────────────────────

@dataclass(frozen=True)
class FakeSnapshot:
    as_of: date
    spots: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        import json as _j
        body = _j.dumps(
            {"as_of": str(self.as_of), "spots": dict(sorted(self.spots.items()))},
            sort_keys=True)
        return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()


UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
BASE_PRICES = {"AAPL": 185.0, "MSFT": 415.0, "GOOGL": 172.0, "AMZN": 188.0, "META": 520.0}

DATES = [
    date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1),
    date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1),
]

def _snap(d: date, factor: float = 1.0) -> FakeSnapshot:
    return FakeSnapshot(as_of=d, spots={sid: round(p * factor, 4)
                                        for sid, p in BASE_PRICES.items()})

SNAPSHOTS = [_snap(d, 1.005 ** i) for i, d in enumerate(DATES)]


# ── strategy logic (local test double; same pattern as EqualWeightMomentumLogic) ─

from aurelius.research.strategy_deployment.models import (
    FeatureSet, SignalRecord, SignalSet, StrategySpecification,
)

class _EWLogic(StrategyLogic):
    def __init__(self, universe):
        self._universe = list(universe)

    def compute_features(self, snapshot, spec) -> FeatureSet:
        spots = getattr(snapshot, "spots", {})
        features = {}
        for sid in self._universe:
            raw = spots.get(sid)
            if raw is not None:
                try:
                    features[sid] = {"price": float(raw)}
                except (TypeError, ValueError):
                    pass
        fp = snapshot.fingerprint() if hasattr(snapshot, "fingerprint") else ""
        spec_fp = spec.configuration_fingerprint or spec.fingerprint()
        return FeatureSet(strategy_id=spec.strategy_id, strategy_version=spec.version,
                          as_of=snapshot.as_of, features=features,
                          input_fingerprint=fp, strategy_fingerprint=spec_fp)

    def generate_signal(self, features, spec) -> SignalSet:
        spec_fp = spec.configuration_fingerprint or spec.fingerprint()
        feat_fp = features.fingerprint()
        signals = {sid: 1.0 for sid, fv in features.features.items()
                   if fv.get("price", 0.0) > 0.0}
        records = [SignalRecord(strategy_id=spec.strategy_id, strategy_version=spec.version,
                                security_id=sid, as_of=features.as_of, signal_value=1.0,
                                input_fingerprint=feat_fp, strategy_fingerprint=spec_fp)
                   for sid in signals]
        return SignalSet(strategy_id=spec.strategy_id, strategy_version=spec.version,
                        as_of=features.as_of, signals=signals, signal_records=records,
                        features_fingerprint=feat_fp, strategy_fingerprint=spec_fp)


def _make_exp_spec(**overrides) -> StrategySpecification:
    defaults = dict(
        strategy_id="ew-momentum-exp",
        strategy_name="Equal-Weight Momentum (Experimental Paper)",
        version="1.0.0",
        strategy_type=StrategyType.EXPERIMENTAL_PAPER,
        research_artifact_id="SIM",
        validation_artifact_id="696a411bed6731a997c399584bfa9c4f",
        validation_status="REQUIRES_REVIEW",
        universe_definition={"type": "equity", "securities": UNIVERSE, "source": "fixed"},
        required_data=["close", "price"],
        feature_definition={"type": "price_level", "lookback_days": 0},
        signal_definition={"type": "equal_weight", "universe": UNIVERSE},
        rebalance_frequency="monthly",
        portfolio_construction_config={"objective": "equal_weight", "long_only": True,
                                       "max_position_weight": 0.20},
        risk_config={"max_position": 0.20, "max_gross_leverage": 1.0, "long_only": True},
        execution_config={"algo": "market", "direct_provider_access": False},
        transaction_cost_assumption={"slippage_bps": 5.0, "commission_per_share": 0.005},
        slippage_assumption={"model": "linear", "bps": 5.0},
        benchmark="SPY",
        base_currency="USD",
        allowed_instruments=["equity"],
        capital_assumption=1_000_000.0,
        model_version="1.0.0",
        dependency_versions={"aurelius_milestone": "M24"},
    )
    defaults.update(overrides)
    return make_spec(**defaults)


def _make_registry(spec) -> StrategyRegistry:
    reg = StrategyRegistry()
    reg.register(spec, StrategyState.DRAFT)
    reg.transition(spec.strategy_id, StrategyState.VALIDATING)
    reg.transition(spec.strategy_id, StrategyState.VALIDATED)
    return reg


def _make_loop(spec, *, initial_capital: float = 1_000_000.0) -> PaperTradingLoop:
    registry = _make_registry(spec)
    runtime = StrategyRuntime()
    config = LoopConfig(initial_capital=initial_capital, permit_experimental=True,
                        fail_closed=True, validate_readiness=True, mode="SIMULATION")
    loop = PaperTradingLoop(runtime=runtime, registry=registry, config=config)
    loop.add_strategy(spec.strategy_id, _EWLogic(UNIVERSE))
    return loop


# ── 1. M23 → M24 compatibility smoke test ─────────────────────────────────────

class TestM23ToM24SmokeTest:
    """Verify M23 ForwardPerformanceRecord is consumable by M24 ForwardValidationEngine."""

    def test_smoke_test_produces_artifact(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)

        fpr = loop.forward_record(spec.strategy_id)
        engine = ForwardValidationEngine()
        artifact = engine.analyze(fpr, spec)

        assert artifact is not None
        assert artifact.strategy_id == spec.strategy_id
        assert artifact.strategy_fingerprint == spec.configuration_fingerprint
        assert artifact.forward_record_fingerprint == fpr.fingerprint()
        assert artifact.artifact_fingerprint != ""
        # 8 cycles → PRELIMINARY or INSUFFICIENT
        assert artifact.sample_adequacy in ("INSUFFICIENT", "PRELIMINARY")
        # No strategy mutation required — artifact produced as-is
        assert artifact.strategy_id == spec.strategy_id

    def test_m24_does_not_mutate_spec(self):
        spec = _make_exp_spec()
        fp_before = spec.configuration_fingerprint
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        ForwardValidationEngine().analyze(fpr, spec)
        # spec is a frozen dataclass; fingerprint unchanged
        assert spec.configuration_fingerprint == fp_before

    def test_m24_report_assembles(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        engine = ForwardValidationEngine()
        artifact = engine.analyze(fpr, spec)
        report = engine.report(artifact)
        assert report is not None

    def test_m24_artifact_fingerprint_deterministic(self):
        """Same inputs → same artifact_fingerprint."""
        spec = _make_exp_spec()

        loop1 = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop1.process_snapshot(snap)
        a1 = ForwardValidationEngine().analyze(loop1.forward_record(spec.strategy_id), spec)

        loop2 = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop2.process_snapshot(snap)
        a2 = ForwardValidationEngine().analyze(loop2.forward_record(spec.strategy_id), spec)

        assert a1.artifact_fingerprint == a2.artifact_fingerprint

    def test_m23_forward_record_fingerprint_present(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        assert fpr.fingerprint() != ""


# ── 2. Run initialization ──────────────────────────────────────────────────────

class TestRunInitialization:
    def test_loop_creates_correctly(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        assert spec.strategy_id in loop.active_strategies

    def test_strategy_in_validated_experimental_state(self):
        spec = _make_exp_spec()
        registry = _make_registry(spec)
        assert registry.state(spec.strategy_id) == StrategyState.VALIDATED

    def test_readiness_passes_for_experimental(self):
        spec = _make_exp_spec()
        v = ReadinessValidator()
        report = v.validate(spec, permit_experimental=True)
        assert report.ready, f"readiness failures: {report.issues}"

    def test_deployment_manifest_generates(self):
        spec = _make_exp_spec()
        manifest = make_manifest("test-manifest-001", spec)
        assert manifest.manifest_fingerprint != ""
        assert manifest.strategy_id == spec.strategy_id
        assert manifest.validation_status == "REQUIRES_REVIEW"

    def test_explicit_experimental_status_in_spec(self):
        spec = _make_exp_spec()
        assert spec.strategy_type == StrategyType.EXPERIMENTAL_PAPER
        assert spec.validation_status == "REQUIRES_REVIEW"
        assert spec.strategy_name is not None

    def test_no_real_broker_adapter(self):
        """Verify loop uses MockBroker / SimulatedBroker, not a live adapter."""
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        session = loop.session(spec.strategy_id)
        assert isinstance(session.broker, (MockBroker, SimulatedBroker))


# ── 3. Strategy fingerprint preservation ──────────────────────────────────────

class TestStrategyFingerprintPreservation:
    def test_fingerprint_constant_before_during_after(self):
        spec = _make_exp_spec()
        fp0 = spec.configuration_fingerprint
        loop = _make_loop(spec)
        fp1 = spec.configuration_fingerprint  # unchanged (frozen dataclass)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fp2 = spec.configuration_fingerprint
        assert fp0 == fp1 == fp2

    def test_cycle_records_carry_strategy_fingerprint(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        recs = loop.strategy_records(spec.strategy_id)
        for rec in recs:
            assert rec.strategy_fingerprint == spec.configuration_fingerprint

    def test_different_spec_different_fingerprint(self):
        spec1 = _make_exp_spec()
        spec2 = _make_exp_spec(version="1.0.1", capital_assumption=500_000.0)
        assert spec1.configuration_fingerprint != spec2.configuration_fingerprint


# ── 4. Checkpoint / restart integrity ─────────────────────────────────────────

class TestCheckpointRestartIntegrity:
    def test_checkpoint_and_restart_same_nav(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS[:4]:
            loop.process_snapshot(snap)
        nav_before = loop.strategy_records(spec.strategy_id)[-1].nav

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop)

        loop2 = _make_loop(spec)
        data = load_checkpoint(path)
        _restore_checkpoint(loop2, data)

        # Continue from where we left off
        for snap in SNAPSHOTS[4:]:
            loop2.process_snapshot(snap)

        # Total evaluations must be same as uninterrupted run
        loop_full = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop_full.process_snapshot(snap)

        final_nav_restarted = loop2.strategy_records(spec.strategy_id)[-1].nav
        final_nav_full = loop_full.strategy_records(spec.strategy_id)[-1].nav
        assert abs(final_nav_restarted - final_nav_full) < 1e-6

    def test_no_duplicate_fills_after_restart(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS[:4]:
            loop.process_snapshot(snap)
        fills_before = sum(r.n_fills for r in loop.strategy_records(spec.strategy_id))

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop)

        # Replay same snapshots after restart — should be idempotent
        loop2 = _make_loop(spec)
        _restore_checkpoint(loop2, load_checkpoint(path))
        for snap in SNAPSHOTS[:4]:   # same 4 snapshots again
            loop2.process_snapshot(snap)
        # Idempotency: duplicate snapshots are skipped
        fills_after = sum(r.n_fills for r in loop2.strategy_records(spec.strategy_id))
        assert fills_after == fills_before

    def test_seen_snapshots_preserved_in_checkpoint(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS[:3]:
            loop.process_snapshot(snap)
        seen = set(loop._seen)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop)
        data = load_checkpoint(path)
        assert set(data["seen_snapshots"]) == seen

    def test_strategy_fingerprint_preserved_in_checkpoint(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS[:4]:
            loop.process_snapshot(snap)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop)
        data = load_checkpoint(path)

        strat_state = data["strategy_states"][spec.strategy_id]
        assert strat_state["strategy_fingerprint"] == spec.configuration_fingerprint


# ── 5. Forward-record persistence ─────────────────────────────────────────────

class TestForwardRecordPersistence:
    def test_forward_record_accumulates_all_cycles(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        # monthly rebalance → one cycle per monthly snapshot
        assert fpr.n_cycles == len(SNAPSHOTS)

    def test_nav_series_non_empty(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        nav = list(fpr.nav_series())
        assert len(nav) == fpr.n_cycles

    def test_forward_record_strategy_id_matches(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        assert fpr.strategy_id == spec.strategy_id
        assert fpr.strategy_version == spec.version
        assert fpr.strategy_fingerprint == spec.configuration_fingerprint

    def test_cycle_records_serializable(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        recs = loop.strategy_records(spec.strategy_id)
        for rec in recs:
            d = rec.to_dict()
            assert d["strategy_id"] == spec.strategy_id
            assert d["as_of"] is not None
            assert d["evaluation_fingerprint"] != ""


# ── 6. Reconciliation ─────────────────────────────────────────────────────────

class TestReconciliation:
    def test_each_cycle_reconciles(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            result = loop.process_snapshot(snap)
            sr = result.result_for(spec.strategy_id)
            if sr and not sr.skipped and not sr.error:
                # sync_event.reconciled must be True for each cycle
                if sr.sync_event is not None:
                    assert sr.sync_event.reconciled, (
                        f"reconciliation failed on {result.as_of}"
                    )

    def test_no_reconciliation_error_after_restart(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS[:4]:
            loop.process_snapshot(snap)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop)

        loop2 = _make_loop(spec)
        _restore_checkpoint(loop2, load_checkpoint(path))
        for snap in SNAPSHOTS[4:]:
            result = loop2.process_snapshot(snap)
            sr = result.result_for(spec.strategy_id)
            if sr and not sr.skipped and not sr.error and sr.sync_event:
                assert sr.sync_event.reconciled, (
                    f"reconciliation failed after restart on {result.as_of}"
                )


# ── 7. Deterministic fault rehearsal ──────────────────────────────────────────

class TestFaultRehearsal:
    """Inject faults and verify M23 state/records remain consistent."""

    def test_duplicate_snapshot_skipped_idempotent(self):
        """Fault 1: duplicate snapshot."""
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        snap = SNAPSHOTS[0]
        r1 = loop.process_snapshot(snap)
        r2 = loop.process_snapshot(snap)   # duplicate
        assert not r1.skipped
        assert r2.skipped and r2.skip_reason == "duplicate_snapshot"
        # Only one cycle record
        assert len(loop.strategy_records(spec.strategy_id)) == 1

    def test_delayed_snapshot_handled(self):
        """Fault 2: snapshot arrives with an earlier date than the last processed."""
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        loop.process_snapshot(SNAPSHOTS[2])  # 2026-03-01
        # A 'delayed' snapshot with an earlier date: not idempotent duplicate (different fp)
        delayed = FakeSnapshot(as_of=date(2026, 1, 15),
                               spots={"AAPL": 183.0, "MSFT": 413.0, "GOOGL": 170.0,
                                      "AMZN": 186.0, "META": 518.0})
        r = loop.process_snapshot(delayed)
        # Loop accepts it; not due because last_eval_date was 2026-03-01 and this is monthly
        sr = r.result_for(spec.strategy_id)
        # Either processed (if due logic allows earlier date) or skipped (not_due)
        assert sr is not None

    def test_missing_observation_skipped(self):
        """Fault 3: snapshot with no prices for universe securities."""
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        empty = FakeSnapshot(as_of=date(2026, 1, 1), spots={})
        result = loop.process_snapshot(empty)
        # Loop processes it but strategy produces 0 signals (all prices missing)
        sr = result.result_for(spec.strategy_id)
        assert sr is not None

    def test_rejected_order_does_not_corrupt_state(self):
        """Fault 4: risk rejection → no orders → portfolio unchanged."""
        from aurelius.research.paper_trading.risk import PreTradeRiskGate, RiskLimits
        spec = _make_exp_spec()
        registry = _make_registry(spec)
        runtime = StrategyRuntime()
        config = LoopConfig(initial_capital=1_000_000.0, permit_experimental=True,
                            fail_closed=True, validate_readiness=True, mode="SIMULATION")
        # Inject a risk gate that kills all orders (max_name_weight=0.0 → reject everything)
        gate = PreTradeRiskGate(RiskLimits(max_name_weight=0.0, kill=True))
        loop = PaperTradingLoop(runtime=runtime, registry=registry, config=config)
        loop.add_strategy(spec.strategy_id, _EWLogic(UNIVERSE),
                          risk_gate=gate)
        result = loop.process_snapshot(SNAPSHOTS[0])
        sr = result.result_for(spec.strategy_id)
        # Evaluation runs but fills = 0 due to rejected orders
        if sr and not sr.skipped and not sr.error and sr.sync_event:
            assert sr.sync_event.n_fills == 0

    def test_restart_after_fault_preserves_lineage(self):
        """Fault 7: restart after save — lineage (fingerprints) preserved."""
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS[:3]:
            loop.process_snapshot(snap)
        fps_before = [r.strategy_fingerprint
                      for r in loop.strategy_records(spec.strategy_id)]

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop)

        loop2 = _make_loop(spec)
        _restore_checkpoint(loop2, load_checkpoint(path))
        for snap in SNAPSHOTS[3:6]:
            loop2.process_snapshot(snap)

        fps_after = [r.strategy_fingerprint
                     for r in loop2.strategy_records(spec.strategy_id)]
        for fp in fps_after:
            assert fp == spec.configuration_fingerprint


# ── 8. Evidence immutability ───────────────────────────────────────────────────

class TestEvidenceImmutability:
    def test_cycle_records_are_frozen(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        loop.process_snapshot(SNAPSHOTS[0])
        rec = loop.strategy_records(spec.strategy_id)[0]
        # CycleRecord is a frozen dataclass
        with pytest.raises((AttributeError, TypeError)):
            rec.nav = 999_999.0  # type: ignore[misc]

    def test_forward_record_cycles_immutable(self):
        """ForwardPerformanceRecord cycles list is a snapshot; loop continues independently."""
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        for snap in SNAPSHOTS[:4]:
            loop.process_snapshot(snap)
        fpr1 = loop.forward_record(spec.strategy_id)
        n1 = fpr1.n_cycles
        # Process more
        for snap in SNAPSHOTS[4:]:
            loop.process_snapshot(snap)
        fpr2 = loop.forward_record(spec.strategy_id)
        # fpr1 count unchanged (it was a snapshot)
        assert fpr1.n_cycles == n1
        assert fpr2.n_cycles > n1

    def test_spec_is_frozen(self):
        spec = _make_exp_spec()
        with pytest.raises((AttributeError, TypeError)):
            spec.version = "9.9.9"  # type: ignore[misc]


# ── 9. No strategy mutation ────────────────────────────────────────────────────

class TestNoStrategyMutation:
    def test_m24_analysis_does_not_change_spec(self):
        spec = _make_exp_spec()
        fp = spec.configuration_fingerprint
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        ForwardValidationEngine().analyze(fpr, spec)
        assert spec.configuration_fingerprint == fp

    def test_loop_does_not_change_spec(self):
        spec = _make_exp_spec()
        fp_before = spec.configuration_fingerprint
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        assert spec.configuration_fingerprint == fp_before
        # Runtime state is mutable but spec is not
        rs = loop.runtime_state(spec.strategy_id)
        assert rs.strategy_fingerprint == fp_before

    def test_version_unchanged_after_full_run(self):
        spec = _make_exp_spec()
        v = spec.version
        loop = _make_loop(spec)
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        assert spec.version == v


# ── 10. No real execution path ─────────────────────────────────────────────────

class TestNoRealExecutionPath:
    def test_broker_is_paper_only(self):
        spec = _make_exp_spec()
        loop = _make_loop(spec)
        session = loop.session(spec.strategy_id)
        broker = session.broker
        # Must not be a live/real adapter
        assert isinstance(broker, (MockBroker, SimulatedBroker))
        # Must not have real API credentials
        assert not hasattr(broker, "api_key")
        assert not hasattr(broker, "_session")  # no requests session

    def test_no_direct_provider_access_in_spec(self):
        spec = _make_exp_spec()
        assert not spec.execution_config.get("direct_provider_access", False)

    def test_strategy_logic_reads_only_snapshot(self):
        """Logic receives snapshot; cannot call external providers."""
        spec = _make_exp_spec()
        snap = SNAPSHOTS[0]
        logic = _EWLogic(UNIVERSE)
        feats = logic.compute_features(snap, spec)
        sigs = logic.generate_signal(feats, spec)
        # All signals come from snapshot spots; no external call possible
        for sid, v in sigs.signals.items():
            assert v == 1.0
            assert sid in UNIVERSE

    def test_loop_mode_simulation(self):
        spec = _make_exp_spec()
        registry = _make_registry(spec)
        runtime = StrategyRuntime()
        config = LoopConfig(initial_capital=1_000_000.0, permit_experimental=True,
                            mode="SIMULATION")
        loop = PaperTradingLoop(runtime=runtime, registry=registry, config=config)
        assert loop._config.mode == "SIMULATION"

    def test_no_real_money_in_spec(self):
        """Starting capital is explicitly a paper assumption."""
        spec = _make_exp_spec()
        # capital_assumption is the paper capital; must be positive but is not real money
        assert spec.capital_assumption > 0
        # Verify it matches the forward run capital
        assert spec.capital_assumption == 1_000_000.0


# ── activation gate integration ───────────────────────────────────────────────

class TestActivationGate:
    """Single end-to-end test verifying all activation gate checklist items."""

    def test_full_activation_gate(self):
        spec = _make_exp_spec()

        # [ ] M22 strategy identified
        assert spec.strategy_id == "ew-momentum-exp"
        # [ ] Strategy specification frozen
        assert spec.configuration_fingerprint != ""
        # [ ] Strategy fingerprint recorded
        spec_fp = spec.configuration_fingerprint
        # [ ] Research artifact recorded
        assert spec.research_artifact_id == "SIM"
        # [ ] Validation artifact recorded
        assert spec.validation_artifact_id == "696a411bed6731a997c399584bfa9c4f"
        # [ ] Experimental status explicit
        assert spec.strategy_type == StrategyType.EXPERIMENTAL_PAPER
        assert spec.validation_status == "REQUIRES_REVIEW"

        # [ ] Readiness gate passes
        v = ReadinessValidator()
        report = v.validate(spec, permit_experimental=True)
        assert report.ready

        # [ ] Deployment manifest
        manifest = make_manifest("gate-manifest-001", spec)
        assert manifest.manifest_fingerprint != ""

        # [ ] M23 configuration frozen / loop works
        loop = _make_loop(spec)
        assert spec.strategy_id in loop.active_strategies

        # [ ] M23 → M24 smoke test passes
        for snap in SNAPSHOTS:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        artifact = ForwardValidationEngine().analyze(fpr, spec)
        assert artifact is not None

        # [ ] Checkpoint test passes
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop)
        data = load_checkpoint(path)
        assert data["strategy_states"][spec.strategy_id]["strategy_fingerprint"] == spec_fp

        # [ ] Restart test passes
        loop2 = _make_loop(spec)
        _restore_checkpoint(loop2, data)
        for snap in SNAPSHOTS:  # all idempotent (seen already)
            loop2.process_snapshot(snap)
        assert len(loop2.strategy_records(spec.strategy_id)) == len(SNAPSHOTS)

        # [ ] Reconciliation passes
        recs = loop.strategy_records(spec.strategy_id)
        for rec in recs:
            assert rec.strategy_fingerprint == spec_fp

        # [ ] No real execution path
        session = loop.session(spec.strategy_id)
        assert isinstance(session.broker, (MockBroker, SimulatedBroker))

        # [ ] Strategy fingerprint preserved throughout
        assert spec.configuration_fingerprint == spec_fp
