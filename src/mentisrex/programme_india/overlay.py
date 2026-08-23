"""The exposure/timing overlay: how much of the 1.5x leverage cap is
actually deployed on any given day.

The core design decision, found necessary after a real backtest failure
(documented in the handbook): the overlay takes the WORSE of a large-cap
trend signal and a broad-market breadth signal, never their average. An
earlier version averaged them, which let a calm-looking Nifty 50 mask a
real mid-cap-specific breakdown through most of 2018 -- the strategy stayed
72-76% invested for months while the NBFC/IL&FS crisis was already visible
in the breadth signal alone. `gate = min(trend, breadth)` is the fix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mentisrex.programme_india.config import IndiaConfig


def trend_score(bench_close: pd.Series, cfg: IndiaConfig) -> pd.Series:
    """Average of two binary moving-average rules on the benchmark index:
    is price above its fast MA, and above its slow MA. 0 = fully bearish,
    1 = fully bullish, 0.5 = mixed."""
    ma_fast = bench_close.rolling(cfg.trend_ma_fast).mean()
    ma_slow = bench_close.rolling(cfg.trend_ma_slow).mean()
    return ((bench_close > ma_fast).astype(float) + (bench_close > ma_slow).astype(float)) / 2.0


def breadth_score(universe_close: pd.DataFrame, cfg: IndiaConfig) -> pd.Series:
    """Fraction of the ENTIRE investable universe (not just large caps)
    trading above its own moving average -- this is what actually saw the
    2018 mid-cap breakdown coming, and it is why it gets equal say with the
    large-cap trend signal rather than being drowned out by it."""
    ma = universe_close.rolling(cfg.breadth_ma, min_periods=int(cfg.breadth_ma * 0.8)).mean()
    above = universe_close > ma
    valid = universe_close.notna() & ma.notna()
    denom = valid.sum(axis=1).replace(0, np.nan)
    return (above & valid).sum(axis=1) / denom


def vol_scalar(bench_close: pd.Series, cfg: IndiaConfig) -> pd.Series:
    """clip(target_vol / realised_vol, floor, ceiling) -- de-risks when the
    market is choppier than the target, re-risks (up to the ceiling) when
    it's calmer. Never removes the leverage cap; only scales within it."""
    bench_ret = bench_close.pct_change()
    realised = bench_ret.rolling(cfg.realised_vol_window).std() * np.sqrt(252)
    return (cfg.target_vol / realised).clip(cfg.vol_scalar_floor, cfg.vol_scalar_ceiling)


def exposure_overlay(bench_close: pd.Series, universe_close: pd.DataFrame,
                      index: pd.DatetimeIndex, cfg: IndiaConfig) -> pd.Series:
    """The full pipeline: gate x vol_scalar x leverage_cap, clipped to
    [0, leverage_cap], shifted by `signal_lag_days` so nothing trades on
    same-day information."""
    trend = trend_score(bench_close, cfg).reindex(index).ffill().fillna(0.5)
    breadth = breadth_score(universe_close, cfg).reindex(index).ffill().fillna(0.5)
    vscalar = vol_scalar(bench_close, cfg).reindex(index).ffill()

    gate = np.minimum(trend, breadth) if cfg.gate_mode == "min" else 0.5 * trend + 0.5 * breadth
    exposure = (gate * vscalar * cfg.leverage_cap).clip(0.0, cfg.leverage_cap)
    return exposure.shift(cfg.signal_lag_days)
