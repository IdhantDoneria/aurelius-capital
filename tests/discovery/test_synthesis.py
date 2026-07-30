"""Unit tests for KnowledgeSynthesizer."""

import pytest

from aurelius.discovery.synthesis import KnowledgeSynthesizer


@pytest.mark.unit
def test_synthesize_returns_valid_report(tmp_path):
    synthesizer = KnowledgeSynthesizer()
    report = synthesizer.synthesize()

    assert len(report.common_themes) > 0
    assert len(report.missing_feature_combinations) > 0
    assert len(report.untested_factor_combinations) > 0
    assert len(report.contradictory_findings) > 0
    assert len(report.research_gaps) > 0
    assert len(report.emerging_trends) > 0
