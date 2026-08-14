"""M32: cross-sectional neutralization + signal redundancy detection."""

import numpy as np
import pytest

from mentisrex.research.cross_sectional import (
    information_coefficient,
    is_disguised,
    neutralize,
    percentile_rank,
    quantile_spread,
    rankdata,
    redundancy_report,
    spearman,
    zscore,
)


def test_rank_ties_average():
    r = rankdata([10, 10, 20, 5])
    assert list(r) == [2.5, 2.5, 4.0, 1.0]


def test_rank_and_percentile_preserve_nan():
    r = rankdata([1.0, np.nan, 3.0])
    assert np.isnan(r[1]) and r[0] == 1.0 and r[2] == 2.0
    p = percentile_rank([1.0, 2.0, 3.0])
    assert p[0] == 0.0 and p[2] == 1.0


def test_zscore_mean0_std1():
    z = zscore([1, 2, 3, 4, 5])
    assert z.mean() == pytest.approx(0.0, abs=1e-12)
    assert z.std(ddof=0) == pytest.approx(1.0, abs=1e-12)


def test_neutralize_removes_group_means():
    x = np.array([1.0, 3.0, 10.0, 12.0])          # group A ~2, group B ~11
    groups = ["A", "A", "B", "B"]
    resid = neutralize(x, groups=groups)
    # residual has ~zero mean within each sector => sector-neutral
    assert resid[:2].mean() == pytest.approx(0.0, abs=1e-9)
    assert resid[2:].mean() == pytest.approx(0.0, abs=1e-9)


def test_neutralize_orthogonal_to_covariate():
    rng = np.random.default_rng(0)
    beta = rng.standard_normal(200)
    x = 3.0 * beta + rng.standard_normal(200) * 0.1   # x almost pure beta
    resid = neutralize(x, covariates=beta)
    # residual is orthogonal to the covariate it was regressed out of
    assert abs(np.corrcoef(resid, beta)[0, 1]) < 1e-9


def test_neutralize_drops_nan_rows():
    x = np.array([1.0, np.nan, 3.0, 4.0])
    resid = neutralize(x, covariates=np.array([1.0, 2.0, np.nan, 4.0]))
    assert np.isnan(resid[1]) and np.isnan(resid[2])
    assert np.isfinite(resid[0]) and np.isfinite(resid[3])


def test_ic_and_quantile_spread_monotone():
    signal = np.arange(100, dtype=float)
    fwd = np.arange(100, dtype=float) * 0.01          # perfectly increasing
    assert information_coefficient(signal, fwd) == pytest.approx(1.0, abs=1e-9)
    qs = quantile_spread(signal, fwd, q=5)
    assert qs["monotonic"] and qs["long_short"] > 0


def test_is_disguised_by_correlation():
    rng = np.random.default_rng(1)
    a = rng.standard_normal(300)
    b = a + rng.standard_normal(300) * 0.01           # near-identical
    fwd = rng.standard_normal(300)
    d = is_disguised(a, b, fwd)
    assert d["disguised"] and d["reason"] == "high_correlation"


def test_is_disguised_by_ic_collapse():
    rng = np.random.default_rng(2)
    known = rng.standard_normal(400)
    fwd = known * 0.5 + rng.standard_normal(400) * 0.1   # edge comes from `known`
    # new signal = known rotated + small independent noise, low raw corr but IC is
    # entirely spanned by known
    new = known + rng.standard_normal(400) * 2.0
    d = is_disguised(new, known, fwd, corr_threshold=0.99)
    assert d["disguised"] and d["reason"] == "ic_collapse"


def test_independent_signal_not_flagged():
    rng = np.random.default_rng(3)
    a = rng.standard_normal(300)
    b = rng.standard_normal(300)
    fwd = a * 0.4 + rng.standard_normal(300) * 0.5
    d = is_disguised(a, b, fwd)
    assert not d["disguised"] and d["reason"] == "independent"


def test_redundancy_report_screens_library():
    rng = np.random.default_rng(4)
    base = rng.standard_normal(200)
    lib = {"momentum": base, "value": rng.standard_normal(200)}
    new = base + rng.standard_normal(200) * 0.01
    rep = redundancy_report(new, lib)
    assert rep["redundant"] and rep["n_compared"] == 2
    assert rep["matches"][0]["signal"] == "momentum"


def test_spearman_symmetry_and_nan_safe():
    a = [1.0, 2.0, np.nan, 4.0]
    b = [2.0, 1.0, 3.0, 8.0]
    assert spearman(a, b) == pytest.approx(spearman(b, a))
