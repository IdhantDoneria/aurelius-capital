"""DuckDB analytical store — fast read layer for research queries.

PostgreSQL is the authoritative store. DuckDB is the research-speed replica:
  - Rolling window calculations (20-day MA, 60-day volatility)
  - Cross-sectional factor sorts (all symbols at one date)
  - Parquet export for backtesting engines
  - Aggregations over millions of rows without touching PostgreSQL

Sync pattern: call write_bars() after each ingestion run to populate DuckDB.
For full historical sync, use sync_from_postgres() once (nightly job).

DuckDB file is local — not replicated. Loss is non-critical (rebuild from PostgreSQL).

In-memory mode (db_path=":memory:"): used in tests.
In-memory keeps a persistent connection to avoid losing the schema between calls.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger

logger = get_logger(__name__)

_CREATE_OHLCV = """
CREATE TABLE IF NOT EXISTS ohlcv (
    symbol             VARCHAR        NOT NULL,
    timestamp          TIMESTAMPTZ    NOT NULL,
    frequency          VARCHAR(10)    NOT NULL,
    open               DECIMAL(20,8)  NOT NULL,
    high               DECIMAL(20,8)  NOT NULL,
    low                DECIMAL(20,8)  NOT NULL,
    close              DECIMAL(20,8)  NOT NULL,
    volume             DECIMAL(28,4)  NOT NULL,
    vwap               DECIMAL(20,8),
    trade_count        INTEGER,
    quality_score      SMALLINT,
    source             VARCHAR(50),
    adjustment_factor  DECIMAL(16,8)  NOT NULL DEFAULT 1.0,
    PRIMARY KEY (symbol, timestamp, frequency)
)
"""


class DuckDBStore:
    """DuckDB-backed analytical store for OHLCV data."""

    def __init__(self, db_path: str = "./data/analytics.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None

        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            # In-memory: must reuse one connection or the schema disappears between calls
            self._persistent_conn = duckdb.connect(":memory:")

        with self._conn() as conn:
            conn.execute(_CREATE_OHLCV)

    @contextmanager
    def _conn(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        if self._in_memory and self._persistent_conn is not None:
            yield self._persistent_conn
        else:
            conn = duckdb.connect(self._path)
            try:
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        if self._persistent_conn:
            self._persistent_conn.close()
            self._persistent_conn = None

    def write_bars(self, bars: list[dict]) -> int:
        """Upsert bars into DuckDB. Overwrites on (symbol, timestamp, frequency) conflict."""
        if not bars:
            return 0
        rows = [
            (
                b["symbol"],
                b["timestamp"],
                b["frequency"],
                b["open"],
                b["high"],
                b["low"],
                b["close"],
                b["volume"],
                b.get("vwap"),
                b.get("trade_count"),
                b.get("quality_score"),
                b.get("source"),
                b.get("adjustment_factor", 1.0),
            )
            for b in bars
        ]
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO ohlcv
                    (symbol, timestamp, frequency, open, high, low, close, volume,
                     vwap, trade_count, quality_score, source, adjustment_factor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        logger.info("duckdb_write", bar_count=len(bars))
        return len(bars)

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """Execute arbitrary SQL and return rows as dicts."""
        with self._conn() as conn:
            result = conn.execute(sql, params or [])
            cols = [d[0] for d in result.description]
            return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]

    def rolling_mean(
        self,
        symbol: str,
        window: int = 20,
        frequency: str = "1d",
    ) -> list[dict]:
        """Rolling average close price over a window of bars."""
        return self.query(
            f"""
            SELECT symbol, timestamp, close,
                AVG(close) OVER (
                    PARTITION BY symbol
                    ORDER BY timestamp
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS ma_{window}
            FROM ohlcv
            WHERE symbol = ? AND frequency = ?
            ORDER BY timestamp
            """,
            [symbol, frequency],
        )

    def cross_sectional(self, as_of: date, frequency: str = "1d") -> list[dict]:
        """Latest bar per symbol on or before as_of. Used for factor construction."""
        return self.query(
            """
            SELECT DISTINCT ON (symbol)
                symbol, timestamp, open, high, low, close, volume, vwap, quality_score
            FROM ohlcv
            WHERE frequency = ? AND CAST(timestamp AS DATE) <= ?
            ORDER BY symbol, timestamp DESC
            """,
            [frequency, as_of.isoformat()],
        )

    def quality_summary(self) -> list[dict]:
        """Per-symbol data quality statistics. Flags symbols needing attention."""
        return self.query(
            """
            SELECT
                symbol,
                frequency,
                COUNT(*)                                              AS bar_count,
                MIN(timestamp)                                        AS earliest,
                MAX(timestamp)                                        AS latest,
                AVG(quality_score)                                    AS avg_quality,
                SUM(CASE WHEN quality_score < 60 THEN 1 ELSE 0 END)  AS low_quality_bars,
                SUM(CASE WHEN volume = 0          THEN 1 ELSE 0 END)  AS zero_volume_bars
            FROM ohlcv
            GROUP BY symbol, frequency
            ORDER BY avg_quality ASC
            """
        )

    def export_parquet(
        self,
        output_path: str,
        symbol: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> str:
        """Export filtered OHLCV data to Parquet for use by backtesting engines."""
        where_parts: list[str] = []
        params: list = []
        if symbol:
            where_parts.append("symbol = ?")
            params.append(symbol)
        if start:
            where_parts.append("CAST(timestamp AS DATE) >= ?")
            params.append(start.isoformat())
        if end:
            where_parts.append("CAST(timestamp AS DATE) <= ?")
            params.append(end.isoformat())

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        sql = f"SELECT * FROM ohlcv {where} ORDER BY symbol, timestamp"

        with self._conn() as conn:
            conn.execute(f"COPY ({sql}) TO '{output_path}' (FORMAT PARQUET)", params)

        logger.info("parquet_export", path=output_path, symbol=symbol)
        return output_path
