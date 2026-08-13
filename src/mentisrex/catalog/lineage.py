"""LineageTracker — records and queries data lineage edges between entities."""

from __future__ import annotations

from mentisrex.catalog.models import LineageEdge
from mentisrex.catalog.store import CatalogStore
from mentisrex.core.logging import get_logger

logger = get_logger(__name__)


class LineageTracker:
    """Records source→target provenance edges and answers impact queries."""

    def __init__(self, catalog: CatalogStore) -> None:
        self._catalog = catalog

    def record(
        self,
        source_id: str,
        source_type: str,
        target_id: str,
        target_type: str,
        rel_type: str,
        metadata: dict | None = None,
    ) -> LineageEdge:
        edge = LineageEdge(
            source_id=source_id,
            source_type=source_type,
            target_id=target_id,
            target_type=target_type,
            rel_type=rel_type,
            metadata=metadata or {},
        )
        self._catalog.add_lineage_edge(edge)
        logger.info("lineage_edge", source=source_id, target=target_id, rel=rel_type)
        return edge

    # ── Convenience helpers for common edge types ──────────────────────────────

    def dataset_feeds_feature(self, dataset_id: str, feature_id: str, **meta: object) -> LineageEdge:
        return self.record(dataset_id, "dataset", feature_id, "feature", "feeds", dict(meta))

    def feature_used_by_experiment(self, feature_id: str, experiment_id: str, **meta: object) -> LineageEdge:
        return self.record(feature_id, "feature", experiment_id, "experiment", "used_by", dict(meta))

    def experiment_produces_strategy(self, experiment_id: str, strategy_id: str, **meta: object) -> LineageEdge:
        return self.record(experiment_id, "experiment", strategy_id, "strategy", "produces", dict(meta))

    def paper_references_dataset(self, paper_id: str, dataset_id: str, **meta: object) -> LineageEdge:
        return self.record(paper_id, "paper", dataset_id, "dataset", "referenced_by", dict(meta))

    # ── Graph queries ──────────────────────────────────────────────────────────

    def get_upstream(self, node_id: str) -> list[LineageEdge]:
        """Edges where node_id is the target — what feeds into it."""
        return [e for e in self._catalog.get_lineage(node_id) if e.target_id == node_id]

    def get_downstream(self, node_id: str) -> list[LineageEdge]:
        """Edges where node_id is the source — what it feeds into."""
        return [e for e in self._catalog.get_lineage(node_id) if e.source_id == node_id]

    def impact_analysis(self, dataset_id: str) -> dict:
        """What downstream entities would be affected if this dataset changed."""
        downstream = self.get_downstream(dataset_id)
        upstream = self.get_upstream(dataset_id)
        return {
            "dataset_id": dataset_id,
            "upstream": [
                {"id": e.source_id, "type": e.source_type, "rel": e.rel_type}
                for e in upstream
            ],
            "downstream": [
                {"id": e.target_id, "type": e.target_type, "rel": e.rel_type}
                for e in downstream
            ],
            "directly_affected_count": len(downstream),
        }
