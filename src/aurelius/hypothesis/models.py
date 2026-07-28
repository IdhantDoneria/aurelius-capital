"""HypothesisRecord — structured output of the Hypothesis Generation Framework."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class HypothesisRecord:
    # Identity
    id: str                               # uuid4
    parent_papers: list[str]              # paper IDs from LiteratureStore

    # Research context
    research_category: str                # factor_anomaly, macro, portfolio_construction, …
    economic_intuition: str               # WHY this should be a profitable strategy
    testable_statement: str               # "IF [condition] THEN [outcome] AMONG [universe] OVER [horizon]"
    expected_behavior: str                # what to observe in the data

    # Scope
    asset_classes: list[str]
    required_datasets: list[str]
    required_features: list[str]
    holding_period: str                   # e.g. "1_month", "1_week", "1_day"

    # Risk and uncertainty
    expected_risks: list[str]
    confidence_score: float               # 0.0–1.0
    assumptions: list[str]
    dependencies: list[str]              # prerequisite factors or hypotheses
    validation_requirements: list[str]

    # Lifecycle
    status: str                           # Draft | Active | Rejected | Promoted
    version: int
    created_at: datetime
    updated_at: datetime
    researcher: str                       # "llm", "template", or human name
    generation_method: str               # llm | template | manual

    # Duplicate detection
    similar_to: list[str] = field(default_factory=list)  # hypothesis IDs of near-duplicates

    # Rejection info
    rejection_reason: str = ""           # set when status=Rejected
