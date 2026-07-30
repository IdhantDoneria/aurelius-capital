"""Operations health monitor — collects pipeline metrics from folder state and journal."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from aurelius.core.logging import get_logger
from aurelius.operations.config import OperationsConfig
from aurelius.operations.journal import PipelineJournal
from aurelius.operations.models import HealthStatus

logger = get_logger(__name__)

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".rst", ".tex", ".json"}


class OperationsMonitor:
    def __init__(self, config: OperationsConfig) -> None:
        self._cfg = config
        self._started_at = time.monotonic()
        self._journal = PipelineJournal(config.logs)

    def health(self) -> HealthStatus:
        incoming = _count_files(self._cfg.incoming)
        processing = _count_files(self._cfg.processing)
        processed = _count_files(self._cfg.processed)
        rejected = _count_files(self._cfg.rejected)
        last_ts = _last_modified(self._cfg.processed)

        # Derive status from queue depths
        if incoming > 50 or processing > 10:
            status = "degraded"
        elif rejected > processed * 0.3 and processed > 0:
            status = "degraded"
        else:
            status = "healthy"

        return HealthStatus(
            status=status,
            incoming_queue_size=incoming,
            processing_queue_size=processing,
            processed_total=processed,
            rejected_total=rejected,
            last_processed_at=last_ts,
            uptime_seconds=time.monotonic() - self._started_at,
            components=self._component_statuses(),
        )

    def metrics(self) -> dict:
        """Extended metrics beyond the health snapshot."""
        today_entries = self._journal.load_today()
        job_entries = [e for e in today_entries if e.get("event") == "job_update"]
        stage_entries = [e for e in today_entries if e.get("event") == "stage"]

        completed = [j for j in job_entries if j["job"]["status"] == "completed"]
        failed = [j for j in job_entries if j["job"]["status"] in ("failed", "rejected")]

        processing_times = [
            j["job"]["processing_seconds"]
            for j in completed
            if j["job"].get("processing_seconds", 0) > 0
        ]
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 0.0

        stage_failures = {}
        for e in stage_entries:
            if e.get("status") == "failed":
                stage_failures[e["stage"]] = stage_failures.get(e["stage"], 0) + 1

        experiments_planned = sum(
            1 for j in completed if j["job"].get("experiment_spec") is not None
        )

        scores = [
            j["job"]["priority_score"]
            for j in completed
            if j["job"].get("priority_score", 0) > 0
        ]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        return {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "papers_processed_today": len(completed),
            "papers_failed_today": len(failed),
            "avg_processing_seconds": round(avg_time, 2),
            "experiments_planned_today": experiments_planned,
            "avg_priority_score": round(avg_score, 2),
            "stage_failure_counts": stage_failures,
            "pipeline_success_rate": (
                len(completed) / (len(completed) + len(failed))
                if (completed or failed)
                else 1.0
            ),
            "corpus_folder_stats": {
                "incoming": _count_files(self._cfg.incoming),
                "processing": _count_files(self._cfg.processing),
                "processed": _count_files(self._cfg.processed),
                "rejected": _count_files(self._cfg.rejected),
            },
        }

    def _component_statuses(self) -> dict[str, str]:
        return {
            "incoming_folder": "ok" if self._cfg.incoming.exists() else "missing",
            "processed_folder": "ok" if self._cfg.processed.exists() else "missing",
            "logs_folder": "ok" if self._cfg.logs.exists() else "missing",
            "metadata_folder": "ok" if self._cfg.metadata.exists() else "missing",
        }


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1 for p in path.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in _SUPPORTED_EXTENSIONS
    )


def _last_modified(path: Path) -> datetime | None:
    if not path.exists():
        return None
    files = [p for p in path.iterdir() if p.is_file()]
    if not files:
        return None
    return datetime.fromtimestamp(max(p.stat().st_mtime for p in files), tz=UTC)
