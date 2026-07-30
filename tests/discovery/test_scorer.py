"""Unit tests for NoveltyScorer."""

import pytest

from aurelius.discovery.generator import AlphaHypothesisGenerator
from aurelius.discovery.scorer import NoveltyScorer
from aurelius.discovery.synthesis import KnowledgeSynthesizer


@pytest.mark.unit
def test_scorer_evaluates_candidate_hypotheses():
    synthesizer = KnowledgeSynthesizer()
    report = synthesizer.synthesize()

    generator = AlphaHypothesisGenerator()
    candidates = generator.generate_candidates(report, limit=1)
    cand = candidates[0]

    scorer = NoveltyScorer()
    score = scorer.score(cand)

    assert score.hypothesis_id == cand.id
    assert 1 <= score.novelty <= 5
    assert 0.0 <= score.similarity_to_previous <= 1.0
    assert 0.0 <= score.research_value <= 100.0
    assert 1 <= score.expected_compute_cost <= 5
    assert score.explanation != ""
