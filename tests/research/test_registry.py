"""Research experiment registry regression (AIDP M7). All offline.

Lifecycle, order-independent hashing, stable fingerprints, duplicate detection,
reproduction, search, comparison, and a clean failure path.
"""

from __future__ import annotations

import pytest

from aurelius.research.experiment_registry import ExperimentRegistry, RegistryStore, check
from aurelius.research.experiment_registry import hashing, lineage


@pytest.fixture
def reg():
    r = ExperimentRegistry(store=RegistryStore(":memory:"))
    yield r
    r.close()


def _dv():
    return lineage.dataset_versions(prices=100, fundamentals=50, insiders=20, universe=10,
                                    securitymaster=10, feature_registry_version="fr1")


def _start(reg, name="exp", params=None, features=None, seed=42):
    return reg.start_experiment(
        name, parameters=params or {"lookback": 252, "top": 50},
        features=features or ["market_cap", "roe"], dataset_versions=_dv(),
        random_seed=seed, description="desc")


# 1. start records metadata ───────────────────────────────────────────────────────

def test_start_records_metadata(reg):
    exp = _start(reg)
    assert exp.status == "running"
    assert exp.name == "exp" and exp.random_seed == 42
    assert exp.git_commit and exp.python_version and exp.platform  # auto-captured lineage
    assert exp.created_at is not None and exp.started_at is not None
    loaded = reg.load(exp.experiment_id)
    assert loaded.parameters == {"lookback": 252, "top": 50}
    assert sorted(loaded.features) == ["market_cap", "roe"]
    assert loaded.dataset_versions["prices_version"] == 100


# 2. finish computes duration ──────────────────────────────────────────────────────

def test_finish_computes_duration(reg):
    exp = _start(reg)
    done = reg.finish_experiment(exp, metrics={"Sharpe": 1.8, "MaxDrawdown": -0.2})
    assert done.status == "finished"
    assert done.duration_seconds is not None and done.duration_seconds >= 0
    reloaded = reg.load(exp.experiment_id)
    assert reloaded.metrics["Sharpe"] == 1.8
    assert reloaded.status == "finished"


# 3. parameter hash independent of ordering ────────────────────────────────────────

def test_parameter_hash_order_independent():
    assert hashing.hash_params({"lookback": 252, "top": 50}) == \
           hashing.hash_params({"top": 50, "lookback": 252})
    # nested dicts too
    assert hashing.hash_params({"a": {"x": 1, "y": 2}}) == hashing.hash_params({"a": {"y": 2, "x": 1}})
    assert hashing.hash_params({"lookback": 252}) != hashing.hash_params({"lookback": 100})


# 4. dataset fingerprint stable ────────────────────────────────────────────────────

def test_dataset_fingerprint_stable():
    a = hashing.dataset_fingerprint(_dv())
    b = hashing.dataset_fingerprint(_dv())
    assert a == b                                       # deterministic across calls
    changed = dict(_dv(), prices_version=999)
    assert hashing.dataset_fingerprint(changed) != a    # any version change → new fingerprint


# 5. duplicate detection ───────────────────────────────────────────────────────────

def test_duplicate_detected(reg):
    first = _start(reg)
    reg.finish_experiment(first, metrics={"Sharpe": 1.0})
    # identical data + features + params (params reordered) → duplicate
    dup = reg.start_experiment("exp2", parameters={"top": 50, "lookback": 252},
                               features=["roe", "market_cap"], dataset_versions=_dv(),
                               random_seed=7)
    assert dup.duplicate_of == first.experiment_id
    assert dup.fingerprint == first.fingerprint
    # a different parameter → not a duplicate
    solo = reg.start_experiment("exp3", parameters={"lookback": 100},
                                features=["roe"], dataset_versions=_dv())
    assert solo.duplicate_of is None


# 6. reproduce returns identical configuration ─────────────────────────────────────

def test_reproduce_identical_config(reg):
    exp = _start(reg, params={"lookback": 252, "top": 50})
    reg.finish_experiment(exp, metrics={"Sharpe": 2.0})
    cfg = reg.reproduce(exp.experiment_id)
    assert cfg["parameters"] == {"lookback": 252, "top": 50}
    assert sorted(cfg["features"]) == ["market_cap", "roe"]
    assert cfg["dataset_versions"] == exp.dataset_versions
    assert cfg["research_matrix_version"] == exp.dataset_versions["research_matrix_version"]
    # re-running the reproduced config reproduces the fingerprint
    rerun = reg.start_experiment(cfg["name"], parameters=cfg["parameters"],
                                 features=cfg["features"], dataset_versions=cfg["dataset_versions"])
    assert rerun.fingerprint == exp.fingerprint


# 7. search ─────────────────────────────────────────────────────────────────────────

def test_search(reg):
    a = _start(reg, name="alpha")
    reg.finish_experiment(a, metrics={"Sharpe": 1.0})
    b = _start(reg, name="beta", params={"lookback": 60})
    by_name = reg.search(name="alpha")
    assert len(by_name) == 1 and by_name[0].experiment_id == a.experiment_id
    finished = reg.search(status="finished")
    assert [e.experiment_id for e in finished] == [a.experiment_id]
    running = reg.search(status="running")
    assert b.experiment_id in [e.experiment_id for e in running]


# 8. compare metric differences ────────────────────────────────────────────────────

def test_compare_metric_differences(reg):
    a = _start(reg, name="a", params={"lookback": 252})
    reg.finish_experiment(a, metrics={"Sharpe": 1.0, "CAGR": 0.10})
    b = _start(reg, name="b", params={"lookback": 60})
    reg.finish_experiment(b, metrics={"Sharpe": 1.5, "CAGR": 0.14})
    cmp = reg.compare(a.experiment_id, b.experiment_id)
    assert cmp["metrics"]["Sharpe"]["delta"] == pytest.approx(0.5)
    assert cmp["metrics"]["CAGR"]["delta"] == pytest.approx(0.04)
    assert cmp["parameters_changed"] is True
    assert cmp["same_fingerprint"] is False


# 9. failure path records exception without corrupting registry ────────────────────

def test_failure_path(reg):
    exp = _start(reg)
    failed = reg.fail_experiment(exp, ValueError("bad data"), notes="crashed in backtest")
    assert failed.status == "failed"
    assert "ValueError" in failed.error and "bad data" in failed.error
    reloaded = reg.load(exp.experiment_id)
    assert reloaded.status == "failed"
    # registry still usable — a fresh experiment records fine
    ok = reg.start_experiment("recovery", parameters={"lookback": 10},
                              features=["close"], dataset_versions=_dv())
    assert reg.load(ok.experiment_id).status == "running"
    # quality flags the incomplete failed run without raising
    rep = check(reloaded)
    assert rep["experiment_id"] == exp.experiment_id and isinstance(rep["issues"], list)
