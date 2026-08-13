"""HealthMonitor — aggregates health signals across all registered datasets."""

from __future__ import annotations

from datetime import datetime, timezone

from mentisrex.catalog.models import DatasetHealth, DatasetRecord
from mentisrex.catalog.store import CatalogStore
from mentisrex.core.logging import get_logger

logger = get_logger(__name__)


class HealthMonitor:
    """Produces per-dataset and fleet-level health summaries."""

    def __init__(self, catalog: CatalogStore) -> None:
        self._catalog = catalog

    def dataset_health(self, dataset: DatasetRecord) -> DatasetHealth:
        latest_qr = self._catalog.latest_quality_report(dataset.id)
        versions = self._catalog.list_versions(dataset.id)
        return DatasetHealth(
            dataset_id=dataset.id,
            name=dataset.name,
            status=dataset.status,
            quality_score=dataset.quality_score,
            last_quality_check=latest_qr.checked_at if latest_qr else None,
            feed_delayed=latest_qr.feed_delayed if latest_qr else False,
            version_count=len(versions),
            last_updated=dataset.updated_at,
        )

    def all_health(self, limit: int = 100) -> list[DatasetHealth]:
        datasets = self._catalog.list_datasets(limit=limit)
        return [self.dataset_health(ds) for ds in datasets]

    def generate_report(self) -> dict:
        """Fleet-level health report — suitable for dashboards and alerting."""
        all_h = self.all_health()
        total = len(all_h)
        scores = [h.quality_score for h in all_h]
        avg_score = round(sum(scores) / total, 1) if total else 0.0
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_datasets": total,
            "active": sum(1 for h in all_h if h.status == "active"),
            "deprecated": sum(1 for h in all_h if h.status in ("deprecated", "replaced")),
            "delayed_feeds": sum(1 for h in all_h if h.feed_delayed),
            "avg_quality_score": avg_score,
            "datasets_below_70": sum(1 for h in all_h if h.quality_score < 70),
            "datasets": [h.model_dump() for h in all_h],
        }
