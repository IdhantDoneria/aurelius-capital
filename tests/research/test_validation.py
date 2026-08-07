"""Research Validation Framework regression (AIDP M9). All offline, deterministic.

Bootstrap, permutation, walk-forward, sensitivity/stability, capacity, multiple
testing, overfitting, verdict logic, artifacts, and registry + execution integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from aurelius.backtesting.analytics.performance import EquityPoint, PerformanceMetrics, RoundTrip
from aurelius.research.validation import ResearchValidator, ValidationConfig, check
from aurelius.research.validation import (
    bootstrap,
    capacity as cap_mod,
    multiple_testing,
    overfitting,
    permutation,
    scoring,
    walkforward,
)
from aurelius.research.validation.significance import sharpe, significance
from aurelius.research.experiment_registry import ExperimentRegistry, RegistryStore, lineage


def _series(drift, vol, n=750, seed=1):
    rng = np.random.default_rng(seed)
    return list(rng.normal(drift, vol, n))


def _pm(drift=0.0012, vol=0.008, n=750, turnover=2.0, seed=1):
    rets = _series(drift, vol, n, seed)
    t0 = datetime(2016, 1, 1, tzinfo=UTC)
    eq = [1e6]
    for r in rets:
        eq.append(eq[-1] * (1 + r))
    curve = [EquityPoint(t0 + timedelta(days=i), eq[i]) for i in range(len(eq))]
    peak, dd = eq[0], []
    for i, e in enumerate(eq):
        peak = max(peak, e)
        dd.append((curve[i].timestamp, (e - peak) / peak))
    rts = [RoundTrip("A", "long", t0, t0 + timedelta(days=5), 100, 100.0, 110.0, 900.0),
           RoundTrip("B", "long", t0, t0 + timedelta(days=8), 100, 50.0, 48.0, -200.0)]
    return PerformanceMetrics(
        cagr=0.2, annualized_volatility=vol * np.sqrt(252), sharpe_ratio=2.0,
        max_drawdown=min(d for _, d in dd), num_trades=2, annual_turnover=turnover,
        avg_holding_period_days=6.5, equity_curve=curve, drawdown_series=dd,
        daily_returns=rets, round_trips=rts)


@pytest.fixture
def registry():
    r = ExperimentRegistry(store=RegistryStore(":memory:"))
    yield r
    r.close()


def _experiment(registry, name="val"):
    dv = lineage.dataset_versions(prices=100, fundamentals=50, insiders=20, universe=10,
                                  securitymaster=10, feature_registry_version="fr1")
    exp = registry.start_experiment(name, parameters={"lookback": 20}, features=["market_cap"],
                                    dataset_versions=dv, random_seed=1)
    registry.finish_experiment(exp, metrics={"Sharpe": 1.5})
    return registry.load(exp.experiment_id)


def _validator(**over):
    cfg = ValidationConfig(bootstrap_samples=300, monte_carlo_samples=200,
                           permutation_samples=400, n_trials=1, **over)
    return ResearchValidator(config=cfg)


# 1. bootstrap correctness ──────────────────────────────────────────────────────

def test_bootstrap_correctness():
    r = _series(0.001, 0.01, 500)
    ci = bootstrap.bootstrap_ci(r, np.mean, n_samples=500, method="iid", seed=7)
    assert ci["ci_low"] <= ci["estimate"] <= ci["ci_high"]
    assert ci["ci_low"] < np.mean(r) < ci["ci_high"]         # brackets the true mean
    # deterministic given the seed
    ci2 = bootstrap.bootstrap_ci(r, np.mean, n_samples=500, method="iid", seed=7)
    assert ci["ci_low"] == ci2["ci_low"] and ci["ci_high"] == ci2["ci_high"]
    # all four methods run
    for m in bootstrap.METHODS:
        assert bootstrap.bootstrap_ci(r, sharpe, n_samples=100, method=m, seed=1)["n_samples"] == 100


# 2. permutation correctness ─────────────────────────────────────────────────────

def test_permutation_correctness():
    strong = _series(0.0015, 0.006, 500, seed=2)     # clear positive drift
    p_strong = permutation.permutation_test(strong, sharpe, kind="sign", n_samples=500, seed=0)
    assert p_strong["p_value"] < 0.05
    noise = _series(0.0, 0.01, 500, seed=3)           # zero-mean noise
    p_noise = permutation.permutation_test(noise, sharpe, kind="sign", n_samples=500, seed=0)
    assert p_noise["p_value"] > 0.05          # zero-mean noise: not significant at 5%


# 3. walk-forward splits ──────────────────────────────────────────────────────────

def test_walkforward_splits():
    r = _series(0.001, 0.01, 500)
    roll = walkforward.rolling_windows(r, n_folds=5)
    assert roll["folds"] == 5 and 0.0 <= roll["share_positive"] <= 1.0
    exp = walkforward.expanding_windows(r, n_folds=5)
    assert exp["folds"] == 5
    ts = [datetime(2016, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(len(r))]
    loo = walkforward.leave_one_out(r, ts, by="year")
    assert loo["folds"] >= 2 and "max_swing" in loo    # spans multiple years


# 4. parameter sensitivity / stability ────────────────────────────────────────────

def test_parameter_sensitivity():
    from aurelius.research.validation import sensitivity, stability
    # evaluator: Sharpe peaks near lookback=20, flat plateau around it
    def evaluator(overrides):
        v = overrides.get("lookback", 20)
        drift = 0.0012 - 0.00002 * abs(v - 20)
        return _series(max(drift, 0.0), 0.008, 400, seed=int(v))
    grid = [10, 15, 20, 25, 30]
    stab = stability.stability_curve(evaluator, "lookback", grid)
    assert 0.0 <= stab["plateau_score"] <= 1.0 and stab["peak"] > 0
    sens = sensitivity.parameter_perturbation(evaluator, "lookback", grid)
    assert "dispersion" in sens
    # no evaluator → honest insufficient_data, not a fake number
    assert sensitivity.parameter_perturbation(None, "lookback", grid)["insufficient_data"]


# 5. capacity estimation ──────────────────────────────────────────────────────────

def test_capacity_estimation():
    pm = _pm()
    with_adv = cap_mod.capacity_analysis(pm, aum=1e8, adv=5e7)
    assert with_adv["adv_supplied"] and with_adv["implementation_shortfall"] >= 0
    assert with_adv["estimated_capacity_aum"] > 0
    without = cap_mod.capacity_analysis(pm, adv=None)
    assert without["adv_supplied"] is False and "capacity_signal" in without


# 6. multiple-testing correction ──────────────────────────────────────────────────

def test_multiple_testing():
    pvals = [0.001, 0.02, 0.04, 0.5, 0.8]
    bonf = multiple_testing.bonferroni(pvals)
    assert bonf["adjusted"][0] == pytest.approx(0.005)      # 0.001 * 5
    assert all(a >= p for a, p in zip(bonf["adjusted"], pvals))
    holm = multiple_testing.holm(pvals)
    bh = multiple_testing.benjamini_hochberg(pvals)
    assert holm["reject"][0] and bh["reject"][0]            # strongest survives all
    assert sum(bh["reject"]) >= sum(bonf["reject"])         # BH at least as powerful


# 7. overfitting pipeline ─────────────────────────────────────────────────────────

def test_overfitting_pipeline():
    strong = _series(0.0015, 0.006, 750, seed=2)
    weak = _series(0.00005, 0.012, 750, seed=3)
    dsr_strong = overfitting.deflated_sharpe_ratio(strong, n_trials=1)["dsr"]
    dsr_weak = overfitting.deflated_sharpe_ratio(weak, n_trials=100)["dsr"]
    assert dsr_strong > 0.9 and dsr_weak < 0.5
    # PBO on a random config matrix ~ 0.5 (no genuine edge)
    rng = np.random.default_rng(0)
    mat = rng.normal(0, 0.01, size=(400, 8))
    pbo = overfitting.pbo_cscv(mat)
    assert 0.0 <= pbo["pbo"] <= 1.0
    # single config → insufficient
    assert overfitting.pbo_cscv(rng.normal(0, 0.01, size=(400, 1)))["insufficient_data"]


# 8. verdict logic ────────────────────────────────────────────────────────────────

def test_verdict_logic():
    v = _validator()
    strong = v.validate(_experiment_stub(), _pm(drift=0.0012, vol=0.008))
    assert strong.overall_verdict == "PASS"
    weak = v.validate(_experiment_stub(), _pm(drift=0.00003, vol=0.013))
    assert weak.overall_verdict == "REJECT" and weak.critical_failures
    # strong but excessive turnover → PASS_WITH_WARNINGS
    warned = v.validate(_experiment_stub(), _pm(drift=0.0012, vol=0.008, turnover=15.0))
    assert warned.overall_verdict == "PASS_WITH_WARNINGS"
    assert any("turnover" in w for w in warned.warnings)


# 9. artifact generation ──────────────────────────────────────────────────────────

def test_artifact_generation(tmp_path):
    rep = _validator().validate(_experiment_stub(), _pm(), artifacts_dir=str(tmp_path))
    arts = rep.execution_metadata["artifacts"]
    assert set(arts) == {"validation_report.json", "validation_visuals.json", "plot_validation.py"}
    for meta in arts.values():
        from pathlib import Path
        assert Path(meta["location"]).exists() and meta["hash"]
    assert rep.manifest_hash and check(rep)["ok"]


# 10. registry integration ────────────────────────────────────────────────────────

def test_registry_integration(registry, tmp_path):
    exp = _experiment(registry)
    v = ResearchValidator(config=ValidationConfig(bootstrap_samples=200, monte_carlo_samples=100,
                          permutation_samples=200, n_trials=1), registry=registry)
    rep = v.validate(exp, _pm(), artifacts_dir=str(tmp_path))
    reloaded = registry.load(exp.experiment_id)
    assert "ValidationScore" in reloaded.metrics
    assert reloaded.metrics["ValidationScore"] == pytest.approx(rep.research_score)
    assert rep.overall_verdict in reloaded.notes
    assert any("validation_report" in a["artifact_type"] for a in reloaded.artifacts)


# 11. execution integration (M8 → M9) ──────────────────────────────────

def test_execution_integration(registry, tmp_path):
    from aurelius.research.execution import ResearchRunner, RunConfiguration

    class _Report:
        metrics = _pm()

    def executor(session):
        return _Report()

    runner = ResearchRunner(registry=registry)
    dv = lineage.dataset_versions(prices=100, fundamentals=50, insiders=20, universe=10,
                                  securitymaster=10, feature_registry_version="fr1")
    cfg = RunConfiguration(name="e2e", parameters={"lookback": 20}, features=["market_cap"],
                           dataset_versions=dv, random_seed=1, executor=executor,
                           artifacts_dir=str(tmp_path / "run"))
    session = runner.run(cfg)
    # validate the completed session directly
    v = ResearchValidator(config=ValidationConfig(bootstrap_samples=150, monte_carlo_samples=80,
                          permutation_samples=150, n_trials=1), registry=registry)
    rep = v.validate(session.experiment, session, artifacts_dir=str(tmp_path / "val"))
    assert rep.overall_verdict in ("PASS", "PASS_WITH_WARNINGS", "REQUIRES_REVIEW", "REJECT")
    assert registry.load(session.experiment_id).metrics.get("ValidationScore") is not None


# 12. failure recovery ────────────────────────────────────────────────────────────

def test_failure_recovery():
    class Broken:
        pass  # no metrics / daily_returns
    rep = _validator().validate(_experiment_stub(), Broken())
    assert rep.overall_verdict == "REQUIRES_REVIEW"
    assert rep.critical_failures and rep.manifest_hash


# scoring sanity ───────────────────────────────────────────────────────────────────

def test_scoring_weights_configurable():
    summaries = {"significance": significance(_series(0.001, 0.01, 400)),
                 "overfitting": {"dsr": 0.9}, "robustness": {"rolling": {"share_positive": 0.8},
                 "expanding": {"share_positive": 0.8}, "missing_data": {"max_degradation": 0.0}},
                 "capacity": {"adv_utilisation": 0.05}}
    res = scoring.score(summaries, None, weights={"statistical_validity": 0.5})
    assert 0 <= res["research_score"] <= 100
    assert set(res["components"]) == set(scoring.DEFAULT_WEIGHTS)
    assert abs(sum(res["contributions"].values()) - res["research_score"]) < 1e-6


class _ExpStub:
    experiment_id = "STUB"
    fingerprint = "fp"
    git_commit = "commit"
    random_seed = 1
    dataset_versions = {"feature_registry_version": "fr1"}
    features = ["market_cap"]
    artifacts: list = []
    metrics: dict = {}


def _experiment_stub():
    return _ExpStub()
