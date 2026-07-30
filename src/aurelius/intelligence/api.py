"""Research Intelligence REST API — FastAPI router (Phase 17)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from aurelius.core.logging import get_logger
from aurelius.intelligence.engine import _PERIOD_DAYS, ResearchIntelligence
from aurelius.paper.outcomes import PaperOutcome

logger = get_logger(__name__)
router = APIRouter(prefix="/intel", tags=["research-intelligence"])

_intel: ResearchIntelligence | None = None


def _get_intel() -> ResearchIntelligence:
    global _intel
    if _intel is None:
        _intel = ResearchIntelligence()
    return _intel


@router.get("/meta", summary="Meta-analysis: category/feature/test/dataset/regime evidence")
async def meta() -> dict[str, Any]:
    return _get_intel().meta_analysis()


@router.get("/recommendations", summary="Evidence-cited research recommendations")
async def recommendations() -> list[dict[str, Any]]:
    return _get_intel().recommendations()


@router.get("/trends", summary="Long-term trends across research productivity/quality/debt")
async def trends() -> dict[str, Any]:
    return _get_intel().trends()


@router.get("/self-evaluation", summary="Firm research self-evaluation metrics")
async def self_evaluation() -> dict[str, Any]:
    return _get_intel().self_evaluation()


@router.get("/report/{period}", summary="Periodic report (daily|weekly|monthly|quarterly|annual)")
async def report(
    period: str = Path(..., description="daily|weekly|monthly|quarterly|annual"),
) -> dict[str, Any]:
    if period not in _PERIOD_DAYS:
        raise HTTPException(400, f"period must be one of {list(_PERIOD_DAYS)}")
    return _get_intel().report(period)


@router.get(
    "/report/{period}/markdown",
    summary="Periodic report as rendered markdown",
    response_class=PlainTextResponse,
)
async def report_markdown(period: str) -> str:
    if period not in _PERIOD_DAYS:
        raise HTTPException(400, f"period must be one of {list(_PERIOD_DAYS)}")
    return _get_intel().report(period)["markdown"]


# ── Paper-trading outcome ingestion (the validation→live loop) ──────────────────


class PaperOutcomeIn(BaseModel):
    hypothesis_id: str
    strategy_name: str
    outcome: PaperOutcome  # running | confirmed | degraded | failed
    regime: str | None = None
    paper_sharpe: float | None = None
    paper_return: float | None = None
    paper_max_drawdown: float | None = None
    live_days: int | None = Field(None, ge=0)
    backtest_sharpe: float | None = None
    notes: str = ""


@router.post("/paper-outcome", summary="Record a paper-trading outcome for a hypothesis")
async def record_paper_outcome(body: PaperOutcomeIn) -> dict[str, str]:
    oid = _get_intel().paper.record(
        body.hypothesis_id,
        body.strategy_name,
        body.outcome,
        regime=body.regime,
        paper_sharpe=body.paper_sharpe,
        paper_return=body.paper_return,
        paper_max_drawdown=body.paper_max_drawdown,
        live_days=body.live_days,
        backtest_sharpe=body.backtest_sharpe,
        notes=body.notes,
    )
    return {"id": oid}


@router.get("/paper-outcomes", summary="All recorded paper-trading outcomes")
async def paper_outcomes() -> list[dict[str, Any]]:
    return _get_intel().paper.all()
