"""Tests for the paper priority scorer."""

import pytest
from mentisrex.operations.scorer import score_paper


def _meta(**kwargs):
    base = {
        "title": "Test Paper",
        "year": 2024,
        "abstract": "A" * 200,
        "methodology": "OLS regression with Fama-MacBeth cross-sections.",
        "results": "Sharpe ratio 1.2, t-stat 3.1",
        "datasets_mentioned": ["Ken French", "CRSP"],
        "features_mentioned": ["momentum", "value", "size"],
        "statistical_tests": ["t-statistic", "p-value", "Sharpe ratio"],
        "reference_count": 40,
        "arxiv_id": "2401.12345",
    }
    base.update(kwargs)
    return base


def test_score_returns_valid_range():
    score = score_paper("p1", _meta())
    assert 0.0 <= score.total <= 10.0


def test_newer_paper_scores_higher_novelty():
    old = score_paper("p1", _meta(year=2010))
    new = score_paper("p2", _meta(year=2024))
    assert new.novelty > old.novelty


def test_no_datasets_reduces_availability():
    with_ds = score_paper("p1", _meta(datasets_mentioned=["Ken French"]))
    without = score_paper("p2", _meta(datasets_mentioned=[]))
    # dataset_availability component differs; total reflects it
    assert with_ds.dataset_availability != without.dataset_availability


def test_no_methodology_reduces_reproducibility():
    with_m = score_paper("p1", _meta())
    without_m = score_paper("p2", _meta(methodology=""))
    assert with_m.reproducibility > without_m.reproducibility


def test_high_reference_count_boosts_influence():
    few = score_paper("p1", _meta(reference_count=5, statistical_tests=[]))
    many = score_paper("p2", _meta(reference_count=60, statistical_tests=["t-statistic"]))
    assert many.influence > few.influence


def test_missing_year_gives_partial_novelty():
    score = score_paper("p1", _meta(year=None))
    assert score.novelty == pytest.approx(0.3)


def test_rationale_non_empty():
    score = score_paper("p1", _meta())
    assert score.rationale != ""


def test_paper_score_fields():
    score = score_paper("paper-abc", _meta())
    assert score.paper_id == "paper-abc"
    assert isinstance(score.engineering_effort, float)
