"""Tests for CatalogStore CRUD, search, bootstrap."""

import pytest

from aurelius.catalog.models import DatasetRecord
from aurelius.catalog.store import CatalogStore


@pytest.fixture
def store() -> CatalogStore:
    return CatalogStore(":memory:")


def test_register_and_get(store: CatalogStore) -> None:
    ds = DatasetRecord(id="test_ds", name="Test Dataset", source="yahoo", asset_class="equity")
    store.register(ds)
    result = store.get("test_ds")
    assert result is not None
    assert result.name == "Test Dataset"
    assert result.source == "yahoo"


def test_get_missing_returns_none(store: CatalogStore) -> None:
    assert store.get("nonexistent") is None


def test_list_datasets_filter_by_source(store: CatalogStore) -> None:
    store.register(DatasetRecord(id="a", name="A", source="yahoo"))
    store.register(DatasetRecord(id="b", name="B", source="alpaca"))
    results = store.list_datasets(source="yahoo")
    assert len(results) == 1
    assert results[0].id == "a"


def test_list_datasets_filter_by_status(store: CatalogStore) -> None:
    store.register(DatasetRecord(id="x", name="X", source="s", status="active"))
    store.register(DatasetRecord(id="y", name="Y", source="s", status="deprecated"))
    active = store.list_datasets(status="active")
    assert all(r.status == "active" for r in active)


def test_update_quality_score(store: CatalogStore) -> None:
    store.register(DatasetRecord(id="q", name="Q", source="s"))
    store.update_quality_score("q", 88.5)
    assert store.get("q").quality_score == 88.5


def test_deprecate(store: CatalogStore) -> None:
    store.register(DatasetRecord(id="d", name="D", source="s"))
    store.deprecate("d")
    assert store.get("d").status == "deprecated"


def test_deprecate_with_replacement(store: CatalogStore) -> None:
    store.register(DatasetRecord(id="old", name="Old", source="s"))
    store.deprecate("old", replaced_by="new")
    assert store.get("old").status == "replaced"


def test_search(store: CatalogStore) -> None:
    store.register(DatasetRecord(id="ohlcv", name="OHLCV Daily Equity", source="yahoo"))
    store.register(DatasetRecord(id="kgraph", name="Knowledge Graph", source="internal"))
    results = store.search("equity")
    assert any(r.id == "ohlcv" for r in results)
    assert not any(r.id == "kgraph" for r in results)


def test_bootstrap_registers_builtin_datasets(store: CatalogStore) -> None:
    store.bootstrap()
    datasets = store.list_datasets()
    ids = {d.id for d in datasets}
    assert "ohlcv_daily_market" in ids
    assert "knowledge_graph" in ids
    assert "literature_papers" in ids


def test_bootstrap_is_idempotent(store: CatalogStore) -> None:
    store.bootstrap()
    store.bootstrap()
    datasets = store.list_datasets()
    ids = [d.id for d in datasets]
    assert len(ids) == len(set(ids))
