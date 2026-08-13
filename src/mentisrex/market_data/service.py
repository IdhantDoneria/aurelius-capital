"""IngestionService — top-level facade for the market data pipeline.

Composes adapters, pipeline, and storage. Callers import only this class.

Usage:
    service = IngestionService(db=db_manager, source_id=alpaca_source_uuid)
    report = await service.ingest_historical(
        symbols=["AAPL", "MSFT"],
        start=date(2020, 1, 1),
        end=date(2024, 12, 31),
        adapter=AlpacaAdapter.from_settings(),
    )
    print(f"Ingested {report.accepted} bars, avg quality {report.avg_quality_score:.1f}")
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from mentisrex.core.logging import get_logger
from mentisrex.infrastructure.database.connection import DatabaseManager
from mentisrex.market_data.adapters.base import MarketDataAdapter, RawBar
from mentisrex.market_data.adapters.csv_loader import CSVLoader
from mentisrex.market_data.pipeline.ingestion import IngestionPipeline, IngestionReport
from mentisrex.market_data.storage.duckdb_store import DuckDBStore

logger = get_logger(__name__)


class IngestionService:
    def __init__(
        self,
        db: DatabaseManager,
        source_id: UUID,
        duckdb_store: DuckDBStore | None = None,
    ) -> None:
        self._pipeline = IngestionPipeline(db, source_id)
        self._duckdb = duckdb_store

    async def ingest_historical(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adapter: MarketDataAdapter,
        frequency: str = "1d",
        concurrency: int = 5,
        on_conflict: str = "ignore",
    ) -> IngestionReport:
        """Fetch and ingest historical OHLCV for multiple symbols.

        concurrency: max simultaneous adapter fetches (rate-limit-aware).
        """
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end, datetime.min.time(), tzinfo=UTC)
        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch(symbol: str) -> list[RawBar]:
            async with semaphore:
                try:
                    return await adapter.fetch_ohlcv(symbol, start_dt, end_dt, frequency)
                except Exception as exc:
                    logger.error(
                        "adapter_fetch_failed", symbol=symbol, adapter=adapter.name, error=str(exc)
                    )
                    return []

        results = await asyncio.gather(*[_fetch(s) for s in symbols])
        all_bars: list[RawBar] = [bar for result in results for bar in result]

        report = await self._pipeline.run(all_bars, on_conflict=on_conflict)
        self._maybe_sync_duckdb(all_bars)
        return report

    async def ingest_csv(
        self,
        file_path: Path,
        default_symbol: str | None = None,
        frequency: str = "1d",
        on_conflict: str = "ignore",
    ) -> IngestionReport:
        """Load and ingest OHLCV data from a CSV file."""
        bars = CSVLoader().load_file(file_path, default_symbol=default_symbol, frequency=frequency)
        report = await self._pipeline.run(bars, on_conflict=on_conflict)
        self._maybe_sync_duckdb(bars)
        return report

    async def start_realtime_stream(
        self,
        symbols: list[str],
        adapter: MarketDataAdapter,
        on_bar: Callable[[RawBar], Awaitable[None]] | None = None,
    ) -> None:
        """Stream real-time bars. Runs until cancelled.

        on_bar: optional callback per bar. Default: ingest each bar immediately.
        Wrap in asyncio.create_task() and cancel to stop streaming.
        """
        async for bar in adapter.stream_bars(symbols):
            if on_bar:
                await on_bar(bar)
            else:
                await self._pipeline.run([bar])

    def _maybe_sync_duckdb(self, bars: list[RawBar]) -> None:
        if not self._duckdb or not bars:
            return
        dicts = [
            {
                "symbol": b.symbol,
                "timestamp": b.timestamp,
                "frequency": b.frequency,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "vwap": b.vwap,
                "trade_count": b.trade_count,
                "quality_score": None,
                "source": b.source,
            }
            for b in bars
        ]
        try:
            self._duckdb.write_bars(dicts)
        except Exception as exc:
            logger.warning("duckdb_sync_failed", error=str(exc))
