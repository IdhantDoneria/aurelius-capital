"""Multi-factor research scoring — Step 1.

Every factor is a pure function returning 0..1 (1 = most favourable for research).
Overall priority is a weighted sum. Weights are calibration knobs, not constants
of nature — tune per desk. The `estimated_research_value` and `diversification`
factors are the two the continuous-learning loop (Step 6) feeds via ResearchContext.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from mentisrex.hypothesis.models import HypothesisRecord

# Factor weights. Sum ≈ 1.0. Research value + novelty dominate: the Director
# optimises long-run research output, not any single backtest.
WEIGHTS: dict[str, float] = {
    "economic_rationale": 0.12,
    "novelty": 0.14,
    "data_availability": 0.10,
    "feature_availability": 0.10,
    "compute_cost": 0.06,  # cheap = high score
    "implementation_complexity": 0.06,  # simple = high score
    "statistical_feasibility": 0.10,
    "estimated_research_value": 0.14,
    "diversification": 0.06,
    "business_impact": 0.12,
}

# Prior accept-rate for a category with no track record yet (weak, optimistic).
_CATEGORY_SUCCESS_PRIOR = 0.15

# Samples-per-year proxy per holding period → statistical feasibility.
# More independent observations = a more testable hypothesis.
_HOLDING_SAMPLES = {
    "intraday": 1.0,
    "1_day": 0.9,
    "daily": 0.9,
    "1_week": 0.7,
    "weekly": 0.7,
    "1_month": 0.5,
    "monthly": 0.5,
    "1_quarter": 0.3,
    "quarterly": 0.3,
    "1_year": 0.15,
    "annual": 0.15,
}
# Compute cost per holding period (higher-frequency = more bars = pricier).
_HOLDING_COST = {
    "intraday": 1.0,
    "1_day": 0.6,
    "daily": 0.6,
    "1_week": 0.4,
    "weekly": 0.4,
    "1_month": 0.25,
    "monthly": 0.25,
    "1_quarter": 0.2,
    "quarterly": 0.2,
    "1_year": 0.15,
    "annual": 0.15,
}

# Keywords that imply an ML/GPU workload → raises compute + complexity.
_ML_HINTS = ("embedding", "neural", "deep", "transformer", "lstm", "nn_", "ml_")


@dataclass
class ResearchContext:
    """Firm state the scorer needs. Built once per prioritisation pass from the
    Knowledge Graph + research history (see director._load_context)."""

    known_datasets: set[str] = field(default_factory=set)  # lowercased labels
    known_features: set[str] = field(default_factory=set)
    category_counts: dict[str, int] = field(default_factory=dict)  # saturation
    category_success: dict[str, float] = field(default_factory=dict)  # accept rate 0..1
    category_trials: dict[str, int] = field(default_factory=dict)
    total_hypotheses: int = 0


@dataclass
class FactorScores:
    economic_rationale: float
    novelty: float
    data_availability: float
    feature_availability: float
    compute_cost: float
    implementation_complexity: float
    statistical_feasibility: float
    estimated_research_value: float
    diversification: float
    business_impact: float
    overall: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _frac_known(required: list[str], known: set[str]) -> float:
    """Fraction of required items present. Empty requirement = 0.5 (neutral/unknown)."""
    if not required:
        return 0.5
    hits = sum(1 for r in required if r.strip().lower() in known)
    return hits / len(required)


def _has_ml(h: HypothesisRecord) -> bool:
    blob = " ".join([*h.required_features, h.testable_statement]).lower()
    return any(k in blob for k in _ML_HINTS)


def score_hypothesis(h: HypothesisRecord, ctx: ResearchContext) -> FactorScores:
    cat = h.research_category or "unknown"
    total = max(ctx.total_hypotheses, 1)

    # Economic rationale: stated confidence + richness of the intuition text.
    richness = _clamp(len(h.economic_intuition) / 280.0)
    economic = _clamp(0.5 * h.confidence_score + 0.5 * richness)

    # Novelty: penalise near-duplicates and over-mined categories.
    dup_pen = 1.0 / (1.0 + len(h.similar_to))
    cat_share = ctx.category_counts.get(cat, 0) / total
    saturation = _clamp(1.0 - cat_share / 0.40)  # >40% of backlog in one cat = saturated
    novelty = _clamp(0.6 * dup_pen + 0.4 * saturation)

    data_av = _frac_known(h.required_datasets, ctx.known_datasets)
    feat_av = _frac_known(h.required_features, ctx.known_features)

    # Compute cost → score (cheap is good, so invert).
    freq_cost = _HOLDING_COST.get(h.holding_period, 0.5)
    breadth_cost = _clamp((len(h.asset_classes) + len(h.required_features)) / 12.0)
    ml_cost = 0.3 if _has_ml(h) else 0.0
    cost = _clamp(0.5 * freq_cost + 0.3 * breadth_cost + ml_cost)
    compute_cost = 1.0 - cost

    # Implementation complexity → score (simple is good, invert).
    complexity = len(h.dependencies) + len(h.required_features) + len(h.validation_requirements)
    if _has_ml(h):
        complexity += 3
    impl = 1.0 / (1.0 + complexity / 6.0)

    stat_feasible = _HOLDING_SAMPLES.get(h.holding_period, 0.5)

    # Estimated research value: category track record + novelty + rationale.
    base = ctx.category_success.get(cat, _CATEGORY_SUCCESS_PRIOR)
    research_value = _clamp(0.4 * base + 0.3 * novelty + 0.3 * economic)

    # Diversification from prior work: reward under-researched categories.
    diversification = _clamp(1.0 - cat_share)

    # Business impact: breadth of applicability x conviction.
    breadth_score = _clamp(len(h.asset_classes) / 3.0)
    business = _clamp(0.5 * h.confidence_score + 0.5 * breadth_score)

    factors = {
        "economic_rationale": economic,
        "novelty": novelty,
        "data_availability": data_av,
        "feature_availability": feat_av,
        "compute_cost": compute_cost,
        "implementation_complexity": impl,
        "statistical_feasibility": stat_feasible,
        "estimated_research_value": research_value,
        "diversification": diversification,
        "business_impact": business,
    }
    overall = _clamp(sum(WEIGHTS[k] * v for k, v in factors.items()))
    return FactorScores(**factors, overall=overall)


def top_drivers(f: FactorScores, n: int = 3) -> list[tuple[str, float]]:
    """Highest weighted contributors — used in decision explanations."""
    contrib = {k: WEIGHTS[k] * v for k, v in f.as_dict().items() if k != "overall"}
    return sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)[:n]


def weakest_factors(f: FactorScores, n: int = 3) -> list[tuple[str, float]]:
    raw = {k: v for k, v in f.as_dict().items() if k != "overall"}
    return sorted(raw.items(), key=lambda kv: kv[1])[:n]


if __name__ == "__main__":
    from datetime import UTC, datetime

    def _mk(**kw) -> HypothesisRecord:
        base = {
            "id": "h",
            "parent_papers": [],
            "research_category": "factor_anomaly",
            "economic_intuition": "x" * 300,
            "testable_statement": "IF a THEN b",
            "expected_behavior": "",
            "asset_classes": ["equities"],
            "required_datasets": ["crsp"],
            "required_features": ["mom_12m"],
            "holding_period": "1_month",
            "expected_risks": [],
            "confidence_score": 0.7,
            "assumptions": [],
            "dependencies": [],
            "validation_requirements": [],
            "similar_to": [],
            "status": "Draft",
            "version": 1,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "researcher": "llm",
            "generation_method": "llm",
        }
        base.update(kw)
        return HypothesisRecord(**base)

    ctx = ResearchContext(
        known_datasets={"crsp"},
        known_features={"mom_12m"},
        category_counts={"factor_anomaly": 5},
        total_hypotheses=10,
        category_success={"factor_anomaly": 0.3},
    )
    fresh = score_hypothesis(_mk(), ctx)
    dupe = score_hypothesis(_mk(similar_to=["a", "b", "c"]), ctx)
    assert 0.0 <= fresh.overall <= 1.0
    assert dupe.novelty < fresh.novelty, "duplicates must score lower novelty"

    # Missing data/features must drag availability to 0.
    missing = score_hypothesis(_mk(required_datasets=["unknown_ds"]), ctx)
    assert missing.data_availability == 0.0
    print("scoring self-check ok:", round(fresh.overall, 3), round(dupe.overall, 3))
