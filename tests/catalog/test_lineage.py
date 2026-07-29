"""Tests for LineageTracker — edge creation, impact analysis, graph queries."""

import pytest

from aurelius.catalog.lineage import LineageTracker
from aurelius.catalog.store import CatalogStore


@pytest.fixture
def tracker() -> LineageTracker:
    return LineageTracker(CatalogStore(":memory:"))


def test_record_edge(tracker: LineageTracker) -> None:
    edge = tracker.record("ds1", "dataset", "feat1", "feature", "feeds")
    assert edge.source_id == "ds1"
    assert edge.target_id == "feat1"
    assert edge.rel_type == "feeds"


def test_dataset_feeds_feature(tracker: LineageTracker) -> None:
    edge = tracker.dataset_feeds_feature("ohlcv", "momentum_feature")
    assert edge.source_type == "dataset"
    assert edge.target_type == "feature"
    assert edge.rel_type == "feeds"


def test_feature_used_by_experiment(tracker: LineageTracker) -> None:
    edge = tracker.feature_used_by_experiment("momentum_feature", "exp_001")
    assert edge.source_type == "feature"
    assert edge.target_type == "experiment"


def test_experiment_produces_strategy(tracker: LineageTracker) -> None:
    edge = tracker.experiment_produces_strategy("exp_001", "strat_momentum")
    assert edge.rel_type == "produces"


def test_paper_references_dataset(tracker: LineageTracker) -> None:
    edge = tracker.paper_references_dataset("paper_123", "ohlcv")
    assert edge.source_type == "paper"
    assert edge.target_type == "dataset"


def test_get_downstream(tracker: LineageTracker) -> None:
    tracker.dataset_feeds_feature("ohlcv", "feat_a")
    tracker.dataset_feeds_feature("ohlcv", "feat_b")
    downstream = tracker.get_downstream("ohlcv")
    target_ids = {e.target_id for e in downstream}
    assert "feat_a" in target_ids
    assert "feat_b" in target_ids


def test_get_upstream(tracker: LineageTracker) -> None:
    tracker.dataset_feeds_feature("ohlcv", "feat_a")
    upstream = tracker.get_upstream("feat_a")
    assert any(e.source_id == "ohlcv" for e in upstream)


def test_impact_analysis(tracker: LineageTracker) -> None:
    tracker.dataset_feeds_feature("ohlcv", "feat_a")
    tracker.dataset_feeds_feature("ohlcv", "feat_b")
    tracker.feature_used_by_experiment("feat_a", "exp_1")
    result = tracker.impact_analysis("ohlcv")
    assert result["dataset_id"] == "ohlcv"
    assert result["directly_affected_count"] == 2
    assert len(result["downstream"]) == 2


def test_impact_analysis_no_edges(tracker: LineageTracker) -> None:
    result = tracker.impact_analysis("isolated_ds")
    assert result["directly_affected_count"] == 0
    assert result["downstream"] == []
