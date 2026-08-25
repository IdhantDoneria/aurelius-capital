"""Accounting invariants of the segment backtester.

A backtester that is wrong by a few basis points a day is indistinguishable
from alpha over ten years, so the arithmetic is pinned against closed-form
answers rather than eyeballed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.swing.costs import CostConfig, FinancingModel
from mentisrex.swing.portfolio import (
    BacktestConfig, MarketPanel, SegmentBacktester,
)

T, N = 60, 4


def make_panel(seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=T)
    on = rng.normal(drift, 0.004, size=(T, N))
    idr = rng.normal(drift, 0.008, size=(T, N))
    close = np.zeros((T, N))
    open_ = np.zeros((T, N))
    prev = np.full(N, 100.0)
    prev_close = np.zeros((T, N))
    for t in range(T):
        prev_close[t] = prev
        open_[t] = prev * (1 + on[t])
        close[t] = open_[t] * (1 + idr[t])
        prev = close[t]
    return MarketPanel(
        dates=dates,
        symbols=np.array([f"S{i}" for i in range(N)]),
        open_=open_, close=close, prev_close=prev_close,
        adv=np.full((T, N), 1e9),
        spread=np.full((T, N), 0.0),
        daily_vol=np.zeros((T, N)),
        tradable=np.ones((T, N), bool),
        htb=np.zeros((T, N), bool),
    )


def zero_financing(dates):
    return FinancingModel(cfg=CostConfig(), overnight_rate=pd.Series(0.0, index=dates))


class ConstantWeights:
    name = "const"

    def __init__(self, w, at="moc", warm=0):
        self.w, self.at, self.warm = w, at, warm

    def warmup(self):
        return self.warm

    def targets_moc(self, t):
        return self.w if self.at == "moc" else None

    def targets_moo(self, t):
        return self.w if self.at == "moo" else None


class Flat:
    name = "flat"

    def warmup(self):
        return 0

    def targets_moc(self, t):
        return np.zeros(N)

    def targets_moo(self, t):
        return None


def test_flat_book_is_exactly_flat():
    p = make_panel()
    bt = SegmentBacktester(p, zero_financing(p.dates), BacktestConfig(costs=CostConfig(commission_cps=0.0, auction_fee_cps=0.0, sec_fee_bps=0.0,
                      taf_cps=0.0, impact_eta_auction=0.0, impact_eta_continuous=0.0)))
    r = bt.run(Flat())
    assert r["equity"].std() == pytest.approx(0.0, abs=1e-6)
    assert r["ret"].abs().max() == pytest.approx(0.0, abs=1e-12)


def test_moc_entry_earns_the_next_close_to_close_return():
    """A book set at the close of t and held must earn t+1's close-to-close
    return -- never t's, which would be look-ahead."""
    p = make_panel()
    w = np.array([1.0, 0.0, 0.0, 0.0])
    cost = CostConfig(commission_cps=0.0, auction_fee_cps=0.0, sec_fee_bps=0.0,
                      taf_cps=0.0, impact_eta_auction=0.0, impact_eta_continuous=0.0)
    bt = SegmentBacktester(p, zero_financing(p.dates), BacktestConfig(costs=cost))
    r = bt.run(ConstantWeights(w))
    # day 1's portfolio return equals asset 0's close-to-close return over day 1
    expected = p.close[1, 0] / p.close[0, 0] - 1.0
    assert r["ret"].iloc[1] == pytest.approx(expected, rel=1e-9)


def test_moc_in_moo_out_earns_only_the_overnight_leg():
    p = make_panel()
    w = np.array([1.0, 0.0, 0.0, 0.0])

    class OvernightOnly:
        name = "on"

        def warmup(self):
            return 0

        def targets_moc(self, t):
            return w

        def targets_moo(self, t):
            return np.zeros(N)

    cost = CostConfig(commission_cps=0.0, auction_fee_cps=0.0, sec_fee_bps=0.0,
                      taf_cps=0.0, impact_eta_auction=0.0, impact_eta_continuous=0.0)
    bt = SegmentBacktester(p, zero_financing(p.dates), BacktestConfig(costs=cost))
    r = bt.run(OvernightOnly())
    expected = p.open_[1, 0] / p.close[0, 0] - 1.0
    assert r["ret"].iloc[1] == pytest.approx(expected, rel=1e-9)
    assert r["pnl_intraday"].abs().max() == pytest.approx(0.0, abs=1e-6)


