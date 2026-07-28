"""Tests for DuckDBDataFeed — production data feed path at 44% coverage.

InMemoryDataFeed is already exercised via engine tests. DuckDBDataFeed
(the production path) has zero tests. We use an in-memory DuckDB store
to avoid real disk I/O.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aurelius.backtesting.data.feed import BarData, DuckDBDataFeed, InMemoryDataFeed


# ── InMemoryDataFeed edge cases ───────────────────────────────────────────────


@pytest.mark.unit
def test_in_memory_empty_feed_no_bars():
    feed = InMemoryDataFeed([])
    assert list(feed.iter_bars()) == []
    assert feed.symbols() == []


@pytest.mark.unit
def test_in_memory_date_filter_start():
    def _b(day: int) -> BarData:
        return BarData(
            "AAPL",
            datetime(2024, 1, day, tzinfo=UTC),
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            Decimal("1e6"),
        )

    bars = [_b(1), _b(5), _b(10), _b(15)]
    feed = InMemoryDataFeed(bars, start_date=date(2024, 1, 5))
    emitted = list(feed.iter_bars())
    assert len(emitted) == 3
    assert all(b.timestamp.day >= 5 for b in emitted)


@pytest.mark.unit
def test_in_memory_date_filter_end():
    def _b(day: int) -> BarData:
        return BarData(
            "AAPL",
            datetime(2024, 1, day, tzinfo=UTC),
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            Decimal("1e6"),
        )

    bars = [_b(1), _b(5), _b(10), _b(15)]
    feed = InMemoryDataFeed(bars, end_date=date(2024, 1, 10))
    emitted = list(feed.iter_bars())
    assert len(emitted) == 3
    assert all(b.timestamp.day <= 10 for b in emitted)


@pytest.mark.unit
def test_in_memory_date_filter_start_and_end():
    def _b(day: int) -> BarData:
        return BarData(
            "AAPL",
            datetime(2024, 1, day, tzinfo=UTC),
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            Decimal("1e6"),
        )

    bars = [_b(1), _b(5), _b(10), _b(15)]
    feed = InMemoryDataFeed(bars, start_date=date(2024, 1, 5), end_date=date(2024, 1, 10))
    emitted = list(feed.iter_bars())
    assert len(emitted) == 2
    assert {b.timestamp.day for b in emitted} == {5, 10}


@pytest.mark.unit
def test_in_memory_symbols_deduped():
    def _b(sym: str, day: int) -> BarData:
        return BarData(
            sym,
            datetime(2024, 1, day, tzinfo=UTC),
            Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1e6"),
        )

    bars = [_b("AAPL", 1), _b("AAPL", 2), _b("MSFT", 1), _b("MSFT", 2)]
    feed = InMemoryDataFeed(bars)
    assert sorted(feed.symbols()) == ["AAPL", "MSFT"]


@pytest.mark.unit
def test_in_memory_date_filter_excludes_all():
    def _b(day: int) -> BarData:
        return BarData(
            "AAPL",
            datetime(2024, 1, day, tzinfo=UTC),
            Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1e6"),
        )

    bars = [_b(1), _b(2), _b(3)]
    feed = InMemoryDataFeed(bars, start_date=date(2025, 1, 1))
    assert list(feed.iter_bars()) == []
    assert feed.symbols() == []


# ── DuckDBDataFeed ────────────────────────────────────────────────────────────


def _setup_duckdb(db_path: str = ":memory:") -> object:
    """Create an in-memory DuckDB with the ohlcv schema and sample data."""
    import duckdb

    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol VARCHAR,
            timestamp TIMESTAMP WITH TIME ZONE,
            frequency VARCHAR,
            open DECIMAL(18,8),
            high DECIMAL(18,8),
            low DECIMAL(18,8),
            close DECIMAL(18,8),
            volume DECIMAL(18,4),
            vwap DECIMAL(18,8)
        )
    """)
    return conn


_CREATE_OHLCV = """
    CREATE TABLE ohlcv (
        symbol VARCHAR, timestamp TIMESTAMPTZ, frequency VARCHAR,
        open DECIMAL, high DECIMAL, low DECIMAL, close DECIMAL,
        volume DECIMAL, vwap DECIMAL, adjustment_factor DECIMAL DEFAULT 1.0
    )
"""


