"""Structured execution event log (AIDP M8).

Every important event is a typed, timestamped `Event` object (not a string), so the
log is machine-readable — queryable by stage, serializable into the run manifest,
and carries structured data. Also mirrored to the platform logger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aurelius.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Event:
    name: str
    stage: str                       # the State the session was in
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "stage": self.stage,
                "timestamp": self.timestamp.isoformat(), "data": self.data}


class EventLog:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, name: str, stage: str, **data: Any) -> Event:
        ev = Event(name=name, stage=stage, timestamp=datetime.now(UTC), data=data)
        self._events.append(ev)
        logger.info("execution_event", event_name=name, event_stage=stage, **data)
        return ev

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def by_name(self, name: str) -> list[Event]:
        return [e for e in self._events if e.name == name]

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self._events]
