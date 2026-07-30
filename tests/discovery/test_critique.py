"""Unit tests for SelfCritiqueEngine."""

import pytest

from aurelius.discovery.critique import SelfCritiqueEngine
from aurelius.discovery.generator import AlphaHypothesisGenerator
from aurelius.discovery.scorer import NoveltyScorer
from aurelius.discovery.synthesis import KnowledgeSynthesizer


@pytest.mark.unit
def test_self_critique_evaluates_falsification():
    synthesizer = KnowledgeSynthesizer()
    report = synthesizer.synthesize()

    generator = AlphaHypothesisGenerator()
    candidates = generator.generate_candidates(report, limit=1)
    cand = candidates[0]

    scorer = NoveltyScorer()
    novelty = scorer.score(cand)

    critique = SelfCritiqueEngine()
    result = critique.evaluate(cand, novelty)

    assert result.hypothesis_id == cand.id
    assert len(result.counter_arguments) == 3
    assert len(result.falsification_tests) == 3
    assert len(result.competing_explanations) == 3
    assert isinstance(result.survived_critique, bool)
    assert result.verdict_reason != ""
