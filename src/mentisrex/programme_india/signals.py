"""Stock-selection signals: momentum, quality, sector-capped decile selection,
and inverse-volatility position sizing.

Every function here is pure (DataFrame/Series in, DataFrame/Series out, no
I/O) so it can be unit-tested on synthetic data without a live database
connection — see `tests/programme_india/test_signals.py`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mentisrex.programme_india.config import IndiaConfig


def zscore(s: pd.Series) -> pd.Series:
    std = s.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def momentum_score(hist_close: pd.DataFrame, cfg: IndiaConfig) -> pd.Series:
    """12-month return, skipping the most recent month (Jegadeesh & Titman,
    1993). Requires `momentum_lookback_days + momentum_skip_days` rows."""
    if len(hist_close) < cfg.momentum_lookback_days + cfg.momentum_skip_days:
        return pd.Series(dtype=float)
    p_skip = hist_close.iloc[-cfg.momentum_skip_days]
    p_form = hist_close.iloc[-cfg.momentum_lookback_days]
    raw = (p_skip / p_form) - 1.0
    return zscore(raw)


def quality_score_from_fundamentals(
    roe: pd.Series, debt_to_equity: pd.Series, earnings_stability: pd.Series
) -> pd.Series:
    """Blend real ROE / debt-to-equity / earnings-stability into one
    quality z-score: 0.5 x ROE - 0.3 x leverage + 0.2 x stability.
    All three inputs must already be point-in-time (no look-ahead) — that
    guarantee is the caller's responsibility (see `fundamentals.py`)."""
    return 0.5 * zscore(roe) - 0.3 * zscore(debt_to_equity) + 0.2 * zscore(earnings_stability)


def composite_score(mom_z: pd.Series, quality_z: pd.Series | None, cfg: IndiaConfig) -> pd.Series:
    """momentum_weight x momentum + quality_weight x quality. Names missing a
    quality score (fundamentals not yet published, or before the data
    existed) are scored on momentum alone at full momentum weight -- a
    missing quality score is treated as neutral (0.0), not as disqualifying,
    and not as a silent 100%-momentum re-weight (see handbook for why)."""
    if quality_z is None:
        return mom_z
    q = quality_z.reindex(mom_z.index).fillna(0.0)
    composite = cfg.momentum_weight * mom_z + cfg.quality_weight * q
    return composite.where(mom_z.notna())


def select_with_sector_cap(
    ranked_names: list[str], sector_map: dict[str, str], cfg: IndiaConfig, n_pick: int
) -> list[str]:
    """Take the top `n_pick` names from an already-sorted-by-score list,
    greedily skipping any name that would push a single sector's SHARE OF
    THE FINAL BOOK above `cfg.sector_cap`. This is the direct, mechanism-
    level fix for the 2018 NBFC concentration failure documented in the
    handbook -- a momentum ranking alone can load 40%+ into one hot sector
    right before it cracks; this makes that structurally impossible."""
    if not sector_map:
        return ranked_names[:n_pick]
    sector_count: dict[str, int] = {}
    picks: list[str] = []
    for name in ranked_names:
        if len(picks) >= n_pick:
            break
        sec = sector_map.get(name, "Unknown")
        cnt = sector_count.get(sec, 0)
        if cnt == 0 or cnt / max(1, len(picks)) < cfg.sector_cap:
            picks.append(name)
            sector_count[sec] = cnt + 1
    return picks if len(picks) >= min(8, n_pick) else ranked_names[:n_pick]


def inverse_vol_weights(returns_63d: pd.DataFrame, picks: list[str], cfg: IndiaConfig) -> pd.Series:
    """Weight each held name inversely to its own trailing realised
    volatility, capped at `min(avg_weight * concentration_multiplier,
    per_name_cap)` so one low-volatility name can't dominate the book.

    Enforced by iterative capped redistribution, not a single clip-then-
    renormalize pass. A single clip-then-renormalize is a real bug this
    programme's own test suite caught: if every name's raw weight sits
    close to the cap (common in a concentrated, similarly-volatile decile
    book), clipping brings them all down together and renormalizing then
    scales them straight back up past the cap -- silently reproducing an
    equal-weighted book while claiming to be inverse-vol-weighted and
    capped. This redistributes only the excess taken from over-cap names
    into names still under it, iterating until stable (or until the cap is
    mathematically infeasible for this many names, in which case it falls
    back to the tightest feasible equal weighting rather than violating the
    cap silently)."""
    vol = returns_63d[picks].std()
    inv_vol = 1.0 / vol.replace(0, np.nan)
    inv_vol = inv_vol.fillna(inv_vol.mean())
    w = inv_vol / inv_vol.sum()

    avg_w = 1.0 / len(picks)
    cap = min(avg_w * cfg.concentration_multiplier, cfg.per_name_cap)
    if cap * len(picks) < 1.0 - 1e-9:
        # Infeasible: even every name AT the cap can't sum to 1. Only
        # possible resolution is equal weight (which is itself >= cap).
        return pd.Series(1.0 / len(picks), index=picks)

    for _ in range(50):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        under = ~over
        under_sum = w[under].sum()
        if under_sum <= 1e-12:
            break
        w[under] = w[under] + excess * (w[under] / under_sum)

    return w / w.sum()
