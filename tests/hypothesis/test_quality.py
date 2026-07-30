"""Unit tests for the quality filter."""

from datetime import UTC, datetime

import pytest

from aurelius.hypothesis.models import HypothesisRecord
from aurelius.hypothesis.quality import check_quality


def _record(**kwargs) -> HypothesisRecord:
    now = datetime.now(UTC)
    defaults = {
        "id": "qtest-001",
        "parent_papers": ["paper-001"],
        "research_category": "factor_anomaly",
        "economic_intuition": "Momentum persists due to investor underreaction to news.",
        "testable_statement": (
            "IF 12-1 momentum signal is high THEN future equity returns positive OVER 1_month"
        ),
        "expected_behavior": "Top decile outperforms.",
        "asset_classes": ["equities"],
        "required_datasets": ["CRSP"],
        "required_features": ["momentum"],
        "holding_period": "1_month",
        "expected_risks": ["momentum_crash"],
        "confidence_score": 0.7,
        "assumptions": ["Markets are not perfectly efficient"],
        "dependencies": [],
        "validation_requirements": ["Sharpe > 0.5"],
        "status": "Draft",
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "researcher": "llm",
        "generation_method": "llm",
    }
    defaults.update(kwargs)
    return HypothesisRecord(**defaults)


@pytest.mark.unit
def test_valid_hypothesis_passes():
    result = check_quality(_record())
    assert result.passed
    assert result.reasons == []


@pytest.mark.unit
def test_empty_testable_statement_fails():
    result = check_quality(_record(testable_statement=""))
    assert not result.passed
    assert "statement_too_short" in result.reasons


@pytest.mark.unit
def test_short_testable_statement_fails():
    result = check_quality(_record(testable_statement="Returns high."))
    assert not result.passed
    assert "statement_too_short" in result.reasons


@pytest.mark.unit
def test_statement_without_conditional_fails():
    result = check_quality(
        _record(
            testable_statement="Momentum factor generates positive excess returns in US equities."
        )
    )
    assert not result.passed
    assert "not_testable_no_conditional" in result.reasons


@pytest.mark.unit
def test_missing_intuition_fails():
    result = check_quality(_record(economic_intuition="Short."))
    assert not result.passed
    assert "intuition_missing" in result.reasons


@pytest.mark.unit
def test_missing_datasets_fails():
    result = check_quality(_record(required_datasets=[]))
    assert not result.passed
    assert "missing_required_data" in result.reasons


@pytest.mark.unit
def test_missing_asset_class_fails():
    result = check_quality(_record(asset_classes=[]))
    assert not result.passed
    assert "asset_class_unspecified" in result.reasons


@pytest.mark.unit
def test_low_confidence_fails():
    result = check_quality(_record(confidence_score=0.0))
    assert not result.passed
    assert "confidence_too_low" in result.reasons


@pytest.mark.unit
def test_vague_statement_fails():
    result = check_quality(_record(testable_statement="IF x THEN returns positive."))
    assert not result.passed
    assert "too_vague" in result.reasons


@pytest.mark.unit
def test_when_conditional_passes():
    result = check_quality(
        _record(
            testable_statement=(
                "WHEN volatility regime is low, equity momentum factor delivers "
                "positive Sharpe over 1-month horizon."
            )
        )
    )
    assert result.passed


@pytest.mark.unit
def test_multiple_failures_accumulate():
    result = check_quality(
        _record(
            testable_statement="",
            required_datasets=[],
            asset_classes=[],
        )
    )
    assert not result.passed
    assert len(result.reasons) >= 3
