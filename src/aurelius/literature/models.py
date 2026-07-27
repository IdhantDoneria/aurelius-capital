"""Paper dataclass — atomic unit of the Literature Intelligence Framework."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime


def paper_id(source: str, source_id: str) -> str:
    """Deterministic ID: first 32 hex chars of sha256(source:source_id)."""
    return hashlib.sha256(f"{source}:{source_id}".encode()).hexdigest()[:32]


@dataclass
class Paper:
    id: str
    source: str       # arxiv | nber | ssrn | jf | jfe | rfs | qf
    source_id: str    # arxiv abs ID, DOI, NBER handle
    title: str
    authors: list[str]
    published_at: date | None
    abstract: str
    url: str
    ingested_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Enriched fields — populated by enrichment.enrich()
    keywords: list[str] = field(default_factory=list)
    asset_classes: list[str] = field(default_factory=list)
    research_category: str = ""
    methodology: str = ""
    datasets: list[str] = field(default_factory=list)
    factors_studied: list[str] = field(default_factory=list)
    statistical_techniques: list[str] = field(default_factory=list)
    main_conclusions: str = ""
    limitations: str = ""
    enriched: bool = False
