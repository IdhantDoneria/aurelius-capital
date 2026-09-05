"""Experiment quality / completeness checks (AIDP M7).

Flags experiments that can't be trusted as a reproduction record: missing
lineage, missing dataset versions, missing parameters, impossible timestamps.
Structural — the PIT correctness of the data itself is guaranteed upstream.
"""

from __future__ import annotations

from mentisrex.research.experiment_registry.models import Experiment

_REQUIRED_VERSIONS = (
    "prices_version",
    "fundamentals_version",
    "insiders_version",
    "universe_version",
    "securitymaster_version",
)


def check(exp: Experiment) -> dict:
    issues: list[str] = []
    if not exp.git_commit:
        issues.append("missing_git_commit")
    dv = exp.dataset_versions or {}
    if any(dv.get(f) is None for f in _REQUIRED_VERSIONS):
        issues.append("missing_dataset_version")
    if dv.get("feature_registry_version") is None:
        issues.append("missing_feature_registry")
    if not exp.parameters:
        issues.append("missing_parameters")
    if exp.started_at and exp.finished_at and exp.finished_at < exp.started_at:
        issues.append("invalid_timestamps")
    if exp.duration_seconds is not None and exp.duration_seconds < 0:
        issues.append("negative_runtime")
    if exp.duplicate_of:
        issues.append("duplicate_fingerprint")
    return {"experiment_id": exp.experiment_id, "ok": not issues, "issues": issues}
