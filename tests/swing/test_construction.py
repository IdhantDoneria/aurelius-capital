"""The risk overlay is what makes the three strategies comparable, so its
invariants are tested rather than assumed."""
from __future__ import annotations

import numpy as np
import pytest

from mentisrex.swing.construction import (
    OverlayConfig, cross_sectional_z, neutralize, rank_normal, size_book, winsorize,
)

rng = np.random.default_rng(0)


def _inputs(n=200):
    score = rng.normal(size=n)
    beta = rng.normal(1.0, 0.3, size=n)
    tradable = np.ones(n, dtype=bool)
    return score, beta, tradable


def test_gross_cap_binds():
    score, beta, tradable = _inputs()
    cfg = OverlayConfig(target_vol=0.50, vol_floor=0.01, gross_cap=1.5, max_weight=0.05)
    w = size_book(score, beta=beta, factor_loadings=None, realised_vol=0.02,
                  drawdown=0.0, cfg=cfg, tradable=tradable)
    assert np.abs(w).sum() <= cfg.gross_cap + 1e-9


def test_per_name_cap_is_a_limit_on_equity_not_on_gross():
    """A single dominant score must not be able to take the whole book.

    The cap is stated as a fraction of equity, so it has to survive volatility
    targeting -- capping a unit-gross vector and renormalising afterwards
    silently removes the cap entirely.
    """
    n = 50
    score = np.zeros(n)
    score[0] = 100.0
    cfg = OverlayConfig(target_vol=0.10, gross_cap=2.0, max_weight=0.02,
                        beta_neutral=False, dollar_neutral=False)
    w = size_book(score, beta=np.ones(n), factor_loadings=None, realised_vol=0.10,
                  drawdown=0.0, cfg=cfg, tradable=np.ones(n, bool))
    assert np.abs(w).max() <= cfg.max_weight + 1e-12


def test_per_name_cap_holds_for_a_diffuse_book():
    score, beta, tradable = _inputs(400)
    cfg = OverlayConfig(target_vol=0.30, vol_floor=0.01, gross_cap=3.0, max_weight=0.01)
    w = size_book(score, beta=beta, factor_loadings=None, realised_vol=0.05,
                  drawdown=0.0, cfg=cfg, tradable=tradable)
    assert np.abs(w).max() <= cfg.max_weight + 1e-12
    assert np.abs(w).sum() <= cfg.gross_cap + 1e-9


def test_dollar_and_beta_neutral():
    score, beta, tradable = _inputs()
    cfg = OverlayConfig(beta_neutral=True, dollar_neutral=True, max_weight=1.0)
    w = size_book(score, beta=beta, factor_loadings=None, realised_vol=0.10,
                  drawdown=0.0, cfg=cfg, tradable=tradable)
    gross = np.abs(w).sum()
    assert abs(w.sum()) / gross < 1e-8
    assert abs((w * beta).sum()) / gross < 1e-8


def test_factor_neutral():
    n = 300
    score = rng.normal(size=n)
    loadings = rng.normal(size=(n, 3))
    cfg = OverlayConfig(beta_neutral=True, dollar_neutral=True, n_stat_factors=3, max_weight=1.0)
    w = size_book(score, beta=rng.normal(1, 0.2, n), factor_loadings=loadings,
                  realised_vol=0.10, drawdown=0.0, cfg=cfg, tradable=np.ones(n, bool))
    gross = np.abs(w).sum()
    for k in range(3):
        assert abs((w * loadings[:, k]).sum()) / gross < 1e-7


def test_untradable_names_get_no_weight():
    score, beta, tradable = _inputs()
    tradable[:50] = False
    cfg = OverlayConfig(max_weight=1.0)
    w = size_book(score, beta=beta, factor_loadings=None, realised_vol=0.10,
                  drawdown=0.0, cfg=cfg, tradable=tradable)
    assert np.all(w[:50] == 0.0)


def test_drawdown_brake_reduces_size_monotonically():
    score, beta, tradable = _inputs()
    cfg = OverlayConfig(dd_brake_start=0.05, dd_brake_full=0.20, dd_brake_floor=0.25,
                        max_weight=1.0, gross_cap=99.0)
    sizes = [
        np.abs(size_book(score, beta=beta, factor_loadings=None, realised_vol=0.10,
                         drawdown=dd, cfg=cfg, tradable=tradable)).sum()
        for dd in (0.0, -0.05, -0.10, -0.15, -0.20, -0.30)
    ]
    assert all(a >= b - 1e-12 for a, b in zip(sizes, sizes[1:]))
    assert sizes[-1] == pytest.approx(sizes[0] * 0.25, rel=1e-6)


