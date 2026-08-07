"""Duplicate-experiment detection (AIDP M7).

Two experiments with the same fingerprint saw the same data, features, and
parameters — one is a reproduction of the other. Rather than silently re-running,
the new experiment is tagged `duplicate_of` the canonical original.
"""

from __future__ import annotations


def detect_duplicate(store, fingerprint: str) -> str | None:
    """Existing canonical experiment_id sharing this fingerprint, else None."""
    return store.find_by_fingerprint(fingerprint)
