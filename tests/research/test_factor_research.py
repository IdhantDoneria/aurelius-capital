"""M34: factor-research campaign layer — multi-date IC / IC-IR / spread / decay."""

import numpy as np
import pytest

from mentisrex.research.factor_research import evaluate_factor, ic_decay


def _panels(T, N, edge, seed=0):
    """T dates, N names. forward return = edge*signal + noise => positive-IC factor."""
    rng = np.random.default_rng(seed)
    signals, fwd = [], []
    for _ in range(T):
        names = [f"s{i}" for i in range(N)]
        sig = rng.standard_normal(N)
        ret = edge * sig + rng.standard_normal(N) * 1.0
        signals.append(dict(zip(names, sig)))
        fwd.append(dict(zip(names, ret)))
    return signals, fwd


def test_positive_factor_has_positive_ic_and_spread():
    signals, fwd = _panels(60, 50, edge=0.8)
    rep = evaluate_factor(signals, fwd, q=5, periods_per_year=12)
    assert rep.ic_mean > 0.1
    assert rep.ls_sharpe > 0
    assert rep.ic_t_stat > 2.0                 # HAC-robust significance
    assert rep.monotonic_fraction > 0.5
    assert 0.0 <= rep.turnover <= 1.0


def test_noise_factor_insignificant():
    signals, fwd = _panels(60, 50, edge=0.0, seed=7)
    rep = evaluate_factor(signals, fwd)
    assert abs(rep.ic_mean) < 0.1
    assert abs(rep.ic_t_stat) < 2.5            # no real edge => not significant


def test_ic_ir_and_hit_rate_bounds():
    signals, fwd = _panels(40, 40, edge=0.5, seed=1)
    rep = evaluate_factor(signals, fwd)
    assert rep.ic_std > 0 and np.isfinite(rep.ic_ir)
    assert 0.0 <= rep.ic_hit_rate <= 1.0


def test_neutralization_removes_group_edge():
    # signal edge lives entirely in a sector mean; sector-neutralizing kills the IC
    rng = np.random.default_rng(3)
    signals, fwd, groups = [], [], []
    for _ in range(40):
        names = [f"s{i}" for i in range(40)]
        grp = ["A" if i < 20 else "B" for i in range(40)]
        base = np.array([1.0 if g == "A" else -1.0 for g in grp])
        sig = base + rng.standard_normal(40) * 0.01
        ret = base + rng.standard_normal(40) * 0.01      # return also sector-driven
        signals.append(dict(zip(names, sig)))
        fwd.append(dict(zip(names, ret)))
        groups.append(dict(zip(names, grp)))
    raw = evaluate_factor(signals, fwd)
    neu = evaluate_factor(signals, fwd, groups=groups, neutralize_signal=True)
    assert raw.ic_mean > 0.5
    assert abs(neu.ic_mean) < abs(raw.ic_mean)           # edge was disguised sector bet


def test_misaligned_names_dropped():
    signals = [{"a": 1.0, "b": 2.0, "c": 3.0}, {"a": 1.0, "b": 2.0, "c": 3.0}]
    fwd = [{"a": 0.1, "b": 0.2}, {"b": 0.2, "c": 0.3}]   # date2 common={b,c}
    rep = evaluate_factor(signals, fwd, q=2)
    assert rep.n_periods == 2                            # both dates have >=2 common names
    # a single-name-overlap date is dropped, not counted
    rep2 = evaluate_factor([{"a": 1.0, "b": 2.0}], [{"b": 0.2, "c": 0.3}], q=2)
    assert rep2.n_periods == 0


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        evaluate_factor([{"a": 1.0}], [])


def test_ic_decay_curve():
    signals, fwd1 = _panels(30, 40, edge=0.9, seed=2)
    # horizon-2 forward returns: weaker edge (decay)
    rng = np.random.default_rng(5)
    fwd2 = []
    for sig in signals:
        names = list(sig)
        s = np.array([sig[n] for n in names])
        fwd2.append(dict(zip(names, 0.2 * s + rng.standard_normal(len(names)))))
    decay = ic_decay(signals, [fwd1, fwd2])
    assert decay[1] > decay[2]                           # IC decays with horizon
