"""Execution quality / completeness checks (AIDP M8).

Verifies a finished session is a trustworthy, reproducible record: reached a
terminal state, produced metrics + the full artifact set with stored hashes, and
was tied to a registry experiment.
"""

from __future__ import annotations

from aurelius.research.execution.artifact_manager import _ARTIFACTS
from aurelius.research.execution.state_machine import State


def check(session) -> dict:
    issues: list[str] = []
    if session.state not in (State.COMPLETED, State.FAILED, State.CANCELLED):
        issues.append("non_terminal_state")
    if session.experiment_id is None:
        issues.append("no_experiment")
    if session.state == State.COMPLETED:
        if not session.metrics:
            issues.append("no_metrics")
        missing = [a for a in _ARTIFACTS if a not in session.artifacts]
        if missing:
            issues.append(f"missing_artifacts:{missing}")
        if any("hash" not in m for m in session.artifacts.values()):
            issues.append("artifact_hash_missing")
    return {"session_id": session.session_id, "state": str(session.state),
            "ok": not issues, "issues": issues}
