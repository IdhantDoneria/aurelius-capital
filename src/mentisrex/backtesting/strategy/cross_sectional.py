"""CrossSectionalFactorStrategy — monthly-rebalancing cross-sectional factor strategy.

On each rebalance date, calls a user-supplied signal function to get
{security_id: score} cross-sections, ranks them, and goes long top-N
/ short bottom-N. Between rebalances, holds positions unchanged.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from mentisrex.backtesting.events.types import Direction, SignalEvent
from mentisrex.backtesting.strategy.base import Strategy, StrategyContext
from mentisrex.core.logging import get_logger

logger = get_logger(__name__)

# How to decide "first bar of a new period" by freq
_PERIOD_KEY: dict[str, Callable[[date], tuple]] = {
    "daily":   lambda d: (d.year, d.month, d.day),
    "weekly":  lambda d: (d.isocalendar().year, d.isocalendar().week),
    "monthly": lambda d: (d.year, d.month),
}


class CrossSectionalFactorStrategy(Strategy):
    """Monthly-rebalancing cross-sectional factor strategy.

    signal_fn(as_of: date) -> dict[str, float]
        Called at each rebalance. Returns raw scores (higher = better).
        Return {} to skip rebalance and hold current positions.

    Percentile-ranks the scores, goes long top q_long fraction,
    short bottom q_short fraction (unless long_only=True).
    Between rebalances: returns [] (holds unchanged).
    """

    name = "cross_sectional_factor"

    def __init__(
        self,
        signal_fn: Callable[[date], dict[str, float]],
        rebalance_freq: str = "monthly",   # "monthly" | "weekly" | "daily"
        q_long: float = 0.2,
        q_short: float = 0.2,
        long_only: bool = True,
        max_positions: int = 50,
    ) -> None:
        if rebalance_freq not in _PERIOD_KEY:
            raise ValueError(f"rebalance_freq must be one of {list(_PERIOD_KEY)}")
        self._signal_fn = signal_fn
        self._freq = rebalance_freq
        self._q_long = q_long
        self._q_short = q_short
        self._long_only = long_only
        self._max_positions = max_positions

        self._last_rebalance_period: tuple | None = None
        self._rebalance_date: date | None = None   # only emit signals on this date
        self._current_longs: set[str] = set()
        self._current_shorts: set[str] = set()
        self._prev_held: set[str] = set()   # symbols held last period (to emit FLAT)

    @property
    def parameters(self) -> dict:
        return {
            "rebalance_freq": self._freq,
            "q_long": self._q_long,
            "q_short": self._q_short,
            "long_only": self._long_only,
            "max_positions": self._max_positions,
        }

    def on_bar(self, ctx: StrategyContext, bar) -> list[SignalEvent]:
        bar_date = bar.timestamp.date()
        period = _PERIOD_KEY[self._freq](bar_date)

        if period != self._last_rebalance_period:
            self._rebalance(bar_date)
            self._last_rebalance_period = period
            self._rebalance_date = bar_date

        # Only emit entry/exit signals on the first bar of the rebalance period.
        # Between rebalances return [] — the engine holds existing positions unchanged.
        # Emitting LONG every bar would re-order on every bar, causing ~20x trade count.
        if bar_date != self._rebalance_date:
            return []

        symbol = bar.symbol
        if symbol in self._current_longs:
            return [SignalEvent(bar.timestamp, symbol, Direction.LONG)]
        if symbol in self._current_shorts:
            return [SignalEvent(bar.timestamp, symbol, Direction.SHORT)]
        # Emit FLAT only for symbols we previously held (exit signal)
        if symbol in self._prev_held:
            return [SignalEvent(bar.timestamp, symbol, Direction.FLAT)]
        return []

    def _rebalance(self, as_of: date) -> None:
        scores = self._signal_fn(as_of)
        if not scores:
            logger.warning("rebalance_skipped_empty_signal", as_of=as_of.isoformat(),
                           held=len(self._current_longs | self._current_shorts))
            return  # hold current positions; previously held remain open

        # Track what was held so we can send FLAT for exits
        self._prev_held = self._current_longs | self._current_shorts

        ranked = sorted(scores, key=scores.__getitem__, reverse=True)
        n = min(len(ranked), self._max_positions * 2)  # cap universe considered
        ranked = ranked[:n] if n < len(ranked) else ranked

        n_long = max(1, round(len(ranked) * self._q_long))
        n_long = min(n_long, self._max_positions)
        self._current_longs = set(ranked[:n_long])

        if self._long_only:
            self._current_shorts = set()
        else:
            n_short = max(1, round(len(ranked) * self._q_short))
            n_short = min(n_short, self._max_positions)
            self._current_shorts = set(ranked[-n_short:]) - self._current_longs
