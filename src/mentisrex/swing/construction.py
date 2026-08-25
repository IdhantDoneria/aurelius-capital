"""Portfolio construction and risk overlay, shared by all three strategies.

Keeping construction out of the alpha modules is what makes the three
strategies comparable: each one emits a raw cross-sectional score, and the
same overlay turns scores into weights. Any performance difference between
them is then a difference in signal, not a difference in how aggressively
each was sized.

Order of operations matters and is fixed here:
    score -> winsorise -> neutralise (market beta, then statistical factors)
          -> scale to unit gross -> per-name cap -> vol target -> gross cap
          -> drawdown brake
Vol targeting sits *after* neutralisation because neutralising changes the
portfolio's volatility, and *before* the gross cap so that the cap binds on
the sized book rather than on an unsized one.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def winsorize(x: np.ndarray, z: float = 3.0) -> np.ndarray:
    """Clip to +/- z robust standard deviations (MAD-scaled)."""
    v = x[np.isfinite(x)]
    if v.size < 10:
        return np.nan_to_num(x)
    med = np.median(v)
    mad = np.median(np.abs(v - med)) * 1.4826
    if mad <= 0:
        return np.nan_to_num(x)
    return np.clip(np.nan_to_num(x, nan=med), med - z * mad, med + z * mad)


def cross_sectional_z(x: np.ndarray) -> np.ndarray:
    """Demeaned, unit-variance cross-section. NaNs become zero exposure."""
    m = np.isfinite(x)
    out = np.zeros_like(x, dtype=float)
    if m.sum() < 10:
        return out
    v = x[m]
    sd = v.std(ddof=1)
    if sd <= 0:
        return out
    out[m] = (v - v.mean()) / sd
    return out


def rank_normal(x: np.ndarray) -> np.ndarray:
    """Map a cross-section to approximately standard-normal scores by rank.

    Used in preference to raw z-scores where the underlying feature has fat
    tails (most volume and gap measures do), because a single outlier
    otherwise takes over the whole book.
    """
    m = np.isfinite(x)
    out = np.zeros_like(x, dtype=float)
    n = int(m.sum())
    if n < 10:
        return out
    order = np.argsort(np.argsort(x[m]))
    u = (order + 0.5) / n
    # inverse normal via the logistic approximation, adequate and monotone
    out[m] = np.sqrt(2.0) * _erfinv(2.0 * u - 1.0)
    return out


def _erfinv(y: np.ndarray) -> np.ndarray:
    a = 0.147
    ln1 = np.log(np.clip(1.0 - y * y, 1e-16, None))
    t1 = 2.0 / (np.pi * a) + ln1 / 2.0
    return np.sign(y) * np.sqrt(np.sqrt(t1 * t1 - ln1 / a) - t1)


def select_tails(score: np.ndarray, pct: float) -> np.ndarray:
    """Keep only the extremes of a cross-section, blanking the middle.

    `pct` is the *total* fraction retained, split evenly between the two
    tails: 0.2 keeps the top and bottom decile. Concentrating raises the
    average edge per name but also raises impact, because the same capital is
    spread over fewer names -- which of those wins is an empirical question
    and the reason this is a parameter.
    """
    if pct >= 1.0:
        return score
    m = np.isfinite(score) & (score != 0)
    n = int(m.sum())
    if n < 20:
        return score
    half = max(pct / 2.0, 1.0 / n)
    lo, hi = np.quantile(score[m], [half, 1.0 - half])
    keep = m & ((score <= lo) | (score >= hi))
    return np.where(keep, score, np.nan)


def neutralize(w: np.ndarray, loadings: np.ndarray) -> np.ndarray:
    """Residualise weights against a set of exposures.

    `loadings` is (N, K). Returns w minus its least-squares projection onto
    the loading columns, so the book carries no net exposure to any of them.
    An intercept column should be included by the caller if dollar
    neutrality is wanted.
    """
    m = np.isfinite(w) & np.all(np.isfinite(loadings), axis=1)
    out = np.zeros_like(w)
    if m.sum() < loadings.shape[1] + 5:
        return np.nan_to_num(w)
    X = loadings[m]
    y = w[m]
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    out[m] = y - X @ coef
    return out


@dataclass
class OverlayConfig:
    target_vol: float = 0.10
    """Annualised portfolio volatility target."""

    vol_lookback: int = 60
    vol_floor: float = 0.02
    max_leverage_scalar: float = 4.0
    """Cap on the vol-targeting multiplier, so a quiet patch cannot lever the
    book without limit into the next volatility shock."""

    gross_cap: float = 2.0
    max_weight: float = 0.02
    """Per-name cap as a fraction of equity."""

    beta_neutral: bool = True
    dollar_neutral: bool = True
    n_stat_factors: int = 0
    """Principal components of the return panel to neutralise against. Used
    as a sector proxy: no sector classification is available in this data
    set, and the leading components of a daily equity return matrix are
    dominated by sector structure."""

    max_participation: float = 0.0
    """Per-name cap as a fraction of the name's trailing daily dollar volume.
    Zero disables it.

    This is the control that actually governs impact, and it is the one a
    weight cap cannot substitute for: impact depends on order size relative
    to the *name's* volume, not relative to the fund. Concentrating a book
    into fewer names raises the edge per name and the impact per name
    together, and only a participation cap lets the first happen without the
    second -- at the price of a smaller book."""

    dd_brake_start: float = 0.08
    dd_brake_full: float = 0.20
    """Linear de-risking between these two drawdown levels; at `dd_brake_full`
    the book is at `dd_brake_floor` of target size."""
    dd_brake_floor: float = 0.25


def size_book(
    score: np.ndarray,
    *,
    beta: np.ndarray,
    factor_loadings: np.ndarray | None,
    realised_vol: float,
    drawdown: float,
    cfg: OverlayConfig,
    tradable: np.ndarray,
    adv_dollar: np.ndarray | None = None,
    equity: float | None = None,
) -> np.ndarray:
    """Turn a raw cross-sectional score into target weights.

    `realised_vol` is the trailing annualised volatility of the *unit-gross*
    version of this same book, so the vol target is applied to the strategy's
    own risk rather than to a generic estimate.
    """
    s = np.where(tradable, score, np.nan)
    s = winsorize(s, 3.0)
    s = np.where(np.isfinite(s) & tradable, s, 0.0)

    cols = []
    if cfg.dollar_neutral:
        cols.append(np.ones_like(s))
    if cfg.beta_neutral:
        cols.append(np.nan_to_num(beta, nan=1.0))
    if factor_loadings is not None and cfg.n_stat_factors > 0:
        cols.extend(factor_loadings[:, : cfg.n_stat_factors].T)
    if cols:
        s = neutralize(s, np.column_stack(cols))
    s = np.where(tradable, s, 0.0)


    gross = np.abs(s).sum()
    if gross <= 0:
        return np.zeros_like(s)
    w = s / gross                                       # unit gross

    vol = max(realised_vol, cfg.vol_floor)
    scalar = min(cfg.target_vol / vol, cfg.max_leverage_scalar)

    if drawdown < -cfg.dd_brake_start:
        span = cfg.dd_brake_full - cfg.dd_brake_start
        frac = min(max((-drawdown - cfg.dd_brake_start) / max(span, 1e-9), 0.0), 1.0)
        scalar *= 1.0 - (1.0 - cfg.dd_brake_floor) * frac

    target_gross = min(scalar, cfg.gross_cap)
    w = w * target_gross

    # The per-name cap is a limit on equity, so it has to be applied to the
    # sized book, not to a unit-gross one -- capping first and renormalising
    # afterwards simply undoes the cap. Capping does perturb neutrality, so
    # the two are alternated a few times; the final clip is what guarantees
    # the cap holds, and any residual net exposure after it is reported by
    # the backtester rather than assumed to be zero.
    cap = np.full_like(w, cfg.max_weight)
    if cfg.max_participation > 0.0 and adv_dollar is not None and equity:
        part_cap = cfg.max_participation * np.nan_to_num(adv_dollar, nan=0.0) / max(equity, 1.0)
        cap = np.minimum(cap, np.where(np.isfinite(part_cap), part_cap, 0.0))

    exposures = np.column_stack(cols) if cols else None
    for _ in range(3):
        w = np.clip(w, -cap, cap)
        if exposures is not None:
            w = np.where(tradable, neutralize(w, exposures), 0.0)
        g = np.abs(w).sum()
        if g <= 0:
            return np.zeros_like(s)
        w = w * (target_gross / g)
    return np.clip(w, -cap, cap)
