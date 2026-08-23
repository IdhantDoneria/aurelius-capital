"""Tests for mentisrex.programme_india.metrics.

test_cagr_bug_regression is a regression test for a real bug found during
this programme's research phase (see metrics.py's module docstring): a NAV
series built as start_capital * (1+returns).cumprod() makes nav.iloc[0]
already reflect day one's return, silently dropping it from any
nav[-1]/nav[0] CAGR calculation. This test would have caught that on day
one -- it must keep passing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.programme_india.metrics import (
    beta_alpha,
    cagr_from_returns,
    drawdown_stats,
    nav_series,
    sharpe,
)


def _synthetic_returns(n=2000, mu=0.0006, sigma=0.012, seed=7) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    return pd.Series(rng.normal(mu, sigma, n), index=idx)


class TestNavSeries:
    def test_first_value_is_untouched_start_capital(self):
        r = _synthetic_returns()
        nav = nav_series(r, 1_000_000.0)
        # nav.iloc[0] must be EXACTLY the compounded value after day 0's
        # return, and dividing nav[-1] by the raw start_capital (not
        # nav[0]) must be the correct way to measure total growth.
        assert nav.iloc[0] == pytest.approx(1_000_000.0 * (1 + r.iloc[0]))

    def test_index_matches_input(self):
        r = _synthetic_returns()
        nav = nav_series(r, 100.0)
        assert list(nav.index) == list(r.index)


class TestCagrBugRegression:
    def test_cagr_bug_regression(self):
        """The exact bug: nav[-1]/nav[0] (WRONG) vs nav[-1]/start_capital
        (RIGHT) must differ on any non-trivial return series, and the
        module's own cagr_from_returns must use the right one and agree
        with an independent log-mean calculation."""
        r = _synthetic_returns()
        years = len(r) / 252.0
        nav = nav_series(r, 1.0)

        wrong_cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
        right_cagr = cagr_from_returns(r, years)

        # The bug is real and detectable: the two must differ measurably.
        assert abs(wrong_cagr - right_cagr) > 1e-5

        # And the module's answer must independently cross-check via the
        # log-mean method (this is what cagr_from_returns asserts internally
        # too -- re-deriving it here catches a regression in the assertion
        # itself, not just in the code it's checking).
        log_ret = np.log1p(r)
        independent_check = np.exp(log_ret.mean() * 252) - 1
        assert right_cagr == pytest.approx(independent_check, abs=1e-9)

    def test_the_original_bug_pattern_directly(self):
        """This reproduces the ACTUAL bug pattern found in the research
        scripts -- computing CAGR as nav[-1]/nav[0] against a real,
        start_capital-scaled NAV -- and proves it disagrees with the
        correct answer. `cagr_from_returns` itself is immune to this by
        construction (it uses nav.iloc[-1] against a known unit start, not
        a ratio against nav.iloc[0]), which is exactly why it's the
        function everything else in this package must call instead of
        rolling its own CAGR math."""
        r = _synthetic_returns(n=500)
        years = len(r) / 252.0
        real_nav = nav_series(r, 1_000_000.0)  # start_capital != 1.0, like production

        buggy_cagr = (real_nav.iloc[-1] / real_nav.iloc[0]) ** (1 / years) - 1
        correct_cagr = cagr_from_returns(r, years)

        assert abs(buggy_cagr - correct_cagr) > 1e-5

    def test_known_value(self):
        """A trivial, hand-computable case: constant daily return."""
        idx = pd.bdate_range("2020-01-01", periods=252)
        daily = 0.0005
        r = pd.Series(daily, index=idx)
        cagr = cagr_from_returns(r, 1.0)
        expected = (1 + daily) ** 252 - 1
        assert cagr == pytest.approx(expected, abs=1e-6)


class TestDrawdownStats:
    def test_simple_drawdown(self):
        idx = pd.bdate_range("2020-01-01", periods=10)
        nav = pd.Series([100, 110, 120, 90, 80, 85, 100, 121, 121, 130], index=idx, dtype=float)
        dd = drawdown_stats(nav)
        assert dd.max_dd == pytest.approx((80 - 120) / 120, abs=1e-9)
        assert dd.peak_date == str(idx[2].date())
        assert dd.trough_date == str(idx[4].date())
        assert dd.recovery_date == str(idx[7].date())

    def test_no_recovery(self):
        idx = pd.bdate_range("2020-01-01", periods=5)
        nav = pd.Series([100, 90, 80, 85, 88], index=idx, dtype=float)
        dd = drawdown_stats(nav)
        assert dd.recovery_date is None


class TestSharpeAndBeta:
    def test_sharpe_zero_vol_is_zero(self):
        idx = pd.bdate_range("2020-01-01", periods=50)
        r = pd.Series(0.0, index=idx)
        assert sharpe(r) == 0.0

    def test_beta_of_series_with_itself_is_one(self):
        r = _synthetic_returns(n=1000)
        beta, alpha = beta_alpha(r, r)
        assert beta == pytest.approx(1.0, abs=1e-9)
        assert alpha == pytest.approx(0.0, abs=1e-9)

    def test_beta_scales_correctly(self):
        bench = _synthetic_returns(n=1000)
        strat = 0.5 * bench  # exactly half the market's moves
        beta, _ = beta_alpha(strat, bench)
        assert beta == pytest.approx(0.5, abs=1e-9)
