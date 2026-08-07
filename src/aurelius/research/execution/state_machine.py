"""Research session state machine (AIDP M8).

Linear happy path with failure/cancel escapes from any active state. Every
transition is validated against the allowed graph; the caller logs it. No
execution state is mutated outside a legal transition.
"""

from __future__ import annotations

import enum

from aurelius.research.execution.exceptions import StateTransitionError


class State(enum.StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    BUILDING_MATRIX = "BUILDING_MATRIX"
    RUNNING = "RUNNING"
    GENERATING_METRICS = "GENERATING_METRICS"
    WRITING_ARTIFACTS = "WRITING_ARTIFACTS"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset({State.COMPLETED, State.FAILED, State.CANCELLED})

# happy-path successor for each active state
_NEXT = {
    State.CREATED: State.VALIDATING,
    State.VALIDATING: State.BUILDING_MATRIX,
    State.BUILDING_MATRIX: State.RUNNING,
    State.RUNNING: State.GENERATING_METRICS,
    State.GENERATING_METRICS: State.WRITING_ARTIFACTS,
    State.WRITING_ARTIFACTS: State.FINALIZING,
    State.FINALIZING: State.COMPLETED,
}

_ACTIVE = frozenset(_NEXT) | {State.CREATED}


def allowed(src: State, dst: State) -> bool:
    if src in TERMINAL:
        return False
    if dst in (State.FAILED, State.CANCELLED):
        return True  # any active state may fail or cancel
    return _NEXT.get(src) == dst


class StateMachine:
    """Holds the current state; `advance()` walks the happy path, `to()` forces a
    specific (legal) transition. Illegal transitions raise."""

    def __init__(self, state: State = State.CREATED) -> None:
        self.state = state

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL

    def next_state(self) -> State | None:
        return _NEXT.get(self.state)

    def to(self, dst: State) -> State:
        if not allowed(self.state, dst):
            raise StateTransitionError(f"{self.state} → {dst} not allowed")
        self.state = dst
        return dst

    def advance(self) -> State:
        nxt = _NEXT.get(self.state)
        if nxt is None:
            raise StateTransitionError(f"no successor for {self.state}")
        return self.to(nxt)
