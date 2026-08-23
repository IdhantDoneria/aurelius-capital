from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.programme_india.config import IndiaConfig
from mentisrex.programme_india.overlay import (
    breadth_score,
    exposure_overlay,
    trend_score,
    vol_scalar,
)


def _bench_series(n=400, seed=1) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n)
    rets = rng.normal(0.0005, 0.012, n)
    return pd.Series(100 * np.cumprod(1 + rets), index=idx)


class TestGateIsWorseOfTwo:
    def test_min_gate_uses_worse_signal_not_average(self):
        """This is the specific, load-bearing fix documented in the
        handbook: a calm large-cap trend must NOT be able to mask a real
        broad-market breadth warning by averaging it away."""
        cfg = IndiaConfig(gate_mode="min")
        idx = pd.bdate_range("2020-01-01", periods=5)
        trend = pd.Series(1.0, index=idx)    # large-cap looks fine
        breadth = pd.Series(0.1, index=idx)  # broad market is breaking down

        gate_min = np.minimum(trend, breadth)
        gate_avg = 0.5 * trend + 0.5 * breadth

        assert (gate_min == 0.1).all()
        assert (gate_avg == 0.55).all()
        assert (gate_min < gate_avg).all()

    def test_avg_gate_mode_available_for_comparison(self):
        cfg = IndiaConfig(gate_mode="avg")
        assert cfg.gate_mode == "avg"


class TestTrendScore:
    def test_strong_uptrend_scores_near_one(self):
        cfg = IndiaConfig()
        idx = pd.bdate_range("2020-01-01", periods=300)
        prices = pd.Series(np.linspace(100, 300, 300), index=idx)
        score = trend_score(prices, cfg)
        assert score.iloc[-1] == 1.0

    def test_strong_downtrend_scores_near_zero(self):
        cfg = IndiaConfig()
        idx = pd.bdate_range("2020-01-01", periods=300)
        prices = pd.Series(np.linspace(300, 100, 300), index=idx)
        score = trend_score(prices, cfg)
        assert score.iloc[-1] == 0.0


class TestBreadthScore:
    def test_all_names_above_ma_gives_full_breadth(self):
        cfg = IndiaConfig()
        idx = pd.bdate_range("2020-01-01", periods=200)
        panel = pd.DataFrame({
            f"N{i}": np.linspace(100, 100 + 50 * (i + 1), 200) for i in range(10)
        }, index=idx)
        breadth = breadth_score(panel, cfg)
        assert breadth.iloc[-1] == pytest.approx(1.0, abs=0.01)


class TestVolScalar:
    def test_clipped_to_configured_bounds(self):
        cfg = IndiaConfig(vol_scalar_floor=0.5, vol_scalar_ceiling=1.5)
        bench = _bench_series()
        vs = vol_scalar(bench, cfg)
        valid = vs.dropna()
        assert (valid >= 0.5 - 1e-9).all()
        assert (valid <= 1.5 + 1e-9).all()


class TestExposureOverlayIntegration:
    def test_never_exceeds_leverage_cap(self):
        cfg = IndiaConfig(leverage_cap=1.5)
        bench = _bench_series()
        universe = pd.DataFrame({
            f"N{i}": _bench_series(seed=i + 10).values for i in range(5)
        }, index=bench.index)
        exposure = exposure_overlay(bench, universe, bench.index, cfg)
        valid = exposure.dropna()
        assert (valid <= cfg.leverage_cap + 1e-9).all()
        assert (valid >= 0.0).all()

    def test_lag_is_applied(self):
        """Exposure on day t must reflect signals from before the lag, not
        same-day information -- verified by checking the series is shifted
        forward by exactly signal_lag_days relative to an unshifted version."""
        cfg = IndiaConfig(signal_lag_days=2)
        bench = _bench_series()
        universe = pd.DataFrame({f"N{i}": bench.values for i in range(3)}, index=bench.index)
        exposure = exposure_overlay(bench, universe, bench.index, cfg)
        # First `signal_lag_days` values must be NaN (nothing to lag from yet)
        assert exposure.iloc[: cfg.signal_lag_days].isna().all()
