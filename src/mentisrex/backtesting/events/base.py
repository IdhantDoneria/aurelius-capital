"""EventQueue — the deterministic core of the event-driven backtester.

Uses Python's heapq for O(log n) push/pop. Events are ordered by
(timestamp, event_type_int, sequence_number).

sequence_number is a global monotonic counter, guaranteeing total order
even when timestamp and event_type are equal. This makes the simulation
100% reproducible: same data + same strategy = identical sequence.

The queue never holds events from different bars simultaneously in normal
operation. Within one bar, the priority ordering enforces:
  Fill(1) → Market(2) → Signal(3) → Order(4)
"""

import heapq
import itertools
from typing import Any

_GLOBAL_SEQ: itertools.count = itertools.count()


class EventQueue:
    """Priority queue for backtest events."""

    __slots__ = ("_heap",)

    def __init__(self) -> None:
        self._heap: list[tuple] = []

    def push(self, event: Any) -> None:
        # Tuple comparison: timestamp first (datetime supports <), then event_type int,
        # then seq. We never reach the event object itself in comparison.
        heapq.heappush(
            self._heap,
            (event.timestamp, event.EVENT_TYPE, event._seq, event),
        )

    def pop(self) -> Any:
        _, _, _, event = heapq.heappop(self._heap)
        return event

    def empty(self) -> bool:
        return not self._heap

    def __len__(self) -> int:
        return len(self._heap)
