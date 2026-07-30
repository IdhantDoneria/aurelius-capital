"""Research Knowledge Graph — DuckDB property graph.

Node types (node.type discriminator):
  paper, author, institution, dataset, asset_class, market, hypothesis, feature,
  factor, experiment, validation_report, paper_trading_result, production_strategy,
  risk_metric, research_category, statistical_test, model, portfolio, decision,
  observation, failure_mode, researcher, tag

Edge rel_types:
  proposes, uses_dataset, generates, produces, evaluates, derived_from, uses_feature,
  belongs_to, references, depends_on, caused_by, affects, contains, authored_by,
  affiliated_with, categorized_as, tagged_with, similar_to, mentions
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from aurelius.core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS kg_nodes (
        id            VARCHAR PRIMARY KEY,
        type          VARCHAR NOT NULL,
        label         VARCHAR NOT NULL,
        properties    JSON    NOT NULL DEFAULT '{}',
        text_corpus   VARCHAR DEFAULT '',
        created_at    TIMESTAMPTZ NOT NULL,
        updated_at    TIMESTAMPTZ NOT NULL,
        created_by    VARCHAR DEFAULT 'system',
        version       INTEGER NOT NULL DEFAULT 1,
        superseded_by VARCHAR,
        change_reason VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS kg_edges (
        id          VARCHAR PRIMARY KEY,
        source_id   VARCHAR NOT NULL REFERENCES kg_nodes(id),
        target_id   VARCHAR NOT NULL REFERENCES kg_nodes(id),
        rel_type    VARCHAR NOT NULL,
        properties  JSON    NOT NULL DEFAULT '{}',
        created_at  TIMESTAMPTZ NOT NULL,
        created_by  VARCHAR DEFAULT 'system',
        UNIQUE (source_id, target_id, rel_type)
    )""",
    """CREATE TABLE IF NOT EXISTS kg_node_history (
        node_id       VARCHAR NOT NULL REFERENCES kg_nodes(id),
        version       INTEGER NOT NULL,
        snapshot      JSON    NOT NULL,
        changed_at    TIMESTAMPTZ NOT NULL,
        changed_by    VARCHAR DEFAULT 'system',
        change_reason VARCHAR,
        PRIMARY KEY (node_id, version)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_kg_nodes_type ON kg_nodes(type)",
    "CREATE INDEX IF NOT EXISTS ix_kg_edges_source ON kg_edges(source_id)",
    "CREATE INDEX IF NOT EXISTS ix_kg_edges_target ON kg_edges(target_id)",
    "CREATE INDEX IF NOT EXISTS ix_kg_edges_rel ON kg_edges(rel_type)",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _edge_id(source: str, target: str, rel: str) -> str:
    return hashlib.sha256(f"{source}:{target}:{rel}".encode()).hexdigest()[:32]


def _as_dicts(result: Any) -> list[dict[str, Any]]:
    cols = [d[0] for d in result.description]
    return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]


# ── Embedder (soft dependency on sentence-transformers) ───────────────────────

_EMBED_MODEL = "all-MiniLM-L6-v2"  # 384-dim, 80 MB, fast
_embedder_cache: Any = None  # False = tried and failed; SentenceTransformer = ready


def _get_embedder() -> Any:
    global _embedder_cache
    if _embedder_cache is not None:
        return _embedder_cache
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]

        _embedder_cache = SentenceTransformer(_EMBED_MODEL)
        logger.info("kg_embedder_loaded", model=_EMBED_MODEL)
    except ImportError:
        _embedder_cache = False
        logger.warning("kg_embedder_unavailable", hint="pip install 'aurelius-capital[ml]'")
    return _embedder_cache


def embed_text(text: str) -> list[float] | None:
    """Encode text to a 384-dim unit vector. Returns None if embedder unavailable."""
    if not text or not text.strip():
        return None
    embedder = _get_embedder()
    if not embedder:
        return None
    return embedder.encode(text, normalize_embeddings=True).tolist()


class KnowledgeGraph:
    def __init__(self, db_path: str = "./data/knowledge_graph.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None
        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")
        with self._conn() as conn:
            for stmt in _SCHEMA:
                conn.execute(stmt)
            self._init_fts(conn)
            self._migrate_embedding_column(conn)

    def _migrate_embedding_column(self, conn: duckdb.DuckDBPyConnection) -> None:
        try:
            conn.execute("ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS embedding FLOAT[]")
        except duckdb.Error:
            pass  # already exists in older DuckDB — silently continue

    def _init_fts(self, conn: duckdb.DuckDBPyConnection) -> None:
        try:
            conn.execute("INSTALL fts")
            conn.execute("LOAD fts")
            conn.execute(
                "PRAGMA create_fts_index("
                "  'kg_nodes', 'id', 'label', 'text_corpus',"
                "  stemmer='porter', stopwords='english', overwrite=1"
                ")"
            )
        except duckdb.Error as exc:
            logger.warning("kg_fts_init_skip", reason=str(exc)[:120])

    def rebuild_fts(self) -> None:
        with self._conn() as conn:
            self._init_fts(conn)

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

    # ── Nodes ────────────────────────────────────────────────────────────────

    def upsert_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        properties: dict[str, Any] | None = None,
        text_corpus: str = "",
        created_by: str = "system",
        change_reason: str = "",
    ) -> None:
        props = json.dumps(properties or {}, default=str)
        now = _now()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT version FROM kg_nodes WHERE id = ?", [node_id]
            ).fetchone()
            if existing:
                version = existing[0]
                snapshot = _as_dicts(
                    conn.execute("SELECT * FROM kg_nodes WHERE id = ?", [node_id])
                )[0]
                conn.execute(
                    """INSERT INTO kg_node_history
                       (node_id, version, snapshot, changed_at, changed_by, change_reason)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        node_id,
                        version,
                        json.dumps(snapshot, default=str),
                        now,
                        created_by,
                        change_reason,
                    ],
                )
                conn.execute(
                    """UPDATE kg_nodes SET label=?, properties=?, text_corpus=?,
                       updated_at=?, created_by=?, version=version+1, change_reason=?
                       WHERE id=?""",
                    [label, props, text_corpus, now, created_by, change_reason, node_id],
                )
            else:
                conn.execute(
                    """INSERT INTO kg_nodes
                       (id, type, label, properties, text_corpus, \
                        created_at, updated_at, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [node_id, node_type, label, props, text_corpus, now, now, created_by],
                )

    def upsert_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
        created_by: str = "system",
    ) -> None:
        edge_id = _edge_id(source_id, target_id, rel_type)
        props = json.dumps(properties or {})
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO kg_edges
                   (id, source_id, target_id, rel_type, properties, created_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (source_id, target_id, rel_type) DO UPDATE SET
                   properties = excluded.properties""",
                [edge_id, source_id, target_id, rel_type, props, now, created_by],
            )

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            rows = _as_dicts(conn.execute("SELECT * FROM kg_nodes WHERE id = ?", [node_id]))
            return rows[0] if rows else None

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        rel_types: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        rel_filter = ""
        rel_params: list[Any] = []
        if rel_types:
            ph = ",".join("?" * len(rel_types))
            rel_filter = f"AND e.rel_type IN ({ph})"
            rel_params = list(rel_types)

        with self._conn() as conn:
            outbound: list[dict[str, Any]] = []
            inbound: list[dict[str, Any]] = []
            if direction in ("out", "both"):
                outbound = _as_dicts(
                    conn.execute(
                        f"""
                    SELECT n.id, n.type, n.label, n.properties, \
                           e.rel_type, e.properties AS edge_props
                    FROM kg_edges e JOIN kg_nodes n ON n.id = e.target_id
                    WHERE e.source_id = ? {rel_filter}
                """,
                        [node_id, *rel_params],
                    )
                )
            if direction in ("in", "both"):
                inbound = _as_dicts(
                    conn.execute(
                        f"""
                    SELECT n.id, n.type, n.label, n.properties, \
                           e.rel_type, e.properties AS edge_props
                    FROM kg_edges e JOIN kg_nodes n ON n.id = e.source_id
                    WHERE e.target_id = ? {rel_filter}
                """,
                        [node_id, *rel_params],
                    )
                )
        return {"outbound": outbound, "inbound": inbound}

    def node_history(self, node_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return _as_dicts(
                conn.execute(
                    "SELECT * FROM kg_node_history WHERE node_id=? ORDER BY version",
                    [node_id],
                )
            )

    # ── Graph traversal ───────────────────────────────────────────────────────

    def traverse(self, root_id: str, depth: int = 2) -> dict[str, Any]:
        """BFS subgraph up to `depth` hops. Returns {nodes, edges} for visualization."""
        visited: set[str] = set()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        frontier: set[str] = {root_id}

        with self._conn() as conn:
            for _ in range(depth):
                if not frontier:
                    break
                ph = ",".join("?" * len(frontier))
                edge_rows = _as_dicts(
                    conn.execute(
                        f"""
                    SELECT id, source_id, target_id, rel_type, properties
                    FROM kg_edges
                    WHERE source_id IN ({ph}) OR target_id IN ({ph})
                """,
                        list(frontier) * 2,
                    )
                )

                next_ids: set[str] = set()
                for e in edge_rows:
                    edges.append(e)
                    next_ids.update({e["source_id"], e["target_id"]})

                new_ids = next_ids - visited
                if new_ids:
                    ph2 = ",".join("?" * len(new_ids))
                    node_rows = _as_dicts(
                        conn.execute(
                            f"SELECT id, type, label, properties FROM kg_nodes WHERE id IN ({ph2})",
                            list(new_ids),
                        )
                    )
                    nodes.extend(node_rows)
                    visited.update(new_ids)

                frontier = next_ids - visited

        return {"nodes": nodes, "edges": edges}

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self, query: str, node_type: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        type_filter = "AND type = ?" if node_type else ""
        type_params: list[Any] = [node_type] if node_type else []

        with self._conn() as conn:
            # ponytail: ILIKE fallback is O(n); upgrade to FTS-only once node count exceeds 10k
            try:
                rows = _as_dicts(
                    conn.execute(
                        f"""
                    SELECT *, fts_main_kg_nodes.match_bm25(id, ?) AS score
                    FROM kg_nodes
                    WHERE score IS NOT NULL AND superseded_by IS NULL {type_filter}
                    ORDER BY score DESC LIMIT ?
                """,
                        [query, *type_params, limit],
                    )
                )
            except duckdb.Error:
                rows = _as_dicts(
                    conn.execute(
                        f"""
                    SELECT *, 1.0 AS score FROM kg_nodes
                    WHERE superseded_by IS NULL
                      AND (LOWER(label) LIKE ? OR LOWER(text_corpus) LIKE ?)
                      {type_filter}
                    LIMIT ?
                """,
                        [f"%{query.lower()}%", f"%{query.lower()}%", *type_params, limit],
                    )
                )
        return rows

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover_repeated_failures(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return _as_dicts(
                conn.execute("""
                SELECT
                    json_extract_string(properties, '$.research_category') AS category,
                    json_extract_string(properties, '$.rejection_reason') AS failure_reason,
                    json_extract_string(properties, '$.reasons') AS reasons,
                    COUNT(*) AS occurrences
                FROM kg_nodes
                WHERE type = 'hypothesis'
                  AND json_extract_string(properties, '$.status') IN ('Rejected', 'rejected')
                GROUP BY 1, 2, 3
                HAVING COUNT(*) > 1
                ORDER BY occurrences DESC
            """)
            )

    def discover_successful_feature_families(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return _as_dicts(
                conn.execute("""
                SELECT
                    n_feat.label AS feature,
                    COUNT(DISTINCT e.source_id) AS experiments,
                    AVG(CAST(json_extract_string(n_val.properties, '$.oos_sharpe') AS DOUBLE))
                        AS avg_oos_sharpe
                FROM kg_nodes n_feat
                JOIN kg_edges e ON e.target_id = n_feat.id
                    AND e.rel_type IN ('uses_feature', 'depends_on')
                JOIN kg_nodes n_exp ON n_exp.id = e.source_id AND n_exp.type = 'experiment'
                JOIN kg_edges e2 ON e2.source_id = n_exp.id AND e2.rel_type = 'produces'
                JOIN kg_nodes n_val ON n_val.id = e2.target_id AND n_val.type = 'validation_report'
                WHERE n_feat.type = 'feature'
                  AND json_extract_string(n_val.properties, '$.verdict') = 'accept'
                GROUP BY n_feat.label
                ORDER BY avg_oos_sharpe DESC NULLS LAST
                LIMIT 20
            """)
            )

    def discover_research_gaps(self) -> list[dict[str, Any]]:
        """Datasets referenced in literature but never used in a hypothesis or experiment."""
        with self._conn() as conn:
            return _as_dicts(
                conn.execute("""
                SELECT n_ds.id, n_ds.label AS dataset, COUNT(e_ref.id) AS paper_citations
                FROM kg_nodes n_ds
                JOIN kg_edges e_ref ON e_ref.target_id = n_ds.id AND e_ref.rel_type = 'mentions'
                WHERE n_ds.type = 'dataset'
                  AND NOT EXISTS (
                    SELECT 1 FROM kg_edges e
                    WHERE e.target_id = n_ds.id
                      AND e.rel_type IN ('uses_dataset', 'depends_on')
                  )
                GROUP BY n_ds.id, n_ds.label
                ORDER BY paper_citations DESC
            """)
            )

    def discover_orphans(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return _as_dicts(
                conn.execute("""
                SELECT n.id, n.type, n.label, n.created_at
                FROM kg_nodes n
                WHERE n.superseded_by IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM kg_edges e WHERE e.source_id = n.id OR e.target_id = n.id
                  )
                ORDER BY n.type, n.label
            """)
            )

    def discover_frequent_methodologies(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return _as_dicts(
                conn.execute("""
                SELECT
                    json_extract_string(properties, '$.methodology') AS methodology,
                    json_extract_string(properties, '$.research_category') AS category,
                    COUNT(*) AS paper_count
                FROM kg_nodes
                WHERE type = 'paper'
                  AND json_extract_string(properties, '$.methodology') IS NOT NULL
                  AND json_extract_string(properties, '$.methodology') != ''
                GROUP BY 1, 2
                ORDER BY paper_count DESC
                LIMIT 20
            """)
            )

    def discover_similar_failures(self, keywords: list[str]) -> list[dict[str, Any]]:
        """Experiments that failed with similar reasons — matches any of the given keywords."""
        pattern = "|".join(keywords)
        with self._conn() as conn:
            return _as_dicts(
                conn.execute(
                    """
                SELECT n.id, n.label, n.created_at,
                       json_extract_string(n.properties, '$.verdict') AS verdict,
                       json_extract_string(n.properties, '$.reasons') AS reasons,
                       json_extract_string(n.properties, '$.strategy_name') AS strategy
                FROM kg_nodes n
                WHERE n.type = 'experiment'
                  AND json_extract_string(n.properties, '$.verdict') IN ('reject', 'REJECT')
                  AND regexp_matches(
                      LOWER(COALESCE(json_extract_string(n.properties, '$.reasons'), '')),
                      LOWER(?)
                  )
                ORDER BY n.created_at DESC
            """,
                    [pattern],
                )
            )

    # ── QC ────────────────────────────────────────────────────────────────────

    def qc_report(self) -> dict[str, Any]:
        with self._conn() as conn:
            total_nodes = conn.execute(
                "SELECT COUNT(*) FROM kg_nodes WHERE superseded_by IS NULL"
            ).fetchone()[0]  # type: ignore[index]
            total_edges = conn.execute("SELECT COUNT(*) FROM kg_edges").fetchone()[0]  # type: ignore[index]
            orphans = conn.execute("""
                SELECT COUNT(*) FROM kg_nodes n WHERE superseded_by IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM kg_edges e WHERE e.source_id=n.id OR e.target_id=n.id
                  )
            """).fetchone()[0]  # type: ignore[index]
            broken_sources = conn.execute("""
                SELECT COUNT(*) FROM kg_edges e
                WHERE NOT EXISTS (SELECT 1 FROM kg_nodes n WHERE n.id=e.source_id)
            """).fetchone()[0]  # type: ignore[index]
            broken_targets = conn.execute("""
                SELECT COUNT(*) FROM kg_edges e
                WHERE NOT EXISTS (SELECT 1 FROM kg_nodes n WHERE n.id=e.target_id)
            """).fetchone()[0]  # type: ignore[index]
            duplicate_labels = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT type, LOWER(label), COUNT(*) c
                    FROM kg_nodes WHERE superseded_by IS NULL
                    GROUP BY 1, 2 HAVING c > 1
                )
            """).fetchone()[0]  # type: ignore[index]
            self_loops = conn.execute(
                "SELECT COUNT(*) FROM kg_edges WHERE source_id = target_id"
            ).fetchone()[0]  # type: ignore[index]

        issues = orphans + broken_sources + broken_targets + self_loops
        return {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "orphan_nodes": orphans,
            "broken_edge_sources": broken_sources,
            "broken_edge_targets": broken_targets,
            "duplicate_labels": duplicate_labels,
            "self_loops": self_loops,
            "health": "ok" if issues == 0 else "issues_detected",
        }

    # ── Stats / growth ────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            by_type = _as_dicts(
                conn.execute("""
                SELECT type, COUNT(*) AS count FROM kg_nodes
                WHERE superseded_by IS NULL GROUP BY type ORDER BY count DESC
            """)
            )
            by_rel = _as_dicts(
                conn.execute("""
                SELECT rel_type, COUNT(*) AS count FROM kg_edges
                GROUP BY rel_type ORDER BY count DESC
            """)
            )
            weekly_growth = _as_dicts(
                conn.execute("""
                SELECT DATE_TRUNC('week', created_at) AS week, COUNT(*) AS nodes_added
                FROM kg_nodes GROUP BY 1 ORDER BY 1
            """)
            )
        return {
            "nodes_by_type": by_type,
            "edges_by_relation": by_rel,
            "weekly_growth": weekly_growth,
        }

    # ── Semantic embeddings ───────────────────────────────────────────────────

    def embed_node(self, node_id: str) -> bool:
        """Generate and persist an embedding for one node. Returns True if stored."""
        node = self.get_node(node_id)
        if not node:
            return False
        text = " ".join(filter(None, [node.get("label", ""), node.get("text_corpus", "")]))
        vec = embed_text(text)
        if vec is None:
            return False
        with self._conn() as conn:
            conn.execute("UPDATE kg_nodes SET embedding = ? WHERE id = ?", [vec, node_id])
        return True

    def embed_all_nodes(self) -> int:
        """Embed every node that is missing an embedding. Returns count stored."""
        with self._conn() as conn:
            unembedded = _as_dicts(
                conn.execute(
                    "SELECT id, label, text_corpus FROM kg_nodes "
                    "WHERE embedding IS NULL AND superseded_by IS NULL"
                )
            )
        count = 0
        for row in unembedded:
            text = " ".join(filter(None, [row.get("label", ""), row.get("text_corpus", "")]))
            vec = embed_text(text)
            if vec is None:
                break  # embedder unavailable — abort loop
            with self._conn() as conn:
                conn.execute("UPDATE kg_nodes SET embedding = ? WHERE id = ?", [vec, row["id"]])
            count += 1
        if count:
            logger.info("kg_embed_all_done", count=count)
        return count

    def semantic_search(
        self, query: str, node_type: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Cosine-similarity search via DuckDB list_cosine_similarity.
        Falls back to FTS/ILIKE if sentence-transformers not installed."""
        vec = embed_text(query)
        if vec is None:
            return self.search(query, node_type=node_type, limit=limit)

        type_filter = "AND type = ?" if node_type else ""
        type_params: list[Any] = [node_type] if node_type else []

        with self._conn() as conn:
            try:
                return _as_dicts(
                    conn.execute(
                        f"""
                    SELECT *, list_cosine_similarity(embedding, ?::FLOAT[]) AS score
                    FROM kg_nodes
                    WHERE embedding IS NOT NULL AND superseded_by IS NULL {type_filter}
                    ORDER BY score DESC NULLS LAST LIMIT ?
                """,
                        [vec, *type_params, limit],
                    )
                )
            except duckdb.Error:
                return self.search(query, node_type=node_type, limit=limit)

    def embedding_coverage(self) -> dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM kg_nodes WHERE superseded_by IS NULL"
            ).fetchone()[0]  # type: ignore[index]
            embedded = conn.execute(
                "SELECT COUNT(*) FROM kg_nodes \
                 WHERE embedding IS NOT NULL AND superseded_by IS NULL"
            ).fetchone()[0]  # type: ignore[index]
        return {
            "total": total,
            "embedded": embedded,
            "pct": round(embedded / total * 100, 1) if total else 0,
            "embedder": _EMBED_MODEL if _get_embedder() else "unavailable",
        }

    # ── Escape hatch ──────────────────────────────────────────────────────────

    def raw_query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return _as_dicts(conn.execute(sql, params or []))


if __name__ == "__main__":
    kg = KnowledgeGraph(":memory:")
    kg.upsert_node(
        "paper:test", "paper", "Test Paper on Momentum", text_corpus="momentum volatility filters"
    )
    kg.upsert_node(
        "hyp:test", "hypothesis", "IF momentum THEN alpha", text_corpus="momentum alpha strategy"
    )
    kg.upsert_edge("paper:test", "hyp:test", "proposes")
    results = kg.search("momentum")
    assert len(results) >= 1, f"Search returned nothing: {results}"
    qc = kg.qc_report()
    # hyp:test has 1 edge, paper:test has 1 edge — no orphans expected
    print(f"KG self-check passed. QC: {qc}")
