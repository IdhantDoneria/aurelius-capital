"""Institutional Research Execution Platform (AIDP M8).

The single orchestrator for every research experiment. Nothing calls the
backtester directly; everything executes through ResearchRunner.
"""

from mentisrex.research.execution.hooks import HOOK_POINTS, HookRegistry
from mentisrex.research.execution.quality import check
from mentisrex.research.execution.runner import ResearchRunner, make_backtest_executor
from mentisrex.research.execution.scheduler import Scheduler, sweep_configs
from mentisrex.research.execution.session import ResearchSession, RunConfiguration
from mentisrex.research.execution.state_machine import State

__all__ = [
    "HOOK_POINTS",
    "HookRegistry",
    "ResearchRunner",
    "ResearchSession",
    "RunConfiguration",
    "Scheduler",
    "State",
    "check",
    "make_backtest_executor",
    "sweep_configs",
]
