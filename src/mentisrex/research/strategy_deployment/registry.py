"""Strategy registry (AIDP M22).

Stores StrategySpecification objects and their lifecycle state. Follows the same
in-memory pattern used by M7 ExperimentRegistry — one authoritative dict, no DB
dependency. Callers that need persistence serialize via spec.to_dict().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from mentisrex.research.strategy_deployment.models import (
    ALLOWED_TRANSITIONS,
    StrategySpecification,
    StrategyState,
)


class StrategyTransitionError(Exception):
    pass


@dataclass
class StrategyEntry:
    spec: StrategySpecification
    state: StrategyState
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    state_updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    notes: str = ""


class StrategyRegistry:
    """In-memory registry of strategy specifications and lifecycle states."""

    def __init__(self) -> None:
        self._entries: dict[str, StrategyEntry] = {}  # strategy_id -> entry

    # ── write ──────────────────────────────────────────────────────────────────

    def register(
        self,
        spec: StrategySpecification,
        state: StrategyState = StrategyState.DRAFT,
        *,
        notes: str = "",
    ) -> StrategyEntry:
        entry = StrategyEntry(spec=spec, state=state, notes=notes)
        self._entries[spec.strategy_id] = entry
        return entry

    def transition(
        self, strategy_id: str, new_state: StrategyState, *, notes: str = ""
    ) -> StrategyEntry:
        entry = self._get(strategy_id)
        allowed = ALLOWED_TRANSITIONS.get(entry.state, set())
        if new_state not in allowed:
            raise StrategyTransitionError(
                f"{entry.state} → {new_state} is not a valid transition for {strategy_id!r}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        entry.state = new_state
        entry.state_updated_at = datetime.now(UTC).replace(tzinfo=None)
        if notes:
            entry.notes = notes
        return entry

    def update_spec(self, spec: StrategySpecification) -> StrategyEntry:
        """Replace the specification for an existing strategy (version bump)."""
        entry = self._get(spec.strategy_id)
        entry.spec = spec
        entry.state_updated_at = datetime.now(UTC).replace(tzinfo=None)
        return entry

    # ── read ───────────────────────────────────────────────────────────────────

    def get(self, strategy_id: str) -> StrategyEntry | None:
        return self._entries.get(strategy_id)

    def state(self, strategy_id: str) -> StrategyState:
        return self._get(strategy_id).state

    def spec(self, strategy_id: str) -> StrategySpecification:
        return self._get(strategy_id).spec

    def list_strategies(self, *, state: StrategyState | None = None) -> list[StrategyEntry]:
        entries = list(self._entries.values())
        if state is not None:
            entries = [e for e in entries if e.state == state]
        return entries

    # ── helpers ────────────────────────────────────────────────────────────────

    def _get(self, strategy_id: str) -> StrategyEntry:
        entry = self._entries.get(strategy_id)
        if entry is None:
            raise KeyError(f"strategy {strategy_id!r} not found in registry")
        return entry
