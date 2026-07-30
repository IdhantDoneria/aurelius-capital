# Research Knowledge Graph — Phase 15

Institutional memory for the Aurelius Capital research platform. Every paper, hypothesis, feature, experiment, and validation result is a node. Every relationship between them is an edge. Researchers query the graph; the graph accumulates knowledge.

---

## Architecture

```
Literature DuckDB  ──┐
Hypothesis DuckDB  ──┤  ingest.py  ──▶  knowledge_graph.duckdb  ──▶  api.py  ──▶  /kg/*
Research DuckDB    ──┘
```

Three layers:
- **`graph.py`** — property graph: schema, CRUD, traversal, search, discovery, QC
- **`ingest.py`** — one adapter per source; all ops idempotent
- **`api.py`** — FastAPI router mounted at `/kg`

Storage is a single DuckDB file (`./data/knowledge_graph.duckdb`, configurable via `KNOWLEDGE_GRAPH_PATH` env var).

---

## Graph Schema

### kg_nodes

| Column | Type | Purpose |
|---|---|---|
| `id` | VARCHAR PK | Preserved from source (paper id, hypothesis uuid, etc.) or `type:slug` for derived entities |
| `type` | VARCHAR | Entity type discriminator |
| `label` | VARCHAR | Human-readable name |
| `properties` | JSON | All type-specific metadata |
| `text_corpus` | VARCHAR | Concatenated text for FTS (abstract, statement, reasons, etc.) |
| `created_at` | TIMESTAMPTZ | First seen |
| `updated_at` | TIMESTAMPTZ | Last modified |
| `created_by` | VARCHAR | Source adapter or researcher |
| `version` | INTEGER | Increments on each update |
| `superseded_by` | VARCHAR | ID of replacement node (soft-delete pattern) |
| `change_reason` | VARCHAR | Why it was updated |

### kg_edges

| Column | Type | Purpose |
|---|---|---|
| `id` | VARCHAR PK | `sha256(source:target:rel_type)[:32]` |
| `source_id` | VARCHAR | FK → kg_nodes.id |
| `target_id` | VARCHAR | FK → kg_nodes.id |
| `rel_type` | VARCHAR | Relationship type |
| `properties` | JSON | Edge metadata |
| `created_at` | TIMESTAMPTZ | |
| `created_by` | VARCHAR | |

UNIQUE constraint on `(source_id, target_id, rel_type)` — upsert-safe.

### kg_node_history

Full snapshot of every node before each update. Provides:
- Time travel ("what did hypothesis X look like when it was first created?")
- Audit trail (who changed it, why, when)

---

## Ontology

### Node Types

| Type | Source | Key properties |
|---|---|---|
| `paper` | LiteratureStore | title, authors, abstract, methodology, factors_studied |
| `author` | LiteratureStore | name |
| `dataset` | All | name |
| `research_category` | Literature + Hypothesis | name |
| `hypothesis` | HypothesisStore | testable_statement, status, confidence_score, research_category |
| `feature` | Hypothesis + Research | name |
| `experiment` | ResearchStore | strategy_name, verdict, oos_sharpe, features_used |
| `validation_report` | ResearchStore | verdict, oos_sharpe, oos_return, reasons |
| `failure_mode` | (derivable via discovery) | description |

Additional types (add nodes manually or via future adapters): `institution`, `factor`, `model`, `production_strategy`, `paper_trading_result`, `portfolio`, `risk_metric`, `statistical_test`, `decision`, `observation`, `tag`, `researcher`, `market`, `asset_class`.

### Relationship Types

| rel_type | From | To | Meaning |
|---|---|---|---|
| `authored_by` | paper | author | Paper has this author |
| `mentions` | paper | dataset | Paper references this dataset |
| `categorized_as` | paper / hypothesis | research_category | Belongs to category |
| `proposes` | paper | hypothesis | Paper is the intellectual source |
| `uses_dataset` | hypothesis | dataset | Hypothesis requires this dataset |
| `uses_feature` | hypothesis | feature | Hypothesis specifies this feature |
| `similar_to` | hypothesis | hypothesis | Near-duplicate detection |
| `generates` | hypothesis | experiment | Experiment tests this hypothesis |
| `depends_on` | experiment | feature | Feature used in this experiment |
| `produces` | experiment | validation_report | Experiment yields this result |
| `evaluates` | validation_report | hypothesis | Report judges this hypothesis |
| `references` | paper | paper | Citation (add via future citation adapter) |

Future rel_types (add without schema changes): `caused_by`, `affects`, `belongs_to`, `derived_from`, `affiliated_with`, `tagged_with`.

---

## API Endpoints

All endpoints are mounted at `/kg`.

### Search & Retrieval

| Method | Path | Description |
|---|---|---|
| `GET` | `/kg/search?q=momentum volatility` | BM25 full-text search across all entities |
| `GET` | `/kg/search?q=...&node_type=hypothesis` | Filtered by entity type |
| `GET` | `/kg/nodes/{id}` | Node detail + direct neighbors |
| `GET` | `/kg/nodes/{id}/history` | All prior versions |
| `GET` | `/kg/graph?root_id={id}&depth=2` | BFS subgraph for visualization |

### Discovery

