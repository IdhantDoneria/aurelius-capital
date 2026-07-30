"""Unit tests for hypothesis generator (mock LLM, no API calls)."""

import json
from datetime import UTC, date, datetime

import pytest

from aurelius.hypothesis.generator import _extract_json_array, _str_list, generate
from aurelius.literature.models import Paper, paper_id


def _paper(enriched: bool = True) -> Paper:
    p = Paper(
        id=paper_id("arxiv", "test-gen"),
        source="arxiv",
        source_id="test-gen",
        title="Momentum Premium in International Equities",
        authors=["Alice Smith", "Bob Jones"],
        published_at=date(2024, 1, 1),
        abstract="We document momentum premium across 40 markets.",
        url="https://arxiv.org/abs/test-gen",
        ingested_at=datetime.now(UTC),
    )
    if enriched:
        p.enriched = True
        p.research_category = "factor_anomaly"
        p.methodology = "empirical"
        p.factors_studied = ["momentum"]
        p.asset_classes = ["equities"]
        p.datasets = ["CRSP", "Compustat"]
        p.main_conclusions = "Momentum generates 1% per month in all markets studied."
        p.limitations = "Does not adjust for transaction costs."
    return p


_MOCK_LLM_RESPONSE = json.dumps(
    [
        {
            "economic_intuition": "Investors underreact to news, causing momentum to persist.",
            "testable_statement": (
                "IF 12-1 month momentum signal is in top quintile "
                "THEN next-month return is positive AMONG international equities OVER 1_month"
            ),
            "expected_behavior": "Top quintile outperforms bottom quintile by 1% monthly.",
            "asset_classes": ["equities"],
            "required_datasets": ["CRSP", "Compustat"],
            "required_features": ["momentum_12_1"],
            "holding_period": "1_month",
            "expected_risks": ["momentum_crash", "factor_crowding"],
            "confidence_score": 0.75,
            "assumptions": ["Prices not fully efficient"],
            "dependencies": [],
            "validation_requirements": ["OOS Sharpe > 0.5", "Positive after costs"],
        }
    ]
)


@pytest.mark.unit
def test_generate_with_llm():
    paper = _paper()
    records = generate(paper, llm=lambda _: _MOCK_LLM_RESPONSE, researcher="test")
    assert len(records) == 1
    h = records[0]
    assert h.status == "Draft"
    assert h.generation_method == "llm"
    assert h.researcher == "test"
    assert h.parent_papers == [paper.id]
    assert "momentum" in h.testable_statement.lower()
    assert h.confidence_score == 0.75
    assert h.asset_classes == ["equities"]


@pytest.mark.unit
def test_generate_llm_caps_at_3():
    four_hyps = json.dumps(
        [
            {
                "economic_intuition": f"Reason {i}.",
                "testable_statement": f"IF signal_{i} high THEN returns positive OVER 1_month",
                "expected_behavior": "Outperforms.",
                "asset_classes": ["equities"],
                "required_datasets": ["CRSP"],
                "required_features": ["sig"],
                "holding_period": "1_month",
                "expected_risks": [],
                "confidence_score": 0.5,
                "assumptions": [],
                "dependencies": [],
                "validation_requirements": [],
            }
            for i in range(4)
        ]
    )
    records = generate(_paper(), llm=lambda _: four_hyps)
    assert len(records) <= 3


@pytest.mark.unit
def test_generate_template_fallback():
    paper = _paper()
    records = generate(paper, llm=None)
    assert len(records) >= 1
    for h in records:
        assert h.generation_method == "template"
        assert h.status == "Draft"
        assert "IF" in h.testable_statement or "if" in h.testable_statement
        assert paper.id in h.parent_papers


@pytest.mark.unit
def test_generate_llm_parse_failure_falls_back():
    records = generate(_paper(), llm=lambda _: "this is not json")
    # Should fall back to template
    assert len(records) >= 1
    assert all(h.generation_method == "template" for h in records)


@pytest.mark.unit
def test_generate_unenriched_paper_template():
    paper = _paper(enriched=False)
    records = generate(paper, llm=None)
    assert len(records) >= 1  # template still works


@pytest.mark.unit
def test_extract_json_array_from_array():
    assert _extract_json_array('[{"a": 1}]') == '[{"a": 1}]'


@pytest.mark.unit
def test_extract_json_array_from_object():
    result = _extract_json_array('{"a": 1}')
    assert result == '[{"a": 1}]'


@pytest.mark.unit
def test_extract_json_array_with_prose():
    result = _extract_json_array('Here is the result:\n[{"a": 1}]\nDone.')
    assert result == '[{"a": 1}]'


@pytest.mark.unit
def test_str_list_helpers():
    assert _str_list(["a", "b"]) == ["a", "b"]
    assert _str_list("single") == ["single"]
    assert _str_list(None) == []
