"""JSONL journal for pipeline state — enables resumability on restart."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from aurelius.core.logging import get_logger
from aurelius.operations.models import PipelineJob

logger = get_logger(__name__)


class PipelineJournal:
    """Append-only JSONL log of every pipeline job and stage transition.

    On restart, scan for jobs in PROCESSING state → resume from last
    successful stage. One file per calendar day for easy rotation.
    """

    def __init__(self, logs_dir: Path) -> None:
        self._dir = logs_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        return self._dir / f"pipeline_{datetime.now(UTC).strftime('%Y%m%d')}.jsonl"

    def record_job(self, job: PipelineJob) -> None:
        entry = {"event": "job_update", "job": job.model_dump(mode="json")}
        self._append(entry)

    def record_stage(self, job_id: str, stage: str, status: str, message: str = "") -> None:
        entry = {
            "event": "stage",
            "job_id": job_id,
            "stage": stage,
            "status": status,
            "message": message,
            "ts": datetime.now(UTC).isoformat(),
        }
        self._append(entry)
        logger.info("pipeline_stage", job_id=job_id, stage=stage, status=status)

    def load_today(self) -> list[dict]:
        path = self._log_path()
        if not path.exists():
            return []
        lines = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return lines

    def load_range(self, start: datetime, end: datetime) -> list[dict]:
        """Load all journal entries between start and end (inclusive by day)."""
        entries = []
        current = start.date()
        while current <= end.date():
            path = self._dir / f"pipeline_{current.strftime('%Y%m%d')}.jsonl"
            if path.exists():
                with path.open() as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            from datetime import timedelta
            current = (datetime.combine(current, datetime.min.time()) + timedelta(days=1)).date()
        return entries

    def find_incomplete_jobs(self) -> list[dict]:
        """Return jobs that were in PROCESSING state — candidates for resume."""
        today = self.load_today()
        job_states: dict[str, dict] = {}
        for entry in today:
            if entry.get("event") == "job_update":
                job = entry["job"]
                job_states[job["id"]] = job
        return [j for j in job_states.values() if j.get("status") == "processing"]

    def _append(self, entry: dict) -> None:
        with self._log_path().open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
