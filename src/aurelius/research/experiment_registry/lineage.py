"""Automatic lineage capture (AIDP M7).

Everything reproducible-but-invisible is captured with no manual entry: the git
commit/branch that produced the run, the interpreter and OS it ran on, and the
append-only versions of every upstream PIT store. The research matrix has no
independent state — its version is a pure function of the stores it reads, so it's
derived, never stored twice.
"""

from __future__ import annotations

import getpass
import platform as _platform
import socket
import subprocess
import sys

from aurelius.research.experiment_registry import hashing


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001 — lineage is best-effort; absence is flagged by quality
        return None


def capture_runtime() -> dict:
    """Git + interpreter + host environment. Automatic; no arguments."""
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "python_version": sys.version.split()[0],
        "platform": _platform.platform(),
        "hostname": socket.gethostname(),
        "user": _try(getpass.getuser),
    }


def _try(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


# canonical dataset-version field order (mirrors the dataset_versions table)
VERSION_FIELDS = (
    "prices_version", "fundamentals_version", "insiders_version", "universe_version",
    "securitymaster_version", "feature_registry_version", "research_matrix_version",
)


def dataset_versions(*, prices=None, fundamentals=None, insiders=None, universe=None,
                     securitymaster=None, feature_registry_version=None) -> dict:
    """Assemble append-only dataset versions. Each *_count is a monotonic row
    count (append-only stores). research_matrix_version is derived: the matrix is
    a deterministic view over the others, so it versions as their combined hash."""
    v = {
        "prices_version": prices,
        "fundamentals_version": fundamentals,
        "insiders_version": insiders,
        "universe_version": universe,
        "securitymaster_version": securitymaster,
        "feature_registry_version": feature_registry_version,
    }
    v["research_matrix_version"] = hashing.dataset_fingerprint(v)
    return v


def versions_from_stores(*, prices=None, fundamentals=None, insiders=None,
                         security_master=None, feature_registry: dict | None = None) -> dict:
    """Convenience: read append-only row counts straight off store handles.
    universe_version = listing-interval count (security_identity_history), the set
    that drives UniverseEngine — no separate universe table exists."""
    fr = hashing.feature_registry_version(feature_registry) if feature_registry is not None else None
    return dataset_versions(
        prices=_count(prices, "raw_ohlcv"),
        fundamentals=_count(fundamentals, "fundamental_facts"),
        insiders=_count(insiders, "insider_transactions"),
        universe=_count(security_master, "security_identity_history"),
        securitymaster=_count(security_master, "security_master"),
        feature_registry_version=fr,
    )


def _count(store, table: str):
    if store is None:
        return None
    with store._conn() as conn:  # noqa: SLF001 — read-only sibling access, matches M4/M6
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
