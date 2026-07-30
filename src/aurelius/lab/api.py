"""Autonomous Research Laboratory REST API — FastAPI router (Phase 18).

Exposes the Supervisor and Monitor. Triggering a cycle is a heavy, mutating
operation, so `/lab/run` is a POST and runs synchronously (one cycle, then
returns its audit summary). Continuous operation is driven by an external
scheduler calling this endpoint, or by `Supervisor.run_forever` in a worker.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from aurelius.core.logging import get_logger
from aurelius.lab.monitor import LabMonitor
from aurelius.lab.supervisor import Supervisor

logger = get_logger(__name__)
router = APIRouter(prefix="/lab", tags=["research-laboratory"])

_sup: Supervisor | None = None


def _get_sup() -> Supervisor:
    global _sup
    if _sup is None:
        # Default install: no paper source, no bars provider → discovery + execution
        # steps skip with a stated reason until those seams are wired. Honest by default.
        _sup = Supervisor()
    return _sup


@router.post("/run", summary="Run one full research cycle (synchronous); returns audit summary")
async def run_cycle() -> dict[str, Any]:
    return _get_sup().run_cycle()


@router.get("/status", summary="Config + last cycle summary")
async def status() -> dict[str, Any]:
    sup = _get_sup()
    return {
        "configured": {
            "paper_source": sup.paper_source is not None,
            "bars_provider": sup.bars_provider is not None,
            "llm": sup.llm is not None,
            "cycle_budget_min": sup.cycle_budget_min,
            "report_periods": list(sup.report_periods),
        },
        "last_cycle": sup.last_cycle,
    }


@router.get("/monitor", summary="Full monitoring snapshot across every subsystem")
async def monitor() -> dict[str, Any]:
    return LabMonitor(_get_sup()).snapshot()


@router.get("/cycles", summary="Recent cycle summaries from the audit trail")
async def cycles(n: int = Query(10, ge=1, le=100)) -> list[dict[str, Any]]:
    return _get_sup().journal.recent_cycles(n)


@router.get("/audit", summary="Full audit trail for a cycle")
async def audit(
    cycle_id: str = Query(..., description="Cycle id from /lab/run or /lab/cycles"),
) -> list[dict[str, Any]]:
    return _get_sup().journal.read(cycle_id=cycle_id)
