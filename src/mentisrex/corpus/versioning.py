"""Document versioning and artifact lineage manager."""

from typing import Any

from mentisrex.corpus.models import CorpusDocument, DocumentVersion, VersionType


class VersionManager:
    """Manages document versions, supporting original paper, extracted knowledge,

    summaries, generated hypotheses, derived features, and experiment references.
    """

    @staticmethod
    def create_initial_version(
        doc: CorpusDocument,
        content: str,
        title: str = "Original Paper Content",
        created_by: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> DocumentVersion:
        version = DocumentVersion(
            doc_id=doc.id,
            version_num=1,
            version_type=VersionType.ORIGINAL,
            title=title,
            content=content,
            metadata=metadata or {},
            created_by=created_by,
            parent_version_id=None,
            diff_summary="Initial document ingestion",
        )
        doc.versions = [version]
        doc.current_version = 1
        return version

    @staticmethod
    def add_version(
        doc: CorpusDocument,
        version_type: VersionType,
        title: str,
        content: str,
        created_by: str = "system",
        parent_version_id: str | None = None,
        diff_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DocumentVersion:
        new_version_num = len(doc.versions) + 1
        if not parent_version_id and doc.versions:
            parent_version_id = doc.versions[-1].id

        version = DocumentVersion(
            doc_id=doc.id,
            version_num=new_version_num,
            version_type=version_type,
            title=title,
            content=content,
            metadata=metadata or {},
            created_by=created_by,
            parent_version_id=parent_version_id,
            diff_summary=diff_summary or f"Added {version_type.value} version",
        )
        doc.versions.append(version)
        doc.current_version = new_version_num
        return version

    @staticmethod
    def get_version(doc: CorpusDocument, version_id_or_num: str | int) -> DocumentVersion | None:
        for v in doc.versions:
            if isinstance(version_id_or_num, int) and v.version_num == version_id_or_num:
                return v
            if isinstance(version_id_or_num, str) and v.id == version_id_or_num:
                return v
        return None

    @staticmethod
    def diff_versions(v1: DocumentVersion, v2: DocumentVersion) -> dict[str, Any]:
        """Computes summary diff between two versions."""
        return {
            "v1_num": v1.version_num,
            "v2_num": v2.version_num,
            "v1_type": v1.version_type,
            "v2_type": v2.version_type,
            "v1_length": len(v1.content),
            "v2_length": len(v2.content),
            "length_delta": len(v2.content) - len(v1.content),
            "parent_link": v2.parent_version_id == v1.id,
        }
