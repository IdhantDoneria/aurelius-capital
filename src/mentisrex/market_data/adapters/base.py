"""Abstract adapter interface and shared RawBar dataclass.

Every data source (Alpaca, Yahoo Finance, CSV, WebSocket) implements
MarketDataAdapter and yields RawBar instances. The pipeline never touches
source-specific types beyond this boundary.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RawBar:
    """Unvalidated bar from any data source.

    All timestamps must be UTC-aware before entering the pipeline.
    Values are Decimal to avoid float rounding — convert at the adapter boundary.
    """

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    frequency: str = "1d"
    vwap: Decimal | None = None
    trade_count: int | None = None
    source: str = "unknown"


class MarketDataAdapter(ABC):
    """One implementation per data source."""

    name: str = "base"

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[RawBar]:
        """Fetch historical OHLCV bars for a single symbol."""
        ...

    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[RawBar]:
        """Stream real-time bars. Override in adapters that support streaming."""
        raise NotImplementedError(f"{self.name} does not support real-time streaming")
        yield  # pragma: no cover — makes return type AsyncIterator[RawBar]
