"""DataFeed — the only source of market data during a backtest.

No component other than the BacktestEngine may call DataFeed.
Strategies access history only through StrategyContext.

InMemoryDataFeed: for tests and small backtests. Holds all bars in RAM.
DuckDBDataFeed: production — reads from the DuckDB analytical store.

DataFeed.iter_bars() emits BarData in strict ascending timestamp order.
If data contains multiple symbols interleaved, bars are sorted globally.
This models "tape order" — as if you're reading a consolidated feed.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BarData:
    """Raw bar from the data feed. Immutable."""

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    frequency: str = "1d"
    vwap: Decimal | None = None


class DataFeed(ABC):
    """Abstract market data source for the backtester."""

    @abstractmethod
    def iter_bars(self) -> Iterator[BarData]:
        """Yield bars in ascending timestamp order. Each bar is the 'current bar'."""
        ...

    @abstractmethod
    def symbols(self) -> list[str]:
        """All symbols in this feed."""
        ...


class InMemoryDataFeed(DataFeed):
    """Holds all bars in memory. Used for tests and small research runs.

    Pass bars in any order — they're sorted at construction time.
    """

    def __init__(
        self,
        bars: list[BarData],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> None:
        filtered = bars
        if start_date:
            filtered = [b for b in filtered if b.timestamp.date() >= start_date]
        if end_date:
            filtered = [b for b in filtered if b.timestamp.date() <= end_date]
        # Chronological sort — deterministic given identical input
        self._bars = sorted(filtered, key=lambda b: (b.timestamp, b.symbol))
        self._symbols = sorted({b.symbol for b in self._bars})

    def iter_bars(self) -> Iterator[BarData]:
        yield from self._bars

    def symbols(self) -> list[str]:
        return self._symbols


def _resolve_connection(db_path: str, *, read_only: bool = False):
    """Return a (connection, parquet_mode) tuple.

    1. .duckdb exists  → file connection (caller must close)
    2. Parquet exists  → in-memory connection with ohlcv view (persistent, don't close)
    3. Neither         → FileNotFoundError

    read_only=True allows concurrent connections to the same file without lock
    contention — always use this for signal functions that run alongside a feed.
    """
    import duckdb

    if Path(db_path).exists():
        return duckdb.connect(db_path, read_only=read_only), False

    stem = Path(db_path).stem
    for candidate in (
        Path(db_path).parent / "parquet" / stem / "ohlcv.parquet",
        Path("data/parquet") / stem / "ohlcv.parquet",
    ):
        if candidate.exists():
            conn = duckdb.connect(":memory:")
            conn.execute(f"CREATE VIEW ohlcv AS SELECT * FROM read_parquet('{candidate}')")
            return conn, True

    raise FileNotFoundError(
        f"Neither '{db_path}' nor a Parquet fallback at data/parquet/{stem}/ohlcv.parquet "
        "was found. Run the ingest pipeline or export_parquet() first."
    )


class DuckDBDataFeed(DataFeed):
    """Reads OHLCV bars from the DuckDB analytical store.

    Streams in chronological order without loading all data into RAM.
    Suitable for multi-year, multi-thousand-symbol backtests.

    Parquet fallback: if the .duckdb file is missing but
    data/parquet/{stem}/ohlcv.parquet exists, opens an in-memory DuckDB
    with a view over that Parquet file. The in-memory connection is kept
    alive for the feed's lifetime and closed on __del__.
    """

    def __init__(
        self,
        db_path: str,
        symbols: list[str] | None = None,
        frequency: str = "1d",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> None:
        self._db_path = db_path
        self._symbol_filter = symbols
        self._frequency = frequency
        self._start = start_date
        self._end = end_date

        # Establish connection early so Parquet mode works across calls.
        # For file-based mode, _parquet_conn stays None and we open per call.
        conn, parquet_mode = _resolve_connection(db_path)
        if parquet_mode:
            self._parquet_conn = conn  # keep alive
        else:
            conn.close()  # file-based: open fresh per call
            self._parquet_conn = None

    def __del__(self) -> None:
        if self._parquet_conn is not None:
            try:
                self._parquet_conn.close()
            except Exception:
                pass

    def _get_conn(self):
        """Return (conn, owned) — owned=True means caller must close it."""
        if self._parquet_conn is not None:
            return self._parquet_conn, False
        import duckdb

        # read_only=True allows concurrent signal functions to open the same file
        return duckdb.connect(self._db_path, read_only=True), True

    def symbols(self) -> list[str]:
        where = self._where_clause()
        conn, owned = self._get_conn()
        try:
            rows = conn.execute(
                f"SELECT DISTINCT symbol FROM ohlcv {where} ORDER BY symbol",
                self._params(),
            ).fetchall()
        finally:
            if owned:
                conn.close()
        return [r[0] for r in rows]

    def iter_bars(self) -> Iterator[BarData]:
        where = self._where_clause()
        # Multiply OHLC by adjustment_factor so backtests see split/dividend-adjusted
        # prices. Volume is divided by adjustment_factor (split-adjusted share count).
        # adjustment_factor defaults to 1.0 for unadjusted data, so this is a no-op
        # when no corporate actions exist.
        sql = (
            f"SELECT symbol, timestamp, frequency, "
            f"open * adjustment_factor, high * adjustment_factor, "
            f"low * adjustment_factor, close * adjustment_factor, "
            f"volume / NULLIF(adjustment_factor, 0), vwap "
            f"FROM ohlcv {where} ORDER BY timestamp, symbol"
        )
        conn, owned = self._get_conn()
        try:
            result = conn.execute(sql, self._params())
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
        finally:
            if owned:
                conn.close()

    def _where_clause(self) -> str:
        parts = ["frequency = ?"]
        if self._symbol_filter:
            placeholders = ",".join("?" * len(self._symbol_filter))
            parts.append(f"symbol IN ({placeholders})")
        if self._start:
            parts.append("CAST(timestamp AS DATE) >= ?")
        if self._end:
            parts.append("CAST(timestamp AS DATE) <= ?")
        return f"WHERE {' AND '.join(parts)}"

    def _params(self) -> list:
        p: list = [self._frequency]
        if self._symbol_filter:
            p.extend(self._symbol_filter)
        if self._start:
            p.append(self._start.isoformat())
        if self._end:
            p.append(self._end.isoformat())
        return p
