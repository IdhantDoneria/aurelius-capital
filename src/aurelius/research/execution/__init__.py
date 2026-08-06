"""Institutional Research Execution Platform (AIDP Phase 8).

The single orchestrator for every research experiment. Nothing calls the
backtester directly; everything executes through ResearchRunner.
"""

from aurelius.research.execution.hooks import HOOK_POINTS, HookRegistry
from aurelius.research.execution.quality import check
from aurelius.research.execution.runner import ResearchRunner, make_backtest_executor
from aurelius.research.execution.scheduler import Scheduler, sweep_configs
from aurelius.research.execution.session import ResearchSession, RunConfiguration
from aurelius.research.execution.state_machine import State

__all__ = [
    "HOOK_POINTS", "HookRegistry", "ResearchRunner", "ResearchSession",
    "RunConfiguration", "Scheduler", "State", "check", "make_backtest_executor",
    "sweep_configs",
]
