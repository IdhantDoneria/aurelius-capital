"""Research Director REST API — FastAPI router (Step 7 backend)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from aurelius.core.logging import get_logger
from aurelius.director.director import ResearchDirector

logger = get_logger(__name__)
router = APIRouter(prefix="/director", tags=["research-director"])

_rd: ResearchDirector | None = None


def _get_rd() -> ResearchDirector:
    global _rd
    if _rd is None:
        _rd = ResearchDirector()
    return _rd


@router.get("/priorities", summary="Ranked backlog with per-hypothesis decisions")
async def priorities(
    include_terminal: bool = Query(False, description="Include archived/rejected/promoted"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return [r.summary() for r in _get_rd().prioritize(include_terminal=include_terminal)[:limit]]


@router.get("/gaps", summary="Research gap analysis")
async def gaps() -> dict[str, Any]:
    return _get_rd().gap_analysis()


@router.get("/roadmap", summary="Daily / weekly / monthly / quarterly research queues")
async def roadmap() -> dict[str, Any]:
    return _get_rd().roadmap()


@router.get("/learning", summary="Continuous-learning stats feeding the scorer")
async def learning() -> dict[str, Any]:
    return _get_rd().learning_stats()


@router.get("/dashboard", summary="Aggregate view: backlog, priorities, utilization, velocity")
async def dashboard() -> dict[str, Any]:
    return _get_rd().dashboard()
