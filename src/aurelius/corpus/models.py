"""Data models for Research Corpus & Institutional Knowledge Management System."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class DocumentType(StrEnum):
    ACADEMIC_PAPER = "academic_paper"
    BOOK = "book"
    CONFERENCE_PROCEEDING = "conference_proceeding"
    WORKING_PAPER = "working_paper"
    RESEARCH_BLOG = "research_blog"
    MARKET_MICROSTRUCTURE = "market_microstructure"
    STATISTICAL_METHODOLOGY = "statistical_methodology"
    ECONOMETRICS = "econometrics"
    MACHINE_LEARNING = "machine_learning"
    OPTIMIZATION = "optimization"
    PORTFOLIO_THEORY = "portfolio_theory"
    RISK_MANAGEMENT = "risk_management"
    ALTERNATIVE_DATA = "alternative_data"
    ECONOMIC_RESEARCH = "economic_research"
    BEHAVIORAL_FINANCE = "behavioral_finance"
    EXECUTION_RESEARCH = "execution_research"


class AssetClass(StrEnum):
    EQUITY = "equity"
    FX = "fx"
    FIXED_INCOME = "fixed_income"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    DERIVATIVE = "derivative"
    MULTI_ASSET = "multi_asset"


class Market(StrEnum):
    US_EQUITIES = "us_equities"
    GLOBAL_EQUITIES = "global_equities"
    US_TREASURIES = "us_treasuries"
    GLOBAL_FX = "global_fx"
    COMMODITIES_FUTURES = "commodities_futures"
    CRYPTO_PERPETUALS = "crypto_perpetuals"
    OPTIONS_VOLATILITY = "options_volatility"
    HIGH_FREQUENCY = "high_frequency"


class VersionType(StrEnum):
    ORIGINAL = "original"
    EXTRACTED_KNOWLEDGE = "extracted_knowledge"
    SUMMARY = "summary"
    GENERATED_HYPOTHESIS = "generated_hypothesis"
    DERIVED_FEATURE = "derived_feature"
    EXPERIMENT_REFERENCE = "experiment_reference"


class ClassificationResult(BaseModel):
    research_domain: str = Field(..., description="Primary domain from taxonomy")
    subdomain: str = Field(default="general", description="Subdomain topic")
    asset_classes: list[AssetClass] = Field(default_factory=list)
    methodology: str = Field(default="empirical", description="Methodology type")
    statistical_methods: list[str] = Field(default_factory=list)
    markets: list[Market] = Field(default_factory=list)
    factors: list[str] = Field(default_factory=list)
    difficulty: int = Field(default=3, ge=1, le=5, description="Technical difficulty scale 1-5")
    novelty: int = Field(default=3, ge=1, le=5, description="Novelty scale 1-5")
    quality_score: float = Field(default=75.0, ge=0.0, le=100.0, description="Quality score 0-100")
    reasoning: str = Field(default="", description="Classification justification")


class DocumentVersion(BaseModel):
    id: str = Field(default_factory=lambda: f"ver_{uuid4().hex[:12]}")
    doc_id: str = Field(..., description="Parent document ID")
    version_num: int = Field(default=1, ge=1)
    version_type: VersionType = Field(default=VersionType.ORIGINAL)
    title: str = Field(..., description="Version title or label")
    content: str = Field(..., description="Text payload or summary")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    created_by: str = Field(default="system")
    parent_version_id: str | None = Field(default=None)
    diff_summary: str = Field(default="Initial version created")


class CorpusDocument(BaseModel):
    id: str = Field(default_factory=lambda: f"doc_{uuid4().hex[:12]}")
    title: str = Field(..., min_length=1)
    doc_type: DocumentType = Field(default=DocumentType.ACADEMIC_PAPER)
    authors: list[str] = Field(default_factory=list)
    publication_date: str | None = Field(default=None)
    venue: str | None = Field(default=None)
    doi: str | None = Field(default=None)
    abstract: str = Field(default="")
    full_text_url: str | None = Field(default=None)
    classification: ClassificationResult | None = Field(default=None)
    current_version: int = Field(default=1)
    versions: list[DocumentVersion] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class CitationEdgeType(StrEnum):
    HYPOTHESIS_ORIGIN = "hypothesis_origin"
    EXPERIMENT_CITE = "experiment_cite"
    STRATEGY_SUPPORT = "strategy_support"
    PAPER_REFERENCE = "paper_reference"


class CitationEdge(BaseModel):
    id: str = Field(default_factory=lambda: f"cite_{uuid4().hex[:12]}")
    source_id: str = Field(..., description="Document ID or entity ID citing target")
    target_id: str = Field(..., description="Document ID or entity ID cited")
    edge_type: CitationEdgeType = Field(default=CitationEdgeType.PAPER_REFERENCE)
    description: str = Field(default="")
    created_at: datetime = Field(default_factory=_now)


class ProvenanceReport(BaseModel):
    target_id: str = Field(
        ..., description="ID of entity being queried (e.g. strategy, experiment, hypothesis)"
    )
    target_type: str = Field(..., description="Entity type: strategy, experiment, hypothesis")
    supporting_papers: list[dict[str, Any]] = Field(default_factory=list)
    supporting_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    supporting_experiments: list[dict[str, Any]] = Field(default_factory=list)
    lineage_path: list[str] = Field(default_factory=list)


class CorpusSearchResult(BaseModel):
    doc_id: str
    title: str
    doc_type: DocumentType
    classification: ClassificationResult | None = None
    score: float = Field(..., description="Relevance or similarity score")
    snippet: str = ""
    match_type: str = Field(default="hybrid", description="semantic, bm25, or hybrid")
