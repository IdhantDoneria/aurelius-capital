"""CrossSectionalFactorStrategy — weekly-rebalancing cross-sectional factor strategy.

On each rebalance date, calls a user-supplied signal function to get
{security_id: score} cross-sections, ranks them, and goes long top-N
/ short bottom-N. Between rebalances, holds positions unchanged except
for intraperiod short stop-losses (checked on every bar).

Short rules:
  - Only enter shorts when regime_fn(date) returns True (low-vol regime).
  - Exit all shorts immediately when regime turns hostile.
  - Stop-loss: exit any short that moves 10% against entry (checked daily).
  - Short universe uses a stricter liquidity filter (short_signal_fn).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from mentisrex.backtesting.events.types import Direction, SignalEvent
from mentisrex.backtesting.strategy.base import Strategy, StrategyContext
from mentisrex.core.logging import get_logger

logger = get_logger(__name__)

# How to decide "first bar of a new period" by freq
_PERIOD_KEY: dict[str, Callable[[date], tuple]] = {
    "daily": lambda d: (d.year, d.month, d.day),
    "weekly": lambda d: (d.isocalendar().year, d.isocalendar().week),
    "monthly": lambda d: (d.year, d.month),
}

_SHORT_STOP_LOSS = 0.10  # exit short when price rises 10% above entry


class CrossSectionalFactorStrategy(Strategy):
    """Cross-sectional momentum strategy with optional regime-gated short book.

    signal_fn(as_of: date) -> dict[str, float]
        Long universe scores (higher = better). {} = skip rebalance.

    short_signal_fn(as_of: date) -> dict[str, float]
        Short universe scores (same scale; bottom scores = short candidates).
        If None, falls back to signal_fn for the short universe.

    regime_fn(as_of: date) -> bool
        True = low-vol regime, shorts allowed.
        False = high-vol regime, all shorts closed, no new shorts opened.
        If None, shorts are always allowed (long_only must be False).
    """

    name = "cross_sectional_factor"

    def __init__(
        self,
        signal_fn: Callable[[date], dict[str, float]],
        rebalance_freq: str = "monthly",
        q_long: float = 0.2,
        q_short: float = 0.2,
        long_only: bool = True,
        max_positions: int = 50,
        short_signal_fn: Callable[[date], dict[str, float]] | None = None,
        regime_fn: Callable[[date], bool] | None = None,
    ) -> None:
        if rebalance_freq not in _PERIOD_KEY:
            raise ValueError(f"rebalance_freq must be one of {list(_PERIOD_KEY)}")
        self._signal_fn = signal_fn
        self._short_signal_fn = short_signal_fn or signal_fn
        self._regime_fn = regime_fn
        self._freq = rebalance_freq
        self._q_long = q_long
        self._q_short = q_short
        self._long_only = long_only
        self._max_positions = max_positions

        self._last_rebalance_period: tuple | None = None
        self._rebalance_date: date | None = None
        self._current_longs: set[str] = set()
        self._current_shorts: set[str] = set()
        self._prev_held: set[str] = set()
        # entry close price for each active short, used for stop-loss
        self._short_entry_price: dict[str, float] = {}

    @property
    def parameters(self) -> dict:
        return {
            "rebalance_freq": self._freq,
            "q_long": self._q_long,
            "q_short": self._q_short,
            "long_only": self._long_only,
            "max_positions": self._max_positions,
            "short_stop_loss": _SHORT_STOP_LOSS,
        }

    def on_bar(self, ctx: StrategyContext, bar) -> list[SignalEvent]:
        bar_date = bar.timestamp.date()
        period = _PERIOD_KEY[self._freq](bar_date)

        if period != self._last_rebalance_period:
            self._rebalance(bar_date)
            self._last_rebalance_period = period
            self._rebalance_date = bar_date

        symbol = bar.symbol

        # Stop-loss: check every bar for shorts that moved 10% against entry.
        # Must run before the rebalance-signal block so a stop-hit on rebalance
        # day still fires (the FLAT from here takes priority over SHORT below).
        if symbol in self._current_shorts and symbol in self._short_entry_price:
            current = float(bar.close)
            entry = self._short_entry_price[symbol]
            if current >= entry * (1 + _SHORT_STOP_LOSS):
                self._current_shorts.discard(symbol)
                del self._short_entry_price[symbol]
                self._prev_held.add(symbol)
                logger.warning(
                    "short_stop_loss_triggered",
                    symbol=symbol,
                    entry=round(entry, 2),
                    current=round(current, 2),
                )
                return [SignalEvent(bar.timestamp, symbol, Direction.FLAT)]

        # Only emit entry/exit signals on the first bar of the rebalance period.
        if bar_date != self._rebalance_date:
            return []

        if symbol in self._current_longs:
            return [SignalEvent(bar.timestamp, symbol, Direction.LONG)]

        if symbol in self._current_shorts:
            # Record entry price on first signal emission for this short
            if symbol not in self._short_entry_price:
                self._short_entry_price[symbol] = float(bar.close)
            return [SignalEvent(bar.timestamp, symbol, Direction.SHORT)]

        if symbol in self._prev_held:
            return [SignalEvent(bar.timestamp, symbol, Direction.FLAT)]

        return []

    def _rebalance(self, as_of: date) -> None:
        scores = self._signal_fn(as_of)
        if not scores:
            logger.warning(
                "rebalance_skipped_empty_signal",
                as_of=as_of.isoformat(),
                held=len(self._current_longs | self._current_shorts),
            )
            return

        self._prev_held = self._current_longs | self._current_shorts

        ranked = sorted(scores, key=scores.__getitem__, reverse=True)
        n_long = min(max(1, round(len(ranked) * self._q_long)), self._max_positions)
        self._current_longs = set(ranked[:n_long])

        if self._long_only:
            self._current_shorts = set()
            self._short_entry_price.clear()
            return

        regime_ok = self._regime_fn(as_of) if self._regime_fn else True

        if not regime_ok:
            # High-vol regime: close all shorts, open no new ones
            if self._current_shorts:
                logger.warning(
                    "shorts_closed_regime_hostile",
                    as_of=as_of.isoformat(),
                    count=len(self._current_shorts),
                )
            self._current_shorts = set()
            self._short_entry_price.clear()
            return

        # Low-vol regime: build short book from stricter short universe
        short_scores = self._short_signal_fn(as_of)
        if short_scores:
            short_ranked = sorted(short_scores, key=short_scores.__getitem__)  # ascending = worst
            n_short = min(max(1, round(len(short_ranked) * self._q_short)), self._max_positions)
            new_shorts = set(short_ranked[:n_short]) - self._current_longs
        else:
            new_shorts = set()

        # Clean up entry prices for shorts that are being exited
        exited = self._current_shorts - new_shorts
        for sym in exited:
            self._short_entry_price.pop(sym, None)

        self._current_shorts = new_shorts
