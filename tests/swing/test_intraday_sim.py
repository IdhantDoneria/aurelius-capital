"""Fill discipline in the bar-level simulator.

Every one of these tests exists because the corresponding mistake is easy to
make and inflates a day-trading backtest enormously: filling on the signal
bar, filling a stop at the stop price when the bar gapped through it, or
exiting on a rule that used the same bar's close.
"""
from __future__ import annotations

import numpy as np
import pytest

from mentisrex.swing.intraday_sim import IntradayRules, running_vwap, simulate_day_symbol

RULES = IntradayRules(entry_from_mod=570, last_entry_mod=930, exit_mod=945,
                      cone_k=1.0, vwap_trail=False, atr_stop_mult=1.0,
                      use_opening_range_stop=False)


def _day(closes, highs=None, lows=None, opens=None, n=None):
    n = n or len(closes)
    mods = np.arange(570, 570 + 15 * n, 15)
    c = np.asarray(closes, dtype=float)
    o = np.asarray(opens, dtype=float) if opens is not None else c.copy()
    h = np.asarray(highs, dtype=float) if highs is not None else np.maximum(o, c)
    l = np.asarray(lows, dtype=float) if lows is not None else np.minimum(o, c)
    return mods, o, h, l, c


def test_entry_fills_on_the_next_bar_open_never_the_signal_bar():
    """The breach is only known at the signal bar's close, so the earliest
    honest fill is the following bar's open."""
    mods, o, h, l, c = _day([100, 110, 110, 110, 110])
    o[2] = 105.0                                  # distinctly different fill price
    cone = np.full(len(mods), 0.01)
    vw = np.full(len(mods), np.nan)
    out = simulate_day_symbol(mods, o, h, l, c, vw, cone, 100.0, np.nan, np.nan, 5.0, RULES)
    assert len(out) == 1
    side, entry_mod, entry_px, *_ = out[0]
    assert side == 1
    assert entry_mod == mods[2]
    assert entry_px == pytest.approx(105.0)


def test_no_entry_when_the_move_stays_inside_the_cone():
    mods, o, h, l, c = _day([100, 100.5, 100.4, 100.2, 100.1])
    cone = np.full(len(mods), 0.05)
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, np.nan, np.nan, 5.0, RULES)
    assert out == []


def test_short_entry_on_a_downside_breach():
    mods, o, h, l, c = _day([100, 90, 90, 90, 90])
    cone = np.full(len(mods), 0.01)
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, np.nan, np.nan, 5.0, RULES)
    assert out and out[0][0] == -1


def test_stop_fills_at_the_stop_price_when_the_bar_straddles_it():
    mods, o, h, l, c = _day([100, 110, 110, 110, 110],
                            lows=[100, 110, 100, 100, 100],
                            opens=[100, 110, 110, 110, 110])
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=570, last_entry_mod=930, exit_mod=945,
                          cone_k=1.0, vwap_trail=False, atr_stop_mult=1.0,
                          use_opening_range_stop=False)
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, np.nan, np.nan, 5.0, rules)
    side, _, entry, xmod, xpx, stop, reason, *_ = out[0]
    assert reason == "stop"
    assert xpx == pytest.approx(stop)
    assert stop == pytest.approx(entry - 5.0)


def test_stop_fills_at_the_open_when_the_bar_gaps_through_it():
    """A gap through the stop cannot fill at the stop -- taking the bar open
    is the conservative side of that ambiguity."""
    # signal on bar 1, entry at bar 2's open of 110, stop at 105, bar 3 gaps
    # straight to 100 without ever trading at 105
    mods, o, h, l, c = _day([100, 110, 110, 100, 100],
                            opens=[100, 110, 110, 100, 100],
                            lows=[100, 110, 109, 99, 99],
                            highs=[100, 110, 111, 101, 101])
    cone = np.full(len(mods), 0.01)
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, np.nan, np.nan, 5.0, RULES)
    side, _, entry, xmod, xpx, stop, reason, *_ = out[0]
    assert reason == "stop"
    assert entry == pytest.approx(110.0)
    assert stop == pytest.approx(105.0)
    assert xpx == pytest.approx(100.0)     # the gap open, not the untouched stop
    assert xpx < stop


