"""Tests for HealthMonitor — health report, freshness detection, fleet summary."""

import pytest

from mentisrex.catalog.models import DatasetRecord, QualityReport
from mentisrex.catalog.monitor import HealthMonitor
from mentisrex.catalog.store import CatalogStore


@pytest.fixture
def catalog() -> CatalogStore:
    store = CatalogStore(":memory:")
    store.register(DatasetRecord(id="ds_a", name="Dataset A", source="yahoo", status="active"))
    store.register(DatasetRecord(id="ds_b", name="Dataset B", source="internal", status="deprecated"))
    return store


@pytest.fixture
def monitor(catalog: CatalogStore) -> HealthMonitor:
    return HealthMonitor(catalog)


def test_dataset_health_no_quality_report(monitor: HealthMonitor, catalog: CatalogStore) -> None:
    ds = catalog.get("ds_a")
    health = monitor.dataset_health(ds)
    assert health.dataset_id == "ds_a"
    assert health.last_quality_check is None
    assert health.feed_delayed is False


def test_dataset_health_with_quality_report(monitor: HealthMonitor, catalog: CatalogStore) -> None:
    report = QualityReport(dataset_id="ds_a", overall_score=85.0, feed_delayed=False, passed=True)
    catalog.save_quality_report(report)
    ds = catalog.get("ds_a")
    health = monitor.dataset_health(ds)
    assert health.quality_score == 85.0
    assert health.last_quality_check is not None


def test_dataset_health_delayed_feed(monitor: HealthMonitor, catalog: CatalogStore) -> None:
    report = QualityReport(dataset_id="ds_a", overall_score=60.0, feed_delayed=True, passed=False)
    catalog.save_quality_report(report)
    ds = catalog.get("ds_a")
    health = monitor.dataset_health(ds)
    assert health.feed_delayed is True


def test_all_health_returns_all(monitor: HealthMonitor) -> None:
    all_h = monitor.all_health()
    assert len(all_h) == 2
    ids = {h.dataset_id for h in all_h}
    assert "ds_a" in ids
    assert "ds_b" in ids


def test_generate_report_structure(monitor: HealthMonitor) -> None:
    report = monitor.generate_report()
    assert "generated_at" in report
    assert "total_datasets" in report
    assert "active" in report
    assert "deprecated" in report
    assert "delayed_feeds" in report
    assert "avg_quality_score" in report
    assert isinstance(report["datasets"], list)


def test_generate_report_counts(monitor: HealthMonitor) -> None:
    report = monitor.generate_report()
    assert report["total_datasets"] == 2
    assert report["active"] == 1
    assert report["deprecated"] == 1


def test_generate_report_empty_catalog() -> None:
    monitor = HealthMonitor(CatalogStore(":memory:"))
    report = monitor.generate_report()
    assert report["total_datasets"] == 0
    assert report["avg_quality_score"] == 0.0