@pytest.mark.unit
def test_duckdb_feed_iter_bars(tmp_path):
    import duckdb

    db = str(tmp_path / "test.db")
    conn = duckdb.connect(db)
    conn.execute(_CREATE_OHLCV)
    conn.execute("""
        INSERT INTO ohlcv (symbol, timestamp, frequency, open, high, low, close, volume, vwap) VALUES
        ('AAPL', '2024-01-01 00:00:00+00', '1d', 184, 186, 183, 185, 1000000, NULL),
        ('AAPL', '2024-01-02 00:00:00+00', '1d', 185, 187, 184, 186, 1100000, NULL),
        ('MSFT', '2024-01-01 00:00:00+00', '1d', 370, 375, 368, 372, 500000, NULL)
    """)
    conn.close()

    feed = DuckDBDataFeed(db_path=db, frequency="1d")
    bars = list(feed.iter_bars())
    assert len(bars) == 3
    assert all(isinstance(b, BarData) for b in bars)
    # All bars must be in chronological order
    timestamps = [b.timestamp for b in bars]
    assert timestamps == sorted(timestamps)


@pytest.mark.unit
def test_duckdb_feed_symbol_filter(tmp_path):
    import duckdb

    db = str(tmp_path / "test.db")
    conn = duckdb.connect(db)
    conn.execute(_CREATE_OHLCV)
    conn.execute("""
        INSERT INTO ohlcv (symbol, timestamp, frequency, open, high, low, close, volume, vwap) VALUES
        ('AAPL', '2024-01-01 00:00:00+00', '1d', 184, 186, 183, 185, 1000000, NULL),
        ('MSFT', '2024-01-01 00:00:00+00', '1d', 370, 375, 368, 372, 500000, NULL),
        ('GOOG', '2024-01-01 00:00:00+00', '1d', 140, 142, 138, 141, 800000, NULL)
    """)
    conn.close()

    feed = DuckDBDataFeed(db_path=db, symbols=["AAPL", "MSFT"], frequency="1d")
    bars = list(feed.iter_bars())
    symbols_seen = {b.symbol for b in bars}
    assert symbols_seen == {"AAPL", "MSFT"}
    assert "GOOG" not in symbols_seen


@pytest.mark.unit
def test_duckdb_feed_date_range_filter(tmp_path):
    import duckdb

    db = str(tmp_path / "test.db")
    conn = duckdb.connect(db)
    conn.execute(_CREATE_OHLCV)
    conn.execute("""
        INSERT INTO ohlcv (symbol, timestamp, frequency, open, high, low, close, volume, vwap) VALUES
        ('AAPL', '2024-01-01 00:00:00+00', '1d', 184, 186, 183, 185, 1000000, NULL),
        ('AAPL', '2024-01-10 00:00:00+00', '1d', 185, 187, 184, 186, 1100000, NULL),
        ('AAPL', '2024-01-20 00:00:00+00', '1d', 186, 188, 185, 187, 1200000, NULL)
    """)
    conn.close()

    feed = DuckDBDataFeed(
        db_path=db,
        frequency="1d",
        start_date=date(2024, 1, 5),
        end_date=date(2024, 1, 15),
    )
    bars = list(feed.iter_bars())
    assert len(bars) == 1
    assert bars[0].timestamp.day == 10


@pytest.mark.unit
def test_duckdb_feed_symbols_method(tmp_path):
    import duckdb

    db = str(tmp_path / "test.db")
    conn = duckdb.connect(db)
    conn.execute(_CREATE_OHLCV)
    conn.execute("""
        INSERT INTO ohlcv (symbol, timestamp, frequency, open, high, low, close, volume, vwap) VALUES
        ('AAPL', '2024-01-01 00:00:00+00', '1d', 184, 186, 183, 185, 1000000, NULL),
        ('MSFT', '2024-01-01 00:00:00+00', '1d', 370, 375, 368, 372, 500000, NULL)
    """)
    conn.close()

    feed = DuckDBDataFeed(db_path=db, frequency="1d")
    syms = feed.symbols()
    assert sorted(syms) == ["AAPL", "MSFT"]


@pytest.mark.unit
def test_duckdb_feed_vwap_null_handled(tmp_path):
    import duckdb

    db = str(tmp_path / "test.db")
    conn = duckdb.connect(db)
    conn.execute(_CREATE_OHLCV)
    conn.execute(
        "INSERT INTO ohlcv (symbol, timestamp, frequency, open, high, low, close, volume, vwap) "
        "VALUES ('AAPL', '2024-01-01 00:00:00+00', '1d', 184, 186, 183, 185, 1000000, NULL)"
    )
    conn.close()

    feed = DuckDBDataFeed(db_path=db, frequency="1d")
    bars = list(feed.iter_bars())
    assert bars[0].vwap is None
