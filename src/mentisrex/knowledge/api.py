"""Knowledge Graph REST API — FastAPI router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from mentisrex.core.logging import get_logger
from mentisrex.knowledge.graph import KnowledgeGraph
from mentisrex.knowledge.ingest import ingest_all

logger = get_logger(__name__)
router = APIRouter(prefix="/kg", tags=["knowledge-graph"])

_kg: KnowledgeGraph | None = None


def _get_kg() -> KnowledgeGraph:
    global _kg
    if _kg is None:
        from mentisrex.infrastructure.config.settings import get_settings

        _kg = KnowledgeGraph(get_settings().knowledge_graph_path)
    return _kg


class IngestResult(BaseModel):
    ingested: dict[str, int]


# ── Read ──────────────────────────────────────────────────────────────────────


@router.get("/stats", summary="Node/edge counts and weekly growth")
async def kg_stats() -> dict[str, Any]:
    return _get_kg().stats()


@router.get("/qc", summary="Quality control report")
async def kg_qc() -> dict[str, Any]:
    return _get_kg().qc_report()


@router.get("/search", summary="Full-text search across all entity types")
async def kg_search(
    q: str = Query(..., min_length=2, description="Natural language query"),
    node_type: str | None = Query(
        None, description="Filter: paper|hypothesis|experiment|feature|…"
    ),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return _get_kg().search(q, node_type=node_type, limit=limit)


@router.get(
    "/semantic-search", summary="Cosine-similarity vector search (requires sentence-transformers)"
)
async def kg_semantic_search(
    q: str = Query(..., min_length=2),
    node_type: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return _get_kg().semantic_search(q, node_type=node_type, limit=limit)


@router.get("/nodes/{node_id}", summary="Node detail + optional neighbors")
async def kg_node(
    node_id: str,
    neighbors: bool = Query(True, description="Include direct neighbors"),
) -> dict[str, Any]:
    node = _get_kg().get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if neighbors:
        node["neighbors"] = _get_kg().get_neighbors(node_id)
    return node


@router.get("/nodes/{node_id}/history", summary="Full version history for a node")
async def kg_node_history(node_id: str) -> list[dict[str, Any]]:
    return _get_kg().node_history(node_id)


@router.get("/graph", summary="BFS subgraph for visualization (Cytoscape.js / D3 compatible)")
async def kg_subgraph(
    root_id: str = Query(..., description="Starting node ID"),
    depth: int = Query(2, ge=1, le=4, description="Hop depth"),
) -> dict[str, Any]:
    return _get_kg().traverse(root_id, depth=depth)


# ── Discovery ─────────────────────────────────────────────────────────────────


@router.get("/discover/failures", summary="Repeated failure patterns across hypotheses")
async def discover_failures() -> list[dict[str, Any]]:
    return _get_kg().discover_repeated_failures()


@router.get("/discover/features", summary="Features correlated with accepted experiments")
async def discover_features() -> list[dict[str, Any]]:
    return _get_kg().discover_successful_feature_families()


@router.get("/discover/gaps", summary="Datasets cited in papers but never tested")
async def discover_gaps() -> list[dict[str, Any]]:
    return _get_kg().discover_research_gaps()


@router.get("/discover/orphans", summary="Nodes with zero edges (disconnected)")
async def discover_orphans() -> list[dict[str, Any]]:
    return _get_kg().discover_orphans()


@router.get("/discover/methodologies", summary="Most frequently cited methodologies")
async def discover_methodologies() -> list[dict[str, Any]]:
    return _get_kg().discover_frequent_methodologies()


@router.get("/discover/similar-failures", summary="Experiments that failed for similar reasons")
async def discover_similar_failures(
    keywords: str = Query(
        ..., description="Comma-separated keywords, e.g. 'overfitting,data_snooping'"
    ),
) -> list[dict[str, Any]]:
    return _get_kg().discover_similar_failures([k.strip() for k in keywords.split(",")])


# ── Write ─────────────────────────────────────────────────────────────────────


@router.post("/ingest", response_model=IngestResult, summary="Sync all sources into the KG")
async def kg_ingest() -> dict[str, Any]:
    ingested = ingest_all(_get_kg())
    return {"ingested": ingested}


@router.post("/embed", summary="Generate embeddings for all unembedded nodes")
async def kg_embed() -> dict[str, Any]:
    count = _get_kg().embed_all_nodes()
    coverage = _get_kg().embedding_coverage()
    return {"newly_embedded": count, "coverage": coverage}


@router.get("/embed/coverage", summary="Embedding coverage stats")
async def kg_embed_coverage() -> dict[str, Any]:
    return _get_kg().embedding_coverage()


# ── Escape hatch (internal only) ──────────────────────────────────────────────


@router.get("/query", summary="Raw DuckDB SQL on kg_nodes / kg_edges / kg_node_history")
async def kg_raw_query(
    sql: str = Query(..., description="SELECT only — internal research tooling"),
) -> list[dict[str, Any]]:
    if not sql.strip().upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT statements allowed")
    try:
        return _get_kg().raw_query(sql)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
