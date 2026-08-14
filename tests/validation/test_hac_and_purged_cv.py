"""M31: HAC standard errors + purged/embargoed CV — leakage & correctness tests."""

import numpy as np
import pytest

from mentisrex.research.validation.cross_validation import (
    purged_kfold,
    walk_forward_purged,
)
from mentisrex.research.validation.hac import (
    auto_lag,
    hac_standard_error,
)
from mentisrex.research.validation.significance import significance


def _ar1(n, phi, seed=0):
    rng = np.random.default_rng(seed)
    e = rng.standard_normal(n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def test_hac_ge_iid_under_positive_autocorrelation():
    r = _ar1(1000, 0.5)
    iid_se = r.std(ddof=0) / np.sqrt(r.size)
    hac_se = hac_standard_error(r)
    # positive serial correlation => HAC inflates the SE relative to IID
    assert hac_se > iid_se * 1.2


def test_hac_matches_iid_at_lag_zero():
    r = _ar1(500, 0.3, seed=1)
    iid_se = r.std(ddof=0) / np.sqrt(r.size)
    assert hac_standard_error(r, lag=0) == pytest.approx(iid_se, rel=1e-12)


def test_hac_lag_bounds_and_auto():
    assert auto_lag(1) == 0
    assert 0 < auto_lag(1000) < 1000
    # lag is clamped to n-1
    assert hac_standard_error(_ar1(10, 0.2), lag=999) == hac_standard_error(_ar1(10, 0.2), lag=9)


def test_significance_carries_hac_fields_and_leaves_iid_intact():
    r = _ar1(300, 0.4, seed=2)
    s = significance(r)
    for k in ("t_stat", "p_value", "standard_error", "sharpe"):  # existing untouched
        assert k in s
    for k in ("hac_se", "hac_t_stat", "hac_p_value", "hac_lag"):  # additive
        assert k in s
    assert s["hac_se"] > s["standard_error"]  # positive AR => wider HAC SE


def test_purged_kfold_no_leakage_within_horizon_and_embargo():
    n, H, emb = 100, 5, 3
    for train, test in purged_kfold(n, n_splits=5, label_horizon=H, embargo=emb):
        assert set(train).isdisjoint(test)
        lo, hi = min(test), max(test)
        for i in train:
            # no train row whose label window [i, i+H] reaches the test block,
            # and none inside the embargo band after it
            assert not (lo - H <= i <= hi + emb)


def test_purged_kfold_covers_all_test_indices_once():
    n = 50
    seen = []
    for _, test in purged_kfold(n, n_splits=5):
        seen.extend(test)
    assert sorted(seen) == list(range(n))


def test_walk_forward_purged_trains_only_on_past_with_gap():
    n, H, emb = 100, 4, 2
    for train, test in walk_forward_purged(n, n_splits=5, label_horizon=H, embargo=emb):
        assert max(train) < min(test) - (H + emb) + 1  # gap enforced
        assert max(train) < min(test)


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        list(purged_kfold(10, n_splits=1))
    with pytest.raises(ValueError):
        list(purged_kfold(10, n_splits=2, label_horizon=-1))