def test_time_exit_forces_flat_before_the_close():
    mods, o, h, l, c = _day([100, 110, 111, 112, 113, 114])
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=570, last_entry_mod=600, exit_mod=mods[-1],
                          cone_k=1.0, vwap_trail=False, atr_stop_mult=5.0,
                          use_opening_range_stop=False)
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, np.nan, np.nan, 50.0, rules)
    assert out[0][6] == "time"
    assert out[0][3] <= rules.exit_mod


def test_vwap_trail_exits_at_the_open_after_the_breach_bar():
    mods, o, h, l, c = _day([100, 110, 109, 108, 108])
    o[:] = [100, 110, 109, 107, 106]
    vw = np.array([100.0, 105.0, 110.0, 110.0, 110.0])   # long closes below VWAP at bar 2
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=570, last_entry_mod=930, exit_mod=945,
                          cone_k=1.0, vwap_trail=True, atr_stop_mult=10.0,
                          use_opening_range_stop=False)
    out = simulate_day_symbol(mods, o, h, l, c, vw, cone, 100.0, np.nan, np.nan, 50.0, rules)
    side, emod, epx, xmod, xpx, stop, reason, *_ = out[0]
    assert reason == "vwap"
    assert epx == pytest.approx(109.0)     # entry: bar 2's open
    assert xpx == pytest.approx(107.0)     # exit: bar 3's open, not bar 2's close


def test_entry_is_blocked_before_the_permitted_hour():
    mods, o, h, l, c = _day([100, 130, 130, 130])
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=mods[-1] + 15, last_entry_mod=mods[-1] + 30,
                          exit_mod=mods[-1] + 45, cone_k=1.0, vwap_trail=False)
    assert simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                               100.0, np.nan, np.nan, 5.0, rules) == []


def test_max_entries_per_day_is_respected():
    mods, o, h, l, c = _day([100, 120, 100, 120, 100, 120, 100, 120])
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=570, last_entry_mod=mods[-2], exit_mod=mods[-1],
                          cone_k=1.0, vwap_trail=False, atr_stop_mult=0.5,
                          use_opening_range_stop=False, max_entries_per_day=1)
    assert len(simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                                   100.0, np.nan, np.nan, 5.0, rules)) <= 1


def test_opening_range_stop_is_used_when_tighter():
    mods, o, h, l, c = _day([100, 110, 110, 110])
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=570, last_entry_mod=930, exit_mod=945,
                          cone_k=1.0, vwap_trail=False, atr_stop_mult=1.0,
                          use_opening_range_stop=True)
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, or_hi=101.0, or_lo=108.0, atr=50.0, rules=rules)
    assert out[0][5] == pytest.approx(108.0)      # OR low beats a 50-wide ATR stop


def test_running_vwap_is_cumulative_and_causal():
    vwap = np.array([10.0, 20.0, 30.0])
    vol = np.array([1.0, 1.0, 2.0])
    got = running_vwap(vwap, vol)
    assert got[0] == pytest.approx(10.0)
    assert got[1] == pytest.approx(15.0)
    assert got[2] == pytest.approx((10 + 20 + 60) / 4)


def test_running_vwap_handles_a_zero_volume_open():
    got = running_vwap(np.array([np.nan, 20.0]), np.array([0.0, 1.0]))
    assert np.isnan(got[0])
    assert got[1] == pytest.approx(20.0)


def test_simulation_reads_the_first_bar_as_the_session_open():
    """`mods[0]` is taken as the open, so bars must reach the simulator in
    time order. This pins the assumption that the caller is responsible for
    sorting -- an unsorted frame produces a different backtest, not an error.
    """
    mods, o, h, l, c = _day([100, 110, 110, 110])
    cone = np.full(len(mods), 0.01)
    forward = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan),
                                  cone, float(o[0]), np.nan, np.nan, 5.0, RULES)
    rev = slice(None, None, -1)
    backward = simulate_day_symbol(mods[rev], o[rev], h[rev], l[rev], c[rev],
                                   np.full(len(mods), np.nan), cone,
                                   float(o[rev][0]), np.nan, np.nan, 5.0, RULES)
    assert forward != backward


