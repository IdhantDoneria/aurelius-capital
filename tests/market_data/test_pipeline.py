"""Tests for IngestionPipeline and IngestionReport.

DB is fully mocked — these are unit tests, not integration tests.
The pipeline's logic (normalize → resolve → validate → store) is tested
in isolation from PostgreSQL.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from mentisrex.market_data.adapters.base import RawBar
from mentisrex.market_data.pipeline.ingestion import IngestionPipeline, IngestionReport

_SOURCE_ID = uuid4()
_SYMBOL_ID = UUID("00000000-0000-0000-0000-000000000001")
_TICKER = "AAPL"


def _raw_bar(**kwargs) -> RawBar:
    defaults = {
        "symbol": "AAPL",
        "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
        "open": Decimal("185.00"),
        "high": Decimal("186.50"),
        "low": Decimal("184.00"),
        "close": Decimal("185.80"),
        "volume": Decimal("50000000"),
        "frequency": "1d",
        "source": "test",
    }
    return RawBar(**{**defaults, **kwargs})


def _make_pipeline() -> tuple[IngestionPipeline, MagicMock, AsyncMock]:
    """Return (pipeline, mock_db, mock_session)."""
    mock_session = AsyncMock()
    mock_db = MagicMock()

    # DatabaseManager.session() is an async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_db.session.return_value = cm

    pipeline = IngestionPipeline(db=mock_db, source_id=_SOURCE_ID)
    return pipeline, mock_db, mock_session


def _mock_symbol_result(ticker: str = _TICKER, sym_id: UUID = _SYMBOL_ID):
    """Mock the result of session.execute(select(Symbol.ticker, Symbol.id))."""
    row = SimpleNamespace(ticker=ticker, id=sym_id)
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter([row]))
    return result


def _mock_multi_symbol_result(tickers: list[str]):
    """Resolver mock returning several (ticker, id) rows."""
    rows = [SimpleNamespace(ticker=t, id=uuid4()) for t in tickers]
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter(rows))
    return result


@pytest.mark.unit
async def test_empty_batch_returns_zero_report():
    pipeline, _, _ = _make_pipeline()
    report = await pipeline.run([])
    assert report.total == 0
    assert report.accepted == 0


@pytest.mark.unit
async def test_unknown_symbol_skipped():
    pipeline, _, mock_session = _make_pipeline()
    # Return empty result — no matching symbols
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter([]))
    mock_session.execute.return_value = result

    report = await pipeline.run([_raw_bar(symbol="UNKNOWN")])
    assert "UNKNOWN" in report.skipped_symbols
    assert report.accepted == 0


@pytest.mark.unit
async def test_valid_bars_inserted():
    pipeline, _, mock_session = _make_pipeline()
    mock_session.execute.return_value = _mock_symbol_result()

    with patch("mentisrex.market_data.pipeline.ingestion.OHLCVRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.bulk_insert.return_value = 1

        report = await pipeline.run([_raw_bar()])

    assert report.total == 1
    assert report.accepted == 1
    assert report.rejected == 0
    mock_repo.bulk_insert.assert_called_once()


@pytest.mark.unit
async def test_invalid_ohlc_bar_rejected():
    """Bar with high < low must be rejected by OHLCVBatchValidator."""
    pipeline, _, mock_session = _make_pipeline()
    mock_session.execute.return_value = _mock_symbol_result()

    bad_bar = _raw_bar(high=Decimal("180.00"), low=Decimal("190.00"))  # high < low

    with patch("mentisrex.market_data.pipeline.ingestion.OHLCVRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.bulk_insert.return_value = 0

        report = await pipeline.run([bad_bar])

    assert report.rejected == 1
    assert report.accepted == 0
    assert len(report.rejection_reasons) > 0


@pytest.mark.unit
async def test_db_error_on_batch_continues():
    """A DB error on one batch should not abort the run — just increment rejected."""
    pipeline, _, mock_session = _make_pipeline()
    mock_session.execute.return_value = _mock_symbol_result()

    with patch("mentisrex.market_data.pipeline.ingestion.OHLCVRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.bulk_insert.side_effect = RuntimeError("DB connection lost")

        report = await pipeline.run([_raw_bar()])

    assert report.rejected > 0
    assert any("DB error" in r for r in report.rejection_reasons)


@pytest.mark.unit
async def test_report_acceptance_rate():
    report = IngestionReport(total=10, accepted=8, rejected=2)
    assert report.acceptance_rate == pytest.approx(0.8)


@pytest.mark.unit
async def test_report_zero_total_acceptance_rate():
    report = IngestionReport(total=0)
    assert report.acceptance_rate == 0.0


@pytest.mark.unit
async def test_normalizer_called_uppercase():
    """Pipeline normalizes lowercase symbols to uppercase."""
    pipeline, _, mock_session = _make_pipeline()
    # Resolver returns AAPL (uppercase)
    mock_session.execute.return_value = _mock_symbol_result()

    # Pass lowercase symbol
    bar = _raw_bar(symbol="aapl")

    with patch("mentisrex.market_data.pipeline.ingestion.OHLCVRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.bulk_insert.return_value = 1

        report = await pipeline.run([bar])

    # If symbol resolved, bar was accepted
    assert report.accepted == 1


@pytest.mark.unit
async def test_gap_warning_logged():
    """Large time gap between consecutive bars generates a gap warning."""
    pipeline, _, mock_session = _make_pipeline()
    mock_session.execute.return_value = _mock_symbol_result()

    bars = [
        _raw_bar(timestamp=datetime(2024, 1, 2, tzinfo=UTC)),
        _raw_bar(timestamp=datetime(2024, 1, 20, tzinfo=UTC)),  # 18-day gap
    ]

    with patch("mentisrex.market_data.pipeline.ingestion.OHLCVRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.bulk_insert.return_value = 2

        report = await pipeline.run(bars)

    assert len(report.gap_warnings) == 1
    assert "AAPL" in report.gap_warnings[0]


@pytest.mark.unit
async def test_gaps_attributed_per_symbol_not_across_symbols():
    """Regression for the grouped gap-detection pass.

    Bars from two symbols are interleaved in input order. Gaps must be computed
    within each symbol's own series, never across the global interleaved stream.
    AAPL has an 18-day gap; MSFT is contiguous — exactly one warning, for AAPL.
    """
    pipeline, _, mock_session = _make_pipeline()
    mock_session.execute.return_value = _mock_multi_symbol_result(["AAPL", "MSFT"])

    bars = [
        _raw_bar(symbol="AAPL", timestamp=datetime(2024, 1, 2, tzinfo=UTC)),
        _raw_bar(symbol="MSFT", timestamp=datetime(2024, 1, 2, tzinfo=UTC)),
        _raw_bar(symbol="MSFT", timestamp=datetime(2024, 1, 3, tzinfo=UTC)),
        _raw_bar(symbol="MSFT", timestamp=datetime(2024, 1, 4, tzinfo=UTC)),
        _raw_bar(symbol="AAPL", timestamp=datetime(2024, 1, 20, tzinfo=UTC)),  # 18-day gap
    ]

    with patch("mentisrex.market_data.pipeline.ingestion.OHLCVRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.bulk_insert.return_value = len(bars)

        report = await pipeline.run(bars)

    assert len(report.gap_warnings) == 1
    assert "AAPL" in report.gap_warnings[0]
    assert not any("MSFT" in w for w in report.gap_warnings)


@pytest.mark.unit
async def test_multiple_symbols_each_gap_reported_once():
    """Two symbols each with their own gap → one warning per symbol."""
    pipeline, _, mock_session = _make_pipeline()
    mock_session.execute.return_value = _mock_multi_symbol_result(["AAPL", "MSFT"])

    bars = [
        _raw_bar(symbol="AAPL", timestamp=datetime(2024, 1, 2, tzinfo=UTC)),
        _raw_bar(symbol="AAPL", timestamp=datetime(2024, 1, 20, tzinfo=UTC)),
        _raw_bar(symbol="MSFT", timestamp=datetime(2024, 1, 2, tzinfo=UTC)),
        _raw_bar(symbol="MSFT", timestamp=datetime(2024, 1, 25, tzinfo=UTC)),
    ]

    with patch("mentisrex.market_data.pipeline.ingestion.OHLCVRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.bulk_insert.return_value = len(bars)

        report = await pipeline.run(bars)

    assert len(report.gap_warnings) == 2
    assert any("AAPL" in w for w in report.gap_warnings)
    assert any("MSFT" in w for w in report.gap_warnings)
