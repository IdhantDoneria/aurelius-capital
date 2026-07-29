"""Tests for QualityEngine — checks, scoring, report persistence."""

import pytest
import duckdb

from aurelius.catalog.models import DatasetRecord
from aurelius.catalog.quality import QualityEngine, _score
from aurelius.catalog.store import CatalogStore


@pytest.fixture
def catalog() -> CatalogStore:
    return CatalogStore(":memory:")


@pytest.fixture
def dataset(catalog: CatalogStore) -> DatasetRecord:
    ds = DatasetRecord(
        id="ohlcv_test",
        name="OHLCV Test",
        source="yahoo",
        schema_def={"symbol": "VARCHAR", "timestamp": "TIMESTAMPTZ", "close": "DOUBLE"},
    )
    catalog.register(ds)
    return ds


@pytest.fixture
def clean_db(tmp_path) -> str:
    db_path = str(tmp_path / "test.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE ohlcv (
            symbol VARCHAR,
            timestamp DATE,
            close DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ohlcv VALUES
            ('AAPL', '2024-01-02', 185.0),
            ('AAPL', '2024-01-03', 186.5),
            ('AAPL', '2024-01-04', 184.0),
            ('MSFT', '2024-01-02', 375.0),
            ('MSFT', '2024-01-03', 377.0)
    """)
    conn.close()
    return db_path


def test_quality_run_clean_data(catalog: CatalogStore, dataset: DatasetRecord, clean_db: str) -> None:
    engine = QualityEngine(catalog)
    report = engine.run(dataset, clean_db, "ohlcv", date_col="timestamp")
    assert report.dataset_id == dataset.id
    assert report.overall_score > 0
    assert report.missing_pct == 0.0
    assert report.duplicate_count == 0


def test_quality_report_persisted(catalog: CatalogStore, dataset: DatasetRecord, clean_db: str) -> None:
    QualityEngine(catalog).run(dataset, clean_db, "ohlcv", date_col="timestamp")
    saved = catalog.latest_quality_report(dataset.id)
    assert saved is not None
    assert saved.dataset_id == dataset.id


def test_quality_score_updated_on_dataset(catalog: CatalogStore, dataset: DatasetRecord, clean_db: str) -> None:
    engine = QualityEngine(catalog)
    report = engine.run(dataset, clean_db, "ohlcv", date_col="timestamp")
    refreshed = catalog.get(dataset.id)
    assert refreshed.quality_score == report.overall_score


def test_quality_run_bad_db_returns_zero_score(catalog: CatalogStore, dataset: DatasetRecord) -> None:
    engine = QualityEngine(catalog)
    report = engine.run(dataset, "/nonexistent/path.duckdb", "ohlcv")
    assert report.overall_score == 0.0
    assert report.passed is False


def test_score_perfect() -> None:
    assert _score(0.0, 0, 0, 0, False, False) == 100.0


def test_score_with_penalties() -> None:
    s = _score(50.0, 100, 5, 10, True, True)
    assert s < 50.0


def test_score_floor_at_zero() -> None:
    # max penalties sum to ~97.6 with these inputs; floor is 0.0
    assert _score(100.0, 10000, 100, 10000, True, True) >= 0.0
    assert _score(100.0, 10000, 100, 10000, True, True) < 5.0


def test_schema_drift_detected(catalog: CatalogStore, dataset: DatasetRecord, tmp_path) -> None:
    ds_with_schema = catalog.get(dataset.id)
    # schema_def has 'symbol','timestamp','close' — we'll create a table missing 'close'
    db_path = str(tmp_path / "drift.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute("CREATE TABLE ohlcv (symbol VARCHAR, timestamp DATE)")
    conn.execute("INSERT INTO ohlcv VALUES ('AAPL', '2024-01-02')")
    conn.close()
    engine = QualityEngine(catalog)
    report = engine.run(ds_with_schema, db_path, "ohlcv", date_col="timestamp")
    assert report.schema_drift is True