def test_vol_target_scales_inversely_with_realised_vol():
    score, beta, tradable = _inputs()
    cfg = OverlayConfig(target_vol=0.10, max_leverage_scalar=99.0, gross_cap=99.0, max_weight=1.0)
    lo = np.abs(size_book(score, beta=beta, factor_loadings=None, realised_vol=0.05,
                          drawdown=0.0, cfg=cfg, tradable=tradable)).sum()
    hi = np.abs(size_book(score, beta=beta, factor_loadings=None, realised_vol=0.20,
                          drawdown=0.0, cfg=cfg, tradable=tradable)).sum()
    assert lo == pytest.approx(4.0 * hi, rel=1e-6)


def test_leverage_scalar_is_capped():
    score, beta, tradable = _inputs()
    cfg = OverlayConfig(target_vol=0.10, vol_floor=0.001, max_leverage_scalar=3.0,
                        gross_cap=99.0, max_weight=1.0)
    w = size_book(score, beta=beta, factor_loadings=None, realised_vol=1e-6,
                  drawdown=0.0, cfg=cfg, tradable=tradable)
    assert np.abs(w).sum() == pytest.approx(3.0, rel=1e-9)


def test_winsorize_clips_outliers_only():
    x = np.concatenate([rng.normal(size=500), np.array([50.0, -50.0])])
    w = winsorize(x, z=3.0)
    assert w.max() < 10 and w.min() > -10
    assert np.allclose(np.sort(w)[10:-10], np.sort(x)[10:-10])


def test_rank_normal_is_monotone_and_centred():
    x = rng.normal(size=400)
    r = rank_normal(x)
    assert np.all(np.diff(r[np.argsort(x)]) >= -1e-12)
    assert abs(r.mean()) < 0.05


def test_rank_normal_ignores_nan():
    x = rng.normal(size=100)
    x[:20] = np.nan
    r = rank_normal(x)
    assert np.all(r[:20] == 0.0)


def test_cross_sectional_z_unit_variance():
    x = rng.normal(5.0, 3.0, size=500)
    z = cross_sectional_z(x)
    assert abs(z.mean()) < 1e-10
    assert z.std(ddof=1) == pytest.approx(1.0, rel=1e-9)


def test_neutralize_removes_projection():
    n = 200
    load = np.column_stack([np.ones(n), rng.normal(size=n)])
    w = 3.0 * load[:, 1] + rng.normal(size=n)
    r = neutralize(w, load)
    assert abs((r * load[:, 1]).sum()) < 1e-8
    assert abs(r.sum()) < 1e-8


def test_participation_cap_binds_on_a_thin_name():
    """The weight cap cannot substitute for a participation cap: impact
    depends on size relative to the *name's* volume, not to the fund."""
    n = 100
    adv = np.full(n, 1e8)
    adv[0] = 1e6                                   # one thin name
    cfg = OverlayConfig(target_vol=0.10, gross_cap=2.0, max_weight=0.05,
                        max_participation=0.001, beta_neutral=False, dollar_neutral=False)
    score = rng.normal(size=n)
    score[0] = 10.0                                # and the signal loves it
    w = size_book(score, beta=np.ones(n), factor_loadings=None, realised_vol=0.10,
                  drawdown=0.0, cfg=cfg, tradable=np.ones(n, bool),
                  adv_dollar=adv, equity=1e8)
    assert abs(w[0]) <= 0.001 * 1e6 / 1e8 + 1e-12
    assert abs(w[0]) < cfg.max_weight


def test_participation_cap_disabled_by_zero():
    n = 50
    cfg_off = OverlayConfig(max_participation=0.0, max_weight=0.05)
    cfg_on = OverlayConfig(max_participation=1e-9, max_weight=0.05)
    score = rng.normal(size=n)
    kw = dict(beta=np.ones(n), factor_loadings=None, realised_vol=0.10, drawdown=0.0,
              tradable=np.ones(n, bool), adv_dollar=np.full(n, 1e8), equity=1e8)
    off = np.abs(size_book(score, cfg=cfg_off, **kw)).sum()
    on = np.abs(size_book(score, cfg=cfg_on, **kw)).sum()
    assert off > 0.5
    assert on < 1e-6 * off
