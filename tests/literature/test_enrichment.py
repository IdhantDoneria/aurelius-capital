"""Unit tests for LLM enrichment (mock LLM, no API calls)."""

import json
from datetime import UTC, date, datetime

import pytest

from aurelius.literature.enrichment import _extract_json, _str_list, enrich
from aurelius.literature.models import Paper, paper_id


def _paper() -> Paper:
    return Paper(
        id=paper_id("arxiv", "test"),
        source="arxiv",
        source_id="test",
        title="Momentum Premium in Equities",
        authors=["Author One", "Author Two"],
        published_at=date(2024, 1, 1),
        abstract="We find significant momentum premium in US equities using 1963-2023 data.",
        url="https://arxiv.org/abs/test",
        ingested_at=datetime.now(UTC),
    )


_VALID_RESPONSE = json.dumps(
    {
        "keywords": ["momentum", "equities", "factor"],
        "asset_classes": ["equities"],
        "research_category": "factor_anomaly",
        "methodology": "empirical",
        "datasets": ["CRSP", "Compustat"],
        "factors_studied": ["momentum"],
        "statistical_techniques": ["Fama-MacBeth regression", "portfolio sorts"],
        "main_conclusions": "Momentum generates significant excess returns net of transaction costs.",
        "limitations": "US equities only; does not account for implementation costs.",
    }
)


@pytest.mark.unit
def test_enrich_populates_all_fields():
    p = _paper()
    result = enrich(p, llm=lambda _: _VALID_RESPONSE)
    assert result.enriched is True
    assert result.keywords == ["momentum", "equities", "factor"]
    assert result.asset_classes == ["equities"]
    assert result.research_category == "factor_anomaly"
    assert result.methodology == "empirical"
    assert result.datasets == ["CRSP", "Compustat"]
    assert result.factors_studied == ["momentum"]
    assert "Fama-MacBeth" in result.statistical_techniques[0]
    assert "excess returns" in result.main_conclusions
    assert "US equities" in result.limitations


@pytest.mark.unit
def test_enrich_returns_same_object():
    p = _paper()
    result = enrich(p, llm=lambda _: _VALID_RESPONSE)
    assert result is p


@pytest.mark.unit
def test_enrich_graceful_on_invalid_json():
    p = _paper()
    result = enrich(p, llm=lambda _: "this is not json at all")
    assert result.enriched is False
    assert result.keywords == []


@pytest.mark.unit
def test_enrich_graceful_on_partial_json():
    p = _paper()
    # Only some fields returned
    partial = json.dumps({"keywords": ["value"], "methodology": "empirical"})
    result = enrich(p, llm=lambda _: partial)
    assert result.enriched is True
    assert result.keywords == ["value"]
    assert result.methodology == "empirical"
    assert result.datasets == []  # missing field defaults to empty


@pytest.mark.unit
def test_enrich_handles_prose_wrapped_json():
    p = _paper()
    wrapped = (
        f"Here is the extracted metadata:\n\n{_VALID_RESPONSE}\n\nLet me know if you need more."
    )
    result = enrich(p, llm=lambda _: wrapped)
    assert result.enriched is True
    assert result.keywords == ["momentum", "equities", "factor"]


@pytest.mark.unit
def test_extract_json_bare():
    assert _extract_json('{"a": 1}') == '{"a": 1}'


@pytest.mark.unit
def test_extract_json_with_surrounding_text():
    assert _extract_json('text before {"a": 1} text after') == '{"a": 1}'


@pytest.mark.unit
def test_extract_json_multiline():
    multiline = '{\n  "a": 1,\n  "b": 2\n}'
    assert _extract_json(multiline) == multiline


@pytest.mark.unit
def test_str_list_from_list():
    assert _str_list(["a", "b"]) == ["a", "b"]


@pytest.mark.unit
def test_str_list_from_string():
    assert _str_list("single") == ["single"]


@pytest.mark.unit
def test_str_list_from_none():
    assert _str_list(None) == []


@pytest.mark.unit
def test_str_list_from_int():
    assert _str_list(42) == []


@pytest.mark.unit
def test_str_list_from_empty_string():
    assert _str_list("") == []
