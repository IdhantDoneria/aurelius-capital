"""Unit tests for duplicate detection."""

import pytest

from mentisrex.hypothesis.deduplication import DuplicateStatus, _jaccard, _tokens, check_duplicates


@pytest.mark.unit
def test_jaccard_identical():
    assert _jaccard("momentum premium equities", "momentum premium equities") == 1.0


@pytest.mark.unit
def test_jaccard_disjoint():
    assert _jaccard("momentum equities", "value bonds") == 0.0


@pytest.mark.unit
def test_jaccard_partial():
    sim = _jaccard("momentum premium equities returns", "momentum value equities factor")
    assert 0.0 < sim < 1.0


@pytest.mark.unit
def test_jaccard_empty():
    assert _jaccard("", "something") == 0.0
    assert _jaccard("something", "") == 0.0


@pytest.mark.unit
def test_tokens_strips_stopwords():
    tokens = _tokens("IF the momentum signal is in top decile THEN returns are positive")
    assert "if" not in tokens
    assert "the" not in tokens
    assert "returns" not in tokens  # high-frequency domain word → stopword
    assert "momentum" in tokens
    assert "decile" in tokens


@pytest.mark.unit
def test_unique_hypothesis():
    existing = [("id1", "IF value signal high THEN bonds outperform OVER 3_months")]
    from datetime import UTC, datetime

    from mentisrex.hypothesis.models import HypothesisRecord

    now = datetime.now(UTC)
    h = HypothesisRecord(
        id="new-id",
        parent_papers=["p1"],
        research_category="macro",
        economic_intuition="Different logic.",
        testable_statement="IF volatility spikes THEN gold returns positive OVER 1_week",
        expected_behavior="Gold outperforms.",
        asset_classes=["commodities"],
        required_datasets=["Bloomberg"],
        required_features=["vix"],
        holding_period="1_week",
        expected_risks=["liquidity"],
        confidence_score=0.6,
        assumptions=[],
        dependencies=[],
        validation_requirements=[],
        status="Draft",
        version=1,
        created_at=now,
        updated_at=now,
        researcher="llm",
        generation_method="llm",
    )
    result = check_duplicates(h, existing)
    assert result.status == DuplicateStatus.UNIQUE


@pytest.mark.unit
def test_near_duplicate_detection():
    stmt = (
        "IF 12-1 momentum signal is in top decile "
        "THEN equity returns are positive OVER 1_month AMONG US stocks"
    )
    existing = [("id1", stmt)]
    from datetime import UTC, datetime

    from mentisrex.hypothesis.models import HypothesisRecord

    now = datetime.now(UTC)
    h = HypothesisRecord(
        id="new-id",
        parent_papers=["p1"],
        research_category="factor_anomaly",
        economic_intuition="Momentum.",
        testable_statement=(
            "IF 12-1 momentum signal is in top decile "
            "THEN equity returns positive OVER 1_month AMONG US stocks"
        ),
        expected_behavior="Top decile outperforms.",
        asset_classes=["equities"],
        required_datasets=["CRSP"],
        required_features=["momentum"],
        holding_period="1_month",
        expected_risks=[],
        confidence_score=0.7,
        assumptions=[],
        dependencies=[],
        validation_requirements=[],
        status="Draft",
        version=1,
        created_at=now,
        updated_at=now,
        researcher="llm",
        generation_method="llm",
    )
    result = check_duplicates(h, existing)
    assert result.status in (DuplicateStatus.NEAR_DUPLICATE, DuplicateStatus.DUPLICATE)
    assert "id1" in result.similar_ids


@pytest.mark.unit
def test_exact_duplicate_detection():
    stmt = "IF momentum factor top decile THEN future returns positive AMONG equities OVER 1_month"
    existing = [("id1", stmt)]
    from datetime import UTC, datetime

    from mentisrex.hypothesis.models import HypothesisRecord

    now = datetime.now(UTC)
    h = HypothesisRecord(
        id="new-id",
        parent_papers=["p1"],
        research_category="factor_anomaly",
        economic_intuition="Momentum.",
        testable_statement=stmt,  # identical
        expected_behavior="Top decile outperforms.",
        asset_classes=["equities"],
        required_datasets=["CRSP"],
        required_features=["momentum"],
        holding_period="1_month",
        expected_risks=[],
        confidence_score=0.7,
        assumptions=[],
        dependencies=[],
        validation_requirements=[],
        status="Draft",
        version=1,
        created_at=now,
        updated_at=now,
        researcher="llm",
        generation_method="llm",
    )
    result = check_duplicates(h, existing)
    assert result.status == DuplicateStatus.DUPLICATE


@pytest.mark.unit
def test_empty_existing_is_unique():
    from datetime import UTC, datetime

    from mentisrex.hypothesis.models import HypothesisRecord

    now = datetime.now(UTC)
    h = HypothesisRecord(
        id="new-id",
        parent_papers=["p1"],
        research_category="macro",
        economic_intuition="Interest rates drive bond returns.",
        testable_statement="IF yield curve inverts THEN recession probability rises OVER 6_months",
        expected_behavior="Negative GDP growth.",
        asset_classes=["fixed_income"],
        required_datasets=["Fed"],
        required_features=["yield_curve_slope"],
        holding_period="6_months",
        expected_risks=["timing"],
        confidence_score=0.5,
        assumptions=[],
        dependencies=[],
        validation_requirements=[],
        status="Draft",
        version=1,
        created_at=now,
        updated_at=now,
        researcher="llm",
        generation_method="llm",
    )
    result = check_duplicates(h, [])
    assert result.status == DuplicateStatus.UNIQUE
    assert result.similar_ids == []
