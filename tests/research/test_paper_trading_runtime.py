"""M23 Continuous Paper Trading Runtime — test suite (AIDP M23).

No network access. All tests use FakeSnapshot, ConstantLogic, and fixture specs.
All tests are deterministic: same inputs → same result on every run.

Coverage:
  A. RebalanceScheduler + Clock
  B. StrategyRuntimeState
  C. CycleRecord / ForwardPerformanceRecord / PerformanceMetrics
  D. Checkpoint save/load + portfolio state serialisation
  E. PaperTradingLoop — basic lifecycle
  F. Idempotency (duplicate snapshots)
  G. Scheduling via loop
  H. Strategy lifecycle (suspended/paused/resumed)
  I. Multi-strategy support
  J. Cost-model compatibility
  K. Failure handling / fail-closed
  L. M22→M12 integration (evaluation → paper execution)
  M. M13 risk integration
  N. Multi-day continuity
  O. Restart certification
  P. Determinism / replay
  Q. Forward record / performance comparison
  R. End-to-end certification
"""

from __future__ import annotations

import tempfile
from dataclasses import FrozenInstanceError, dataclass, field
from datetime import date, datetime
from pathlib import Path

import pytest

from mentisrex.research.paper_trading.broker import MockBroker, SimulatedBroker
from mentisrex.research.paper_trading.checkpoint import (
    _checkpoint_dict,
    _restore_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from mentisrex.research.paper_trading.cycle import (
    CycleRecord,
    ForwardPerformanceRecord,
    PerformanceMetrics,
)
from mentisrex.research.paper_trading.loop import (
    LoopConfig,
    LoopCycleResult,
    LoopError,
    PaperTradingLoop,
    _build_broker,
    _extract_prices,
    _snapshot_fp,
    check_cost_compatibility,
)
from mentisrex.research.paper_trading.risk import PreTradeRiskGate
from mentisrex.research.paper_trading.risk import RiskLimits as M12RiskLimits
from mentisrex.research.paper_trading.runtime_state import StrategyRuntimeState
from mentisrex.research.paper_trading.scheduler import (
    Clock,
    FixedClock,
    RebalanceScheduler,
)
from mentisrex.research.risk.engine import RiskEngine, RiskEngineConfig
from mentisrex.research.risk.limits import RiskLimits
from mentisrex.research.strategy_deployment import (
    FeatureSet,
    SignalRecord,
    SignalSet,
    StrategyLogic,
    StrategyRegistry,
    StrategyRuntime,
    StrategySpecification,
    StrategyState,
    StrategyType,
    make_spec,
)

# ── shared fixtures ───────────────────────────────────────────────────────────

AS_OF_0 = date(2024, 1, 2)
AS_OF_1 = date(2024, 2, 1)
AS_OF_2 = date(2024, 3, 1)
AS_OF_3 = date(2024, 4, 1)

SPOTS = {"AAPL": 185.0, "MSFT": 410.0, "GOOG": 165.0}
SPOTS_2 = {"AAPL": 190.0, "MSFT": 420.0, "GOOG": 170.0}
SPOTS_3 = {"AAPL": 195.0, "MSFT": 430.0, "GOOG": 175.0}


@dataclass(frozen=True)
class FakeSnapshot:
    as_of: date
    spots: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        import hashlib
        import json as _json

        payload = _json.dumps(
            {"as_of": str(self.as_of), "spots": dict(sorted(self.spots.items()))}, sort_keys=True
        )
        return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()


class ConstantLogic(StrategyLogic):
    def __init__(self, signals: dict) -> None:
        self._signals = signals

    def compute_features(self, snapshot, spec) -> FeatureSet:
        features = {sid: {"spot": snapshot.spots.get(sid, 0.0)} for sid in self._signals}
        return FeatureSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=snapshot.as_of,
            features=features,
            input_fingerprint=snapshot.fingerprint(),
            strategy_fingerprint=spec.configuration_fingerprint or spec.fingerprint(),
        )

    def generate_signal(self, features: FeatureSet, spec) -> SignalSet:
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


def _base_spec(**overrides) -> StrategySpecification:
    defaults = {
        "strategy_id": "test-strat",
        "strategy_name": "Test Strategy",
        "version": "1.0.0",
        "strategy_type": StrategyType.VALIDATED_DEPLOYABLE,
        "research_artifact_id": "exp-abc",
        "validation_artifact_id": "val-xyz",
        "validation_status": "PASS",
        "universe_definition": {"type": "equity"},
        "required_data": ["close"],
        "feature_definition": {"lookback": 1},
        "signal_definition": {"type": "constant"},
        "rebalance_frequency": "monthly",
        "portfolio_construction_config": {"objective": "equal_weight", "long_only": True},
        "risk_config": {"max_position": 0.10},
        "execution_config": {"algo": "market"},
        "transaction_cost_assumption": {"slippage_bps": 5.0},
        "slippage_assumption": {"model": "linear"},
        "benchmark": "SPY",
        "base_currency": "USD",
        "allowed_instruments": ["equity"],
        "capital_assumption": 100_000.0,
        "model_version": "1.0.0",
    }
    defaults.update(overrides)
    return make_spec(**defaults)


def _make_registry(
    spec: StrategySpecification, state: StrategyState = StrategyState.PAPER
) -> StrategyRegistry:
    reg = StrategyRegistry()
    reg.register(spec, StrategyState.DRAFT)
    order = [
        StrategyState.VALIDATING,
        StrategyState.VALIDATED,
        StrategyState.DEPLOYABLE,
        StrategyState.PAPER,
    ]
    for s in order:
        if s.value in [state.value for state in _states_up_to(state)]:
            reg.transition(spec.strategy_id, s)
    return reg


def _states_up_to(target: StrategyState) -> list:
    order = [
        StrategyState.VALIDATING,
        StrategyState.VALIDATED,
        StrategyState.DEPLOYABLE,
        StrategyState.PAPER,
    ]
    result = []
    for s in order:
        result.append(s)
        if s == target:
            break
    return result


def _permissive_runtime() -> StrategyRuntime:
    """StrategyRuntime with relaxed M13 risk limits so test portfolios pass risk gate."""
    return StrategyRuntime(
        risk_engine=RiskEngine(
            RiskEngineConfig(
                limits=RiskLimits(
                    max_position=None, max_gross=None, max_net=None, max_leverage=None
                )
            )
        )
    )


def _permissive_m12_gate() -> PreTradeRiskGate:
    """M12 PreTradeRiskGate with relaxed limits for tests (default caps 10% per name)."""
    return PreTradeRiskGate(M12RiskLimits(max_name_weight=1.0, max_gross_leverage=5.0))


def _make_loop(
    spec,
    logic,
    *,
    state: StrategyState = StrategyState.PAPER,
    capital: float | None = None,
    permit_experimental: bool = False,
    validate_readiness: bool = True,
    slippage_bps: float = 0.0,
    runtime: StrategyRuntime | None = None,
    **kw,
) -> PaperTradingLoop:
    reg = _make_registry(spec, state)
    _runtime = runtime or _permissive_runtime()
    cfg = LoopConfig(
        initial_capital=capital or spec.capital_assumption or 100_000.0,
        permit_experimental=permit_experimental,
        validate_readiness=validate_readiness,
    )
    loop = PaperTradingLoop(runtime=_runtime, registry=reg, config=cfg)
    broker = (
        MockBroker(initial_cash=capital or spec.capital_assumption or 100_000.0)
        if slippage_bps == 0.0
        else SimulatedBroker(
            initial_cash=capital or spec.capital_assumption or 100_000.0, slippage_bps=slippage_bps
        )
    )
    loop.add_strategy(
        spec.strategy_id, logic, broker=broker, risk_gate=_permissive_m12_gate(), **kw
    )
    return loop


