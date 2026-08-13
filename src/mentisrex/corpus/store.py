"""DuckDB storage repository for Research Corpus Management System."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from mentisrex.core.logging import get_logger
from mentisrex.corpus.citation import CitationGraph
from mentisrex.corpus.classifier import CorpusClassifier
from mentisrex.corpus.models import (
    CitationEdge,
    CitationEdgeType,
    ClassificationResult,
    CorpusDocument,
    CorpusSearchResult,
    DocumentVersion,
    ProvenanceReport,
    VersionType,
)
from mentisrex.corpus.search import CorpusSearchEngine
from mentisrex.corpus.versioning import VersionManager

if TYPE_CHECKING:
    from mentisrex.knowledge.graph import KnowledgeGraph

logger = get_logger(__name__)

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS corpus_documents (
        id                VARCHAR PRIMARY KEY,
        title             VARCHAR NOT NULL,
        doc_type          VARCHAR NOT NULL,
        authors           VARCHAR DEFAULT '[]',
        publication_date VARCHAR,
        venue             VARCHAR,
        doi               VARCHAR,
        abstract          VARCHAR DEFAULT '',
        full_text_url     VARCHAR,
        classification    JSON,
        current_version   INTEGER NOT NULL DEFAULT 1,
        metadata          JSON DEFAULT '{}',
        created_at        TIMESTAMPTZ NOT NULL,
        updated_at        TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS corpus_versions (
        id                VARCHAR NOT NULL,
        doc_id            VARCHAR NOT NULL,
        version_num       INTEGER NOT NULL,
        version_type      VARCHAR NOT NULL,
        title             VARCHAR NOT NULL,
        content           VARCHAR NOT NULL,
        metadata          JSON DEFAULT '{}',
        created_at        TIMESTAMPTZ NOT NULL,
        created_by        VARCHAR DEFAULT 'system',
        parent_version_id VARCHAR,
        diff_summary      VARCHAR DEFAULT '',
        PRIMARY KEY (doc_id, version_num)
    )""",
    """CREATE TABLE IF NOT EXISTS corpus_citations (
        id          VARCHAR PRIMARY KEY,
        source_id   VARCHAR NOT NULL,
        target_id   VARCHAR NOT NULL,
        edge_type   VARCHAR NOT NULL,
        description VARCHAR DEFAULT '',
        created_at  TIMESTAMPTZ NOT NULL,
        UNIQUE (source_id, target_id, edge_type)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_corpus_docs_type ON corpus_documents(doc_type)",
    "CREATE INDEX IF NOT EXISTS ix_corpus_citations_src ON corpus_citations(source_id)",
    "CREATE INDEX IF NOT EXISTS ix_corpus_citations_tgt ON corpus_citations(target_id)",
]


class CorpusStore:
    """Persistent storage manager for the Research Corpus System."""

    def __init__(
        self, db_path: str = "./data/corpus.duckdb", kg: KnowledgeGraph | None = None
    ) -> None:
        self.db_path = db_path
        self.kg = kg
        self.classifier = CorpusClassifier()
        self.version_mgr = VersionManager()
        self.citation_graph = CitationGraph()
        self.search_engine = CorpusSearchEngine()

        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._init_schema()
        self._load_citations_from_db()

    @contextmanager
    def _get_conn(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        conn = duckdb.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._get_conn() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)
        logger.info("corpus_store_initialized", db_path=self.db_path)

    def _load_citations_from_db(self) -> None:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT source_id, target_id, edge_type, description FROM corpus_citations"
            ).fetchall()
            for src, tgt, etype, desc in rows:
                try:
                    edge_enum = CitationEdgeType(etype)
                except ValueError:
                    edge_enum = CitationEdgeType.PAPER_REFERENCE
                self.citation_graph.add_edge(src, tgt, edge_enum, desc)

    def add_document(
        self,
        title: str,
        content: str,
        doc_type: str = "academic_paper",
        authors: list[str] | None = None,
        publication_date: str | None = None,
        venue: str | None = None,
        doi: str | None = None,
        abstract: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> CorpusDocument:
        authors = authors or []
        metadata = metadata or {}

        doc = CorpusDocument(
            title=title,
            doc_type=doc_type,
            authors=authors,
            publication_date=publication_date,
            venue=venue,
            doi=doi,
            abstract=abstract or content[:300],
            metadata=metadata,
        )

        # Classify automatically
        doc.classification = self.classifier.classify(
            title, abstract or content[:300], content, metadata
        )

        # Version 1 initial content
        self.version_mgr.create_initial_version(
            doc, content, title=f"Original: {title}", metadata=metadata
        )

        # Save to DB
        self.save_document(doc)
        return doc

    def save_document(self, doc: CorpusDocument) -> None:
        classification_json = (
            json.dumps(doc.classification.model_dump()) if doc.classification else "{}"
        )
        authors_json = json.dumps(doc.authors)
        metadata_json = json.dumps(doc.metadata)

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO corpus_documents (
                    id, title, doc_type, authors, publication_date, venue, doi,
                    abstract, full_text_url, classification, current_version, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    title=EXCLUDED.title,
                    doc_type=EXCLUDED.doc_type,
                    authors=EXCLUDED.authors,
                    publication_date=EXCLUDED.publication_date,
                    venue=EXCLUDED.venue,
                    doi=EXCLUDED.doi,
                    abstract=EXCLUDED.abstract,
                    full_text_url=EXCLUDED.full_text_url,
                    classification=EXCLUDED.classification,
                    current_version=EXCLUDED.current_version,
                    metadata=EXCLUDED.metadata,
                    updated_at=EXCLUDED.updated_at
                """,
                [
                    doc.id,
                    doc.title,
                    doc.doc_type,
                    authors_json,
                    doc.publication_date,
                    doc.venue,
                    doc.doi,
                    doc.abstract,
                    doc.full_text_url,
                    classification_json,
                    doc.current_version,
                    metadata_json,
                    doc.created_at,
                    doc.updated_at,
                ],
            )

            # Insert versions
            for ver in doc.versions:
                ver_meta = json.dumps(ver.metadata)
                conn.execute(
                    """
                    INSERT INTO corpus_versions (
                        id, doc_id, version_num, version_type, title, content, metadata, created_at, created_by, parent_version_id, diff_summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (doc_id, version_num) DO UPDATE SET
                        title=EXCLUDED.title,
                        content=EXCLUDED.content,
                        metadata=EXCLUDED.metadata,
                        diff_summary=EXCLUDED.diff_summary
                    """,
                    [
                        ver.id,
                        ver.doc_id,
                        ver.version_num,
                        ver.version_type,
                        ver.title,
                        ver.content,
                        ver_meta,
                        ver.created_at,
                        ver.created_by,
                        ver.parent_version_id,
                        ver.diff_summary,
                    ],
                )

        # Sync to Knowledge Graph if available
        if self.kg:
            text_corpus = f"{doc.title} {doc.abstract} {doc.classification.reasoning if doc.classification else ''}"
            self.kg.upsert_node(
                node_id=doc.id,
                node_type="paper",
                label=doc.title,
                properties=doc.model_dump(),
                text_corpus=text_corpus,
                change_reason="corpus_sync",
            )

        logger.info("corpus_document_saved", doc_id=doc.id, title=doc.title)

    def document_exists_by_hash(self, content_hash: str) -> bool:
        """Exact-match duplicate check on the ingestion content hash.

        Duplicate detection must be exact, not relevance-based: the fuzzy
        `search()` path returns matches for arbitrary query strings and
        cannot key on the stored hash, producing false positives.
        """
        if not content_hash:
            return False
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM corpus_documents "
                "WHERE json_extract_string(metadata, '$.content_hash') = ? LIMIT 1",
                [content_hash],
            ).fetchone()
        return row is not None

    def get_document(self, doc_id: str) -> CorpusDocument | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM corpus_documents WHERE id = ?", [doc_id]).fetchone()
            if not row:
                return None
            cols = [
                d[0] for d in conn.execute("SELECT * FROM corpus_documents LIMIT 0").description
            ]
            data = dict(zip(cols, row, strict=False))

            # Fetch versions
            ver_rows = conn.execute(
                "SELECT * FROM corpus_versions WHERE doc_id = ? ORDER BY version_num ASC", [doc_id]
            ).fetchall()
            vcols = [
                d[0] for d in conn.execute("SELECT * FROM corpus_versions LIMIT 0").description
            ]
            versions = []
            for vr in ver_rows:
                vd = dict(zip(vcols, vr, strict=False))
                versions.append(
                    DocumentVersion(
                        id=vd["id"],
                        doc_id=vd["doc_id"],
                        version_num=vd["version_num"],
                        version_type=vd["version_type"],
                        title=vd["title"],
                        content=vd["content"],
                        metadata=json.loads(vd["metadata"]) if vd["metadata"] else {},
                        created_at=vd["created_at"],
                        created_by=vd["created_by"],
                        parent_version_id=vd["parent_version_id"],
                        diff_summary=vd["diff_summary"],
                    )
                )

            classification = None
            if data["classification"]:
                classification = ClassificationResult(**json.loads(data["classification"]))

            return CorpusDocument(
                id=data["id"],
                title=data["title"],
                doc_type=data["doc_type"],
                authors=json.loads(data["authors"]) if data["authors"] else [],
                publication_date=data["publication_date"],
                venue=data["venue"],
                doi=data["doi"],
                abstract=data["abstract"],
                full_text_url=data["full_text_url"],
                classification=classification,
                current_version=data["current_version"],
                versions=versions,
                metadata=json.loads(data["metadata"]) if data["metadata"] else {},
                created_at=data["created_at"],
                updated_at=data["updated_at"],
            )

    def list_documents(
        self, domain_filter: str | None = None, limit: int = 100
    ) -> list[CorpusDocument]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT id FROM corpus_documents LIMIT ?", [limit]).fetchall()
        docs = []
        for (did,) in rows:
            doc = self.get_document(did)
            if doc:
                if (
                    domain_filter
                    and doc.classification
                    and doc.classification.research_domain != domain_filter
                ):
                    continue
                docs.append(doc)
        return docs

    def add_version(
        self,
        doc_id: str,
        version_type: VersionType,
        title: str,
        content: str,
        created_by: str = "system",
        diff_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DocumentVersion | None:
        doc = self.get_document(doc_id)
        if not doc:
            return None
        ver = self.version_mgr.add_version(
            doc=doc,
            version_type=version_type,
            title=title,
            content=content,
            created_by=created_by,
            diff_summary=diff_summary,
            metadata=metadata,
        )
        self.save_document(doc)
        return ver

    def add_citation(
        self,
        source_id: str,
        target_id: str,
        edge_type: CitationEdgeType = CitationEdgeType.PAPER_REFERENCE,
        description: str = "",
    ) -> CitationEdge:
        edge = self.citation_graph.add_edge(source_id, target_id, edge_type, description)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO corpus_citations (id, source_id, target_id, edge_type, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_id, target_id, edge_type) DO UPDATE SET
                    description=EXCLUDED.description
                """,
                [
                    edge.id,
                    edge.source_id,
                    edge.target_id,
                    edge.edge_type,
                    edge.description,
                    edge.created_at,
                ],
            )
        if self.kg:
            self.kg.upsert_edge(source_id, target_id, edge_type.value)
        return edge

    def search(
        self,
        query: str,
        domain_filter: str | None = None,
        asset_class_filter: str | None = None,
        min_quality_score: float = 0.0,
        limit: int = 10,
    ) -> list[CorpusSearchResult]:
        docs = self.list_documents(limit=500)
        return self.search_engine.search(
            documents=docs,
            query=query,
            domain_filter=domain_filter,
            asset_class_filter=asset_class_filter,
            min_quality_score=min_quality_score,
            limit=limit,
        )

    def get_provenance_report(
        self, target_id: str, target_type: str = "strategy"
    ) -> ProvenanceReport:
        return self.citation_graph.get_provenance_report(target_id, target_type)
