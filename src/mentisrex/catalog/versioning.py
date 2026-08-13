"""VersionManager — dataset snapshots for experiment reproducibility.

Every version stores:
  - row count and schema at snapshot time
  - SHA-256 content fingerprint (sampled for speed)
  - coverage dates if a timestamp column is present

Experiments should record the version ID (or row_hash) of every dataset
they consume so results can be reproduced against the exact same data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import duckdb

from mentisrex.catalog.models import DataVersion
from mentisrex.catalog.store import CatalogStore
from mentisrex.core.logging import get_logger

logger = get_logger(__name__)

_SAMPLE_ROWS = 1000  # ponytail: sample for hash; use full scan if exact reproducibility required


class VersionManager:
    """Creates and queries dataset version snapshots."""

    def __init__(self, catalog: CatalogStore) -> None:
        self._catalog = catalog

    def snapshot(
        self,
        dataset_id: str,
        db_path: str,
        table: str,
        *,
        created_by: str = "system",
        notes: str = "",
    ) -> DataVersion:
        """Snapshot the current state of a DuckDB table and save a version record."""
        meta: dict = {}
        row_hash = ""
        try:
            conn = duckdb.connect(db_path, read_only=True)
            try:
                row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                cols_info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
                schema = {c[1]: c[2] for c in cols_info}

                sample = conn.execute(
                    f"SELECT * FROM {table} USING SAMPLE {_SAMPLE_ROWS}"
                ).fetchall()
                row_hash = hashlib.sha256(
                    json.dumps(sample, default=str, sort_keys=True).encode()
                ).hexdigest()

                try:
                    dr = conn.execute(
                        f"SELECT MIN(timestamp), MAX(timestamp) FROM {table}"
                    ).fetchone()
                    meta["coverage_start"] = str(dr[0]) if dr and dr[0] else None
                    meta["coverage_end"] = str(dr[1]) if dr and dr[1] else None
                except Exception:
                    pass

                meta.update({"row_count": row_count, "schema": schema})
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("snapshot_failed", dataset_id=dataset_id, error=str(exc))
            meta["error"] = str(exc)

        version_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        v = DataVersion(
            dataset_id=dataset_id,
            version=version_str,
            snapshot_meta=meta,
            row_hash=row_hash,
            created_by=created_by,
            notes=notes,
        )
        self._catalog.save_version(v)
        logger.info(
            "version_created",
            dataset_id=dataset_id,
            version=version_str,
            rows=meta.get("row_count"),
        )
        return v

    def get_versions(self, dataset_id: str) -> list[DataVersion]:
        return self._catalog.list_versions(dataset_id)

    def find_by_hash(self, dataset_id: str, row_hash: str) -> DataVersion | None:
        """Locate a version by content hash — for experiment reproducibility lookups."""
        return next(
            (v for v in self.get_versions(dataset_id) if v.row_hash == row_hash),
            None,
        )
