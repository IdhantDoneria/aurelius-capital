"""Data Intelligence Platform — Pydantic models for all catalog entities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


def _uid() -> str:
    return str(uuid.uuid4())


class DatasetRecord(BaseModel):
    id: str = Field(default_factory=_uid)
    name: str
    source: str
    asset_class: str | None = None
    frequency: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    schema_def: dict[str, str] = Field(default_factory=dict)
    update_freq: str | None = None
    license: str | None = None
    quality_score: float = 0.0
    owner: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    status: str = "active"  # active | deprecated | replaced


class DataVersion(BaseModel):
    id: str = Field(default_factory=_uid)
    dataset_id: str
    version: str
    snapshot_meta: dict[str, Any] = Field(default_factory=dict)
    row_hash: str = ""
    created_at: datetime = Field(default_factory=_now)
    created_by: str = "system"
    notes: str = ""


class LineageEdge(BaseModel):
    id: str = Field(default_factory=_uid)
    source_id: str
    source_type: str  # dataset | feature | experiment | strategy | paper
    target_id: str
    target_type: str
    rel_type: str  # feeds | used_by | produces | referenced_by
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class QualityReport(BaseModel):
    id: str = Field(default_factory=_uid)
    dataset_id: str
    checked_at: datetime = Field(default_factory=_now)
    missing_pct: float = 0.0
    duplicate_count: int = 0
    timestamp_gaps: int = 0
    outlier_count: int = 0
    schema_drift: bool = False
    feed_delayed: bool = False
    overall_score: float = 100.0
    details: dict[str, Any] = Field(default_factory=dict)
    passed: bool = True


class GovernanceRecord(BaseModel):
    id: str = Field(default_factory=_uid)
    dataset_id: str
    action: str  # access | deprecate | replace | policy_change
    actor: str = "system"
    details: dict[str, Any] = Field(default_factory=dict)
    retention_days: int | None = None
    logged_at: datetime = Field(default_factory=_now)


class DatasetHealth(BaseModel):
    dataset_id: str
    name: str
    status: str
    quality_score: float
    last_quality_check: datetime | None = None
    feed_delayed: bool = False
    version_count: int = 0
    last_updated: datetime | None = None