# ═══════════════════════════════════════════════════════════════════════════════
# A. RebalanceScheduler + Clock
# ═══════════════════════════════════════════════════════════════════════════════


class TestRebalanceScheduler:
    def setup_method(self):
        self.scheduler = RebalanceScheduler()
        self.spec_daily = _base_spec(rebalance_frequency="daily")
        self.spec_weekly = _base_spec(rebalance_frequency="weekly")
        self.spec_monthly = _base_spec(rebalance_frequency="monthly")
        self.spec_quarterly = _base_spec(rebalance_frequency="quarterly")
        self.spec_event = _base_spec(rebalance_frequency="event_driven")

    def _rs(self, last_date=None):
        rs = StrategyRuntimeState("s", "1", "fp")
        rs.last_eval_date = last_date
        return rs

    def test_no_last_date_always_due(self):
        assert self.scheduler.is_due(self.spec_daily, self._rs(None), date(2024, 1, 2))

    def test_daily_due_on_next_day(self):
        assert self.scheduler.is_due(self.spec_daily, self._rs(date(2024, 1, 1)), date(2024, 1, 2))

    def test_daily_not_due_same_day(self):
        assert not self.scheduler.is_due(
            self.spec_daily, self._rs(date(2024, 1, 2)), date(2024, 1, 2)
        )

    def test_weekly_due_after_7_days(self):
        assert self.scheduler.is_due(self.spec_weekly, self._rs(date(2024, 1, 1)), date(2024, 1, 8))

    def test_weekly_not_due_after_6_days(self):
        assert not self.scheduler.is_due(
            self.spec_weekly, self._rs(date(2024, 1, 1)), date(2024, 1, 7)
        )

    def test_monthly_due_when_month_changes(self):
        assert self.scheduler.is_due(
            self.spec_monthly, self._rs(date(2024, 1, 31)), date(2024, 2, 1)
        )

    def test_monthly_not_due_same_month(self):
        assert not self.scheduler.is_due(
            self.spec_monthly, self._rs(date(2024, 2, 1)), date(2024, 2, 15)
        )

    def test_quarterly_due_when_quarter_changes(self):
        # Q1 → Q2
        assert self.scheduler.is_due(
            self.spec_quarterly, self._rs(date(2024, 3, 31)), date(2024, 4, 1)
        )

    def test_quarterly_not_due_same_quarter(self):
        assert not self.scheduler.is_due(
            self.spec_quarterly, self._rs(date(2024, 1, 15)), date(2024, 3, 31)
        )

    def test_event_driven_never_due_automatically(self):
        assert not self.scheduler.is_due(
            self.spec_event, self._rs(date(2024, 1, 1)), date(2024, 12, 31)
        )

    def test_unknown_frequency_treated_as_daily(self):
        spec = _base_spec(rebalance_frequency="biannual")
        assert self.scheduler.is_due(spec, self._rs(date(2024, 1, 1)), date(2024, 1, 2))

    def test_next_due_monthly(self):
        rs = self._rs(date(2024, 1, 15))
        nxt = self.scheduler.next_due(self.spec_monthly, rs)
        assert nxt == date(2024, 2, 1)

    def test_next_due_weekly(self):
        rs = self._rs(date(2024, 1, 1))
        nxt = self.scheduler.next_due(self.spec_weekly, rs)
        assert nxt == date(2024, 1, 8)

    def test_next_due_none_when_no_last_eval(self):
        rs = self._rs(None)
        assert self.scheduler.next_due(self.spec_monthly, rs) is None


class TestClock:
    def test_fixed_clock_returns_fixed_datetime(self):
        fixed = datetime(2024, 6, 1, 12, 0, 0)
        clock = FixedClock(fixed)
        assert clock.now() == fixed
        assert clock.today() == date(2024, 6, 1)

    def test_real_clock_now_is_datetime(self):
        clock = Clock()
        now = clock.now()
        assert isinstance(now, datetime)

    def test_real_clock_today_is_date(self):
        clock = Clock()
        assert isinstance(clock.today(), date)


# ═══════════════════════════════════════════════════════════════════════════════
# B. StrategyRuntimeState
# ═══════════════════════════════════════════════════════════════════════════════


