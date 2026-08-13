"""Ingestion pipeline: normalize → resolve symbols → validate → store.

IngestionPipeline.run() is the core hot path. It takes raw bars from any adapter,
applies all normalization and validation, and bulk-inserts into PostgreSQL.

Failure handling:
  - Network / DB errors on a batch: logged, rejected count incremented, run continues.
  - Validation failures: per-bar, collected in IngestionReport.rejection_reasons.
  - Unknown symbols: skipped with warning; ingest of symbol data before symbol record
    exists will silently drop those bars.
  - The DB's ON CONFLICT DO NOTHING is the final dedup gate — no in-memory set needed.

Corrupted data detection:
  - OHLCVBatchValidator enforces: positive prices, OHLC relationship, UTC timestamps.
  - Gap detection flags missing bars (e.g., vendor outage) per symbol.
  - quality_score is computed per bar and stored; downstream can filter by score.

Quality measurement:
  - compute_quality_score() returns 0-100 per bar (deducts for missing vwap, zero volume,
    large price moves).
  - IngestionReport.avg_quality_score is the batch mean.
  - Bars with quality_score < 60 are flagged but still stored — research decides cutoff.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from time import monotonic
from uuid import UUID

from sqlalchemy import select

from mentisrex.core.logging import get_logger
from mentisrex.infrastructure.database.connection import DatabaseManager
from mentisrex.infrastructure.database.models.reference import Symbol
from mentisrex.infrastructure.database.repositories.market import OHLCVRepository
from mentisrex.infrastructure.database.validation.market import OHLCVBatchValidator
from mentisrex.market_data.adapters.base import RawBar
from mentisrex.market_data.pipeline.normalizer import detect_gaps, normalize_bar

logger = get_logger(__name__)

_BATCH_SIZE = 5_000  # rows per INSERT statement — tuned for asyncpg throughput


@dataclass
class IngestionReport:
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    skipped_symbols: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    gap_warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    avg_quality_score: float = 0.0

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.total if self.total else 0.0


class IngestionPipeline:
    """Stateless pipeline. One instance per source_id is typical."""

    def __init__(self, db: DatabaseManager, source_id: UUID) -> None:
        self._db = db
        self._source_id = source_id
        self._validator = OHLCVBatchValidator()

    async def _resolve_symbols(self, tickers: list[str]) -> dict[str, UUID]:
        """Single query to resolve all tickers to UUIDs. Skips unknown."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Symbol.ticker, Symbol.id).where(
                    Symbol.ticker.in_([t.upper() for t in tickers]),
                    Symbol.is_active.is_(True),
                )
            )
            return {row.ticker: row.id for row in result}

    def _to_db_dict(self, bar, quality_score: int) -> dict:
        return {
            "symbol_id": bar.symbol_id,
            "source_id": bar.source_id,
            "timestamp": bar.timestamp,
            "frequency": bar.frequency,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "vwap": bar.vwap,
            "trade_count": bar.trade_count,
            "quality_score": quality_score,
            "adjustment_factor": Decimal("1.0"),
        }

    async def run(
        self,
        bars: list[RawBar],
        on_conflict: str = "ignore",
    ) -> IngestionReport:
        """Full pipeline: normalize → resolve → validate → store.

        on_conflict='ignore': skip duplicates (safe for re-ingestion).
        on_conflict='update': overwrite with new data (use for corrections).
        """
        report = IngestionReport(total=len(bars))
        if not bars:
            return report

        t0 = monotonic()

        # 1. Normalize
        normalized = [normalize_bar(b) for b in bars]

        # 2. Resolve symbols in one DB round trip
        tickers = list({b.symbol for b in normalized})
        symbol_map = await self._resolve_symbols(tickers)

        missing = set(tickers) - set(symbol_map)
        if missing:
            report.skipped_symbols.extend(sorted(missing))
            logger.warning("symbols_not_in_db", missing=sorted(missing))

        known_bars = [b for b in normalized if b.symbol in symbol_map]

        # 3. Detect gaps per symbol — single grouping pass, then per-symbol scan.
        # Was O(symbols × total_bars): re-scanned all of known_bars once per ticker.
        # Now one pass to bucket by symbol, then sort+scan each bucket.
        bars_by_symbol: dict[str, list] = defaultdict(list)
        for b in known_bars:
            bars_by_symbol[b.symbol].append(b)
        for ticker in sorted(bars_by_symbol):
            sym_bars = sorted(bars_by_symbol[ticker], key=lambda b: b.timestamp)
            for gap_ts in detect_gaps(sym_bars):
                msg = f"{ticker}: gap detected after {gap_ts.date()}"
                report.gap_warnings.append(msg)
                logger.warning("data_gap", symbol=ticker, after=gap_ts.isoformat())

        # 4. Validate
        raw_dicts = [
            {
                "symbol_id": symbol_map[b.symbol],
                "source_id": self._source_id,
                "timestamp": b.timestamp,
                "frequency": b.frequency,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "vwap": b.vwap,
                "trade_count": b.trade_count,
            }
            for b in known_bars
        ]
        valid_bars, rejected = self._validator.validate_batch(raw_dicts)
        report.rejected += len(rejected)
        report.rejection_reasons.extend(
            r.get("validation_errors", "unknown") for r in rejected[:50]
        )

        # 5. Score quality and build DB dicts
        quality_scores: list[int] = []
        db_dicts: list[dict] = []
        for bar in valid_bars:
            score = bar.compute_quality_score()
            quality_scores.append(score)
            db_dicts.append(self._to_db_dict(bar, score))

        # 6. Bulk insert in batches — failure on one batch doesn't abort the run
        inserted = 0
        for i in range(0, len(db_dicts), _BATCH_SIZE):
            chunk = db_dicts[i : i + _BATCH_SIZE]
            async with self._db.session() as session:
                repo = OHLCVRepository(session)
                try:
                    inserted += await repo.bulk_insert(chunk, on_conflict=on_conflict)
                except Exception as exc:
                    logger.error("batch_insert_failed", batch_start=i, error=str(exc))
                    report.rejected += len(chunk)
                    report.rejection_reasons.append(f"DB error (batch {i}): {exc}")

        report.accepted = inserted
        report.duration_seconds = monotonic() - t0
        report.avg_quality_score = (
            sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        )

        logger.info(
            "ingestion_complete",
            total=report.total,
            accepted=report.accepted,
            rejected=report.rejected,
            skipped_symbols=len(report.skipped_symbols),
            gap_warnings=len(report.gap_warnings),
            duration_s=round(report.duration_seconds, 3),
            avg_quality=round(report.avg_quality_score, 1),
        )
        return report
