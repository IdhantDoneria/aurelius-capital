"""Market data repository.

Key operations:
- Bulk OHLCV insert (thousands of bars per ingest cycle)
- Time-range queries with point-in-time correct adjustment factors
- Corporate action lookup for adjustment computation
- Symbol resolution (ticker → UUID)

Performance notes:
- Bulk insert uses INSERT ... ON CONFLICT DO NOTHING (upsert pattern)
  to safely re-run ingestion without duplicates.
- Time range queries always filter on (symbol_id, timestamp) to hit
  the composite index. Never query by timestamp alone on large tables.
- Adjustment factor queries join corporate_actions on ex_date — ensure
  that index is used by always filtering symbol_id first.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mentisrex.core.logging import get_logger
from mentisrex.infrastructure.database.models.market import (
    CorporateAction,
    MarketDataOHLCV,
)
from mentisrex.infrastructure.database.models.reference import Symbol
from mentisrex.infrastructure.database.repositories.base import BaseRepository

logger = get_logger(__name__)


class SymbolRepository(BaseRepository[Symbol]):
    model_class = Symbol

    async def get_by_ticker(self, ticker: str, exchange_mic: str | None = None) -> Symbol | None:
        """Look up symbol by ticker. Optionally filter by exchange MIC code."""
        query = select(Symbol).where(Symbol.ticker == ticker.upper())
        if exchange_mic:
            # Join to exchanges to filter by MIC — see reference.py for FK
            from mentisrex.infrastructure.database.models.reference import Exchange

            query = query.join(Exchange, Symbol.exchange_id == Exchange.id).where(
                Exchange.mic_code == exchange_mic
            )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_active_equity_universe(self) -> list[Symbol]:
        """Return all active equity symbols. Used to build research universe."""
        result = await self._session.execute(
            select(Symbol)
            .where(Symbol.is_active.is_(True))
            .where(Symbol.asset_class == "equity")
            .order_by(Symbol.ticker)
        )
        return list(result.scalars().all())

    async def bulk_upsert(self, symbols: list[dict]) -> int:
        """Upsert symbols. Returns count inserted (not updated)."""
        if not symbols:
            return 0
        stmt = pg_insert(Symbol).values(symbols)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_symbols_ticker_exchange",
            set_={
                "company_name": stmt.excluded.company_name,
                "sector": stmt.excluded.sector,
                "industry": stmt.excluded.industry,
                "is_active": stmt.excluded.is_active,
                "delisted_at": stmt.excluded.delisted_at,
                "updated_at": func.now(),
            },
        )
        result = await self._session.execute(stmt)
        return result.rowcount


class OHLCVRepository(BaseRepository[MarketDataOHLCV]):
    model_class = MarketDataOHLCV

    async def bulk_insert(
        self,
        bars: list[dict],
        on_conflict: str = "ignore",
    ) -> int:
        """Insert OHLCV bars in bulk. Optimized for ingest throughput.

        on_conflict='ignore': silently skip duplicates (safe for re-ingestion)
        on_conflict='update': overwrite with new data (use for corrections)

        Uses PostgreSQL's INSERT ... ON CONFLICT which is a single round trip.
        Much faster than checking existence then inserting row by row.
        """
        if not bars:
            return 0

        stmt = pg_insert(MarketDataOHLCV).values(bars)

        if on_conflict == "ignore":
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["symbol_id", "timestamp", "frequency", "source_id"]
            )
        elif on_conflict == "update":
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol_id", "timestamp", "frequency", "source_id"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "vwap": stmt.excluded.vwap,
                    "trade_count": stmt.excluded.trade_count,
                    "quality_score": stmt.excluded.quality_score,
                    "ingested_at": func.now(),
                },
            )

        result = await self._session.execute(stmt)
        logger.info("ohlcv_bulk_insert", rows=len(bars), affected=result.rowcount)
        return result.rowcount

    async def get_range(
        self,
        symbol_id: UUID,
        start: datetime,
        end: datetime,
        frequency: str = "1d",
        min_quality_score: int = 60,
        adjusted: bool = True,
    ) -> list[MarketDataOHLCV]:
        """Fetch OHLCV bars for a symbol in a time range.

        Always filters on (symbol_id, timestamp) to use the composite index.
        Quality score filter removes suspect data from research pipelines.
        """
        result = await self._session.execute(
            select(MarketDataOHLCV)
            .where(
                and_(
                    MarketDataOHLCV.symbol_id == symbol_id,
                    MarketDataOHLCV.timestamp >= start,
                    MarketDataOHLCV.timestamp < end,
                    MarketDataOHLCV.frequency == frequency,
                    MarketDataOHLCV.quality_score >= min_quality_score,
                )
            )
            .order_by(MarketDataOHLCV.timestamp.asc())
        )
        return list(result.scalars().all())

    async def get_latest(self, symbol_id: UUID, frequency: str = "1d") -> MarketDataOHLCV | None:
        """Return most recent bar for a symbol."""
        result = await self._session.execute(
            select(MarketDataOHLCV)
            .where(
                and_(
                    MarketDataOHLCV.symbol_id == symbol_id,
                    MarketDataOHLCV.frequency == frequency,
                )
            )
            .order_by(MarketDataOHLCV.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_cross_sectional(
        self,
        symbol_ids: list[UUID],
        timestamp: datetime,
        frequency: str = "1d",
    ) -> list[MarketDataOHLCV]:
        """Fetch one bar per symbol at a given timestamp.
        Used for cross-sectional factor computation.
        """
        result = await self._session.execute(
            select(MarketDataOHLCV).where(
                and_(
                    MarketDataOHLCV.symbol_id.in_(symbol_ids),
                    MarketDataOHLCV.timestamp == timestamp,
                    MarketDataOHLCV.frequency == frequency,
                )
            )
        )
        return list(result.scalars().all())

    async def update_adjustment_factors(
        self,
        symbol_id: UUID,
        before_date: datetime,
        factor: Decimal,
    ) -> int:
        """Apply corporate action adjustment to historical bars.

        Multiplies adjustment_factor for all bars before ex_date.
        Called when a new corporate action is confirmed.

        This is a bulk UPDATE — can affect millions of rows for large symbols.
        Run during off-hours or in a background job.
        """
        from sqlalchemy import update

        stmt = (
            update(MarketDataOHLCV)
            .where(
                and_(
                    MarketDataOHLCV.symbol_id == symbol_id,
                    MarketDataOHLCV.timestamp < before_date,
                )
            )
            .values(adjustment_factor=MarketDataOHLCV.adjustment_factor * factor)
        )
        result = await self._session.execute(stmt)
        count = result.rowcount
        logger.info(
            "adjustment_factors_updated",
            symbol_id=str(symbol_id),
            before_date=before_date.isoformat(),
            factor=str(factor),
            rows_updated=count,
        )
        return count

    async def get_data_coverage(self, symbol_id: UUID, frequency: str = "1d") -> dict:
        """Return data availability stats for a symbol."""
        result = await self._session.execute(
            select(
                func.count().label("bar_count"),
                func.min(MarketDataOHLCV.timestamp).label("earliest"),
                func.max(MarketDataOHLCV.timestamp).label("latest"),
                func.avg(MarketDataOHLCV.quality_score).label("avg_quality"),
            ).where(
                and_(
                    MarketDataOHLCV.symbol_id == symbol_id,
                    MarketDataOHLCV.frequency == frequency,
                )
            )
        )
        row = result.one()
        return {
            "symbol_id": str(symbol_id),
            "frequency": frequency,
            "bar_count": row.bar_count,
            "earliest": row.earliest,
            "latest": row.latest,
            "avg_quality_score": float(row.avg_quality) if row.avg_quality else None,
        }


class CorporateActionRepository(BaseRepository[CorporateAction]):
    model_class = CorporateAction

    async def get_actions_in_range(
        self,
        symbol_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[CorporateAction]:
        """Return all corporate actions with ex_date in range.
        Used to determine which adjustments apply to a backtest period.
        """
        result = await self._session.execute(
            select(CorporateAction)
            .where(
                and_(
                    CorporateAction.symbol_id == symbol_id,
                    CorporateAction.ex_date >= start,
                    CorporateAction.ex_date <= end,
                )
            )
            .order_by(CorporateAction.ex_date.asc())
        )
        return list(result.scalars().all())

    async def get_cumulative_adjustment_factor(
        self,
        symbol_id: UUID,
        as_of_date: datetime,
    ) -> Decimal:
        """Compute the cumulative price adjustment factor as of a date.

        Used for point-in-time correct price adjustment in backtesting.
        Returns 1.0 if no corporate actions found.
        """
        result = await self._session.execute(
            select(CorporateAction)
            .where(
                and_(
                    CorporateAction.symbol_id == symbol_id,
                    CorporateAction.ex_date <= as_of_date,
                    CorporateAction.action_type.in_(["split", "reverse_split"]),
                )
            )
            .order_by(CorporateAction.ex_date.asc())
        )
        actions = list(result.scalars().all())

        factor = Decimal("1.0")
        for action in actions:
            if action.ratio is not None:
                factor *= action.ratio
        return factor
