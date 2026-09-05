"""M37: signal ensembling — combination methods + diversification diagnostics."""

import numpy as np
import pytest

from mentisrex.research.ensemble import (
    combine,
    correlation_matrix,
    effective_bets,
)


def _indep(K, T, seed=0):
    rng = np.random.default_rng(seed)
    return {f"f{i}": list(rng.standard_normal(T) * 0.01 + 0.002) for i in range(K)}


def test_equal_weight_sums_to_one():
    e = combine(_indep(4, 200), method="equal")
    assert sum(e.weights.values()) == pytest.approx(1.0)
    assert all(w == pytest.approx(0.25) for w in e.weights.values())


def test_diversification_benefit_from_independent_factors():
    # independent factors => diversification ratio well above 1
    e = combine(_indep(5, 500), method="equal")
    assert e.diversification_ratio > 1.5
    assert e.effective_bets > 3.0


def test_redundant_factors_collapse_effective_bets():
    rng = np.random.default_rng(1)
    base = rng.standard_normal(300) * 0.01
    sm = {"a": list(base), "b": list(base + 1e-9), "c": list(base + 1e-9)}
    e = combine(sm, method="equal")
    assert e.effective_bets < 1.5  # three copies of one bet ~= one bet
    assert e.avg_correlation > 0.99


def test_inverse_var_downweights_noisy_factor():
    rng = np.random.default_rng(2)
    sm = {
        "calm": list(rng.standard_normal(300) * 0.005),
        "wild": list(rng.standard_normal(300) * 0.05),
    }
    e = combine(sm, method="inverse_var")
    assert e.weights["calm"] > e.weights["wild"]


def test_ic_weight_requires_and_uses_ic_map():
    sm = _indep(3, 200)
    with pytest.raises(ValueError):
        combine(sm, method="ic_weight")
    e = combine(sm, method="ic_weight", ic_map={"f0": 0.1, "f1": 0.05, "f2": 0.0})
    assert e.weights["f0"] > e.weights["f1"] > e.weights["f2"]


def test_empty_raises():
    with pytest.raises(ValueError):
        combine({})


def test_correlation_matrix_shape():
    _names, corr = correlation_matrix(_indep(3, 100))
    assert corr.shape == (3, 3)
    assert np.allclose(np.diag(corr), 1.0)


def test_effective_bets_single_factor():
    M = np.array([[0.01, -0.01, 0.02, 0.0]])
    assert effective_bets(M) == pytest.approx(1.0, abs=1e-9)


def test_combine_from_campaign_library():
    from mentisrex.research.factor_campaign import FactorCampaign

    def factor(edge, seed):
        rng = np.random.default_rng(seed)
        sig, fwd = [], []
        for _ in range(80):
            names = [f"s{i}" for i in range(50)]
            s = rng.standard_normal(50)
            sig.append(dict(zip(names, s, strict=False)))
            fwd.append(dict(zip(names, edge * s + rng.standard_normal(50), strict=False)))
        return sig, fwd

    camp = FactorCampaign(":memory:", t_min=2.0)
    try:
        camp.run("mom", "momentum", *factor(0.8, 1))
        camp.run("val", "value", *factor(0.8, 500))  # independent
        series = camp.return_series(status="PROMISING")
        assert len(series) == 2
        e = combine(series, method="equal")
        assert e.effective_bets > 1.5  # two genuinely independent edges
    finally:
        camp.close()
