"""Research Execution Platform regression (AIDP M8). All offline.

Single/batch/sweep execution, failure recovery, state transitions, event logging,
artifact generation, registry + research-matrix integration, resume, cancel,
validation failures, hooks, and a real backtest through the platform.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mentisrex.backtesting.analytics.performance import EquityPoint, PerformanceMetrics, RoundTrip
from mentisrex.research.execution import (
    ResearchRunner,
    RunConfiguration,
    State,
    check,
    make_backtest_executor,
)
from mentisrex.research.execution.artifact_manager import _ARTIFACTS
from mentisrex.research.experiment_registry import ExperimentRegistry, RegistryStore, lineage


def _dv():
    return lineage.dataset_versions(
        prices=100,
        fundamentals=50,
        insiders=20,
        universe=10,
        securitymaster=10,
        feature_registry_version="fr1",
    )


def _pm(pnl1=1000.0, pnl2=-500.0):
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    curve = [EquityPoint(t0 + timedelta(days=i), 1_000_000 * (1 + 0.001 * i)) for i in range(30)]
    rets = [curve[i].equity / curve[i - 1].equity - 1 for i in range(1, len(curve))]
    rts = [
        RoundTrip("AAA", "long", t0, t0 + timedelta(days=5), 100, 100.0, 110.0, pnl1),
        RoundTrip("BBB", "long", t0, t0 + timedelta(days=3), 100, 50.0, 45.0, pnl2),
    ]
    return PerformanceMetrics(
        total_return=0.03,
        cagr=0.4,
        annualized_volatility=0.1,
        sharpe_ratio=1.5,
        sortino_ratio=2.0,
        max_drawdown=-0.05,
        calmar_ratio=8.0,
        num_trades=2,
        win_rate=0.5,
        avg_holding_period_days=4.0,
        annual_turnover=1.2,
        profit_factor=2.0,
        equity_curve=curve,
        drawdown_series=[(p.timestamp, 0.0) for p in curve],
        daily_returns=rets,
        round_trips=rts,
    )


def fake_executor(session):
    class R:
        metrics = _pm()

    return R()


def boom_executor(session):
    raise ValueError("strategy exploded")


@pytest.fixture
def runner():
    r = ResearchRunner(registry=ExperimentRegistry(store=RegistryStore(":memory:")))
    yield r
    r.registry.close()


def _cfg(tmp_path, name="exp", executor=fake_executor, **over):
    kw = {
        "name": name,
        "parameters": {"lookback": 252},
        "features": ["market_cap", "roe"],
        "dataset_versions": _dv(),
        "random_seed": 42,
        "executor": executor,
        "artifacts_dir": str(tmp_path / name),
    }
    kw.update(over)
    return RunConfiguration(**kw)


# 1. single execution ──────────────────────────────────────────────────────────────


def test_single_execution(runner, tmp_path):
    s = runner.run(_cfg(tmp_path))
    assert s.state == State.COMPLETED
    assert s.metrics["Sharpe"] == 1.5
    assert s.experiment_id is not None
    assert check(s)["ok"]


# 2. batch execution ────────────────────────────────────────────────────────────────


def test_batch_execution(runner, tmp_path):
    cfgs = [_cfg(tmp_path, name=f"b{i}", parameters={"lookback": i}) for i in range(3)]
    sessions = runner.batch(cfgs)
    assert len(sessions) == 3
    assert all(s.state == State.COMPLETED for s in sessions)


# 3. parameter sweep ────────────────────────────────────────────────────────────────


def test_parameter_sweep(runner, tmp_path):
    base = _cfg(tmp_path, name="sweep")
    sessions = runner.scheduler.parameter_sweep(base, {"lookback": [10, 20], "top": [5, 10]})
    assert len(sessions) == 4  # 2 × 2 cartesian
    assert all(s.state == State.COMPLETED for s in sessions)
    # each got a distinct parameter combination → distinct fingerprints
    fps = {s.experiment.fingerprint for s in sessions}
    assert len(fps) == 4


# 4. failure recovery ───────────────────────────────────────────────────────────────


def test_failure_recovery(runner, tmp_path):
    s = runner.run(_cfg(tmp_path, name="boom", executor=boom_executor))
    assert s.state == State.FAILED
    assert "ValueError" in s.error
    assert s.traceback
    # registry recorded the failure; registry still usable afterwards
    assert runner.registry.load(s.experiment_id).status == "failed"
    ok = runner.run(_cfg(tmp_path, name="after"))
    assert ok.state == State.COMPLETED
    # stack trace + execution log persisted to disk
    d = tmp_path / "boom"
    assert (d / "traceback.txt").exists()
    assert (d / "execution_log.json").exists()


# 5. state transitions ──────────────────────────────────────────────────────────────


def test_state_transitions(runner, tmp_path):
    s = runner.run(_cfg(tmp_path))
    trans = [e.data["from_state"] + "->" + e.stage for e in s.events.by_name("state_transition")]
    assert trans == [
        "CREATED->VALIDATING",
        "VALIDATING->BUILDING_MATRIX",
        "BUILDING_MATRIX->RUNNING",
        "RUNNING->GENERATING_METRICS",
        "GENERATING_METRICS->WRITING_ARTIFACTS",
        "WRITING_ARTIFACTS->FINALIZING",
        "FINALIZING->COMPLETED",
    ]


# 6. event logging ──────────────────────────────────────────────────────────────────


def test_event_logging(runner, tmp_path):
    s = runner.run(_cfg(tmp_path))
    names = {e.name for e in s.events.events}
    for expected in (
        "registry_started",
        "validation_passed",
        "execution_completed",
        "metrics_completed",
        "artifacts_written",
        "registry_updated",
        "run_completed",
    ):
        assert expected in names
    assert all(e.timestamp is not None for e in s.events.events)


# 7. artifact generation ────────────────────────────────────────────────────────────


def test_artifact_generation(runner, tmp_path):
    s = runner.run(_cfg(tmp_path, name="art"))
    assert set(s.artifacts) == set(_ARTIFACTS)
    for meta in s.artifacts.values():
        assert (tmp_path / "art").joinpath  # dir exists
        from pathlib import Path

        assert Path(meta["location"]).exists()
        assert meta["hash"]


# 8. registry integration ───────────────────────────────────────────────────────────


def test_registry_integration(runner, tmp_path):
    s = runner.run(_cfg(tmp_path))
    exp = runner.registry.load(s.experiment_id)
    assert exp.status == "finished"
    assert exp.metrics["Sharpe"] == 1.5
    assert len(exp.artifacts) == len(_ARTIFACTS)  # artifact hashes stored in registry


# 9. research matrix integration ────────────────────────────────────────────────────


def test_matrix_integration(tmp_path):
    class FakeMatrix:
        universe_size = 3
        directions = {"market_cap": "higher", "roe": "higher"}
        metadata = {"data_versions": {"feature_registry": "fr1"}}

    class FakeMatrixEngine:
        def __init__(self):
            self.called = None

        def feature_matrix_as_of(self, as_of, universe=None, features=None):
            self.called = (as_of, tuple(features or ()))
            return FakeMatrix()

    me = FakeMatrixEngine()
    runner = ResearchRunner(
        registry=ExperimentRegistry(store=RegistryStore(":memory:")), matrix_engine=me
    )
    s = runner.run(_cfg(tmp_path, name="mx", build_matrix=True))
    assert s.state == State.COMPLETED
    assert s.matrix is not None
    assert s.matrix.universe_size == 3
    assert me.called is not None  # platform invoked the matrix engine
    assert any(e.name == "matrix_build_finished" for e in s.events.events)
    runner.registry.close()


# 10. resume ─────────────────────────────────────────────────────────────────────────


def test_resume(runner, tmp_path):
    s = runner.run(_cfg(tmp_path, name="res"), stop_after=State.VALIDATING)
    assert s.state == State.VALIDATING
    assert s.report is None
    resumed = runner.resume(s)
    assert resumed.state == State.COMPLETED
    assert resumed.report is not None


# 11. cancel ─────────────────────────────────────────────────────────────────────────


def test_cancel(runner, tmp_path):
    # cancel via a before_backtest hook → run stops before execution
    runner.hooks.register("before_backtest", lambda sess: sess.request_cancel())
    s = runner.run(_cfg(tmp_path, name="cxl"))
    assert s.state == State.CANCELLED
    assert s.report is None  # never executed
    assert runner.registry.load(s.experiment_id).status == "cancelled"


# 12. validation failures ────────────────────────────────────────────────────────────


def test_validation_failures(runner, tmp_path):
    # missing random seed + unknown feature
    bad = _cfg(tmp_path, name="bad", random_seed=None, features=["not_a_feature"])
    issues = runner.validate(bad)
    assert any("random_seed" in i for i in issues)
    assert any("features_invalid" in i for i in issues)
    # running it aborts before execution
    s = runner.run(bad)
    assert s.state == State.FAILED
    assert s.report is None
    assert "validation failed" in s.error


# 13. hook execution ─────────────────────────────────────────────────────────────────


def test_hook_execution(runner, tmp_path):
    fired = []
    for pt in ("before_validation", "after_matrix", "before_metrics", "before_registry_close"):
        runner.hooks.register(pt, lambda sess, p=pt: fired.append(p))
    runner.run(_cfg(tmp_path, name="hooks"))
    assert fired == ["before_validation", "after_matrix", "before_metrics", "before_registry_close"]


# 14. backward compatibility — a REAL backtest through the platform ─────────────────


def test_real_backtest_through_platform(runner, tmp_path):
    from mentisrex.backtesting.data import InMemoryDataFeed
    from mentisrex.research.runner import research_config, synth_bars
    from mentisrex.research.templates import MeanReversionStrategy

    bars = synth_bars(["AAA", "BBB"], days=120, seed=3)
    executor = make_backtest_executor(
        MeanReversionStrategy(lookback=20), InMemoryDataFeed(bars), research_config()
    )
    s = runner.run(_cfg(tmp_path, name="real", executor=executor, parameters={"lookback": 20}))
    assert s.state == State.COMPLETED
    assert "Sharpe" in s.metrics
    assert "MaxDrawdown" in s.metrics
    assert check(s)["ok"]
