"""M35: factor campaign runner — status, DoF logging, redundancy screening."""

import numpy as np
import pytest

from mentisrex.research.factor_campaign import FactorCampaign


def _factor(T, N, edge, seed):
    rng = np.random.default_rng(seed)
    signals, fwd = [], []
    for _ in range(T):
        names = [f"s{i}" for i in range(N)]
        sig = rng.standard_normal(N)
        ret = edge * sig + rng.standard_normal(N)
        signals.append(dict(zip(names, sig, strict=False)))
        fwd.append(dict(zip(names, ret, strict=False)))
    return signals, fwd


@pytest.fixture
def camp():
    c = FactorCampaign(":memory:", t_min=2.0, redundancy_threshold=0.8)
    yield c
    c.close()


def test_promising_factor(camp):
    sig, fwd = _factor(60, 50, edge=0.8, seed=0)
    res = camp.run("mom12", "momentum", sig, fwd)
    assert res.status == "PROMISING"
    assert res.report.ic_t_stat > 2.0
    assert camp.n_trials("momentum") == 1


def test_insignificant_factor(camp):
    sig, fwd = _factor(60, 50, edge=0.0, seed=9)
    res = camp.run("noise", "misc", sig, fwd)
    assert res.status == "INSIGNIFICANT"


def test_redundant_factor_flagged(camp):
    sig, fwd = _factor(80, 60, edge=0.9, seed=1)
    first = camp.run("mom_a", "momentum", sig, fwd)
    assert first.status == "PROMISING"
    # same underlying signal, tiny relabel => near-identical long-short returns
    sig2 = [{k: v + 1e-6 for k, v in d.items()} for d in sig]
    second = camp.run("mom_b", "momentum", sig2, fwd)
    assert second.status == "REDUNDANT"
    assert second.redundant_with == "mom_a"


def test_dof_ledger_accumulates_across_runs(camp):
    for i in range(5):
        sig, fwd = _factor(40, 40, edge=0.3, seed=100 + i)
        camp.run(f"v{i}", "reversal", sig, fwd, variant=f"v{i}")
    # 5 distinct variants of one mechanism => 5 degrees of freedom
    assert camp.n_trials("reversal") == 5


def test_library_listing_and_filter(camp):
    sig, fwd = _factor(60, 50, edge=0.8, seed=0)
    camp.run("good", "momentum", sig, fwd)
    sig2, fwd2 = _factor(60, 50, edge=0.0, seed=9)
    camp.run("bad", "misc", sig2, fwd2)
    assert len(camp.library()) == 2
    promising = camp.library(status="PROMISING")
    assert len(promising) == 1
    assert promising[0]["name"] == "good"


def test_independent_factor_not_redundant(camp):
    sig1, fwd1 = _factor(80, 60, edge=0.9, seed=1)
    camp.run("mom", "momentum", sig1, fwd1)
    sig2, fwd2 = _factor(80, 60, edge=0.9, seed=777)  # independent draws
    res = camp.run("other", "value", sig2, fwd2)
    assert res.status != "REDUNDANT"
