"""Strategy interface and StrategyContext.

Strategy.on_bar() is the ONLY point where strategy code executes.
It receives a StrategyContext (read-only view of the world) and a MarketEvent.
It returns a list of SignalEvents — one per instrument the strategy wants to trade.

StrategyContext enforces the no-look-ahead contract:
  context.history(symbol) returns only bars with timestamp ≤ current bar's timestamp.
  context.portfolio is a read-only view of current portfolio state.
  context.now is the current simulation timestamp.

Strategy implementations must NOT:
  - Store references to StrategyContext between calls (stale data).
  - Access external data sources.
  - Import the DataFeed directly.
  - Use datetime.now() — use context.now.

Example — minimal SMA crossover:

    class SMACross(Strategy):
        name = "sma_cross"
        def __init__(self, fast: int = 10, slow: int = 50):
            self.fast, self.slow = fast, slow
        def on_bar(self, ctx, bar):
            h = ctx.history(bar.symbol, self.slow + 1)
            if len(h) < self.slow:
                return []
            closes = [x.close for x in h]
            if sum(closes[-self.fast:]) / self.fast > sum(closes) / self.slow:
                return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG)]
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
"""

from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from decimal import Decimal

from mentisrex.backtesting.events.types import MarketEvent, SignalEvent
from mentisrex.backtesting.portfolio.state import PortfolioState


class StrategyContext:
    """What a strategy is allowed to see. Enforces temporal isolation."""

    def __init__(
        self,
        history: dict[str, deque],
        portfolio: PortfolioState,
        now: datetime,
        max_bars: int,
    ) -> None:
        self._history = history
        self._portfolio = portfolio
        self._now = now
        self._max_bars = max_bars

    def history(self, symbol: str, lookback: int | None = None) -> list[MarketEvent]:
        """Return historical bars for symbol up to current time.

        lookback: if provided, return at most the last N bars.
        Never returns more than max_history_bars (configured at engine level).
        """
        bars = list(self._history.get(symbol, []))
        if lookback is not None:
            bars = bars[-lookback:]
        return bars

    def close_series(self, symbol: str, lookback: int | None = None) -> list[Decimal]:
        """Convenience: just the close prices."""
        return [b.close for b in self.history(symbol, lookback)]

    @property
    def portfolio(self) -> PortfolioState:
        """Read-only access to current portfolio state."""
        return self._portfolio

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def symbols_with_data(self) -> list[str]:
        return [s for s, h in self._history.items() if h]


class Strategy(ABC):
    """Base class for all backtesting strategies.

    Subclass this. Override on_bar(). Return SignalEvents.
    Do not override __init__ without calling super().__init__().
    """

    name: str = "base_strategy"

    @abstractmethod
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        """Called once per bar per symbol in the universe.

        Must be pure: no side effects, no state mutation outside self.
        Any state (moving averages, etc.) should be derived from context.history().
        """
        ...

    @property
    def parameters(self) -> dict:
        """Strategy parameters for experiment tracking and reporting."""
        return {}

    def on_start(self, context: StrategyContext) -> None:  # noqa: B027
        """Called once before the backtest begins. Override for initialization."""

    def on_end(self, context: StrategyContext) -> None:  # noqa: B027
        """Called once after the last bar. Override for cleanup or final signals."""
