"""Unit tests for LiteratureStore (in-memory DuckDB)."""

from datetime import UTC, date, datetime

import pytest

from mentisrex.literature.models import Paper, paper_id
from mentisrex.literature.store import LiteratureStore


def _paper(
    source: str = "arxiv",
    source_id: str = "0001",
    title: str = "Title",
    abstract: str = "This paper studies asset pricing.",
) -> Paper:
    return Paper(
        id=paper_id(source, source_id),
        source=source,
        source_id=source_id,
        title=title,
        authors=["Author One"],
        published_at=date(2024, 1, 15),
        abstract=abstract,
        url=f"https://arxiv.org/abs/{source_id}",
        ingested_at=datetime.now(UTC),
    )


@pytest.fixture
def store() -> LiteratureStore:
    return LiteratureStore(":memory:")


@pytest.mark.unit
def test_upsert_new(store: LiteratureStore) -> None:
    assert store.upsert(_paper()) is True


@pytest.mark.unit
def test_upsert_duplicate_returns_false(store: LiteratureStore) -> None:
    p = _paper()
    store.upsert(p)
    assert store.upsert(p) is False


@pytest.mark.unit
def test_exists(store: LiteratureStore) -> None:
    store.upsert(_paper())
    assert store.exists("arxiv", "0001")
    assert not store.exists("arxiv", "9999")


@pytest.mark.unit
def test_get_roundtrip(store: LiteratureStore) -> None:
    p = _paper()
    store.upsert(p)
    got = store.get(p.id)
    assert got is not None
    assert got.title == "Title"
    assert got.authors == ["Author One"]
    assert got.source == "arxiv"


@pytest.mark.unit
def test_search_by_query(store: LiteratureStore) -> None:
    store.upsert(_paper(source_id="a1", title="Momentum and Value", abstract="Momentum works."))
    store.upsert(_paper(source_id="a2", title="Low Volatility Anomaly"))
    results = store.search(query="momentum")
    assert len(results) == 1
    assert "Momentum" in results[0].title


@pytest.mark.unit
def test_search_by_source(store: LiteratureStore) -> None:
    store.upsert(_paper(source="arxiv", source_id="a1"))
    store.upsert(_paper(source="nber", source_id="n1"))
    results = store.search(source="arxiv")
    assert all(r.source == "arxiv" for r in results)


@pytest.mark.unit
def test_search_by_since(store: LiteratureStore) -> None:
    store.upsert(_paper(source_id="a1"))  # published 2024-01-15
    results = store.search(since=date(2025, 1, 1))
    assert len(results) == 0
    results = store.search(since=date(2024, 1, 1))
    assert len(results) == 1


@pytest.mark.unit
def test_pending_enrichment(store: LiteratureStore) -> None:
    p = _paper()
    store.upsert(p)
    pending = store.pending_enrichment()
    assert len(pending) == 1
    # Enrich and re-upsert
    p.enriched = True
    store.upsert(p)
    assert store.pending_enrichment() == []


@pytest.mark.unit
def test_upsert_preserves_enrichment(store: LiteratureStore) -> None:
    """Re-upserting an unenriched paper must not overwrite enriched data."""
    p = _paper()
    p.enriched = True
    p.keywords = ["momentum"]
    store.upsert(p)

    # Simulate re-ingest: same paper but unenriched
    p2 = _paper()
    assert p2.enriched is False
    store.upsert(p2)

    got = store.get(p.id)
    assert got is not None
    assert got.enriched is True
    assert got.keywords == ["momentum"]


@pytest.mark.unit
def test_stats(store: LiteratureStore) -> None:
    store.upsert(_paper(source="arxiv", source_id="a1"))
    store.upsert(_paper(source="nber", source_id="n1"))
    s = store.stats()
    assert s["total"] == 2
    assert s["enriched"] == 0
    assert s["by_source"]["arxiv"] == 1
    assert s["by_source"]["nber"] == 1


@pytest.mark.unit
def test_all_papers(store: LiteratureStore) -> None:
    for i in range(5):
        store.upsert(_paper(source_id=str(i)))
    assert len(store.all_papers()) == 5
