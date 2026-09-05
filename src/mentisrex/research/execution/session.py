"""ResearchSession & immutable RunConfiguration (AIDP M8).

A RunConfiguration is a frozen, fully-specified experiment definition (the only
thing needed to execute a run). A ResearchSession owns one run's mutable execution
state — experiment, matrix, report, metrics, artifacts, timings, state machine,
event log. Nothing outside the session mutates that state; the pipeline drives the
session through its transitions and the session records them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from mentisrex.research.execution.event_log import EventLog
from mentisrex.research.execution.hooks import HookRegistry
from mentisrex.research.execution.state_machine import State, StateMachine


@dataclass(frozen=True)
class RunConfiguration:
    """Immutable experiment definition. Everything the platform needs to execute,
    validate, and later reproduce a single run."""

    name: str
    parameters: dict = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    dataset_versions: dict = field(default_factory=dict)
    random_seed: int | None = None
    universe: list[dict] | None = None
    as_of: date | None = None
    description: str = ""
    # dependency-injected executor: (session) -> object with `.metrics`
    # (a backtester PerformanceMetrics). None → the platform's default executor.
    executor: Callable[[Any], Any] | None = None
    benchmark_returns: list[float] | None = None
    artifacts_dir: str | None = None
    policy: str = "fail_fast"  # fail_fast | continue_on_error
    build_matrix: bool = False
    metadata: dict = field(default_factory=dict)


class ResearchSession:
    def __init__(
        self,
        config: RunConfiguration,
        *,
        registry,
        matrix_engine=None,
        hooks: HookRegistry | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.matrix_engine = matrix_engine
        self.hooks = hooks or HookRegistry()
        self.session_id = uuid.uuid4().hex
        self.created_at = datetime.now(UTC)

        self.sm = StateMachine()
        self.events = EventLog()

        # execution artifacts (only the session writes these)
        self.experiment = None
        self.matrix = None
        self.report = None
        self.metrics: dict = {}
        self.artifacts: dict = {}
        self.stage_timings: dict[str, float] = {}
        self.error: str | None = None
        self.traceback: str | None = None
        self._cancel = False

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    def state(self) -> State:
        return self.sm.state

    def transition(self, dst: State, **data) -> None:
        prev = self.sm.state
        self.sm.to(dst)
        self.events.emit("state_transition", stage=dst, from_state=str(prev), **data)

    # ── cancellation (cooperative) ──────────────────────────────────────────────

    def request_cancel(self) -> None:
        self._cancel = True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel

    # ── convenience ─────────────────────────────────────────────────────────────

    @property
    def experiment_id(self) -> str | None:
        return self.experiment.experiment_id if self.experiment else None
