"""Unit tests for Paper model and paper_id helper."""

from datetime import UTC, date, datetime

import pytest

from mentisrex.literature.models import Paper, paper_id


@pytest.mark.unit
def test_paper_id_deterministic():
    assert paper_id("arxiv", "2301.00001") == paper_id("arxiv", "2301.00001")


@pytest.mark.unit
def test_paper_id_unique_across_sources():
    assert paper_id("arxiv", "2301.00001") != paper_id("nber", "2301.00001")


@pytest.mark.unit
def test_paper_id_unique_across_ids():
    assert paper_id("arxiv", "0001") != paper_id("arxiv", "0002")


@pytest.mark.unit
def test_paper_id_length():
    assert len(paper_id("arxiv", "x")) == 32


@pytest.mark.unit
def test_paper_defaults():
    p = Paper(
        id=paper_id("arxiv", "x"),
        source="arxiv",
        source_id="x",
        title="Test",
        authors=["A B"],
        published_at=date(2024, 1, 1),
        abstract="abstract",
        url="http://x",
        ingested_at=datetime.now(UTC),
    )
    assert p.enriched is False
    assert p.keywords == []
    assert p.asset_classes == []
    assert p.methodology == ""
    assert p.factors_studied == []
