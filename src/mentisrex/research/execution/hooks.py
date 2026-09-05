"""Pluggable hook system (AIDP M8).

Named extension points fired around each pipeline stage. Plugins register
callables `(session) -> None`; the platform stays closed for modification, open
for extension. Hook exceptions surface under the run's error policy (fail-fast by
default), so a broken plugin can't silently corrupt a run.
"""

from __future__ import annotations

from collections.abc import Callable

HOOK_POINTS = (
    "before_validation",
    "after_validation",
    "before_matrix",
    "after_matrix",
    "before_backtest",
    "after_backtest",
    "before_metrics",
    "after_metrics",
    "before_registry_close",
)


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = {p: [] for p in HOOK_POINTS}

    def register(self, point: str, fn: Callable) -> None:
        if point not in self._hooks:
            raise ValueError(f"unknown hook point: {point}")
        self._hooks[point].append(fn)

    def fire(self, point: str, session) -> None:
        for fn in self._hooks.get(point, []):
            fn(session)
