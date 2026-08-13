"""FastAPI Router for Autonomous Alpha Discovery Engine."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from mentisrex.discovery.engine import AlphaDiscoveryEngine
from mentisrex.discovery.models import DiscoveryCycleResult, SynthesisReport

discovery_router = APIRouter(prefix="/discovery", tags=["alpha-discovery"])

_engine: AlphaDiscoveryEngine | None = None


def get_discovery_engine() -> AlphaDiscoveryEngine:
    global _engine
    if _engine is None:
        _engine = AlphaDiscoveryEngine()
    return _engine


class RunCycleRequest(BaseModel):
    candidate_limit: int = 5


@discovery_router.post("/run", response_model=DiscoveryCycleResult)
def run_discovery_cycle(req: RunCycleRequest) -> DiscoveryCycleResult:
    """Trigger an autonomous Alpha Discovery cycle (Synthesize -> Generate -> Score -> Critique -> Submit)."""
    try:
        engine = get_discovery_engine()
        return engine.run_discovery_cycle(candidate_limit=req.candidate_limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@discovery_router.get("/synthesize", response_model=SynthesisReport)
def synthesize_knowledge() -> SynthesisReport:
    """Synthesize knowledge across institutional stores and report research gaps."""
    try:
        engine = get_discovery_engine()
        return engine.synthesizer.synthesize()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@discovery_router.get("/hypotheses", response_model=list[dict])
def list_submitted_hypotheses(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    """Retrieve hypotheses submitted to the Hypothesis Store."""
    try:
        engine = get_discovery_engine()
        records = engine.hypotheses.search(limit=limit)
        return [
            {
                "id": r.id,
                "research_category": r.research_category,
                "statement": r.testable_statement,
                "economic_intuition": r.economic_intuition,
                "confidence_score": r.confidence_score,
                "status": r.status,
                "generation_method": r.generation_method,
            }
            for r in records
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
