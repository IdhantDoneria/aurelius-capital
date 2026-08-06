"""Execution platform exceptions (AIDP Phase 8)."""

from __future__ import annotations


class ExecutionError(Exception):
    """Base for all execution-platform errors."""


class ValidationError(ExecutionError):
    """Pre-execution validation failed; the run must abort before any side effect."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(f"validation failed: {', '.join(issues)}")


class StateTransitionError(ExecutionError):
    """Illegal state-machine transition requested."""


class CancelledError(ExecutionError):
    """The session was cancelled cooperatively."""
