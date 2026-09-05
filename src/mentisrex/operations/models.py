"""Pydantic models for the autonomous research operations engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class PermanentIngestError(Exception):
    """A document failure that can never succeed on retry.

    Corrupt/undecodable/unparseable content or unsupported documents. The
    pipeline rejects these immediately with no backoff — retrying a permanent
    content error only burns wall-clock time and serializes the queue.
    """


class IngestTimeout(Exception):
    """Per-file wall-clock timeout exceeded during ingestion."""


class StageResult(BaseModel):
    stage: str
    status: str  # success | failed | skipped
    message: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class PipelineJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_filename: str
    file_path: str
    content_hash: str = ""
    status: JobStatus = JobStatus.PENDING
    stages: list[StageResult] = Field(default_factory=list)
    paper_metadata: dict[str, Any] = Field(default_factory=dict)
    corpus_doc_id: str = ""
    priority_score: float = 0.0
    experiment_spec: dict[str, Any] | None = None
    error: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    retry_count: int = 0
    processing_seconds: float = 0.0


class PaperScore(BaseModel):
    paper_id: str
    novelty: float = 0.0
    influence: float = 0.0
    reproducibility: float = 0.0
    dataset_availability: float = 0.0
    expected_value: float = 0.0
    engineering_effort: float = 5.0  # lower = easier; inverted in total
    total: float = 0.0
    rationale: str = ""


class ExperimentSpec(BaseModel):
    paper_id: str
    title: str
    strategy_name: str
    hypothesis_statement: str
    required_datasets: list[str] = Field(default_factory=list)
    required_features: list[str] = Field(default_factory=list)
    methodology: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    expected_metrics: list[str] = Field(default_factory=list)
    reproducibility_checklist: list[str] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    ready_to_run: bool = False
    priority_score: float = 0.0


class DailyReport(BaseModel):
    date: str
    papers_ingested: int = 0
    papers_failed: int = 0
    papers_rejected: int = 0
    experiments_queued: int = 0
    experiments_completed: int = 0
    kg_nodes_added: int = 0
    corpus_total: int = 0
    pipeline_success_rate: float = 0.0
    avg_processing_seconds: float = 0.0
    top_papers: list[dict] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class HealthStatus(BaseModel):
    status: str = "healthy"  # healthy | degraded | unhealthy
    incoming_queue_size: int = 0
    processing_queue_size: int = 0
    processed_total: int = 0
    rejected_total: int = 0
    last_processed_at: datetime | None = None
    uptime_seconds: float = 0.0
    components: dict[str, str] = Field(default_factory=dict)
