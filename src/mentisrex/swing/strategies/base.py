"""Shared plumbing for the cross-sectional strategies.

A subclass supplies only `raw_score`; sizing, neutralisation and turnover
staging live here so that all three books are constructed identically and
any performance difference is attributable to signal rather than to sizing.

Volatility targeting is done in two passes rather than with a feedback
controller. Pass one runs the book at fixed unit gross and records its daily
return; pass two feeds a *trailing* estimate of that unit-gross volatility
back in as the sizing denominator. The estimate at date t uses only returns
up to t-1, so it is causal, and unlike a controller it cannot oscillate.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..construction import OverlayConfig, size_book


@dataclass
class FeatureCube:
    """Wide arrays keyed by feature name, all shaped (T, N)."""

    dates: pd.DatetimeIndex
    symbols: np.ndarray
    data: dict[str, np.ndarray]

    def __getitem__(self, k: str) -> np.ndarray:
        return self.data[k]

    def row(self, k: str, t: int) -> np.ndarray:
        return self.data[k][t]


@dataclass
class StagingConfig:
    hold_days: int = 5
    """Target holding period. The live book is the equal-weighted average of
    the last `hold_days` daily target vectors, so roughly 1/hold_days of the
    book turns each session instead of all of it on one day."""

    stage: bool = True


class CrossSectionalStrategy:
    name = "base"
    trade_at = "moc"

    def __init__(
        self,
        cube: FeatureCube,
        overlay: OverlayConfig,
        staging: StagingConfig,
        *,
        beta: np.ndarray,
        factor_loadings: np.ndarray | None = None,
        tradable: np.ndarray | None = None,
        trade_at: str | None = None,
        warmup_days: int = 260,
        unit_vol: np.ndarray | None = None,
    ) -> None:
        self.cube = cube
        self.overlay = overlay
        self.staging = staging
        self.beta = beta
        self.factor_loadings = factor_loadings
        self.T, self.N = cube.data[next(iter(cube.data))].shape
        self.tradable = tradable if tradable is not None else np.ones((self.T, self.N), bool)
        if trade_at is not None:
            self.trade_at = trade_at
        self._warmup = warmup_days
        self._queue: list[np.ndarray] = []
        self._drawdown = 0.0
        self.unit_vol = unit_vol
        self.unit_weights: list[np.ndarray] = []

    # -- interface -----------------------------------------------------------
    def warmup(self) -> int:
        return self._warmup

    def raw_score(self, t: int) -> np.ndarray:
        raise NotImplementedError

    def observe(self, drawdown: float) -> None:
        self._drawdown = drawdown

    def reset(self) -> None:
        self._queue = []
        self._drawdown = 0.0
        self.unit_weights = []

    # -- construction --------------------------------------------------------
    def _overlay_for(self, t: int) -> OverlayConfig:
        return self.overlay

    def _target(self, t: int) -> np.ndarray:
        cfg = self._overlay_for(t)
        vol = cfg.target_vol if self.unit_vol is None else float(self.unit_vol[t])
        w = size_book(
            self.raw_score(t),
            beta=self.beta[t],
            factor_loadings=None if self.factor_loadings is None else self.factor_loadings[t],
            realised_vol=vol,
            drawdown=self._drawdown,
            cfg=cfg,
            tradable=self.tradable[t],
        )
        if self.staging.stage and self.staging.hold_days > 1:
            self._queue.append(w)
            if len(self._queue) > self.staging.hold_days:
                self._queue.pop(0)
            w = np.mean(np.stack(self._queue), axis=0)
        w = np.where(self.tradable[t], w, 0.0)
        self.unit_weights.append(w)
        return w

    def targets_moc(self, t: int) -> np.ndarray | None:
        return self._target(t) if self.trade_at == "moc" else None

    def targets_moo(self, t: int) -> np.ndarray | None:
        return self._target(t) if self.trade_at == "moo" else None


def unit_gross_vol_series(
    strategy: CrossSectionalStrategy,
    ret_matrix: np.ndarray,
    *,
    lookback: int = 60,
    floor: float = 0.02,
) -> np.ndarray:
    """Causal trailing volatility of the strategy run at fixed unit gross.

    `ret_matrix[t]` must be the segment return the book actually earns
    between the day it is set and the day it is marked, already lagged, so
    that entry t of the product is a realised, not a contemporaneous, return.
    """
    saved_overlay = strategy.overlay
    strategy.overlay = OverlayConfig(
        target_vol=1.0,
        vol_lookback=saved_overlay.vol_lookback,
        vol_floor=1.0,
        max_leverage_scalar=1.0,
        gross_cap=1.0,
        max_weight=saved_overlay.max_weight,
        beta_neutral=saved_overlay.beta_neutral,
        dollar_neutral=saved_overlay.dollar_neutral,
        n_stat_factors=saved_overlay.n_stat_factors,
        dd_brake_start=1.0,
        dd_brake_full=2.0,
        dd_brake_floor=1.0,
    )
    strategy.unit_vol = None
    strategy.reset()

    T = strategy.T
    rets = np.zeros(T)
    for t in range(strategy.warmup(), T):
        w = strategy._target(t)
        rets[t] = float(np.nansum(w * ret_matrix[t]))

    s = pd.Series(rets)
    vol = (
        s.rolling(lookback, min_periods=20).std(ddof=1).shift(1) * np.sqrt(252)
    ).bfill().fillna(floor)
    strategy.overlay = saved_overlay
    strategy.reset()
    return np.maximum(vol.to_numpy(), floor)
