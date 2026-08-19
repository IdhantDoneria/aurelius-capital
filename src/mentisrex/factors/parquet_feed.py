"""ParquetDataFeed — DataFeed backed by a Parquet file instead of .duckdb.

Use when analytics.duckdb has been deleted but the Parquet export at
data/parquet/analytics/ohlcv.parquet still exists.

Uses in-memory DuckDB + read_parquet() — no new dependencies.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import duckdb

from mentisrex.backtesting.data.feed import BarData, DataFeed


class ParquetDataFeed(DataFeed):
    """Reads OHLCV bars from a Parquet file via in-memory DuckDB.

    parquet_path   path to ohlcv.parquet (e.g. data/parquet/analytics/ohlcv.parquet)
    symbols        optional symbol filter; None = all symbols
    frequency      bar frequency to filter on (default '1d')
    start_date     inclusive lower bound on bar date
    end_date       inclusive upper bound on bar date
    """

    def __init__(
        self,
        parquet_path: str,
        symbols: list[str] | None = None,
        frequency: str = "1d",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> None:
        self._path = parquet_path
        self._symbol_filter = symbols
        self._frequency = frequency
        self._start = start_date
        self._end = end_date

    def symbols(self) -> list[str]:
        where, params = self._where()
        with duckdb.connect(":memory:") as conn:
            rows = conn.execute(
                f"SELECT DISTINCT symbol FROM read_parquet(?) {where} ORDER BY symbol",
                [self._path, *params],
            ).fetchall()
        return [r[0] for r in rows]

    def iter_bars(self) -> Iterator[BarData]:
        where, params = self._where()
        sql = (
            f"SELECT symbol, timestamp, frequency, "
            f"open * adjustment_factor, high * adjustment_factor, "
            f"low * adjustment_factor, close * adjustment_factor, "
            f"volume / adjustment_factor, vwap "
            f"FROM read_parquet(?) {where} ORDER BY timestamp, symbol"
        )
        with duckdb.connect(":memory:") as conn:
            result = conn.execute(sql, [self._path, *params])
            while True:
                row = result.fetchone()
                if row is None:
                    break
                yield BarData(
                    symbol=row[0],
                    timestamp=row[1],
                    frequency=row[2],
                    open=Decimal(str(row[3])),
                    high=Decimal(str(row[4])),
                    low=Decimal(str(row[5])),
                    close=Decimal(str(row[6])),
                    volume=Decimal(str(row[7])),
                    vwap=Decimal(str(row[8])) if row[8] is not None else None,
                )

    def _where(self) -> tuple[str, list]:
        parts = ["frequency = ?"]
        params: list = [self._frequency]
        if self._symbol_filter:
            placeholders = ",".join("?" * len(self._symbol_filter))
            parts.append(f"symbol IN ({placeholders})")
            params.extend(self._symbol_filter)
        if self._start:
            parts.append("CAST(timestamp AS DATE) >= ?")
            params.append(self._start.isoformat())
        if self._end:
            parts.append("CAST(timestamp AS DATE) <= ?")
            params.append(self._end.isoformat())
        return f"WHERE {' AND '.join(parts)}", params
