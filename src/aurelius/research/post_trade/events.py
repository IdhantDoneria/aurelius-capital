"""Event log (AIDP M15).

The append-only, globally-sequenced spine of the post-trade engine. Every lifecycle
fact — trade booked, position moved, cash posted, settlement completed, corporate
action applied — lands here as an immutable event. Nothing is mutated or reordered,
so a session is fully replayable: re-applying the events in `seq` order reproduces the
state. Same pattern as the M14 OMS audit trail, generalised to all post-trade events.
"""

from __future__ import annotations


class EventLog:
    def __init__(self) -> None:
        self._events: list = []
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def append(self, event) -> None:
        self._events.append(event)

    def emit(self, factory) -> object:
        """`factory(seq) -> event`; appends and returns the built event."""
        ev = factory(self.next_seq())
        self._events.append(ev)
        return ev

    @property
    def events(self) -> list:
        return list(self._events)

    def of_type(self, cls) -> list:
        return [e for e in self._events if isinstance(e, cls)]

    def replay(self, handler) -> None:
        """Feed every event, in order, to `handler(event)` — deterministic recovery."""
        for e in self._events:
            handler(e)

    def __len__(self) -> int:
        return len(self._events)
