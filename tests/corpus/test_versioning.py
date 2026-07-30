"""Unit tests for VersionManager."""

from aurelius.corpus.models import CorpusDocument, VersionType
from aurelius.corpus.versioning import VersionManager


def test_version_workflow() -> None:
    doc = CorpusDocument(title="Test Document", doc_type="academic_paper")
    v1 = VersionManager.create_initial_version(doc, content="Original text of the paper.")

    assert doc.current_version == 1
    assert len(doc.versions) == 1
    assert v1.version_type == VersionType.ORIGINAL
    assert v1.parent_version_id is None

    # Add summary version
    v2 = VersionManager.add_version(
        doc=doc,
        version_type=VersionType.SUMMARY,
        title="Paper Summary",
        content="Key conclusion: momentum works best in high volatility.",
        created_by="researcher_1",
    )

    assert doc.current_version == 2
    assert len(doc.versions) == 2
    assert v2.version_type == VersionType.SUMMARY
    assert v2.parent_version_id == v1.id

    # Add generated hypothesis version
    v3 = VersionManager.add_version(
        doc=doc,
        version_type=VersionType.GENERATED_HYPOTHESIS,
        title="Hypothesis H-101",
        content="IF market volatility > 20% THEN 12-1m momentum Sharpe > 1.2",
    )

    assert doc.current_version == 3
    assert len(doc.versions) == 3
    assert v3.parent_version_id == v2.id

    diff = VersionManager.diff_versions(v1, v2)
    assert diff["v1_num"] == 1
    assert diff["v2_num"] == 2
    assert diff["parent_link"] is True
