"""Bar-level intraday simulator for the day-trading sleeve.

The cross-sectional simulator in `portfolio.py` marks positions across whole
segments, which is right for a book that is set at one auction and unwound
at another. It is wrong for a strategy whose entire return comes from a
path -- where it entered, where the stop sat, whether VWAP was lost before
the close. That strategy is simulated here, bar by bar.

Fill discipline throughout: a rule evaluated on bar `i` fills at the *open of
bar i+1*. Stops fill at the stop price when the bar's range contains it, and
at the bar's open when the bar gaps through it, which is the conservative
side of the ambiguity. Nothing is ever filled at a price that could only be
known after the decision.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RTH_OPEN = 9 * 60 + 30
RTH_CLOSE = 16 * 60
BAR_MINUTES = 15
BARS_PER_SESSION = (RTH_CLOSE - RTH_OPEN) // BAR_MINUTES


@dataclass
class IntradayRules:
    entry_from_mod: int = 10 * 60
    """No entries before this ET minute. The first half hour is left alone:
    it is where the opening range is being formed and where spreads are at
    their widest."""

    last_entry_mod: int = 15 * 60
    exit_mod: int = 15 * 60 + 45
    """Force flat here, before the closing auction, so the sleeve never
    carries overnight risk and never competes with a closing-auction sleeve
    for the same print."""

    cone_k: float = 1.0
    """Entry threshold in units of the time-of-day expected move."""

    use_opening_range_stop: bool = True
    atr_stop_mult: float = 1.0
    vwap_trail: bool = True
    """Exit a long whose bar closes below session VWAP. VWAP is the
    benchmark institutional algorithms are measured against, so losing it is
    evidence the flow that started the move has stopped."""

    max_entries_per_day: int = 1
    risk_per_trade: float = 0.0010
    """Fraction of equity risked between entry and initial stop."""

    max_position_weight: float = 0.10
    max_adv_participation: float = 0.02
    """Cap notional at this share of the name's trailing dollar volume."""


@dataclass
class Trade:
    d: pd.Timestamp
    symbol: str
    side: int
    entry_mod: int
    entry_px: float
    exit_mod: int
    exit_px: float
    stop_px: float
    reason: str
    notional: float
    gross_ret: float

    @property
    def pnl_gross(self) -> float:
        return self.notional * self.gross_ret


def simulate_day_symbol(
    mods: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    vwap_run: np.ndarray,
    cone: np.ndarray,
    p_open: float,
    or_hi: float,
    or_lo: float,
    atr: float,
    rules: IntradayRules,
) -> list[tuple]:
    """Simulate one symbol on one day. Returns raw trade tuples.

    `cone[i]` is the expected absolute log move from the open by bar `i`.
    `vwap_run[i]` is the running session VWAP through bar `i`.
    """
    out: list[tuple] = []
    n = len(mods)
    i = 0
    entries = 0
    while i < n - 1 and entries < rules.max_entries_per_day:
        m = mods[i]
        if m < rules.entry_from_mod:
            i += 1
            continue
        if m > rules.last_entry_mod:
            break
        c = cone[i]
        if not np.isfinite(c) or c <= 0 or close[i] <= 0 or p_open <= 0:
            i += 1
            continue

        dev = np.log(close[i] / p_open)
        side = 0
        if dev > rules.cone_k * c:
            side = 1
        elif dev < -rules.cone_k * c:
            side = -1
        if side == 0:
            i += 1
            continue

        # fill on the next bar's open -- the signal was only known at this
        # bar's close
        j = i + 1
        entry_px = open_[j]
        if not np.isfinite(entry_px) or entry_px <= 0:
            i += 1
            continue

        stops = []
        if rules.use_opening_range_stop and np.isfinite(or_hi) and np.isfinite(or_lo):
            stops.append(or_lo if side > 0 else or_hi)
        if np.isfinite(atr) and atr > 0:
            stops.append(entry_px - side * rules.atr_stop_mult * atr)
        if not stops:
            i += 1
            continue
        # tightest stop = the one closest to entry
        stop_px = min(stops, key=lambda s: abs(entry_px - s))
        risk = abs(entry_px - stop_px)
        if risk <= 0 or risk / entry_px < 1e-4:
            i += 1
            continue

        exit_px, exit_mod, reason = None, None, ""
        k = j
        while k < n:
            if side > 0 and low[k] <= stop_px:
                exit_px = stop_px if open_[k] > stop_px else open_[k]
                exit_mod, reason = mods[k], "stop"
                break
            if side < 0 and high[k] >= stop_px:
                exit_px = stop_px if open_[k] < stop_px else open_[k]
                exit_mod, reason = mods[k], "stop"
                break
            if mods[k] >= rules.exit_mod:
                exit_px, exit_mod, reason = close[k], mods[k], "time"
                break
            # The VWAP check runs from the entry bar onward. Skipping the
            # entry bar would hold a position that closed on the wrong side of
            # VWAP for an extra bar purely to avoid a same-bar round trip,
            # which flatters the exit rather than making it conservative --
            # the fill is still the *next* bar's open either way.
            if (
                rules.vwap_trail
                and np.isfinite(vwap_run[k])
                and ((side > 0 and close[k] < vwap_run[k]) or (side < 0 and close[k] > vwap_run[k]))
            ):
                if k + 1 < n:
                    exit_px, exit_mod, reason = open_[k + 1], mods[k + 1], "vwap"
                else:
                    exit_px, exit_mod, reason = close[k], mods[k], "vwap"
                break
            k += 1
        if exit_px is None:
            exit_px, exit_mod, reason = close[n - 1], mods[n - 1], "eod"

        gross_ret = side * (exit_px / entry_px - 1.0)
        out.append(
            (side, int(mods[j]), float(entry_px), int(exit_mod), float(exit_px),
             float(stop_px), reason, float(risk / entry_px), float(gross_ret))
        )
        entries += 1
        # resume scanning after the exit
        i = max(k + 1, j + 1)
    return out


def running_vwap(vwap: np.ndarray, volume: np.ndarray) -> np.ndarray:
    pv = np.nan_to_num(vwap) * np.nan_to_num(volume)
    cv = np.cumsum(np.nan_to_num(volume))
    out = np.divide(np.cumsum(pv), np.maximum(cv, 1e-9))
    return np.where(cv > 0, out, np.nan)
