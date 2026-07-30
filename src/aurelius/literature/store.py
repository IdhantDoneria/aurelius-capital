"""DuckDB-backed persistence for the Literature Intelligence Framework."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger
from aurelius.knowledge import hooks as kg_hooks
from aurelius.literature.models import Paper

logger = get_logger(__name__)

_CREATE_PAPERS = """
CREATE TABLE IF NOT EXISTS papers (
    id                     VARCHAR PRIMARY KEY,
    source                 VARCHAR NOT NULL,
    source_id              VARCHAR NOT NULL,
    title                  VARCHAR NOT NULL,
    authors                VARCHAR,
    published_at           DATE,
    abstract               VARCHAR,
    url                    VARCHAR,
    keywords               VARCHAR,
    asset_classes          VARCHAR,
    research_category      VARCHAR,
    methodology            VARCHAR,
    datasets               VARCHAR,
    factors_studied        VARCHAR,
    statistical_techniques VARCHAR,
    main_conclusions       VARCHAR,
    limitations            VARCHAR,
    ingested_at            TIMESTAMPTZ NOT NULL,
    enriched               BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (source, source_id)
)
"""


class LiteratureStore:
    def __init__(self, db_path: str = "./data/literature.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None
        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")
        with self._conn() as conn:
            conn.execute(_CREATE_PAPERS)

    @contextmanager
    def _conn(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        if self._in_memory and self._persistent_conn is not None:
            yield self._persistent_conn
        else:
            conn = duckdb.connect(self._path)
            try:
                yield conn
            finally:
                conn.close()

    def upsert(self, paper: Paper) -> bool:
        """Insert or update paper. Returns True if newly inserted."""
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT enriched FROM papers WHERE source = ? AND source_id = ?",
                [paper.source, paper.source_id],
            ).fetchone()

            if existing:
                existing_enriched = bool(existing[0])
                # If paper is already enriched and the new record is not, preserve enrichment
                if existing_enriched and not paper.enriched:
                    conn.execute(
                        "UPDATE papers SET title=?, authors=?, published_at=?, abstract=?, url=? "
                        "WHERE source=? AND source_id=?",
                        [
                            paper.title,
                            json.dumps(paper.authors),
                            paper.published_at,
                            paper.abstract,
                            paper.url,
                            paper.source,
                            paper.source_id,
                        ],
                    )
                else:
                    conn.execute(
                        """UPDATE papers SET
                            title=?, authors=?, published_at=?, abstract=?, url=?,
                            keywords=?, asset_classes=?, research_category=?,
                            methodology=?, datasets=?, factors_studied=?,
                            statistical_techniques=?, main_conclusions=?,
                            limitations=?, enriched=?
                        WHERE source=? AND source_id=?""",
                        [
                            paper.title,
                            json.dumps(paper.authors),
                            paper.published_at,
                            paper.abstract,
                            paper.url,
                            json.dumps(paper.keywords),
                            json.dumps(paper.asset_classes),
                            paper.research_category,
                            paper.methodology,
                            json.dumps(paper.datasets),
                            json.dumps(paper.factors_studied),
                            json.dumps(paper.statistical_techniques),
                            paper.main_conclusions,
                            paper.limitations,
                            paper.enriched,
                            paper.source,
                            paper.source_id,
                        ],
                    )
                kg_hooks.on_paper(paper)
                return False

            conn.execute(
                "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    paper.id,
                    paper.source,
                    paper.source_id,
                    paper.title,
                    json.dumps(paper.authors),
                    paper.published_at,
                    paper.abstract,
                    paper.url,
                    json.dumps(paper.keywords),
                    json.dumps(paper.asset_classes),
                    paper.research_category,
                    paper.methodology,
                    json.dumps(paper.datasets),
                    json.dumps(paper.factors_studied),
                    json.dumps(paper.statistical_techniques),
                    paper.main_conclusions,
                    paper.limitations,
                    paper.ingested_at,
                    paper.enriched,
                ],
            )
            kg_hooks.on_paper(paper)
            return True

    def exists(self, source: str, source_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM papers WHERE source=? AND source_id=?",
                [source, source_id],
            ).fetchone()
            return row is not None

    def get(self, paper_id: str) -> Paper | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM papers WHERE id=?", [paper_id]).fetchone()
            return self._row_to_paper(row) if row else None

    def search(
        self,
        query: str | None = None,
        source: str | None = None,
        category: str | None = None,
        since: date | None = None,
        enriched_only: bool = False,
        limit: int = 50,
    ) -> list[Paper]:
        clauses: list[str] = []
        params: list = []
        if query:
            clauses.append("(title ILIKE ? OR abstract ILIKE ?)")
            params += [f"%{query}%", f"%{query}%"]
        if source:
            clauses.append("source = ?")
            params.append(source)
        if category:
            clauses.append("research_category = ?")
            params.append(category)
        if since:
            clauses.append("published_at >= ?")
            params.append(since)
        if enriched_only:
            clauses.append("enriched = TRUE")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM papers {where} ORDER BY published_at DESC NULLS LAST LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_paper(r) for r in rows]

    def pending_enrichment(self, limit: int = 50) -> list[Paper]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE enriched = FALSE AND abstract IS NOT NULL "
                "AND abstract != '' ORDER BY published_at DESC NULLS LAST LIMIT ?",
                [limit],
            ).fetchall()
            return [self._row_to_paper(r) for r in rows]

    def all_papers(self, limit: int = 10_000) -> list[Paper]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY published_at DESC NULLS LAST LIMIT ?",
                [limit],
            ).fetchall()
            return [self._row_to_paper(r) for r in rows]

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]  # type: ignore[index]
            enriched = conn.execute("SELECT COUNT(*) FROM papers WHERE enriched=TRUE").fetchone()[0]  # type: ignore[index]
            by_source = conn.execute(
                "SELECT source, COUNT(*) FROM papers GROUP BY source ORDER BY source"
            ).fetchall()
            return {
                "total": total,
                "enriched": enriched,
                "by_source": {row[0]: row[1] for row in by_source},
            }

    def _row_to_paper(self, row: tuple) -> Paper:
        (
            id_,
            source,
            source_id,
            title,
            authors_j,
            published_at,
            abstract,
            url,
            keywords_j,
            asset_classes_j,
            research_category,
            methodology,
            datasets_j,
            factors_j,
            techniques_j,
            main_conclusions,
            limitations,
            ingested_at,
            enriched,
        ) = row
        return Paper(
            id=id_,
            source=source,
            source_id=source_id,
            title=title,
            authors=json.loads(authors_j or "[]"),
            published_at=published_at,
            abstract=abstract or "",
            url=url or "",
            ingested_at=(
                ingested_at
                if isinstance(ingested_at, datetime)
                else datetime.fromisoformat(str(ingested_at))
            ),
            keywords=json.loads(keywords_j or "[]"),
            asset_classes=json.loads(asset_classes_j or "[]"),
            research_category=research_category or "",
            methodology=methodology or "",
            datasets=json.loads(datasets_j or "[]"),
            factors_studied=json.loads(factors_j or "[]"),
            statistical_techniques=json.loads(techniques_j or "[]"),
            main_conclusions=main_conclusions or "",
            limitations=limitations or "",
            enriched=bool(enriched),
        )
