"""Vectorised research backtest for the India momentum-quality programme.

This is a RESEARCH harness, not a live trading system -- it takes an
already-assembled price/volume panel and produces a daily return series. It
has no broker connection, no state persistence across runs, and no live
risk-gate enforcement (see the package docstring and the handbook's
"Engineering maturity" section for what that would still take to build).

All data (the NSE price panel, real fundamentals, sector map, benchmark
series) is passed in by the caller rather than loaded internally, so this
module has no hard dependency on any particular local file layout and can
be exercised with small synthetic panels in tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mentisrex.programme_india.config import IndiaConfig
from mentisrex.programme_india.costs import (
    exposure_change_cost,
    leverage_carry_drag,
    operational_error_drag,
    rebalance_cost,
    turnover,
)
from mentisrex.programme_india.overlay import exposure_overlay
from mentisrex.programme_india.signals import (
    composite_score,
    inverse_vol_weights,
    momentum_score,
    select_with_sector_cap,
    zscore,
)


@dataclass
class QualityLookup:
    """Point-in-time quality scores. `get(as_of)` must return a Series of
    quality z-scores indexed by symbol, using only fundamentals published
    on or before `as_of` -- point-in-time correctness is this class's
    contract, not the caller's."""
    frame: pd.DataFrame  # columns: symbol, available_from, quality_score

    def get(self, as_of: pd.Timestamp) -> pd.Series:
        avail = self.frame[self.frame["available_from"] <= as_of]
        if avail.empty:
            return pd.Series(dtype=float)
        latest = avail.sort_values("available_from").groupby("symbol").tail(1)
        return latest.set_index("symbol")["quality_score"]


def monthly_rebalance_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(index, index=index)
    return sorted(s.groupby([index.year, index.month]).max().values)


def run_stock_sleeve(
    close: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    rebal_dates: list[pd.Timestamp],
    sector_map: dict[str, str],
    quality: QualityLookup | None,
    cfg: IndiaConfig,
) -> tuple[pd.Series, float]:
    """Returns (daily_return_series, average_names_held)."""
    all_days = close.index
    daily_ret = close.pct_change()
    ret_out = pd.Series(0.0, index=all_days)
    prev_weights = pd.Series(dtype=float)
    holdings_by_period: list[tuple] = []
    n_names_log: list[int] = []

    for i, rd in enumerate(rebal_dates):
        loc = all_days.get_loc(rd)
        if loc < cfg.momentum_lookback_days + 5:
            continue
        hist_close = close.iloc[: loc + 1]
        hist_dv = dollar_volume.iloc[max(0, loc - 70): loc + 1]
        avg_dv = hist_dv.mean()
        n_hist = hist_close.notna().sum()
        eligible = avg_dv[n_hist >= cfg.min_history_days].sort_values(ascending=False)
        liquid_universe = eligible.index[: cfg.top_n_liquid]
        if len(liquid_universe) < 20:
            continue

        sub_close = hist_close[liquid_universe]
        mom_z = momentum_score(sub_close, cfg)
        if mom_z.empty:
            continue
        q = quality.get(rd).reindex(liquid_universe) if quality is not None else None
        composite = composite_score(mom_z, q, cfg).dropna()
        if len(composite) < 20:
            continue

        n_pick = max(8, int(len(composite) * cfg.quintile))
        ranked = list(composite.sort_values(ascending=False).index)
        picks = select_with_sector_cap(ranked[: max(n_pick * 3, n_pick)], sector_map, cfg, n_pick)

        n_names_log.append(len(picks))
        returns_63d = sub_close[picks].pct_change().iloc[-63:]
        w = inverse_vol_weights(returns_63d, picks, cfg)

        to = turnover(w, prev_weights)
        period_end = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else all_days[-1]
        holdings_by_period.append((rd, period_end, w, to))
        prev_weights = w

    for rd, period_end, weights, to in holdings_by_period:
        start_loc = all_days.get_loc(rd) + 1
        end_loc = all_days.get_loc(period_end)
        if start_loc > end_loc:
            continue
        window = all_days[start_loc: end_loc + 1]
        sub_ret = daily_ret.reindex(columns=weights.index).loc[window]
        port_ret = (sub_ret * weights.values).sum(axis=1, min_count=1).fillna(0.0)
        cost = rebalance_cost(to, cfg)
        if len(port_ret) > 0:
            port_ret.iloc[0] -= cost
        ret_out.loc[window] = port_ret.values

    avg_names = float(np.mean(n_names_log)) if n_names_log else 0.0
    return ret_out, avg_names


def run_backtest(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    bench_close: pd.Series,
    rf_daily: pd.Series,
    sector_map: dict[str, str],
    quality: QualityLookup | None,
    cfg: IndiaConfig,
) -> tuple[pd.Series, pd.Series, float]:
    """Full pipeline: stock sleeve + exposure overlay + costs -> one daily
    net return series, on `close`'s full date index. Returns
    (strategy_returns, exposure, average_names_held)."""
    dollar_volume = close * volume
    rebal_dates = monthly_rebalance_dates(close.index)

    stock_ret, avg_names = run_stock_sleeve(close, dollar_volume, rebal_dates, sector_map, quality, cfg)

    exposure = exposure_overlay(bench_close, close, close.index, cfg)
    exposure = exposure.reindex(close.index).ffill().fillna(0.0)

    exp_cost = exposure_change_cost(exposure, cfg)
    lev_drag = leverage_carry_drag(exposure, cfg)
    op_drag = operational_error_drag(cfg)

    strategy_ret = (exposure * stock_ret + (1 - exposure).clip(lower=0.0) * rf_daily
                     - exp_cost - lev_drag - op_drag)
    return strategy_ret, exposure, avg_names