def test_costs_reduce_equity_monotonically():
    p = make_panel()
    rng = np.random.default_rng(3)
    w = rng.normal(size=N) * 0.1

    def final(cps):
        bt = SegmentBacktester(
            p, zero_financing(p.dates),
            BacktestConfig(costs=CostConfig(commission_cps=cps, auction_fee_cps=0.0,
                                            sec_fee_bps=0.0, taf_cps=0.0,
                                            impact_eta_auction=0.0)),
        )
        return bt.run(ConstantWeights(w))["equity"].iloc[-1]

    a, b, c = final(0.0), final(0.1), final(0.5)
    assert a > b > c


def test_financing_charges_a_levered_book_and_not_an_unlevered_one():
    p = make_panel()
    fin = FinancingModel(cfg=CostConfig(), overnight_rate=pd.Series(0.05, index=p.dates))
    cost = CostConfig(commission_cps=0.0, auction_fee_cps=0.0, sec_fee_bps=0.0,
                      taf_cps=0.0, impact_eta_auction=0.0, impact_eta_continuous=0.0)

    lev = SegmentBacktester(p, fin, BacktestConfig(costs=cost)).run(
        ConstantWeights(np.array([1.5, 1.5, -1.5, -1.5]))
    )
    small = SegmentBacktester(p, fin, BacktestConfig(costs=cost)).run(
        ConstantWeights(np.array([0.25, 0.25, 0.0, 0.0]))
    )
    assert lev["financing"].mean() > small["financing"].mean()
    assert small["financing"].mean() == pytest.approx(0.0, abs=1e-6)


def test_untradable_name_is_force_closed_and_stops_accruing():
    p = make_panel()
    p.tradable[30:, 0] = False
    p.close[30:, 0] = np.nan
    p.open_[30:, 0] = np.nan
    cost = CostConfig(commission_cps=0.0, auction_fee_cps=0.0, sec_fee_bps=0.0,
                      taf_cps=0.0, impact_eta_auction=0.0, impact_eta_continuous=0.0)
    bt = SegmentBacktester(p, zero_financing(p.dates), BacktestConfig(costs=cost))
    r = bt.run(ConstantWeights(np.array([1.0, 0.0, 0.0, 0.0])))
    assert r["n_pos"].iloc[35] == 0
    assert np.isfinite(r["equity"].iloc[-1])


def test_delist_haircut_is_charged_once_on_the_dead_name():
    p = make_panel()
    p.tradable[30:, 0] = False
    p.close[30:, 0] = np.nan
    p.open_[30:, 0] = np.nan
    cost = CostConfig(commission_cps=0.0, auction_fee_cps=0.0, sec_fee_bps=0.0,
                      taf_cps=0.0, impact_eta_auction=0.0, impact_eta_continuous=0.0)
    w = np.array([1.0, 0.0, 0.0, 0.0])

    def final(h):
        bt = SegmentBacktester(p, zero_financing(p.dates),
                               BacktestConfig(costs=cost, delist_haircut=h))
        return bt.run(ConstantWeights(w))

    clean = final(0.0)
    hurt = final(-0.30)
    assert hurt["equity"].iloc[-1] < clean["equity"].iloc[-1]
    assert (hurt["delist_loss"] != 0).sum() == 1


def test_turnover_matches_notional_traded():
    p = make_panel()
    cost = CostConfig(commission_cps=0.0, auction_fee_cps=0.0, sec_fee_bps=0.0,
                      taf_cps=0.0, impact_eta_auction=0.0, impact_eta_continuous=0.0)
    bt = SegmentBacktester(p, zero_financing(p.dates), BacktestConfig(costs=cost))
    w = np.array([0.5, -0.5, 0.0, 0.0])
    r = bt.run(ConstantWeights(w))
    # first day builds a book of gross 1.0 from nothing
    assert r["turnover"].iloc[0] == pytest.approx(1.0, rel=1e-6)
    # thereafter only drift is rebalanced, so turnover is small
    assert r["turnover"].iloc[5:].max() < 0.2


def test_warmup_suppresses_trading():
    p = make_panel()
    bt = SegmentBacktester(p, zero_financing(p.dates), BacktestConfig())
    r = bt.run(ConstantWeights(np.array([1.0, 0.0, 0.0, 0.0]), warm=20))
    assert r["traded"].iloc[:20].sum() == 0.0
    assert r["traded"].iloc[20] > 0.0
