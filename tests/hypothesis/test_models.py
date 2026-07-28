"""Unit tests for HypothesisRecord model."""
import pytest
from datetime import UTC, datetime

from aurelius.hypothesis.models import HypothesisRecord


def _record(**kwargs) -> HypothesisRecord:
    now = datetime.now(UTC)
    defaults = dict(
        id="test-id-001",
        parent_papers=["paper-001"],
        research_category="factor_anomaly",
        economic_intuition="Momentum persists due to investor underreaction.",
        testable_statement=(
            "IF 12-1 month momentum is in top decile "
            "THEN next-month return is positive AMONG US equities OVER 1_month"
        ),
        expected_behavior="Top-decile momentum stocks outperform bottom decile by 1% per month.",
        asset_classes=["equities"],
        required_datasets=["CRSP"],
        required_features=["momentum_12_1"],
        holding_period="1_month",
        expected_risks=["momentum_crash", "factor_crowding"],
        confidence_score=0.75,
        assumptions=["Prices are not perfectly efficient"],
        dependencies=[],
        validation_requirements=["OOS Sharpe > 0.5", "Positive after costs"],
        status="Draft",
        version=1,
        created_at=now,
        updated_at=now,
        researcher="llm",
        generation_method="llm",
    )
    defaults.update(kwargs)
    return HypothesisRecord(**defaults)


@pytest.mark.unit
def test_record_creates_with_defaults():
    h = _record()
    assert h.status == "Draft"
    assert h.version == 1
    assert h.similar_to == []
    assert h.rejection_reason == ""


@pytest.mark.unit
def test_record_status_lifecycle():
    h = _record()
    h.status = "Active"
    assert h.status == "Active"
    h.status = "Rejected"
    h.rejection_reason = "too_vague"
    assert h.rejection_reason == "too_vague"


@pytest.mark.unit
def test_record_holds_all_required_fields():
    h = _record()
    assert h.economic_intuition
    assert h.testable_statement
    assert h.asset_classes
    assert h.required_datasets
    assert h.confidence_score > 0