def _blotter(rows):
    import pandas as pd
    return pd.DataFrame(rows)


def test_daily_loss_limit_counts_only_pnl_realised_before_each_entry():
    """A position entered at 10:00 and exited at 15:45 tells you nothing at
    11:00. Counting unrealised trades would let the limit fire on losses the
    desk could not yet have seen."""
    from mentisrex.swing.strategies.dayburn import DayburnConfig, apply_daily_loss_limit

    cfg = DayburnConfig(daily_loss_limit=0.01)
    equity = 100.0
    t = _blotter([
        # a big loser that does not resolve until the end of the session
        {"entry_mod": 600, "exit_mod": 945, "notional": 100.0, "gross_ret": -0.50},
        # entered while the first is still open: must survive
        {"entry_mod": 660, "exit_mod": 700, "notional": 10.0, "gross_ret": 0.01},
    ])
    kept = apply_daily_loss_limit(t, equity, cfg)
    assert len(kept) == 2


def test_daily_loss_limit_stops_new_risk_once_realised_losses_breach_it():
    from mentisrex.swing.strategies.dayburn import DayburnConfig, apply_daily_loss_limit

    cfg = DayburnConfig(daily_loss_limit=0.01)
    equity = 100.0
    t = _blotter([
        {"entry_mod": 600, "exit_mod": 620, "notional": 100.0, "gross_ret": -0.05},
        {"entry_mod": 660, "exit_mod": 700, "notional": 10.0, "gross_ret": 0.01},
        {"entry_mod": 700, "exit_mod": 900, "notional": 10.0, "gross_ret": 0.01},
    ])
    kept = apply_daily_loss_limit(t, equity, cfg)
    assert len(kept) == 1
    assert kept["entry_mod"].tolist() == [600]


def test_daily_loss_limit_is_a_no_op_when_disabled():
    from mentisrex.swing.strategies.dayburn import DayburnConfig, apply_daily_loss_limit

    cfg = DayburnConfig(daily_loss_limit=0.0)
    t = _blotter([{"entry_mod": 600, "exit_mod": 620, "notional": 100.0, "gross_ret": -0.90}])
    assert len(apply_daily_loss_limit(t, 100.0, cfg)) == 1


def test_a_stop_on_the_wrong_side_of_entry_is_rejected():
    """A gap between the signal bar and the fill can put the opening-range
    stop above a long's entry. Such a 'stop' does not protect the trade, it
    books a guaranteed profit the moment it is touched."""
    mods, o, h, l, c = _day([100, 110, 110, 110])
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=570, last_entry_mod=930, exit_mod=945,
                          cone_k=1.0, vwap_trail=False, atr_stop_mult=1.0,
                          use_opening_range_stop=True)
    # opening-range low sits *above* the fill price, and no ATR stop is
    # available either
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, or_hi=130.0, or_lo=125.0, atr=np.nan, rules=rules)
    assert out == []


def test_a_valid_atr_stop_is_used_when_the_range_stop_is_unusable():
    mods, o, h, l, c = _day([100, 110, 110, 110])
    cone = np.full(len(mods), 0.01)
    rules = IntradayRules(entry_from_mod=570, last_entry_mod=930, exit_mod=945,
                          cone_k=1.0, vwap_trail=False, atr_stop_mult=1.0,
                          use_opening_range_stop=True)
    out = simulate_day_symbol(mods, o, h, l, c, np.full(len(mods), np.nan), cone,
                              100.0, or_hi=130.0, or_lo=125.0, atr=4.0, rules=rules)
    assert len(out) == 1
    assert out[0][5] == pytest.approx(106.0)      # entry 110 less one ATR
