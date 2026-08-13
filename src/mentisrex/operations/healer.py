"""Self-healing logic: retry decisions, repair strategies, escalation."""

from __future__ import annotations

import time
from typing import Any

from mentisrex.core.logging import get_logger
from mentisrex.operations.models import JobStatus, PermanentIngestError, PipelineJob

logger = get_logger(__name__)

# Stages that are safe to retry automatically
_RETRYABLE_STAGES = {
    "extract_metadata",
    "store_corpus",
    "update_kg",
    "score",
    "plan_experiment",
    "archive",
}

# Stages whose failure should immediately reject (no retry)
_FATAL_STAGES = {"validate", "assign_id"}


class SelfHealer:
    def __init__(self, max_retries: int = 3, retry_delay_seconds: int = 60) -> None:
        self._max_retries = max_retries
        self._retry_delay = retry_delay_seconds

    def should_retry(self, job: PipelineJob, stage: str, exc: Exception | None = None) -> bool:
        # Permanent content failures never succeed on retry — reject immediately.
        if isinstance(exc, PermanentIngestError):
            return False
        if stage in _FATAL_STAGES:
            return False
        if stage not in _RETRYABLE_STAGES:
            return False
        return job.retry_count < self._max_retries

    def wait_before_retry(self, job: PipelineJob, max_wait: float | None = None) -> None:
        delay = self._retry_delay * (2 ** job.retry_count)  # exponential backoff
        capped = min(delay, 300)  # cap at 5 minutes
        if max_wait is not None:
            capped = min(capped, max_wait)  # never sleep past the per-file deadline
        logger.info("retry_backoff", job_id=job.id, delay_seconds=capped, retry_count=job.retry_count)
        if capped > 0:
            time.sleep(capped)

    def classify_error(self, exc: Exception) -> str:
        """Classify exception into a repair category."""
        msg = str(exc).lower()
        if "permission" in msg or "access denied" in msg:
            return "permission_error"
        if "not found" in msg or "no such file" in msg:
            return "file_missing"
        if "duckdb" in msg or "database" in msg:
            return "db_error"
        if "connection" in msg or "timeout" in msg:
            return "network_error"
        if "memory" in msg or "oom" in msg:
            return "resource_error"
        return "unknown_error"

    def attempt_repair(self, job: PipelineJob, stage: str, exc: Exception) -> dict[str, Any]:
        """Try automatic repair. Returns action taken."""
        category = self.classify_error(exc)
        action = {"category": category, "stage": stage, "repaired": False, "note": ""}

        if category == "file_missing":
            # File moved unexpectedly — nothing we can do automatically
            action["note"] = "Source file missing; manual recovery required"
        elif category == "db_error":
            action["note"] = "DB error; will retry on next attempt"
            action["repaired"] = True
        elif category == "network_error":
            action["note"] = "Network error; will retry with backoff"
            action["repaired"] = True
        else:
            action["note"] = f"Unclassified error: {exc}"

        logger.warning(
            "healer_action",
            job_id=job.id,
            stage=stage,
            category=category,
            repaired=action["repaired"],
        )
        return action

    def needs_escalation(self, job: PipelineJob) -> bool:
        """True if job should be flagged for human review."""
        return (
            job.retry_count >= self._max_retries
            or any(s.stage in _FATAL_STAGES and s.status == "failed" for s in job.stages)
        )
