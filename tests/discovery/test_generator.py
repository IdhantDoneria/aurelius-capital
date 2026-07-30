"""Unit tests for AlphaHypothesisGenerator."""

import pytest

from aurelius.discovery.generator import AlphaHypothesisGenerator
from aurelius.discovery.synthesis import KnowledgeSynthesizer


@pytest.mark.unit
def test_generator_produces_structured_hypotheses():
    synthesizer = KnowledgeSynthesizer()
    report = synthesizer.synthesize()

    generator = AlphaHypothesisGenerator()
    candidates = generator.generate_candidates(report, limit=5)

    assert len(candidates) == 5
    for c in candidates:
        assert c.title != ""
        assert len(c.economic_intuition) > 10
        assert len(c.testable_statement) > 10
        assert len(c.why_it_exists) > 0
        assert len(c.why_it_might_fail) > 0
        assert len(c.supporting_literature) > 0
        assert len(c.validation_plan) > 0
