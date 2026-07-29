"""Tests for VersionManager — snapshot, hash, reproducibility lookup."""

import pytest
import duckdb

from aurelius.catalog.models import DatasetRecord
from aurelius.catalog.store import CatalogStore
from aurelius.catalog.versioning import VersionManager


@pytest.fixture
def catalog() -> CatalogStore:
    store = CatalogStore(":memory:")
    store.register(DatasetRecord(id="ohlcv", name="OHLCV", source="yahoo"))
    return store


@pytest.fixture
def sample_db(tmp_path) -> str:
    db_path = str(tmp_path / "sample.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute("CREATE TABLE ohlcv (symbol VARCHAR, timestamp DATE, close DOUBLE)")
    conn.execute("""
        INSERT INTO ohlcv VALUES
            ('AAPL', '2024-01-02', 185.0),
            ('AAPL', '2024-01-03', 186.5),
            ('MSFT', '2024-01-02', 375.0)
    """)
    conn.close()
    return db_path


def test_snapshot_creates_version(catalog: CatalogStore, sample_db: str) -> None:
    vm = VersionManager(catalog)
    v = vm.snapshot("ohlcv", sample_db, "ohlcv")
    assert v.dataset_id == "ohlcv"
    assert v.version != ""
    assert v.row_hash != ""
    assert v.snapshot_meta.get("row_count") == 3


def test_snapshot_schema_captured(catalog: CatalogStore, sample_db: str) -> None:
    v = VersionManager(catalog).snapshot("ohlcv", sample_db, "ohlcv")
    assert "schema" in v.snapshot_meta
    assert "symbol" in v.snapshot_meta["schema"]


def test_get_versions_returns_history(catalog: CatalogStore, sample_db: str) -> None:
    vm = VersionManager(catalog)
    vm.snapshot("ohlcv", sample_db, "ohlcv", notes="v1")
    vm.snapshot("ohlcv", sample_db, "ohlcv", notes="v2")
    versions = vm.get_versions("ohlcv")
    assert len(versions) >= 2


def test_find_by_hash(catalog: CatalogStore, sample_db: str) -> None:
    vm = VersionManager(catalog)
    v = vm.snapshot("ohlcv", sample_db, "ohlcv")
    found = vm.find_by_hash("ohlcv", v.row_hash)
    assert found is not None
    assert found.id == v.id


def test_find_by_hash_missing(catalog: CatalogStore) -> None:
    vm = VersionManager(catalog)
    assert vm.find_by_hash("ohlcv", "deadbeef") is None


def test_snapshot_bad_db_still_returns_version(catalog: CatalogStore) -> None:
    vm = VersionManager(catalog)
    v = vm.snapshot("ohlcv", "/bad/path.duckdb", "ohlcv")
    assert v.dataset_id == "ohlcv"
    assert "error" in v.snapshot_meta
