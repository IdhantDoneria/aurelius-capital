"""Local execution scheduler (AIDP M8).

Generates RunConfigurations from a base config and drives them through the runner.
Single, batch, parameter sweep, walk-forward, and rolling-window sequences. No
distributed execution — each run is local and synchronous, but configs are the
unit of parallelism a future distributed backend would consume.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import date

from mentisrex.research.execution.session import RunConfiguration
from mentisrex.research.execution.state_machine import State


class Scheduler:
    def __init__(self, runner) -> None:
        self._runner = runner

    def single(self, config: RunConfiguration):
        return [self._runner.run(config)]

    def batch(self, configs: list[RunConfiguration], *, policy: str = "continue_on_error"):
        sessions = []
        for cfg in configs:
            s = self._runner.run(cfg)
            sessions.append(s)
            if policy == "fail_fast" and s.state == State.FAILED:
                break
        return sessions

    # ── config generators ───────────────────────────────────────────────────────

    def parameter_sweep(self, base: RunConfiguration, grid: dict[str, list], **kw):
        return self.batch(sweep_configs(base, grid), **kw)

    def walk_forward(self, base: RunConfiguration, as_of_dates: list[date], **kw):
        configs = [replace(base, as_of=d, name=f"{base.name}@wf:{d.isoformat()}")
                   for d in as_of_dates]
        return self.batch(configs, **kw)

    def rolling_window(self, base: RunConfiguration, as_of_dates: list[date],
                       lookback_days: int, **kw):
        configs = [replace(base, as_of=d, name=f"{base.name}@roll:{d.isoformat()}",
                           parameters={**base.parameters, "lookback_days": lookback_days})
                   for d in as_of_dates]
        return self.batch(configs, **kw)


def sweep_configs(base: RunConfiguration, grid: dict[str, list]) -> list[RunConfiguration]:
    """Cartesian product of the grid, each a config with base.parameters overridden."""
    keys = list(grid)
    out = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        overrides = dict(zip(keys, combo, strict=True))
        tag = ",".join(f"{k}={v}" for k, v in overrides.items())
        out.append(replace(base, parameters={**base.parameters, **overrides},
                           name=f"{base.name}[{tag}]"))
    return out
