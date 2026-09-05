"""Experiment model (AIDP M7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Experiment:
    experiment_id: str
    name: str
    status: str  # running | finished | failed
    description: str = ""
    # lineage / metadata (auto-captured)
    git_commit: str | None = None
    git_branch: str | None = None
    python_version: str | None = None
    platform: str | None = None
    hostname: str | None = None
    user: str | None = None
    random_seed: int | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    notes: str = ""
    # content
    dataset_versions: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    artifacts: list[dict] = field(
        default_factory=list
    )  # {artifact_type, artifact_location, artifact_hash}
    # identity
    fingerprint: str | None = None
    parameter_hash: str | None = None
    duplicate_of: str | None = None
    # failure
    error: str | None = None
