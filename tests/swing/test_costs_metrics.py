"""Cost estimators and performance statistics."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.swing.costs import (
    CostConfig, FinancingModel, corwin_schultz_spread, impact_cost, modelled_spread,
    round_trip_bps, spread_cost,
)
from mentisrex.swing.metrics import (
    deflated_sharpe, evaluate, newey_west_t, probabilistic_sharpe, stationary_bootstrap,
)

rng = np.random.default_rng(11)


def _synthetic_hl(true_spread: float, n: int = 4000, sigma: float = 0.015):
    """Efficient price with a bid-ask bounce, sampled to daily high/low."""
    p = 100 * np.exp(np.cumsum(rng.normal(0, sigma / np.sqrt(390), n * 390)))
    p = p.reshape(n, 390)
    half = true_spread / 2.0
    side = rng.choice([-1.0, 1.0], size=p.shape)
    obs = p * (1.0 + side * half)
    return pd.Series(obs.max(axis=1)), pd.Series(obs.min(axis=1)), pd.Series(obs[:, -1])


def test_corwin_schultz_is_biased_upward_at_realistic_spread_levels():
    """Pins the reason this estimator is a diagnostic and not a cost input.

    With a 40bp spread injected under 1.5%/day volatility it overstates by
    roughly 3x; at 5bp it overstates by more than an order of magnitude. Any
    future attempt to wire it back into the cost model has to break this
    test first.
    """
    wide = corwin_schultz_spread(*_synthetic_hl(0.004)[:2]).median()
    tight = corwin_schultz_spread(*_synthetic_hl(0.0005)[:2]).median()
    assert wide / 0.004 > 2.0
    assert tight / 0.0005 > 5.0


def test_corwin_schultz_still_ranks_spread_levels_correctly():
    """It is biased in level but monotone in the true spread, which is why it
    survives as a diagnostic."""
    wide = corwin_schultz_spread(*_synthetic_hl(0.010)[:2]).median()
    tight = corwin_schultz_spread(*_synthetic_hl(0.001)[:2]).median()
    assert wide > tight


def test_modelled_spread_hits_its_calibration_anchors():
    vol = np.array([0.015, 0.020, 0.030, 0.040])
    adv = np.array([5e9, 2e8, 2e7, 5e6])
    px = np.array([200.0, 100.0, 60.0, 40.0])
    bps = modelled_spread(vol, adv, px) * 1e4
    for got, want in zip(bps, [1.5, 4.5, 15.0, 40.0]):
        assert got == pytest.approx(want, rel=0.25)


def test_modelled_spread_respects_the_one_cent_tick_floor():
    """A $6 stock cannot trade inside one tick however liquid it is."""
    s = modelled_spread(np.array([0.010]), np.array([5e9]), np.array([6.0]))[0]
    assert s == pytest.approx(0.01 / 6.0, rel=1e-9)


def test_modelled_spread_widens_with_vol_and_narrows_with_volume():
    base = modelled_spread(np.array([0.02]), np.array([1e8]), np.array([100.0]))[0]
    assert modelled_spread(np.array([0.04]), np.array([1e8]), np.array([100.0]))[0] > base
    assert modelled_spread(np.array([0.02]), np.array([1e9]), np.array([100.0]))[0] < base


def test_spread_scalar_is_linear():
    a = modelled_spread(np.array([0.02]), np.array([1e8]), np.array([100.0]), scalar=1.0)[0]
    b = modelled_spread(np.array([0.02]), np.array([1e8]), np.array([100.0]), scalar=3.0)[0]
    assert b == pytest.approx(3.0 * a, rel=1e-9)


def test_corwin_schultz_nans_rather_than_zeroes_on_failure():
    """A failed estimate must not become an assertion of free trading."""
    flat = pd.Series(np.full(50, 100.0))
    s = corwin_schultz_spread(flat * 1.001, flat)
    assert (s.dropna() > 0).all()
    assert not (s.fillna(0.0) < 0).any()


def test_auction_pays_no_spread_but_continuous_does():
    cfg = CostConfig()
    sp = np.full(5, 0.002)
    assert spread_cost(sp, cfg, auction=True).sum() == 0.0
    assert spread_cost(sp, cfg, auction=False).sum() > 0.0


def test_impact_is_square_root_in_participation():
    cfg = CostConfig()
    adv = np.array([1e9]); vol = np.array([0.02])
    small = impact_cost(np.array([1e6]), adv, vol, cfg, auction=False)[0]
    big = impact_cost(np.array([4e6]), adv, vol, cfg, auction=False)[0]
    assert big / small == pytest.approx(2.0, rel=1e-6)


def test_auction_impact_exceeds_continuous_at_equal_notional():
    """The close is deep in absolute terms but an order is a far bigger share
    of it, so the same notional moves it more."""
    cfg = CostConfig()
    adv = np.array([1e9]); vol = np.array([0.02]); q = np.array([5e6])
    assert impact_cost(q, adv, vol, cfg, auction=True)[0] > impact_cost(q, adv, vol, cfg, auction=False)[0]


def test_round_trip_bps_rises_with_size_and_volatility():
    cfg = CostConfig()
    base = round_trip_bps(0.001, 0.01, 0.02, cfg, auction=False)
    assert round_trip_bps(0.001, 0.04, 0.02, cfg, auction=False) > base
    assert round_trip_bps(0.001, 0.01, 0.06, cfg, auction=False) > base


def test_financing_signs():
    dates = pd.bdate_range("2023-01-01", periods=10)
    fin = FinancingModel(cfg=CostConfig(), overnight_rate=pd.Series(0.05, index=dates))
    d = dates[5]
    assert fin.daily_charge(d, 100.0, 100.0, 0.0) == pytest.approx(0.0)      # unlevered long
    assert fin.daily_charge(d, 100.0, 200.0, 0.0) > 0.0                      # levered long
    assert fin.daily_charge(d, 100.0, 0.0, 100.0) != 0.0                     # short: borrow vs rebate


def test_financing_charges_more_for_hard_to_borrow():
    dates = pd.bdate_range("2023-01-01", periods=10)
    fin = FinancingModel(cfg=CostConfig(), overnight_rate=pd.Series(0.05, index=dates))
    d = dates[5]
    easy = fin.daily_charge(d, 100.0, 100.0, 100.0, htb_short_notional=0.0)
    hard = fin.daily_charge(d, 100.0, 100.0, 100.0, htb_short_notional=100.0)
    assert hard > easy


def test_zero_rates_still_charge_borrow():
    """The 2016-2021 zero-rate regime does not make shorting free."""
    dates = pd.bdate_range("2019-01-01", periods=10)
    fin = FinancingModel(cfg=CostConfig(), overnight_rate=pd.Series(0.0, index=dates))
    assert fin.daily_charge(dates[5], 100.0, 0.0, 100.0) > 0.0


def _series(mu, sd, n=1500, seed=1):
    r = np.random.default_rng(seed).normal(mu, sd, n)
    return pd.Series(r, index=pd.bdate_range("2018-01-01", periods=n))


def test_evaluate_recovers_the_sample_sharpe_exactly():
    """Checked against the sample moments, not the population ones: with
    6000 observations the sampling error on an annualised Sharpe is about
    0.20, so a population-based assertion would be a coin flip."""
    r = _series(0.0004, 0.008, n=6000)
    p = evaluate(r)
    expected = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert p.sharpe == pytest.approx(expected, rel=1e-12)
    assert p.sharpe == pytest.approx(0.0004 / 0.008 * np.sqrt(252), abs=0.45)


def test_evaluate_beta_and_alpha_against_a_constructed_benchmark():
    b = _series(0.0003, 0.010, n=3000, seed=5)
    noise = _series(0.0, 0.004, n=3000, seed=6)
    r = 0.0002 + 0.6 * b + noise
    p = evaluate(r, benchmark=b)
    assert p.beta == pytest.approx(0.6, abs=0.05)
    assert p.alpha_annual == pytest.approx(0.0002 * 252, abs=0.02)
    assert p.alpha_t > 2.0


def test_drawdown_and_time_under_water():
    eq = pd.Series([1.0, 1.1, 0.9, 0.95, 1.2], index=pd.bdate_range("2020-01-01", periods=5))
    p = evaluate(eq.pct_change().dropna())
    assert p.max_drawdown == pytest.approx(0.9 / 1.1 - 1.0, rel=1e-9)
    assert 0.0 < p.time_under_water <= 1.0


def test_newey_west_t_shrinks_under_positive_autocorrelation():
    n = 3000
    e = np.random.default_rng(2).normal(0, 1, n)
    ar = np.zeros(n)
    for i in range(1, n):
        ar[i] = 0.6 * ar[i - 1] + e[i]
    s = pd.Series(ar + 0.15)
    assert newey_west_t(s, lags=10) < abs(s.mean() / s.std(ddof=1) * np.sqrt(n))


def test_probabilistic_sharpe_bounds():
    v = probabilistic_sharpe(0.05, 1000, 0.0, 3.0, 0.0)
    assert 0.0 <= v <= 1.0
    assert probabilistic_sharpe(0.10, 1000, 0.0, 3.0) > probabilistic_sharpe(0.02, 1000, 0.0, 3.0)


def test_deflated_sharpe_falls_as_trials_rise():
    r = _series(0.0005, 0.008, n=2500)
    p = evaluate(r)
    a, _ = deflated_sharpe(p.sharpe, r, n_trials=2)
    b, _ = deflated_sharpe(p.sharpe, r, n_trials=200)
    c, _ = deflated_sharpe(p.sharpe, r, n_trials=20000)
    assert a >= b >= c


def test_bootstrap_distribution_brackets_the_realised_sample():
    r = _series(0.0004, 0.008, n=1200)
    d = stationary_bootstrap(r, n_paths=400, mean_block=10)
    realised = evaluate(r).sharpe
    lo, hi = d["sharpe"].quantile([0.02, 0.98])
    assert lo < realised < hi
    assert (d["max_drawdown"] <= 0).all()
