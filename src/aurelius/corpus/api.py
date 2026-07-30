"""FastAPI presentation router for Research Corpus Management System."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from aurelius.corpus.models import (
    CitationEdgeType,
    ClassificationResult,
    CorpusDocument,
    CorpusSearchResult,
    DocumentVersion,
    ProvenanceReport,
    VersionType,
)
from aurelius.corpus.store import CorpusStore
from aurelius.corpus.taxonomy import QuantTaxonomy
from aurelius.infrastructure.config.settings import get_settings

router = APIRouter(prefix="/corpus", tags=["Research Corpus"])

_store_instance: CorpusStore | None = None


def get_corpus_store() -> CorpusStore:
    global _store_instance
    if _store_instance is None:
        settings = get_settings()
        _store_instance = CorpusStore(db_path=settings.corpus_path)
    return _store_instance


# ── Request / Response Models ──────────────────────────────────────────────────


class DocumentAcquireRequest(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    doc_type: str = Field(default="academic_paper")
    authors: list[str] = Field(default_factory=list)
    publication_date: str | None = None
    venue: str | None = None
    doi: str | None = None
    abstract: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddVersionRequest(BaseModel):
    version_type: VersionType = Field(default=VersionType.SUMMARY)
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    created_by: str = Field(default="system")
    diff_summary: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClassifyRequest(BaseModel):
    title: str
    abstract: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddCitationRequest(BaseModel):
    source_id: str
    target_id: str
    edge_type: CitationEdgeType = Field(default=CitationEdgeType.PAPER_REFERENCE)
    description: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/taxonomy", summary="Get Quantitative Finance Taxonomy")
async def get_taxonomy() -> dict[str, Any]:
    """Retrieve full hierarchical taxonomy tree, factor definitions, and statistical methods."""
    return {
        "domains": QuantTaxonomy.DOMAINS,
        "factors": QuantTaxonomy.FACTORS,
        "statistical_methods": QuantTaxonomy.STATISTICAL_METHODS,
    }


@router.post("/documents", response_model=CorpusDocument, summary="Acquire Document")
async def acquire_document(req: DocumentAcquireRequest) -> CorpusDocument:
    """Acquire a new document into the research corpus with automatic multi-dimensional classification."""
    store = get_corpus_store()
    doc = store.add_document(
        title=req.title,
        content=req.content,
        doc_type=req.doc_type,
        authors=req.authors,
        publication_date=req.publication_date,
        venue=req.venue,
        doi=req.doi,
        abstract=req.abstract,
        metadata=req.metadata,
    )
    return doc


@router.get("/documents", response_model=list[CorpusDocument], summary="List Corpus Documents")
async def list_documents(
    domain: str | None = Query(default=None, description="Filter by research domain"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[CorpusDocument]:
    """List documents in the institutional research corpus."""
    store = get_corpus_store()
    return store.list_documents(domain_filter=domain, limit=limit)


@router.get("/documents/{doc_id}", response_model=CorpusDocument, summary="Get Document")
async def get_document(doc_id: str) -> CorpusDocument:
    """Get a document by ID with complete version history."""
    store = get_corpus_store()
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return doc


@router.post(
    "/documents/{doc_id}/versions", response_model=DocumentVersion, summary="Add Document Version"
)
async def add_document_version(doc_id: str, req: AddVersionRequest) -> DocumentVersion:
    """Add a new version artifact to a document (e.g. extracted knowledge, summary, hypothesis)."""
    store = get_corpus_store()
    ver = store.add_version(
        doc_id=doc_id,
        version_type=req.version_type,
        title=req.title,
        content=req.content,
        created_by=req.created_by,
        diff_summary=req.diff_summary,
        metadata=req.metadata,
    )
    if not ver:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return ver


@router.post(
    "/documents/classify", response_model=ClassificationResult, summary="Classify Document Text"
)
async def classify_text(req: ClassifyRequest) -> ClassificationResult:
    """Run automated multi-dimensional classification on arbitrary document text."""
    store = get_corpus_store()
    return store.classifier.classify(req.title, req.abstract, req.content, req.metadata)


@router.post("/citations", summary="Add Citation Edge")
async def add_citation(req: AddCitationRequest) -> dict[str, Any]:
    """Add citation edge tracking literature provenance (paper -> hypothesis, experiment, strategy)."""
    store = get_corpus_store()
    edge = store.add_citation(req.source_id, req.target_id, req.edge_type, req.description)
    return {"status": "ok", "edge_id": edge.id, "edge": edge.model_dump()}


@router.get(
    "/provenance/{target_id}", response_model=ProvenanceReport, summary="Get Citation Provenance"
)
async def get_provenance(
    target_id: str,
    target_type: str = Query(
        default="strategy", description="Entity type: strategy, experiment, hypothesis"
    ),
) -> ProvenanceReport:
    """Retrieve full literature provenance report for a strategy, experiment, or hypothesis."""
    store = get_corpus_store()
    return store.get_provenance_report(target_id, target_type)


@router.get(
    "/search", response_model=list[CorpusSearchResult], summary="Semantic Natural Language Search"
)
async def search_corpus(
    query: str = Query(..., min_length=1, description="Natural language query"),
    domain: str | None = Query(default=None),
    asset_class: str | None = Query(default=None),
    min_quality: float = Query(default=0.0, ge=0.0, le=100.0),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[CorpusSearchResult]:
    """Perform hybrid natural language and semantic search over all corpus documents."""
    store = get_corpus_store()
    return store.search(
        query=query,
        domain_filter=domain,
        asset_class_filter=asset_class,
        min_quality_score=min_quality,
        limit=limit,
    )
