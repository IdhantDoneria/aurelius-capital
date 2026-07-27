"""Tests for DuckDBStore — use in-memory DuckDB, no file I/O."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aurelius.market_data.storage.duckdb_store import DuckDBStore


@pytest.fixture
def store() -> DuckDBStore:
    s = DuckDBStore(db_path=":memory:")
    yield s
    s.close()


def _bar_dict(
    symbol: str = "AAPL",
    ts: datetime | None = None,
    close: float = 185.0,
    quality: int = 90,
) -> dict:
    if ts is None:
        ts = datetime(2024, 1, 15, tzinfo=UTC)
    return {
        "symbol": symbol,
        "timestamp": ts,
        "frequency": "1d",
        "open": Decimal("184.00"),
        "high": Decimal("186.00"),
        "low": Decimal("183.00"),
        "close": Decimal(str(close)),
        "volume": Decimal("50000000"),
        "vwap": Decimal("185.20"),
        "trade_count": 120000,
        "quality_score": quality,
        "source": "test",
    }


@pytest.mark.unit
def test_write_and_query_bars(store: DuckDBStore):
    written = store.write_bars([_bar_dict()])
    assert written == 1

    rows = store.query("SELECT * FROM ohlcv")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


@pytest.mark.unit
def test_write_empty_batch(store: DuckDBStore):
    assert store.write_bars([]) == 0


@pytest.mark.unit
def test_upsert_overwrites_on_conflict(store: DuckDBStore):
    store.write_bars([_bar_dict(close=185.0)])
    store.write_bars([_bar_dict(close=190.0)])  # same PK

    rows = store.query("SELECT close FROM ohlcv WHERE symbol = 'AAPL'")
    assert len(rows) == 1
    assert float(rows[0]["close"]) == pytest.approx(190.0)


@pytest.mark.unit
def test_rolling_mean_returns_data(store: DuckDBStore):
    bars = [
        _bar_dict(ts=datetime(2024, 1, d, tzinfo=UTC), close=float(100 + d))
        for d in range(1, 6)
    ]
    store.write_bars(bars)

    result = store.rolling_mean("AAPL", window=3)
    assert len(result) == 5
    # First two rows can't have full window — check third
    assert result[2]["ma_3"] == pytest.approx((101 + 102 + 103) / 3)


@pytest.mark.unit
def test_cross_sectional_returns_latest_per_symbol(store: DuckDBStore):
    store.write_bars([
        _bar_dict("AAPL", datetime(2024, 1, 2, tzinfo=UTC), close=185.0),
        _bar_dict("AAPL", datetime(2024, 1, 3, tzinfo=UTC), close=186.0),
        _bar_dict("MSFT", datetime(2024, 1, 3, tzinfo=UTC), close=376.0),
    ])

    rows = store.cross_sectional(as_of=date(2024, 1, 3))
    symbols = {r["symbol"] for r in rows}
    assert symbols == {"AAPL", "MSFT"}

    aapl = next(r for r in rows if r["symbol"] == "AAPL")
    assert float(aapl["close"]) == pytest.approx(186.0)  # latest


@pytest.mark.unit
def test_cross_sectional_excludes_future_bars(store: DuckDBStore):
    store.write_bars([
        _bar_dict("AAPL", datetime(2024, 1, 2, tzinfo=UTC), close=185.0),
        _bar_dict("AAPL", datetime(2024, 1, 10, tzinfo=UTC), close=200.0),  # future
    ])

    rows = store.cross_sectional(as_of=date(2024, 1, 5))
    assert len(rows) == 1
    assert float(rows[0]["close"]) == pytest.approx(185.0)


@pytest.mark.unit
def test_quality_summary(store: DuckDBStore):
    store.write_bars([
        _bar_dict("AAPL", datetime(2024, 1, 2, tzinfo=UTC), quality=90),
        _bar_dict("AAPL", datetime(2024, 1, 3, tzinfo=UTC), quality=40),  # low quality
        _bar_dict("MSFT", datetime(2024, 1, 2, tzinfo=UTC), quality=95),
    ])

    summary = store.quality_summary()
    aapl = next(r for r in summary if r["symbol"] == "AAPL")
    assert aapl["bar_count"] == 2
    assert aapl["low_quality_bars"] == 1
    assert float(aapl["avg_quality"]) == pytest.approx(65.0)


@pytest.mark.unit
def test_query_with_params(store: DuckDBStore):
    store.write_bars([_bar_dict("AAPL"), _bar_dict("MSFT")])

    rows = store.query("SELECT symbol FROM ohlcv WHERE symbol = ?", ["AAPL"])
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
