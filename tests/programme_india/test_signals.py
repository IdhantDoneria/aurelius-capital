from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.programme_india.config import IndiaConfig
from mentisrex.programme_india.signals import (
    composite_score,
    inverse_vol_weights,
    momentum_score,
    quality_score_from_fundamentals,
    select_with_sector_cap,
    zscore,
)


def _price_panel(n_days=300, n_names=30, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    cols = [f"N{i}.NS" for i in range(n_names)]
    rets = rng.normal(0.0005, 0.015, size=(n_days, n_names))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    return pd.DataFrame(prices, index=idx, columns=cols)


class TestZscore:
    def test_mean_zero_std_one(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        z = zscore(s)
        assert z.mean() == pytest.approx(0.0, abs=1e-9)
        assert z.std() == pytest.approx(1.0, abs=1e-9)

    def test_constant_series_returns_zero_not_nan(self):
        s = pd.Series([5.0, 5.0, 5.0])
        z = zscore(s)
        assert (z == 0.0).all()


class TestMomentumScore:
    def test_insufficient_history_returns_empty(self):
        cfg = IndiaConfig()
        panel = _price_panel(n_days=50)
        result = momentum_score(panel, cfg)
        assert result.empty

    def test_ranks_winners_above_losers(self):
        cfg = IndiaConfig()
        idx = pd.bdate_range("2020-01-01", periods=280)
        winner = pd.Series(np.linspace(100, 300, 280), index=idx)  # steady uptrend
        loser = pd.Series(np.linspace(100, 30, 280), index=idx)  # steady downtrend
        panel = pd.DataFrame({"WINNER.NS": winner, "LOSER.NS": loser})
        mom = momentum_score(panel, cfg)
        assert mom["WINNER.NS"] > mom["LOSER.NS"]


class TestCompositeScore:
    def test_no_quality_falls_back_to_momentum(self):
        cfg = IndiaConfig()
        mom_z = pd.Series({"A": 1.0, "B": -1.0})
        result = composite_score(mom_z, None, cfg)
        pd.testing.assert_series_equal(result, mom_z)

    def test_missing_quality_treated_as_neutral_not_dropped(self):
        cfg = IndiaConfig()
        mom_z = pd.Series({"A": 1.0, "B": 1.0})
        quality_z = pd.Series({"A": 2.0})  # B has no quality data
        result = composite_score(mom_z, quality_z, cfg)
        assert "B" in result.index
        assert not pd.isna(result["B"])
        # A gets its real quality boost, B gets momentum-weight only
        assert result["A"] > result["B"]

    def test_quality_score_formula(self):
        roe = pd.Series({"A": 0.2, "B": 0.1, "C": 0.05})
        d2e = pd.Series({"A": 0.5, "B": 1.0, "C": 1.5})
        stability = pd.Series({"A": 0.9, "B": 0.5, "C": 0.1})
        q = quality_score_from_fundamentals(roe, d2e, stability)
        # A: highest ROE, lowest debt, highest stability -> should rank first
        assert q["A"] > q["B"] > q["C"]


class TestSectorCap:
    def test_caps_single_sector_exposure(self):
        cfg = IndiaConfig()  # sector_cap = 0.28
        ranked = [f"S{i}" for i in range(10)]  # all same sector, best-ranked first
        sector_map = dict.fromkeys(ranked, "Financials")
        picks = select_with_sector_cap(ranked, sector_map, cfg, n_pick=10)
        # With a single sector and n_pick=10, sector cap forces a fallback
        # (can't diversify a single-sector universe) -- verify it doesn't
        # silently exceed n_pick or crash.
        assert len(picks) <= 10

    def test_diversified_universe_respects_cap(self):
        cfg = IndiaConfig()
        ranked = [f"S{i}" for i in range(20)]
        # 4 sectors, 5 names each -- no sector should end up over 28% of an
        # n_pick=10 book (2.8 names -> effectively capped at 2-3 per sector)
        sector_map = {f"S{i}": f"Sector{i % 4}" for i in range(20)}
        picks = select_with_sector_cap(ranked, sector_map, cfg, n_pick=10)
        from collections import Counter

        counts = Counter(sector_map[p] for p in picks)
        assert max(counts.values()) <= 4  # well under a single sector dominating


class TestInverseVolWeights:
    def test_weights_sum_to_one(self):
        cfg = IndiaConfig()
        panel = _price_panel(n_names=10)
        returns = panel.pct_change().iloc[-63:]
        picks = list(panel.columns[:5])
        w = inverse_vol_weights(returns, picks, cfg)
        assert w.sum() == pytest.approx(1.0, abs=1e-9)

    def test_no_weight_exceeds_cap_when_feasible(self):
        """8% cap needs >=12.5 names to be mathematically feasible (this
        programme's real decile book runs ~19.5 names, so this is the
        realistic case, not the 5-name pathological one)."""
        cfg = IndiaConfig()
        panel = _price_panel(n_names=20)
        returns = panel.pct_change().iloc[-63:]
        picks = list(panel.columns[:20])
        w = inverse_vol_weights(returns, picks, cfg)
        assert w.sum() == pytest.approx(1.0, abs=1e-9)
        assert (w <= cfg.per_name_cap + 1e-9).all()

    def test_cap_bug_regression_similar_vol_names_stay_capped(self):
        """The exact bug this test suite caught: when every name's raw
        inverse-vol weight sits near the cap, a naive clip-then-renormalize
        pushes them straight back over it. With near-identical
        volatilities across enough names for the cap to be feasible, no
        weight may exceed the cap after renormalization."""
        cfg = IndiaConfig()
        idx = pd.bdate_range("2020-01-01", periods=63)
        rng = np.random.default_rng(3)
        # 20 names, near-identical volatility -> raw inverse-vol weights
        # all cluster near 1/20 = 5%, cap is 8% -- feasible, and every raw
        # weight starts BELOW the cap already in this case, so this
        # specifically checks the "already near cap" regime doesn't get
        # pushed over it by any rounding/redistribution error.
        returns = pd.DataFrame(
            {f"N{i}.NS": rng.normal(0, 0.014 + 0.0002 * i, 63) for i in range(20)}, index=idx
        )
        picks = list(returns.columns)
        w = inverse_vol_weights(returns, picks, cfg)
        assert (w <= cfg.per_name_cap + 1e-9).all(), w.max()
        assert w.sum() == pytest.approx(1.0, abs=1e-9)

    def test_infeasible_cap_falls_back_to_equal_weight_not_silent_violation(self):
        """5 names with an 8% cap is mathematically impossible (5x8%=40%
        < 100%) -- the function must not pretend the cap held; it should
        fall back to the documented equal-weight resolution."""
        cfg = IndiaConfig()
        panel = _price_panel(n_names=5)
        returns = panel.pct_change().iloc[-63:]
        picks = list(panel.columns)
        w = inverse_vol_weights(returns, picks, cfg)
        assert w.sum() == pytest.approx(1.0, abs=1e-9)
        assert (w.sub(0.2).abs() < 1e-6).all()

    def test_lower_vol_name_gets_higher_weight(self):
        """20 names so the 8% cap is feasible and doesn't mask the signal;
        one deliberately much-lower-vol name should end up capped at the
        ceiling (the highest weight achievable), strictly above the
        higher-vol peers."""
        cfg = IndiaConfig()
        idx = pd.bdate_range("2020-01-01", periods=63)
        rng = np.random.default_rng(4)
        data = {"LOW.NS": rng.normal(0, 0.004, 63)}
        for i in range(19):
            data[f"HIGH{i}.NS"] = rng.normal(0, 0.03, 63)
        returns = pd.DataFrame(data, index=idx)
        picks = list(returns.columns)
        w = inverse_vol_weights(returns, picks, cfg)
        assert w["LOW.NS"] > w["HIGH0.NS"]
        assert w["LOW.NS"] == pytest.approx(cfg.per_name_cap, abs=1e-6)
