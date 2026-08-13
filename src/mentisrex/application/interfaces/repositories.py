"""Abstract repository interfaces.

Domain and application layers depend on these abstractions.
Infrastructure layer implements them concretely.
This is the Dependency Inversion Principle in action.
"""

from abc import ABC, abstractmethod

from mentisrex.domain.entities.market import OHLCV, Symbol, TimeRange


class MarketDataRepository(ABC):
    """Persistence contract for market data."""

    @abstractmethod
    async def save_ohlcv(self, bar: OHLCV) -> None:
        """Persist a single OHLCV bar."""
        ...

    @abstractmethod
    async def save_ohlcv_batch(self, bars: list[OHLCV]) -> int:
        """Persist a batch of bars. Returns count saved."""
        ...

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: Symbol,
        time_range: TimeRange,
    ) -> list[OHLCV]:
        """Fetch OHLCV bars for a symbol within a time range."""
        ...

    @abstractmethod
    async def get_latest_bar(self, symbol: Symbol) -> OHLCV | None:
        """Return the most recent bar for a symbol, or None."""
        ...

    @abstractmethod
    async def symbol_exists(self, symbol: Symbol) -> bool:
        """Return True if any data exists for this symbol."""
        ...
