"""The robustness harness has to be trustworthy before its verdicts are."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.swing.validation import (
    breakeven_cost_multiple, cost_sensitivity, parameter_sensitivity, regime_split,
    signal_decay, subperiods, walk_forward,
)

rng = np.random.default_rng(4)


def _ret(n=1500, mu=0.0004, sd=0.008, seed=1):
    return pd.Series(
        np.random.default_rng(seed).normal(mu, sd, n),
        index=pd.bdate_range("2018-01-01", periods=n),
    )


def test_subperiods_partitions_without_gaps_or_overlap():
    r = _ret(n=1500)
    t = subperiods(r)
    assert len(t) >= 5
    assert t["n_days"].sum() == pytest.approx(len(r), abs=40)


def test_regime_split_uses_expanding_quantiles_not_full_sample():
    """A day's regime label must be knowable on that day. With expanding
    quantiles the first year is unlabelled; with full-sample quantiles it
    would not be."""
    r = _ret(n=1500)
    vix = pd.Series(rng.lognormal(2.8, 0.35, len(r)), index=r.index)
    t = regime_split(r, vix, n_buckets=3, labels=("lo", "mid", "hi"))
    assert set(t.index) <= {"lo", "mid", "hi"}
    assert t["n_days"].sum() < len(r)          # warm-up genuinely excluded
    assert t["n_days"].sum() > 0.5 * len(r)


def test_regime_split_detects_a_planted_conditional_edge():
    n = 2000
    idx = pd.bdate_range("2016-01-01", periods=n)
    vix = pd.Series(rng.lognormal(2.8, 0.4, n), index=idx)
    hi = vix > vix.median()
    r = pd.Series(rng.normal(0, 0.008, n), index=idx) + np.where(hi, 0.0015, 0.0)
    t = regime_split(r, vix, n_buckets=3, labels=("lo", "mid", "hi"))
    assert t.loc["hi", "sharpe"] > t.loc["lo", "sharpe"]


def test_walk_forward_never_scores_on_training_data():
    dates = pd.bdate_range("2015-01-01", periods=2200)
    seen: list[tuple] = []

    def run_fn(params, idx):
        seen.append((params["k"], idx[0], idx[-1]))
        return pd.Series(rng.normal(0.0002 * params["k"], 0.008, len(idx)), index=idx)

    oos, folds = walk_forward(run_fn, [{"k": 1}, {"k": 2}], dates, train_years=3, test_years=1)
    assert len(folds) >= 5
    assert not oos.index.duplicated().any()
    for _, f in folds.iterrows():
        assert f["test_start"] > f["train_end"]


def test_walk_forward_test_windows_tile_without_gaps():
    """Every session after the first training window must appear exactly once
    in the out-of-sample record. Advancing the anchor by the *training*
    length instead of the test length silently drops whole years."""
    dates = pd.bdate_range("2015-01-01", periods=2200)

    def run_fn(params, idx):
        return pd.Series(0.0004, index=idx)

    oos, folds = walk_forward(run_fn, [{"k": 1}], dates, train_years=3, test_years=1)
    first_test = pd.Timestamp(folds["test_start"].iloc[0])
    expected = dates[dates >= first_test]
    assert len(oos) == len(expected)
    assert (oos.index == expected).all()


def test_walk_forward_output_is_contiguous_and_ordered():
    dates = pd.bdate_range("2016-01-01", periods=2000)

    def run_fn(params, idx):
        return pd.Series(0.0005, index=idx)

    oos, folds = walk_forward(run_fn, [{"k": 1}], dates, train_years=3, test_years=1)
    assert oos.index.is_monotonic_increasing
    assert oos.index[0] > dates[0]


def test_parameter_sensitivity_reports_every_grid_point():
    grid = [{"a": a, "b": b} for a in (1, 2) for b in (10, 20, 30)]

    def run_fn(p):
        return pd.Series(
            rng.normal(0.0001 * p["a"], 0.008, 800),
            index=pd.bdate_range("2019-01-01", periods=800),
        )

    t = parameter_sensitivity(run_fn, grid)
    assert len(t) == 6
    assert {"a", "b", "sharpe", "cagr", "max_dd", "nw_t"} <= set(t.columns)


def test_cost_sensitivity_is_monotonically_worse():
    def run_fn(m):
        return pd.Series(
            0.0006 - 0.0002 * m + rng.normal(0, 1e-9, 600),
            index=pd.bdate_range("2020-01-01", periods=600),
        )

    t = cost_sensitivity(run_fn, multiples=(0.5, 1.0, 2.0, 4.0))
    assert t["cagr"].is_monotonic_decreasing


def test_breakeven_multiple_interpolates_the_crossing():
    t = pd.DataFrame({"cost_multiple": [1.0, 2.0, 3.0, 4.0], "cagr": [0.10, 0.04, -0.02, -0.08]})
    be = breakeven_cost_multiple(t)
    assert 2.0 < be < 3.0
    assert be == pytest.approx(2.0 + 1.0 * 0.04 / 0.06, rel=1e-6)


def test_breakeven_multiple_when_never_profitable():
    t = pd.DataFrame({"cost_multiple": [1.0, 2.0], "cagr": [-0.01, -0.05]})
    assert breakeven_cost_multiple(t) == 1.0


def test_signal_decay_recovers_a_planted_one_day_signal():
    T, N = 400, 120
    score = rng.normal(size=(T, N))
    fwd = np.zeros((T, N))
    fwd[:] = rng.normal(0, 0.02, size=(T, N))
    fwd += 0.01 * score                        # information only in the next day
    t = signal_decay(score, fwd, horizons=(1, 5))
    assert t.loc[t["horizon_days"] == 1, "mean_ic"].iloc[0] > 0.2
    assert t.loc[t["horizon_days"] == 1, "t_stat"].iloc[0] > 5


def test_signal_decay_reports_no_ic_for_pure_noise():
    T, N = 400, 120
    score = rng.normal(size=(T, N))
    fwd = rng.normal(0, 0.02, size=(T, N))
    t = signal_decay(score, fwd, horizons=(1, 5))
    assert t["mean_ic"].abs().max() < 0.05


def test_vix_overlay_rebuild_preserves_every_risk_field():
    """A hand-rebuilt config silently drops fields added later, which is how
    a risk limit stops being applied without anything failing."""
    import dataclasses
    import numpy as np
    from mentisrex.swing.construction import OverlayConfig
    from mentisrex.swing.strategies import Lastlight, LastlightConfig
    from mentisrex.swing.strategies.base import FeatureCube, StagingConfig

    T, N = 5, 40
    zeros = np.zeros((T, N))
    cols = ["close_push", "close_push_daily", "close_vol_share", "rvol", "gap_z",
            "earn_near", "amihud20", "p_close"]
    cube = FeatureCube(dates=pd.bdate_range("2020-01-01", periods=T),
                       symbols=np.arange(N), data={c: zeros.copy() for c in cols})
    base = OverlayConfig(target_vol=0.10, max_participation=0.0007, gross_cap=2.2,
                         max_weight=0.011, dd_brake_floor=0.31)
    s = Lastlight(cube, base, StagingConfig(hold_days=1, stage=False),
                  beta=np.ones((T, N)), tradable=np.ones((T, N), bool),
                  config=LastlightConfig(), vix=np.full(T, 30.0))
    scaled = s._overlay_for(0)
    assert scaled.target_vol > base.target_vol
    for f in dataclasses.fields(OverlayConfig):
        if f.name != "target_vol":
            assert getattr(scaled, f.name) == getattr(base, f.name), f.name


def test_rolling_beta_handles_a_sample_shorter_than_its_window():
    """A short sample must yield no beta, not a broadcast error. Guarding
    this matters because the short-sample path is the one hit when iterating
    on partial data."""
    import numpy as np

    w, T, N = 60, 30, 5
    r = np.random.default_rng(0).normal(0, 0.01, (T, N))
    out = np.full_like(r, np.nan)
    if T > w:
        c = np.cumsum(np.vstack([np.zeros((1, N)), r]), axis=0)
        out[w:] = c[w + 1: T + 1] - c[1: T + 1 - w]
    assert np.isnan(out).all()


def test_rolling_beta_matches_a_direct_sum_when_the_window_fits():
    import numpy as np

    w, T, N = 5, 20, 3
    r = np.arange(T * N, dtype=float).reshape(T, N)
    c = np.cumsum(np.vstack([np.zeros((1, N)), r]), axis=0)
    out = np.full_like(r, np.nan)
    out[w:] = c[w + 1: T + 1] - c[1: T + 1 - w]
    assert np.allclose(out[w], r[1: w + 1].sum(axis=0))
    assert np.allclose(out[-1], r[T - w:].sum(axis=0))


def test_walk_forward_breaks_ties_toward_the_simpler_configuration():
    """With equal scores the earlier grid entry must win. Breaking toward the
    later one makes an inert parameter look as though it were being chosen
    deliberately in every fold -- which is exactly what happened before this
    was pinned."""
    dates = pd.bdate_range("2016-01-01", periods=1600)
    grid = [{"k": 1}, {"k": 2}, {"k": 3}]

    noise = pd.Series(
        np.random.default_rng(3).normal(0.0005, 0.008, len(dates)), index=dates
    )

    def run_fn(params, idx):
        return noise.reindex(idx)                # identical for every k

    _, folds = walk_forward(run_fn, grid, dates, train_years=2, test_years=1)
    assert len(folds) >= 2
    assert set(folds["chosen"]) == {"{'k': 1}"}


def test_walk_forward_still_prefers_a_genuinely_better_configuration():
    """The parsimony tie-break must not override a real difference."""
    dates = pd.bdate_range("2016-01-01", periods=1600)
    grid = [{"k": 1}, {"k": 2}]
    noise = pd.Series(
        np.random.default_rng(9).normal(0, 0.008, len(dates)), index=dates
    )

    def run_fn(params, idx):
        return (0.0004 * params["k"] + noise).reindex(idx)

    _, folds = walk_forward(run_fn, grid, dates, train_years=2, test_years=1)
    assert set(folds["chosen"]) == {"{'k': 2}"}
