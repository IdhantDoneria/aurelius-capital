"""Audit record — full reproducibility envelope for every validation run.

Every calculation is pinned to: software version, dataset fingerprint,
config hash, random seed, git commit, and execution environment.
Callers can replay an identical run by restoring these inputs.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from aurelius.backtesting.config import BacktestConfig


@dataclass
class AuditRecord:
    validated_at: datetime
    python_version: str
    platform: str
    aurelius_commit: str        # git short hash; "unknown" if not in a git repo
    config_hash: str            # SHA-256[:16] of serialized BacktestConfig
    dataset_fingerprint: str    # from research.models.dataset_fingerprint
    random_seed: int
    key_package_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "validated_at": self.validated_at.isoformat(),
            "python_version": self.python_version,
            "platform": self.platform,
            "aurelius_commit": self.aurelius_commit,
            "config_hash": self.config_hash,
            "dataset_fingerprint": self.dataset_fingerprint,
            "random_seed": self.random_seed,
            "key_package_versions": self.key_package_versions,
        }


_REPO_ROOT = Path(__file__).parent.parent.parent.parent  # aurelius-capital/

_TRACKED_PACKAGES = ["duckdb", "fastapi", "sqlalchemy", "pydantic", "structlog"]


def capture_environment(config: BacktestConfig, dataset_fingerprint: str) -> AuditRecord:
    """Snapshot the execution environment for reproducibility."""
    # git short hash
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_REPO_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except Exception:
        commit = "unknown"

    # config hash
    config_dict = {k: str(v) for k, v in vars(config).items()}
    config_hash = hashlib.sha256(
        json.dumps(config_dict, sort_keys=True).encode()
    ).hexdigest()[:16]

    # package versions
    versions: dict[str, str] = {}
    for pkg in _TRACKED_PACKAGES:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "unknown"

    return AuditRecord(
        validated_at=datetime.now(UTC),
        python_version=sys.version,
        platform=platform.platform(),
        aurelius_commit=commit,
        config_hash=config_hash,
        dataset_fingerprint=dataset_fingerprint,
        random_seed=config.random_seed,
        key_package_versions=versions,
    )