| Method | Path | Description |
|---|---|---|
| `GET` | `/kg/discover/failures` | Repeated failure patterns across rejected hypotheses |
| `GET` | `/kg/discover/features` | Features associated with accepted experiments |
| `GET` | `/kg/discover/gaps` | Datasets cited but never tested |
| `GET` | `/kg/discover/orphans` | Nodes with no edges |
| `GET` | `/kg/discover/methodologies` | Most frequently used methodologies |
| `GET` | `/kg/discover/similar-failures?keywords=overfitting,data_snooping` | Experiments failing for similar reasons |

### Operations

| Method | Path | Description |
|---|---|---|
| `POST` | `/kg/ingest` | Sync all sources into the KG (idempotent) |
| `GET` | `/kg/stats` | Node/edge counts by type, weekly growth |
| `GET` | `/kg/qc` | Quality control: orphans, broken refs, duplicates |
| `GET` | `/kg/query?sql=SELECT...` | Raw DuckDB SQL (SELECT only, internal tooling) |

---

## Search Engine

**Primary:** DuckDB FTS extension (BM25 with Porter stemmer, English stopwords) on `label` and `text_corpus` columns. Rebuilt after every `ingest_all()` call.

**Fallback:** `ILIKE` search on `label` and `text_corpus` if FTS index is unavailable.

**Semantic/embedding search:** Not implemented. The FTS engine covers ~90% of research queries. Add sentence-transformers embeddings as `FLOAT[]` column and use DuckDB's `list_cosine_similarity` when false-negative rate becomes measurable.

---

## Versioning

Every `upsert_node()` call on an existing node:
1. Saves the current row to `kg_node_history` (keyed by `node_id + version`)
2. Increments `version` and records `change_reason`

Nodes are never deleted — use `superseded_by` for soft replacement.

---

## Visualization

`GET /kg/graph?root_id=...&depth=N` returns `{nodes: [...], edges: [...]}` compatible with:
- **Cytoscape.js** — direct consumption of `nodes`/`edges` arrays
- **D3 force-directed** — use `nodes` and `edges` as `links`
- **Sigma.js** — wrap in its graph format

No server-side rendering library needed.

---

## Extension Points

**New node type:** Just call `upsert_node(..., node_type="my_new_type", ...)`. No schema change.

**New relationship type:** Just call `upsert_edge(..., rel_type="my_new_rel", ...)`. No schema change.

**New ingestion source:** Add a function `ingest_source(kg, db_path)` in `ingest.py` and register it in `ingest_all()`.

**Automated ingestion:** Wire `ingest_all()` to a scheduler (e.g. after each `HypothesisStore.save()`, after each `ResearchStore.record_experiment()`). The KG will update continuously.

---

## Example Queries (via `/kg/query`)

```sql
-- "Show every failed momentum hypothesis that used volatility filters"
SELECT n.id, n.label, json_extract_string(n.properties, '$.rejection_reason') AS reason
FROM kg_nodes n
JOIN kg_edges e ON e.source_id = n.id AND e.rel_type IN ('uses_feature', 'uses_dataset')
JOIN kg_nodes nf ON nf.id = e.target_id AND LOWER(nf.label) LIKE '%volat%'
WHERE n.type = 'hypothesis'
  AND json_extract_string(n.properties, '$.research_category') LIKE '%momentum%'
  AND json_extract_string(n.properties, '$.status') IN ('Rejected', 'rejected');

-- "Which datasets are most frequently associated with successful strategies?"
SELECT nf.label AS dataset, COUNT(DISTINCT ne.id) AS experiments,
       AVG(CAST(json_extract_string(nv.properties, '$.oos_sharpe') AS DOUBLE)) AS avg_sharpe
FROM kg_nodes nf
JOIN kg_edges e1 ON e1.target_id = nf.id AND e1.rel_type = 'uses_dataset'
JOIN kg_nodes nh ON nh.id = e1.source_id AND nh.type = 'hypothesis'
JOIN kg_edges e2 ON e2.source_id = nh.id AND e2.rel_type = 'generates'
JOIN kg_nodes ne ON ne.id = e2.target_id AND ne.type = 'experiment'
JOIN kg_edges e3 ON e3.source_id = ne.id AND e3.rel_type = 'produces'
JOIN kg_nodes nv ON nv.id = e3.target_id
WHERE json_extract_string(nv.properties, '$.verdict') = 'accept'
  AND nf.type = 'dataset'
GROUP BY nf.label ORDER BY avg_sharpe DESC;

-- "What papers influenced our highest-confidence research?"
SELECT np.label AS paper, nh.label AS hypothesis,
       CAST(json_extract_string(nh.properties, '$.confidence_score') AS DOUBLE) AS confidence
FROM kg_nodes np
JOIN kg_edges e ON e.source_id = np.id AND e.rel_type = 'proposes'
JOIN kg_nodes nh ON nh.id = e.target_id AND nh.type = 'hypothesis'
WHERE np.type = 'paper'
ORDER BY confidence DESC NULLS LAST LIMIT 20;
```

---

## QC Checks

Run automatically via `GET /kg/qc`. Detects:
- **Orphan nodes** — nodes with no edges (possible ingestion error)
- **Broken edge sources/targets** — edge points to non-existent node
- **Duplicate labels** — same label + type more than once (possible duplicate entity)
- **Self-loops** — edge from node to itself (always a bug)

Missing metadata detection: use `raw_query` with `json_extract_string(properties, '$.field') IS NULL`.