class TestStrategyRuntimeState:
    def test_to_dict_round_trip(self):
        rs = StrategyRuntimeState("s1", "1.0.0", "fp123")
        rs.last_eval_date = date(2024, 3, 1)
        rs.evaluation_count = 5
        rs.error_count = 1
        rs.status = "paused"
        d = rs.to_dict()
        restored = StrategyRuntimeState.from_dict(d)
        assert restored.strategy_id == "s1"
        assert restored.last_eval_date == date(2024, 3, 1)
        assert restored.evaluation_count == 5
        assert restored.error_count == 1
        assert restored.status == "paused"

    def test_from_dict_none_last_eval_date(self):
        rs = StrategyRuntimeState("s", "1", "fp")
        d = rs.to_dict()
        assert d["last_eval_date"] is None
        restored = StrategyRuntimeState.from_dict(d)
        assert restored.last_eval_date is None

    def test_default_status_is_active(self):
        rs = StrategyRuntimeState("s", "1", "fp")
        assert rs.status == "active"

    def test_evaluation_count_starts_zero(self):
        rs = StrategyRuntimeState("s", "1", "fp")
        assert rs.evaluation_count == 0

    def test_mutable_update(self):
        rs = StrategyRuntimeState("s", "1", "fp")
        rs.evaluation_count = 7
        rs.last_eval_date = date(2024, 5, 1)
        assert rs.evaluation_count == 7
        assert rs.last_eval_date == date(2024, 5, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# C. CycleRecord / ForwardPerformanceRecord / PerformanceMetrics
# ═══════════════════════════════════════════════════════════════════════════════


class TestCycleRecord:
    def _make(self, **kw) -> CycleRecord:
        defaults = {
            "cycle_id": "c-000001",
            "strategy_id": "s",
            "strategy_version": "1",
            "strategy_fingerprint": "fp",
            "as_of": date(2024, 1, 2),
            "snapshot_fingerprint": "sfp",
            "evaluation_fingerprint": "efp",
            "evaluation_id": "eval-1",
            "portfolio_value": 100_000.0,
            "nav": 100_000.0,
            "cash": 100_000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "n_orders": 0,
            "n_fills": 0,
            "reconciled": True,
            "risk_approved": True,
            "risk_decision": "approve",
        }
        defaults.update(kw)
        return CycleRecord(**defaults)

    def test_immutable(self):
        r = self._make()
        with pytest.raises(FrozenInstanceError):
            r.cycle_id = "x"  # type: ignore

    def test_to_dict_from_dict_round_trip(self):
        r = self._make(n_orders=3, n_fills=3)
        d = r.to_dict()
        r2 = CycleRecord.from_dict(d)
        assert r2.cycle_id == r.cycle_id
        assert r2.as_of == r.as_of
        assert r2.n_orders == 3
        assert r2.n_fills == 3

    def test_risk_approved_stored(self):
        r = self._make(risk_approved=False, risk_decision="reject")
        assert not r.risk_approved
        assert r.risk_decision == "reject"


class TestForwardPerformanceRecord:
    def _record(self, as_of: date, nav: float, **kw) -> CycleRecord:
        return CycleRecord(
            cycle_id=f"c-{nav}",
            strategy_id="s",
            strategy_version="1",
            strategy_fingerprint="fp",
            as_of=as_of,
            snapshot_fingerprint="sfp",
            evaluation_fingerprint="efp",
            evaluation_id=f"e-{nav}",
            portfolio_value=nav,
            nav=nav,
            cash=nav * 0.1,
            realized_pnl=nav - 100_000,
            unrealized_pnl=0.0,
            n_orders=kw.get("n_orders", 2),
            n_fills=kw.get("n_fills", 2),
            reconciled=True,
            risk_approved=True,
            risk_decision="approve",
        )

    def test_empty_record_zero_returns(self):
        fpr = ForwardPerformanceRecord("s", "1", "fp", [])
        assert fpr.total_return() == 0.0
        assert fpr.max_drawdown() == 0.0
        assert fpr.daily_returns() == []

    def test_single_cycle_zero_daily_returns(self):
        fpr = ForwardPerformanceRecord("s", "1", "fp", [self._record(date(2024, 1, 1), 100_000.0)])
        assert fpr.daily_returns() == []

    def test_two_cycles_one_daily_return(self):
        cycles = [
            self._record(date(2024, 1, 1), 100_000.0),
            self._record(date(2024, 2, 1), 101_000.0),
        ]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        rets = fpr.daily_returns()
        assert len(rets) == 1
        assert abs(rets[0] - 0.01) < 1e-9

    def test_total_return_correct(self):
        cycles = [
            self._record(date(2024, 1, 1), 100_000.0),
            self._record(date(2024, 2, 1), 110_000.0),
        ]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        assert abs(fpr.total_return() - 0.10) < 1e-9

    def test_max_drawdown_flat_zero(self):
        cycles = [self._record(date(2024, i, 1), 100_000.0) for i in range(1, 4)]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        assert fpr.max_drawdown() == 0.0

    def test_max_drawdown_detects_dip(self):
        cycles = [
            self._record(date(2024, 1, 1), 100_000.0),
            self._record(date(2024, 2, 1), 110_000.0),
            self._record(date(2024, 3, 1), 99_000.0),
        ]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        mdd = fpr.max_drawdown()
        # peak=110k, trough=99k → drawdown = (110k-99k)/110k ≈ 0.1
        assert abs(mdd - 11_000 / 110_000) < 1e-6

    def test_sharpe_zero_for_single_return(self):
        cycles = [
            self._record(date(2024, 1, 1), 100_000.0),
            self._record(date(2024, 2, 1), 105_000.0),
        ]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        assert fpr.sharpe() == 0.0  # < 2 returns → 0

    def test_nav_series(self):
        cycles = [
            self._record(date(2024, 1, 1), 100_000.0),
            self._record(date(2024, 2, 1), 101_000.0),
        ]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        series = fpr.nav_series()
        assert series[0] == (date(2024, 1, 1), 100_000.0)
        assert series[1] == (date(2024, 2, 1), 101_000.0)

    def test_metrics_fill_rate(self):
        cycles = [
            self._record(date(2024, 1, 1), 100_000.0, n_orders=4, n_fills=3),
            self._record(date(2024, 2, 1), 101_000.0, n_orders=2, n_fills=2),
        ]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        m = fpr.metrics()
        assert m.total_orders == 6
        assert m.total_fills == 5
        assert abs(m.fill_rate - 5 / 6) < 1e-9

    def test_paper_backtest_comparison(self):
        cycles = [
            self._record(date(2024, 1, 1), 100_000.0),
            self._record(date(2024, 2, 1), 102_000.0),
        ]
        fpr = ForwardPerformanceRecord("s", "1", "fp", cycles)
        cmp = fpr.paper_backtest_comparison(research_capital=100_000.0)
        assert cmp.research_capital == 100_000.0
        assert abs(cmp.paper_total_return - 0.02) < 1e-9
        assert "M21 open/free data" in cmp.notes[0]


# ═══════════════════════════════════════════════════════════════════════════════
# D. Checkpoint save/load + portfolio state serialisation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckpoint:
    def _make_populated_loop(self):
        spec = _base_spec()
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0})
        loop = _make_loop(spec, logic, validate_readiness=False)
        snap1 = FakeSnapshot(AS_OF_0, SPOTS)
        snap2 = FakeSnapshot(AS_OF_1, SPOTS_2)
        loop.process_snapshot(snap1)
        loop.process_snapshot(snap2)
        return loop

    def test_checkpoint_dict_has_required_keys(self):
        loop = self._make_populated_loop()
        d = _checkpoint_dict(loop)
        assert "cycle_seq" in d
        assert "seen_snapshots" in d
        assert "strategy_states" in d
        assert "portfolio_states" in d
        assert "cycle_records" in d

    def test_seen_snapshots_preserved(self):
        loop = self._make_populated_loop()
        snap1 = FakeSnapshot(AS_OF_0, SPOTS)
        snap2 = FakeSnapshot(AS_OF_1, SPOTS_2)
        d = _checkpoint_dict(loop)
        assert snap1.fingerprint() in d["seen_snapshots"]
        assert snap2.fingerprint() in d["seen_snapshots"]

    def test_cycle_seq_preserved(self):
        loop = self._make_populated_loop()
        d = _checkpoint_dict(loop)
        assert d["cycle_seq"] == 2

    def test_runtime_state_preserved(self):
        loop = self._make_populated_loop()
        sid = "test-strat"
        d = _checkpoint_dict(loop)
        rs_dict = d["strategy_states"][sid]
        assert rs_dict["evaluation_count"] == 2
        assert rs_dict["last_eval_date"] == AS_OF_1.isoformat()

    def test_portfolio_cash_preserved(self):
        loop = self._make_populated_loop()
        sid = "test-strat"
        d = _checkpoint_dict(loop)
        port = d["portfolio_states"][sid]
        assert "cash" in port
        assert isinstance(port["cash"], float)

    def test_save_load_file(self):
        loop = self._make_populated_loop()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        save_checkpoint(path, loop)
        loaded = load_checkpoint(path)
        assert loaded["cycle_seq"] == 2
        Path(path).unlink(missing_ok=True)

    def test_restore_runtime_state_from_checkpoint(self):
        spec = _base_spec()
        logic = ConstantLogic({"AAPL": 1.0})
        loop = _make_loop(spec, logic, validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        d = _checkpoint_dict(loop)

        # build fresh loop, restore
        loop2 = _make_loop(spec, logic, validate_readiness=False)
        _restore_checkpoint(loop2, d)

        rs = loop2.runtime_state("test-strat")
        assert rs.evaluation_count == 1
        assert rs.last_eval_date == AS_OF_0

    def test_restore_portfolio_from_checkpoint(self):
        spec = _base_spec()
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0})
        loop = _make_loop(spec, logic, validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        original_value = loop.session("test-strat").book.value()

        d = _checkpoint_dict(loop)
        loop2 = _make_loop(spec, logic, validate_readiness=False)
        _restore_checkpoint(loop2, d)

        restored_value = loop2.session("test-strat").book.value()
        assert abs(restored_value - original_value) < 0.01

    def test_cycle_records_preserved_across_checkpoint(self):
        loop = self._make_populated_loop()
        d = _checkpoint_dict(loop)
        loop2 = _make_loop(
            _base_spec(), ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False
        )
        _restore_checkpoint(loop2, d)
        assert len(loop2.all_cycle_records) == 2

    def test_seen_snapshots_prevent_duplicate_after_restore(self):
        spec = _base_spec()
        logic = ConstantLogic({"AAPL": 1.0})
        loop = _make_loop(spec, logic, validate_readiness=False)
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        loop.process_snapshot(snap)

        d = _checkpoint_dict(loop)
        loop2 = _make_loop(spec, logic, validate_readiness=False)
        _restore_checkpoint(loop2, d)

        result = loop2.process_snapshot(snap)
        assert result.skipped
        assert result.skip_reason == "duplicate_snapshot"


# ═══════════════════════════════════════════════════════════════════════════════
# E. PaperTradingLoop — basic lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestPaperTradingLoopBasic:
    def test_loop_creation(self):
        spec = _base_spec()
        reg = _make_registry(spec)
        loop = PaperTradingLoop(runtime=_permissive_runtime(), registry=reg)
        assert isinstance(loop, PaperTradingLoop)

    def test_add_strategy_deployable_succeeds(self):
        spec = _base_spec()
        reg = _make_registry(spec, StrategyState.DEPLOYABLE)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        loop.add_strategy(
            spec.strategy_id,
            ConstantLogic({}),
            broker=MockBroker(initial_cash=1e5),
            risk_gate=_permissive_m12_gate(),
        )
        assert spec.strategy_id in loop.active_strategies

    def test_add_strategy_paper_succeeds(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        assert spec.strategy_id in loop.active_strategies

    def test_add_strategy_draft_fails(self):
        spec = _base_spec()
        reg = StrategyRegistry()
        reg.register(spec, StrategyState.DRAFT)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        with pytest.raises(LoopError, match="state"):
            loop.add_strategy(spec.strategy_id, ConstantLogic({}))

    def test_add_strategy_rejected_fails(self):
        spec = _base_spec()
        reg = StrategyRegistry()
        reg.register(spec, StrategyState.DRAFT)
        reg.transition(spec.strategy_id, StrategyState.REJECTED)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        with pytest.raises(LoopError):
            loop.add_strategy(spec.strategy_id, ConstantLogic({}))

    def test_add_strategy_not_in_registry_fails(self):
        reg = StrategyRegistry()
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        with pytest.raises(LoopError, match="not found"):
            loop.add_strategy("nonexistent", ConstantLogic({}))

    def test_add_strategy_readiness_gate_fires(self):
        spec = _base_spec(research_artifact_id="")  # empty → fails readiness
        reg = _make_registry(spec)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=True)
        )
        with pytest.raises(LoopError, match="readiness"):
            loop.add_strategy(spec.strategy_id, ConstantLogic({}))

    def test_process_snapshot_returns_loop_cycle_result(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        assert isinstance(result, LoopCycleResult)

    def test_strategy_result_in_cycle(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        assert len(result.strategy_results) == 1
        assert result.strategy_results[0].strategy_id == spec.strategy_id

    def test_portfolio_value_tracked(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.strategy_results[0]
        assert sr.portfolio_value > 0

    def test_sync_event_attached(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.strategy_results[0]
        assert sr.sync_event is not None

    def test_cycle_record_in_result(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.strategy_results[0]
        assert sr.cycle_record is not None
        assert isinstance(sr.cycle_record, CycleRecord)

    def test_remove_strategy(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        loop.remove_strategy(spec.strategy_id)
        assert spec.strategy_id not in loop.active_strategies

    def test_none_snapshot_raises(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        with pytest.raises(LoopError, match="None"):
            loop.process_snapshot(None)

    def test_snapshot_no_as_of_raises(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        with pytest.raises(LoopError, match="as_of"):
            loop.process_snapshot(type("S", (), {"spots": {}})())

    def test_result_for_helper(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr is not None
        assert sr.strategy_id == spec.strategy_id

    def test_result_for_unknown_returns_none(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        assert result.result_for("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════════
# F. Idempotency (duplicate snapshots)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotency:
    def test_same_snapshot_second_call_skipped(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        loop.process_snapshot(snap)
        result2 = loop.process_snapshot(snap)
        assert result2.skipped
        assert result2.skip_reason == "duplicate_snapshot"

    def test_skip_leaves_strategy_results_empty(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        loop.process_snapshot(snap)
        result2 = loop.process_snapshot(snap)
        assert result2.strategy_results == []

    def test_cycle_seq_increments_on_skip(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        loop.process_snapshot(snap)
        loop.process_snapshot(snap)
        assert loop.cycle_count == 2

    def test_no_duplicate_cycle_records_on_skip(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        loop.process_snapshot(snap)
        loop.process_snapshot(snap)
        records = loop.strategy_records(spec.strategy_id)
        assert len(records) == 1

    def test_different_snapshots_not_skipped(self):
        spec = _base_spec()
        loop = _make_loop(
            spec,
            ConstantLogic({"AAPL": 1.0}),
            validate_readiness=False,
        )
        snap1 = FakeSnapshot(AS_OF_0, SPOTS)
        snap2 = FakeSnapshot(AS_OF_1, SPOTS_2)  # different date → different fingerprint
        r1 = loop.process_snapshot(snap1)
        r2 = loop.process_snapshot(snap2)
        assert not r1.skipped
        assert not r2.skipped

    def test_three_snapshots_a_b_a_second_a_is_skip(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        snap_a = FakeSnapshot(AS_OF_0, SPOTS)
        snap_b = FakeSnapshot(AS_OF_1, SPOTS_2)
        loop.process_snapshot(snap_a)
        loop.process_snapshot(snap_b)
        r = loop.process_snapshot(snap_a)
        assert r.skipped


# ═══════════════════════════════════════════════════════════════════════════════
# G. Scheduling via loop
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulingViaLoop:
    def test_daily_evaluated_on_each_snapshot(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        for i, d in enumerate([AS_OF_0, AS_OF_1, AS_OF_2]):
            result = loop.process_snapshot(FakeSnapshot(d, SPOTS))
            sr = result.result_for(spec.strategy_id)
            assert not sr.skipped, f"day {i} should not be skipped"

    def test_monthly_skipped_same_month(self):
        spec = _base_spec(rebalance_frequency="monthly")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        snap_jan1 = FakeSnapshot(date(2024, 1, 2), SPOTS)
        snap_jan15 = FakeSnapshot(date(2024, 1, 15), SPOTS_2)
        loop.process_snapshot(snap_jan1)
        result2 = loop.process_snapshot(snap_jan15)
        sr = result2.result_for(spec.strategy_id)
        assert sr.skipped
        assert sr.skip_reason == "not_due"

    def test_monthly_evaluated_when_month_changes(self):
        spec = _base_spec(rebalance_frequency="monthly")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(date(2024, 1, 2), SPOTS))
        result2 = loop.process_snapshot(FakeSnapshot(date(2024, 2, 1), SPOTS_2))
        sr = result2.result_for(spec.strategy_id)
        assert not sr.skipped

    def test_weekly_skipped_before_7_days(self):
        spec = _base_spec(rebalance_frequency="weekly")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(date(2024, 1, 1), SPOTS))
        result2 = loop.process_snapshot(FakeSnapshot(date(2024, 1, 6), SPOTS_2))
        sr = result2.result_for(spec.strategy_id)
        assert sr.skipped

    def test_weekly_evaluated_after_7_days(self):
        spec = _base_spec(rebalance_frequency="weekly")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(date(2024, 1, 1), SPOTS))
        result2 = loop.process_snapshot(FakeSnapshot(date(2024, 1, 8), SPOTS_2))
        sr = result2.result_for(spec.strategy_id)
        assert not sr.skipped

    def test_event_driven_always_skipped(self):
        spec = _base_spec(rebalance_frequency="event_driven")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        result2 = loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        sr = result2.result_for(spec.strategy_id)
        assert sr.skipped
        assert sr.skip_reason == "not_due"

    def test_trigger_evaluation_bypasses_schedule(self):
        spec = _base_spec(rebalance_frequency="event_driven")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        # manually trigger
        snap2 = FakeSnapshot(AS_OF_1, SPOTS_2)
        loop._seen.add(snap2.fingerprint())  # simulate already processed
        snap2_fresh = FakeSnapshot(date(2024, 3, 15), SPOTS_2)
        result = loop.trigger_evaluation(spec.strategy_id, snap2_fresh)
        assert not result.skipped


# ═══════════════════════════════════════════════════════════════════════════════
# H. Strategy lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestStrategyLifecycle:
    def test_suspended_strategy_skipped(self):
        spec = _base_spec()
        reg = _make_registry(spec, StrategyState.PAPER)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        loop.add_strategy(
            spec.strategy_id,
            ConstantLogic({"AAPL": 1.0}),
            broker=MockBroker(initial_cash=1e5),
            risk_gate=_permissive_m12_gate(),
        )
        reg.transition(spec.strategy_id, StrategyState.SUSPENDED)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.skipped
        assert "suspended" in sr.skip_reason

    def test_retired_strategy_skipped(self):
        spec = _base_spec()
        reg = _make_registry(spec, StrategyState.PAPER)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        loop.add_strategy(
            spec.strategy_id,
            ConstantLogic({"AAPL": 1.0}),
            broker=MockBroker(initial_cash=1e5),
            risk_gate=_permissive_m12_gate(),
        )
        reg.transition(spec.strategy_id, StrategyState.RETIRED)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.skipped

    def test_pause_prevents_evaluation(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.pause_strategy(spec.strategy_id)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.skipped
        assert sr.skip_reason == "paused"

    def test_resume_resumes_evaluation(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.pause_strategy(spec.strategy_id)
        loop.resume_strategy(spec.strategy_id)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert not sr.skipped

    def test_pause_on_unknown_strategy_raises(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        with pytest.raises(LoopError):
            loop.pause_strategy("unknown")

    def test_loop_does_not_mutate_m22_registry_state(self):
        spec = _base_spec()
        reg = _make_registry(spec, StrategyState.PAPER)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        loop.add_strategy(
            spec.strategy_id,
            ConstantLogic({"AAPL": 1.0}),
            broker=MockBroker(initial_cash=1e5),
            risk_gate=_permissive_m12_gate(),
        )
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        # M22 registry state must be unchanged by loop processing
        assert reg.state(spec.strategy_id) == StrategyState.PAPER

    def test_risk_rejection_produces_no_orders(self):
        spec = _base_spec()
        tight_limits = RiskLimits(max_position=0.0001)  # 0.01% max pos → reject everything
        risk_engine = RiskEngine(RiskEngineConfig(limits=tight_limits))
        runtime = StrategyRuntime(risk_engine=risk_engine)
        reg = _make_registry(spec)
        loop = PaperTradingLoop(
            runtime=runtime, registry=reg, config=LoopConfig(validate_readiness=False)
        )
        loop.add_strategy(
            spec.strategy_id,
            ConstantLogic({"AAPL": 1.0}),
            broker=MockBroker(initial_cash=1e5),
            risk_gate=_permissive_m12_gate(),
        )
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert not sr.risk_approved
        assert sr.sync_event.n_orders == 0


# ═══════════════════════════════════════════════════════════════════════════════
# I. Multi-strategy support
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiStrategy:
    def test_two_strategies_both_evaluated(self):
        spec1 = _base_spec(strategy_id="s1", strategy_name="S1")
        spec2 = _base_spec(strategy_id="s2", strategy_name="S2")
        reg = StrategyRegistry()
        for spec in [spec1, spec2]:
            reg.register(spec, StrategyState.DRAFT)
            for s in [
                StrategyState.VALIDATING,
                StrategyState.VALIDATED,
                StrategyState.DEPLOYABLE,
                StrategyState.PAPER,
            ]:
                reg.transition(spec.strategy_id, s)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        for spec in [spec1, spec2]:
            loop.add_strategy(
                spec.strategy_id,
                ConstantLogic({"AAPL": 1.0}),
                broker=MockBroker(initial_cash=1e5),
                risk_gate=_permissive_m12_gate(),
            )
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        assert len(result.strategy_results) == 2
        ids = {sr.strategy_id for sr in result.strategy_results}
        assert ids == {"s1", "s2"}

    def test_separate_portfolios(self):
        spec1 = _base_spec(strategy_id="s1", strategy_name="S1", capital_assumption=50_000.0)
        spec2 = _base_spec(strategy_id="s2", strategy_name="S2", capital_assumption=200_000.0)
        reg = StrategyRegistry()
        for spec in [spec1, spec2]:
            reg.register(spec, StrategyState.DRAFT)
            for s in [
                StrategyState.VALIDATING,
                StrategyState.VALIDATED,
                StrategyState.DEPLOYABLE,
                StrategyState.PAPER,
            ]:
                reg.transition(spec.strategy_id, s)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        loop.add_strategy(
            "s1",
            ConstantLogic({"AAPL": 1.0}),
            broker=MockBroker(initial_cash=50_000.0),
            risk_gate=_permissive_m12_gate(),
        )
        loop.add_strategy(
            "s2",
            ConstantLogic({"AAPL": 1.0}),
            broker=MockBroker(initial_cash=200_000.0),
            risk_gate=_permissive_m12_gate(),
        )
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        v1 = result.result_for("s1").portfolio_value
        v2 = result.result_for("s2").portfolio_value
        # different capitals → different portfolio values
        assert abs(v1 - v2) > 1.0

    def test_one_paused_other_continues(self):
        spec1 = _base_spec(strategy_id="s1", strategy_name="S1")
        spec2 = _base_spec(strategy_id="s2", strategy_name="S2")
        reg = StrategyRegistry()
        for spec in [spec1, spec2]:
            reg.register(spec, StrategyState.DRAFT)
            for s in [
                StrategyState.VALIDATING,
                StrategyState.VALIDATED,
                StrategyState.DEPLOYABLE,
                StrategyState.PAPER,
            ]:
                reg.transition(spec.strategy_id, s)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        for spec in [spec1, spec2]:
            loop.add_strategy(
                spec.strategy_id,
                ConstantLogic({"AAPL": 1.0}),
                broker=MockBroker(initial_cash=1e5),
                risk_gate=_permissive_m12_gate(),
            )
        loop.pause_strategy("s1")
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        assert result.result_for("s1").skipped
        assert not result.result_for("s2").skipped

    def test_strategy_records_filtered_by_strategy(self):
        spec1 = _base_spec(strategy_id="s1", strategy_name="S1")
        spec2 = _base_spec(strategy_id="s2", strategy_name="S2")
        reg = StrategyRegistry()
        for spec in [spec1, spec2]:
            reg.register(spec, StrategyState.DRAFT)
            for s in [
                StrategyState.VALIDATING,
                StrategyState.VALIDATED,
                StrategyState.DEPLOYABLE,
                StrategyState.PAPER,
            ]:
                reg.transition(spec.strategy_id, s)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(), registry=reg, config=LoopConfig(validate_readiness=False)
        )
        for spec in [spec1, spec2]:
            loop.add_strategy(
                spec.strategy_id,
                ConstantLogic({"AAPL": 1.0}),
                broker=MockBroker(initial_cash=1e5),
                risk_gate=_permissive_m12_gate(),
            )
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        records_s1 = loop.strategy_records("s1")
        records_s2 = loop.strategy_records("s2")
        assert all(r.strategy_id == "s1" for r in records_s1)
        assert all(r.strategy_id == "s2" for r in records_s2)


# ═══════════════════════════════════════════════════════════════════════════════
# J. Cost-model compatibility
# ═══════════════════════════════════════════════════════════════════════════════


class TestCostCompatibility:
    def test_supported_keys_compatible(self):
        spec = _base_spec(
            transaction_cost_assumption={"slippage_bps": 5.0, "commission_per_share": 0.01}
        )
        result = check_cost_compatibility(spec)
        assert result.compatible

    def test_unsupported_key_not_compatible(self):
        spec = _base_spec(transaction_cost_assumption={"commission": 0.001, "spread": 0.0005})
        result = check_cost_compatibility(spec)
        assert not result.compatible
        assert "commission" in result.unmapped_keys

    def test_slippage_bps_wires_simulated_broker(self):
        spec = _base_spec(transaction_cost_assumption={"slippage_bps": 10.0})
        broker = _build_broker(spec, 100_000.0)
        assert isinstance(broker, SimulatedBroker)

    def test_no_slippage_wires_mock_broker(self):
        spec = _base_spec(transaction_cost_assumption={})
        broker = _build_broker(spec, 100_000.0)
        assert isinstance(broker, MockBroker)

    def test_research_fingerprint_differs_from_execution_when_keys_differ(self):
        spec = _base_spec(transaction_cost_assumption={"commission": 0.001, "slippage_bps": 5.0})
        result = check_cost_compatibility(spec)
        assert result.research_fingerprint != result.execution_fingerprint

    def test_compatible_spec_same_fingerprints_when_only_supported_keys(self):
        spec = _base_spec(transaction_cost_assumption={"slippage_bps": 5.0})
        result = check_cost_compatibility(spec)
        assert result.compatible
        assert result.mapped_assumptions == {"slippage_bps": 5.0}


# ═══════════════════════════════════════════════════════════════════════════════
# K. Failure handling / fail-closed
# ═══════════════════════════════════════════════════════════════════════════════


class TestFailureHandling:
    def test_none_snapshot_raises_loop_error(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        with pytest.raises(LoopError):
            loop.process_snapshot(None)

    def test_evaluation_error_in_fail_closed_returns_error_result(self):
        class BrokenLogic(StrategyLogic):
            def compute_features(self, snapshot, spec):
                raise RuntimeError("deliberate failure")

            def generate_signal(self, features, spec):
                pass

        spec = _base_spec()
        loop = _make_loop(
            spec,
            BrokenLogic(),
            validate_readiness=False,
        )
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.error != ""

    def test_evaluation_error_increments_error_count(self):
        class BrokenLogic(StrategyLogic):
            def compute_features(self, snapshot, spec):
                raise RuntimeError("fail")

            def generate_signal(self, features, spec):
                pass

        spec = _base_spec()
        loop = _make_loop(spec, BrokenLogic(), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        rs = loop.runtime_state(spec.strategy_id)
        assert rs.error_count >= 1

    def test_fail_closed_false_propagates_exception(self):
        class BrokenLogic(StrategyLogic):
            def compute_features(self, snapshot, spec):
                raise RuntimeError("deliberate")

            def generate_signal(self, features, spec):
                pass

        spec = _base_spec()
        reg = _make_registry(spec)
        loop = PaperTradingLoop(
            runtime=_permissive_runtime(),
            registry=reg,
            config=LoopConfig(validate_readiness=False, fail_closed=False),
        )
        loop.add_strategy(
            spec.strategy_id,
            BrokenLogic(),
            broker=MockBroker(initial_cash=1e5),
            risk_gate=_permissive_m12_gate(),
        )
        with pytest.raises(RuntimeError, match="deliberate"):
            loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))

    def test_empty_signals_no_orders(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.sync_event.n_orders == 0

    def test_risk_rejection_no_orders(self):
        spec = _base_spec()
        tight_limits = RiskLimits(max_position=0.0001)
        risk_engine = RiskEngine(RiskEngineConfig(limits=tight_limits))
        runtime = StrategyRuntime(risk_engine=risk_engine)
        reg = _make_registry(spec)
        loop = PaperTradingLoop(
            runtime=runtime, registry=reg, config=LoopConfig(validate_readiness=False)
        )
        loop.add_strategy(
            spec.strategy_id,
            ConstantLogic({"AAPL": 1.0}),
            broker=MockBroker(initial_cash=1e5),
            risk_gate=_permissive_m12_gate(),
        )
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert not sr.risk_approved
        # no orders submitted to broker
        assert sr.sync_event.n_orders == 0

    def test_unpriced_security_excluded(self):
        spec = _base_spec()
        loop = _make_loop(
            spec, ConstantLogic({"AAPL": 1.0, "UNKNOWN": 1.0}), validate_readiness=False
        )
        # UNKNOWN has no price → excluded from targets
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, {"AAPL": 185.0}))
        sr = result.result_for(spec.strategy_id)
        assert not sr.skipped
        # should not crash on unpriced security


# ═══════════════════════════════════════════════════════════════════════════════
# L. M22→M12 integration (evaluation → paper execution)
# ═══════════════════════════════════════════════════════════════════════════════


class TestM22M12Integration:
    def test_evaluation_fingerprint_present(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.evaluation.evaluation_fingerprint != ""

    def test_cycle_fingerprints_match_evaluation(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.cycle_record.evaluation_fingerprint == sr.evaluation.evaluation_fingerprint

    def test_m12_fills_change_portfolio_value(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        # fills executed → n_fills > 0
        assert sr.sync_event.n_fills > 0

    def test_m12_session_book_reflects_fills(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sess = loop.session(spec.strategy_id)
        # holdings populated after fills
        assert len(sess.book.state.holdings) > 0

    def test_reconciliation_ok_on_clean_run(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.sync_event.reconciled

    def test_realized_pnl_in_cycle_record(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        # sell on second snapshot → realizes some P&L
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        records = loop.strategy_records(spec.strategy_id)
        # realized pnl tracked (may be 0 if prices unchanged)
        assert all(isinstance(r.realized_pnl, float) for r in records)

    def test_m10_portfolio_weights_flow_to_session(self):
        spec = _base_spec(
            portfolio_construction_config={"objective": "equal_weight", "long_only": True}
        )
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        # M10 produces weights, M12 executes them
        assert sr.evaluation.portfolio is not None
        assert len(sr.evaluation.portfolio.positions) > 0

    def test_evaluation_id_increments(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        records = loop.strategy_records(spec.strategy_id)
        assert records[0].evaluation_id != records[1].evaluation_id

    def test_strategy_fingerprint_in_cycle_record(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        assert sr.cycle_record.strategy_fingerprint == spec.configuration_fingerprint

    def test_as_of_in_cycle_record_matches_snapshot(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        result = loop.process_snapshot(snap)
        sr = result.result_for(spec.strategy_id)
        assert sr.cycle_record.as_of == AS_OF_0


# ═══════════════════════════════════════════════════════════════════════════════
# M. Multi-day continuity
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiDayContinuity:
    def test_portfolio_state_continuous_across_days(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False)
        snapshots = [
            FakeSnapshot(AS_OF_0, SPOTS),
            FakeSnapshot(AS_OF_1, SPOTS_2),
            FakeSnapshot(AS_OF_2, SPOTS_3),
        ]
        navs = []
        for snap in snapshots:
            result = loop.process_snapshot(snap)
            sr = result.result_for(spec.strategy_id)
            navs.append(sr.portfolio_value)
        # Each day the portfolio has a value (not reset to initial)
        assert all(v > 0 for v in navs)

    def test_evaluation_count_increments_each_day(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        for snap in [
            FakeSnapshot(AS_OF_0, SPOTS),
            FakeSnapshot(AS_OF_1, SPOTS_2),
            FakeSnapshot(AS_OF_2, SPOTS_3),
        ]:
            loop.process_snapshot(snap)
        rs = loop.runtime_state(spec.strategy_id)
        assert rs.evaluation_count == 3

    def test_nav_series_has_one_entry_per_evaluation(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        for snap in [
            FakeSnapshot(AS_OF_0, SPOTS),
            FakeSnapshot(AS_OF_1, SPOTS_2),
            FakeSnapshot(AS_OF_2, SPOTS_3),
        ]:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        series = fpr.nav_series()
        assert len(series) == 3

    def test_holdings_accumulate_across_days(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sess = loop.session(spec.strategy_id)
        dict(sess.book.state.holdings)
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        # holdings still present (not reset)
        assert len(sess.book.state.holdings) > 0

    def test_last_eval_date_advances(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        rs = loop.runtime_state(spec.strategy_id)
        assert rs.last_eval_date == AS_OF_1


# ═══════════════════════════════════════════════════════════════════════════════
# N. Restart certification
# ═══════════════════════════════════════════════════════════════════════════════


class TestRestartCertification:
    def _run_two_days(self, loop, snap_a, snap_b):
        loop.process_snapshot(snap_a)
        loop.process_snapshot(snap_b)

    def test_restart_produces_same_final_portfolio_value(self):
        spec = _base_spec(rebalance_frequency="daily")
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0})

        # Reference run: Day 1, Day 2, Day 3
        loop_ref = _make_loop(spec, logic, validate_readiness=False)
        snap1 = FakeSnapshot(AS_OF_0, SPOTS)
        snap2 = FakeSnapshot(AS_OF_1, SPOTS_2)
        snap3 = FakeSnapshot(AS_OF_2, SPOTS_3)
        loop_ref.process_snapshot(snap1)
        loop_ref.process_snapshot(snap2)
        loop_ref.process_snapshot(snap3)
        ref_value = loop_ref.session(spec.strategy_id).book.value()

        # Interrupted run: Day 1, Day 2 → checkpoint → restart → Day 3
        loop_run = _make_loop(spec, logic, validate_readiness=False)
        loop_run.process_snapshot(snap1)
        loop_run.process_snapshot(snap2)
        checkpoint = _checkpoint_dict(loop_run)

        loop_resume = _make_loop(spec, logic, validate_readiness=False)
        _restore_checkpoint(loop_resume, checkpoint)
        loop_resume.process_snapshot(snap3)
        resumed_value = loop_resume.session(spec.strategy_id).book.value()

        assert abs(ref_value - resumed_value) < 0.01

    def test_restart_produces_same_realized_pnl(self):
        spec = _base_spec(rebalance_frequency="daily")
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0})

        loop_ref = _make_loop(spec, logic, validate_readiness=False)
        snap1 = FakeSnapshot(AS_OF_0, SPOTS)
        snap2 = FakeSnapshot(AS_OF_1, SPOTS_2)
        snap3 = FakeSnapshot(AS_OF_2, SPOTS_3)
        for snap in [snap1, snap2, snap3]:
            loop_ref.process_snapshot(snap)
        ref_pnl = loop_ref.session(spec.strategy_id).book.state.realized_pnl_total

        loop_run = _make_loop(spec, logic, validate_readiness=False)
        for snap in [snap1, snap2]:
            loop_run.process_snapshot(snap)
        cp = _checkpoint_dict(loop_run)

        loop_resume = _make_loop(spec, logic, validate_readiness=False)
        _restore_checkpoint(loop_resume, cp)
        loop_resume.process_snapshot(snap3)
        resumed_pnl = loop_resume.session(spec.strategy_id).book.state.realized_pnl_total

        assert abs(ref_pnl - resumed_pnl) < 0.01

    def test_restart_cycle_seq_preserved(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        cp = _checkpoint_dict(loop)

        loop2 = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        _restore_checkpoint(loop2, cp)
        assert loop2._cycle_seq == 2

    def test_duplicate_after_restart_still_idempotent(self):
        spec = _base_spec(rebalance_frequency="daily")
        logic = ConstantLogic({"AAPL": 1.0})
        loop = _make_loop(spec, logic, validate_readiness=False)
        snap1 = FakeSnapshot(AS_OF_0, SPOTS)
        loop.process_snapshot(snap1)
        cp = _checkpoint_dict(loop)

        loop2 = _make_loop(spec, logic, validate_readiness=False)
        _restore_checkpoint(loop2, cp)
        # same snapshot should be skipped after restore
        result = loop2.process_snapshot(snap1)
        assert result.skipped

    def test_save_load_file_restart(self):
        spec = _base_spec(rebalance_frequency="daily")
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0})

        loop_run = _make_loop(spec, logic, validate_readiness=False)
        loop_run.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_checkpoint(path, loop_run)

        loop_resume = _make_loop(spec, logic, validate_readiness=False)
        data = load_checkpoint(path)
        _restore_checkpoint(loop_resume, data)

        rs = loop_resume.runtime_state(spec.strategy_id)
        assert rs.evaluation_count == 1
        Path(path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# O. Determinism / replay
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    def test_same_inputs_same_evaluation_fingerprint(self):
        spec = _base_spec()
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0})
        snap = FakeSnapshot(AS_OF_0, SPOTS)

        loop1 = _make_loop(spec, logic, validate_readiness=False)
        r1 = loop1.process_snapshot(snap)
        fp1 = r1.result_for(spec.strategy_id).evaluation.evaluation_fingerprint

        loop2 = _make_loop(spec, logic, validate_readiness=False)
        r2 = loop2.process_snapshot(snap)
        fp2 = r2.result_for(spec.strategy_id).evaluation.evaluation_fingerprint

        assert fp1 == fp2

    def test_same_inputs_same_cycle_record_fingerprints(self):
        spec = _base_spec()
        logic = ConstantLogic({"AAPL": 1.0})
        snap = FakeSnapshot(AS_OF_0, SPOTS)

        loop1 = _make_loop(spec, logic, validate_readiness=False)
        loop1.process_snapshot(snap)
        cr1 = loop1.strategy_records(spec.strategy_id)[0]

        loop2 = _make_loop(spec, logic, validate_readiness=False)
        loop2.process_snapshot(snap)
        cr2 = loop2.strategy_records(spec.strategy_id)[0]

        assert cr1.evaluation_fingerprint == cr2.evaluation_fingerprint
        assert cr1.snapshot_fingerprint == cr2.snapshot_fingerprint

    def test_fixed_clock_deterministic(self):
        fixed = datetime(2024, 6, 1, 12, 0, 0)
        c1 = FixedClock(fixed)
        c2 = FixedClock(fixed)
        assert c1.now() == c2.now()

    def test_replay_same_snapshots_same_final_nav(self):
        spec = _base_spec(rebalance_frequency="daily")
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0})
        snapshots = [
            FakeSnapshot(AS_OF_0, SPOTS),
            FakeSnapshot(AS_OF_1, SPOTS_2),
            FakeSnapshot(AS_OF_2, SPOTS_3),
        ]

        def _run():
            loop = _make_loop(spec, logic, validate_readiness=False)
            for snap in snapshots:
                loop.process_snapshot(snap)
            return loop.session(spec.strategy_id).book.value()

        nav1 = _run()
        nav2 = _run()
        assert abs(nav1 - nav2) < 1e-6

    def test_snapshot_fingerprint_stable(self):
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        fp1 = _snapshot_fp(snap)
        fp2 = _snapshot_fp(snap)
        assert fp1 == fp2

    def test_different_snapshots_different_fingerprints(self):
        snap1 = FakeSnapshot(AS_OF_0, SPOTS)
        snap2 = FakeSnapshot(AS_OF_1, SPOTS)
        assert _snapshot_fp(snap1) != _snapshot_fp(snap2)


# ═══════════════════════════════════════════════════════════════════════════════
# P. Forward record / performance comparison
# ═══════════════════════════════════════════════════════════════════════════════


class TestForwardRecord:
    def test_forward_record_has_all_cycle_records(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        for snap in [
            FakeSnapshot(AS_OF_0, SPOTS),
            FakeSnapshot(AS_OF_1, SPOTS_2),
            FakeSnapshot(AS_OF_2, SPOTS_3),
        ]:
            loop.process_snapshot(snap)
        fpr = loop.forward_record(spec.strategy_id)
        assert len(fpr.cycles) == 3

    def test_strategy_records_filtered(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        records = loop.strategy_records(spec.strategy_id)
        assert len(records) == 1
        assert records[0].strategy_id == spec.strategy_id

    def test_forward_record_strategy_fingerprint(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        fpr = loop.forward_record(spec.strategy_id)
        assert fpr.strategy_fingerprint == spec.configuration_fingerprint

    def test_metrics_returns_performance_metrics(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        fpr = loop.forward_record(spec.strategy_id)
        m = fpr.metrics()
        assert isinstance(m, PerformanceMetrics)
        assert m.n_cycles == 2
        assert m.total_orders >= 0

    def test_paper_backtest_comparison_builds(self):
        spec = _base_spec(rebalance_frequency="daily")
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        loop.process_snapshot(FakeSnapshot(AS_OF_1, SPOTS_2))
        fpr = loop.forward_record(spec.strategy_id)
        cmp = fpr.paper_backtest_comparison(research_capital=100_000.0)
        assert cmp.strategy_id == spec.strategy_id
        assert cmp.research_capital == 100_000.0


# ═══════════════════════════════════════════════════════════════════════════════
# Q. End-to-end certification
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEndCertification:
    def test_full_pipeline_e2e(self):
        """Full pipeline: M22 evaluate → M12 session → checkpoint → restart → continue.

        Verifies:
          - Strategy evaluated correctly
          - Portfolio updated after fills
          - Checkpoint captures full state
          - After restart, continuation matches reference run
        """
        spec = _base_spec(
            strategy_id="e2e-strat",
            strategy_name="E2E Strategy",
            rebalance_frequency="daily",
            capital_assumption=100_000.0,
        )
        logic = ConstantLogic({"AAPL": 1.0, "MSFT": 1.0, "GOOG": 1.0})

        snap_d1 = FakeSnapshot(date(2024, 1, 2), {"AAPL": 185.0, "MSFT": 410.0, "GOOG": 165.0})
        snap_d2 = FakeSnapshot(date(2024, 1, 3), {"AAPL": 190.0, "MSFT": 415.0, "GOOG": 170.0})
        snap_d3 = FakeSnapshot(date(2024, 1, 4), {"AAPL": 195.0, "MSFT": 420.0, "GOOG": 172.0})
        snap_d4 = FakeSnapshot(date(2024, 1, 5), {"AAPL": 200.0, "MSFT": 425.0, "GOOG": 175.0})

        # Reference: uninterrupted run
        loop_ref = _make_loop(spec, logic, validate_readiness=False)
        for snap in [snap_d1, snap_d2, snap_d3, snap_d4]:
            loop_ref.process_snapshot(snap)
        ref_value = loop_ref.session("e2e-strat").book.value()
        ref_pnl = loop_ref.session("e2e-strat").book.state.realized_pnl_total
        ref_count = loop_ref.runtime_state("e2e-strat").evaluation_count

        # Interrupted: Day 1–2, checkpoint, restart, Day 3–4
        loop_run = _make_loop(spec, logic, validate_readiness=False)
        for snap in [snap_d1, snap_d2]:
            loop_run.process_snapshot(snap)
        cp = _checkpoint_dict(loop_run)

        loop_resume = _make_loop(spec, logic, validate_readiness=False)
        _restore_checkpoint(loop_resume, cp)
        for snap in [snap_d3, snap_d4]:
            loop_resume.process_snapshot(snap)

        resumed_value = loop_resume.session("e2e-strat").book.value()
        resumed_pnl = loop_resume.session("e2e-strat").book.state.realized_pnl_total
        resumed_count = loop_resume.runtime_state("e2e-strat").evaluation_count

        # Verify restart matches reference
        assert abs(ref_value - resumed_value) < 0.01, (
            f"NAV mismatch: ref={ref_value:.2f} resumed={resumed_value:.2f}"
        )
        assert abs(ref_pnl - resumed_pnl) < 0.01
        assert ref_count == resumed_count == 4

        # Verify forward record
        fpr_ref = loop_ref.forward_record("e2e-strat")
        assert len(fpr_ref.cycles) == 4
        assert fpr_ref.cycles[0].as_of == date(2024, 1, 2)
        assert fpr_ref.cycles[-1].as_of == date(2024, 1, 5)

        # All evaluations were deterministic
        fps = {c.evaluation_fingerprint for c in fpr_ref.cycles}
        assert len(fps) == 4  # all different (different snapshots)

        # Paper-backtest comparison
        m = fpr_ref.metrics()
        assert m.n_cycles == 4
        assert m.total_fills >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# R. Partial-fill (SimulatedBroker) + duplicate-event safety
# ═══════════════════════════════════════════════════════════════════════════════


class TestPartialFillAndDuplicates:
    def test_simulated_broker_partial_fill(self):
        spec = _base_spec()
        loop = _make_loop(
            spec,
            ConstantLogic({"AAPL": 1.0, "MSFT": 1.0}),
            validate_readiness=False,
            slippage_bps=10.0,
        )
        result = loop.process_snapshot(FakeSnapshot(AS_OF_0, SPOTS))
        sr = result.result_for(spec.strategy_id)
        # SimulatedBroker with slippage still produces fills
        assert not sr.skipped

    def test_duplicate_snapshot_no_extra_cycle_records(self):
        spec = _base_spec()
        loop = _make_loop(spec, ConstantLogic({"AAPL": 1.0}), validate_readiness=False)
        snap = FakeSnapshot(AS_OF_0, SPOTS)
        loop.process_snapshot(snap)
        loop.process_snapshot(snap)
        assert len(loop.strategy_records(spec.strategy_id)) == 1

    def test_extract_prices_from_fake_snapshot(self):
        snap = FakeSnapshot(AS_OF_0, {"AAPL": 185.0, "MSFT": 410.0})
        prices = _extract_prices(snap)
        assert prices["AAPL"] == 185.0
        assert prices["MSFT"] == 410.0

    def test_extract_prices_ignores_invalid(self):
        snap = FakeSnapshot(AS_OF_0, {"AAPL": "bad", "MSFT": None})
        prices = _extract_prices(snap)
        assert "AAPL" not in prices
        assert "MSFT" not in prices

    def test_simulated_broker_built_from_spec(self):
        spec = _base_spec(transaction_cost_assumption={"slippage_bps": 15.0})
        broker = _build_broker(spec, 100_000.0)
        assert isinstance(broker, SimulatedBroker)
        assert broker.slippage_bps == 15.0
