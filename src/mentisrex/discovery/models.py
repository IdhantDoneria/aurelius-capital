"""Data models for Autonomous Alpha Discovery Engine."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class DiscoveryHypothesis(BaseModel):
    id: str = Field(default_factory=lambda: f"alpha_hyp_{uuid4().hex[:12]}")
    title: str = Field(..., min_length=1)
    research_category: str = Field(default="factor_anomaly")
    economic_intuition: str = Field(...)
    testable_statement: str = Field(...)
    expected_behavior: str = Field(...)
    why_it_exists: str = Field(...)
    why_it_might_fail: str = Field(...)
    supporting_literature: list[str] = Field(default_factory=list)
    contradicting_literature: list[str] = Field(default_factory=list)
    required_datasets: list[str] = Field(default_factory=list)
    required_features: list[str] = Field(default_factory=list)
    holding_period: str = Field(default="1_month")
    asset_classes: list[str] = Field(default_factory=lambda: ["equities"])
    validation_plan: list[str] = Field(default_factory=list)
    expected_weaknesses: list[str] = Field(default_factory=list)
    generation_rule: str = Field(default="factor_combination")
    status: str = Field(default="Proposed", description="Proposed, Approved, Rejected")
    rejection_reason: str = Field(default="")
    created_at: datetime = Field(default_factory=_now)


class SynthesisReport(BaseModel):
    common_themes: list[str] = Field(default_factory=list)
    missing_feature_combinations: list[dict[str, Any]] = Field(default_factory=list)
    untested_factor_combinations: list[dict[str, Any]] = Field(default_factory=list)
    contradictory_findings: list[str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    emerging_trends: list[str] = Field(default_factory=list)
    synthesized_at: datetime = Field(default_factory=_now)


class NoveltyScore(BaseModel):
    hypothesis_id: str
    novelty: int = Field(default=3, ge=1, le=5)
    similarity_to_previous: float = Field(default=0.0, ge=0.0, le=1.0)
    research_value: float = Field(default=50.0, ge=0.0, le=100.0)
    economic_rationale: int = Field(default=3, ge=1, le=5)
    testability: int = Field(default=3, ge=1, le=5)
    expected_compute_cost: int = Field(default=2, ge=1, le=5)
    potential_impact: float = Field(default=50.0, ge=0.0, le=100.0)
    explanation: str = Field(default="")


class SelfCritiqueReport(BaseModel):
    hypothesis_id: str
    counter_arguments: list[str] = Field(default_factory=list)
    falsification_tests: list[str] = Field(default_factory=list)
    competing_explanations: list[str] = Field(default_factory=list)
    survived_critique: bool = Field(default=True)
    critique_score: float = Field(default=75.0, ge=0.0, le=100.0)
    verdict_reason: str = Field(default="")


class DiscoveryCycleResult(BaseModel):
    cycle_id: str = Field(default_factory=lambda: f"cycle_{uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=_now)
    synthesis: SynthesisReport
    candidates_generated: int = Field(default=0)
    approved_hypotheses: list[DiscoveryHypothesis] = Field(default_factory=list)
    rejected_hypotheses: list[DiscoveryHypothesis] = Field(default_factory=list)
