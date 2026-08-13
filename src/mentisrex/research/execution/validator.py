"""Pre-execution validation (AIDP M8).

A run aborts *before any side effect* if its configuration is incomplete or
inconsistent. Reuses M6's feature registry and M7's hashing — no new
validation logic duplicated.
"""

from __future__ import annotations

from mentisrex.market_data.research_matrix import FEATURES
from mentisrex.research.execution.exceptions import ValidationError
from mentisrex.research.experiment_registry import hashing

_REQUIRED_VERSIONS = ("prices_version", "fundamentals_version", "insiders_version",
                      "universe_version", "securitymaster_version")


def validate(session) -> list[str]:
    """Return [] if the run may proceed, else raise ValidationError(issues)."""
    cfg = session.config
    issues: list[str] = []

    # strategy / executor
    if not callable(cfg.executor):
        issues.append("strategy_invalid: config.executor is not callable")

    # universe
    if cfg.universe is not None:
        if not isinstance(cfg.universe, list) or any("security_id" not in s for s in cfg.universe):
            issues.append("universe_invalid: expected list of dicts with security_id")

    # research matrix
    if cfg.build_matrix and session.matrix_engine is None:
        issues.append("research_matrix_invalid: build_matrix set but no matrix_engine injected")

    # features must be registered (M6)
    unknown = [f for f in cfg.features if f not in FEATURES]
    if unknown:
        issues.append(f"features_invalid: {unknown}")

    # dataset versions
    dv = cfg.dataset_versions or {}
    if any(dv.get(f) is None for f in _REQUIRED_VERSIONS):
        issues.append("dataset_versions_missing")
    if dv.get("feature_registry_version") is None:
        issues.append("feature_registry_missing")

    # registry availability
    if session.registry is None:
        issues.append("registry_unavailable")

    # parameters / hash
    if not isinstance(cfg.parameters, dict):
        issues.append("parameter_hash_invalid: parameters not a dict")
    else:
        hashing.hash_params(cfg.parameters)  # must not raise

    # seed
    if cfg.random_seed is None:
        issues.append("random_seed_missing")

    if issues:
        raise ValidationError(issues)
    return issues


def consistency_check(session) -> list[str]:
    """Advanced: after the matrix is built, verify its metadata matches the
    experiment registry's. Non-fatal — returns warnings."""
    warns: list[str] = []
    m, exp = session.matrix, session.experiment
    if m is None or exp is None:
        return warns
    if set(m.directions) != set(session.config.features):
        warns.append("matrix_feature_mismatch")
    fr_matrix = m.metadata.get("data_versions", {}).get("feature_registry") if hasattr(m, "metadata") else None
    if fr_matrix is not None and fr_matrix != exp.dataset_versions.get("feature_registry_version"):
        warns.append("feature_registry_version_mismatch")
    return warns
