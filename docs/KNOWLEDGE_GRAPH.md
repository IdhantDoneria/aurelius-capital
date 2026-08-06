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

---

## Momentum Campaign synthesis (2026-08-03)

Institutional-memory deltas from the 14-run US+India momentum campaign
(`campaign/momentum/Knowledge_Graph_Summary.md`):

1. **Momentum is market-structure-dependent, not universal.** US = weak,
   insignificant long/short relative-strength (best +58.8% WML, p 0.161). India =
   significant long-only trend (+416%, Sharpe 1.012, p 0.026); its L/S version is
   destroyed by the short leg.
2. **The short leg is the liability.** Carries the −71% drawdown in the US;
   flips every India L/S book negative in a bull regime (momentum-crash asymmetry).
3. **Leverage-cap × decile-breadth (M3) is a first-order fidelity constraint on
   all L/S factor books.** Fixed 5%/name × ~200 decile names = ~10× nominal gross
   vs a 1.5× cap → ~30 names fill. Uniform US+India; not a defect.
4. **Long-only > long/short momentum in a trending single-regime market**
   (India). Regime- and survivorship-dependent.
5. **0 platform defects** across 14 runs + a leverage root-cause investigation.
6. **Robust vs fragile:** robust (directional) = 6m formation, extreme deciles,
   monthly rebalance; fragile = the L/S spread, tercile breadth, 63-day holding;
   data-dependent = India significance (bull + survivorship).

## Pairs Trading Campaign synthesis (2026-08-04)

Institutional-memory deltas from the 14-run US+India pairs campaign
(`campaign/pairs/Knowledge_Graph_Summary.md`):

1. **Distance-pairs stat-arb does NOT survive to 2014–2026 US+India.** 0/14 configs
   significant (all adjusted p = 1.000, all OOS Sharpe negative). Do & Faff's
   (2010/2012) decay-to-below-costs, confirmed empirically. A well-powered null
   (591–4833 OOS trades/config), not a sample artifact — the old toy blocker (22
   trades) is resolved.
2. **Gatev faithfully reproduced, still rejects.** 12-mo SSD formation, top-N
   portfolio, 2-SD entry / convergence exit on 300 liquid names; US canonical
   −1.076 / −5.7%, India −0.425 / +8.7%, both REJECT. Failure is Class D (market
   evolution), not a defect.
3. **Diversification INVERTS under fixed-% sizing + the 1.5× gross cap.** top40 is
   the worst config in both markets (−60% / −42% drawdown): 40 pairs × 2 legs × 5%
   = 400% nominal gross → truncation breaks dollar-neutrality → directional risk.
   Same leverage constraint as momentum (M3/P5); first-order for any market-neutral
   book. More pairs made it worse — opposite of Gatev.
4. **India less-efficient ⇒ less-bad, not good** — beats US on 5/7 configs, faint
   positive returns, but every config still insignificant and survivorship-inflated.
5. **0 platform defects** across 14 pairs runs.
6. **No production strategy justified** (unlike momentum's 1 config). Negative
   result is the deliverable; gate any revisit behind P5 sizing + P3 re-formation +
   delisting data.
7. **`MultiPairStrategy` = composition, not engine change** — N `PairsStrategy` in
   one backtest yields a true diversified equity curve (averaging N Sharpes would
   fake it).

## Momentum campaign — CLOSED / ARCHIVE (2026-08-05, M11)

Program-level node. Full detail: `campaign/momentum/Knowledge_Graph_Summary.md` +
`campaign/momentum/Momentum_*.md`.

1. **Hypothesis FALSIFIED** — "cross-sectional price momentum on 2014–2026 price-only
   data is deployable alpha." Direct falsifiers: M5 gross OOS negative (−23.76%, no
   alpha at zero cost), M10 continuous-deployment ruin (>100% DD) + negative
   liquidity-filtered returns (−10/−23/−42%), 0/14 configs significant.
2. **Internally consistent, 0 platform defects** across M1–M10 (M9 forensic audit:
   deterministic, no leakage, cap/async amplifiers not defects).
3. **Kept as infrastructure** (survive the archive): M2 $5 screen, M4 1-month skip,
   M5 dual gross/net reporting, **M8 bounded equal-weight construction** (mandatory for
   any universe-reducing campaign), M7 generic liquidity framework (default OFF).
4. **Data ceiling is binding** (M6): price+volume only, survivorship-inflated. Single
   highest-leverage action = acquire **CRSP + Compustat** (PIT membership, delisting
   returns, fundamentals).
5. **Next-alpha ranking** (`Momentum_Future_Roadmap.md`): runnable-now = low-vol >
   residual-momentum > mean-reversion; post-data flagship = value > quality/
   profitability; pairs already 0/14; alt-data strategic/blocked.
6. **Decision: ARCHIVE.** Retire the signal, keep the platform. M12 = new alpha family
   from the roadmap.

## M12 — Low-Volatility (2026-08-06) — REJECT

1. **Low-vol L/S has no risk-adjusted edge here.** Canonical adjusted p = 0.366, OOS
   Sharpe 0.176; 0/8 variants clean. Shape of the anomaly present, significance absent.
2. **Third L/S equity family to die by short-leg ruin** (after momentum, pairs).
   Continuous DD −103% at *zero* cost; NAV-proportional sizing under the 1.5× gross cap
   compounds the short high-vol leg through zero equity. Genuine behavior, **no defect**
   (M9). Positive OOS slice (+20.9%) coexists with continuous ruin because slices reset
   capital.
3. **High-vol names are illiquid micro-caps** → short-leg capacity floor ₹0.27 cr vs
   long-leg ₹16 cr. Low-vol must be **long-biased** to deploy.
4. **Cost is never the L/S killer; construction is** (~4pp gross-to-high vs −100%+ DD).
5. **0 significant L/S equity factors on 2014–2026 Aurelius data** (momentum 0/14 L/S,
   pairs 0/14, low-vol 0/8). Only survivor pattern = long-only single-market. Next-value
   actions: long-only low-vol, vol-scaled construction, **acquire CRSP + Compustat**
   (unblocks idio-vol/BAB, survivorship, fundamentals — program-wide binding constraint).
6. **`LowVolStrategy` factor kept** as infrastructure for the long-only future test.

## M13 — Long-Only Low-Volatility (2026-08-06) — DEFER

1. **Removing the short leg removes the ruin — M12's diagnosis confirmed.** Long-only
   low-vol (allow_short=False, else frozen vs M12) continuous DD −36.26% vs L/S −103.35%;
   no ruin in any variant. The short high-vol leg was the whole problem.
2. **Deployable but not significant.** Canonical adjusted p = 0.1182 (fails 5% gate,
   ~3× closer than M12's 0.366); continuous Sharpe 0.31 / CAGR 8.3%; ₹12.19 cr capacity
   (p10), turnover 0.19. Verdict **reject** on the gate, but the book is economically live.
3. **Edge is regime-concentrated, not stationary.** IS Sharpe 0.017 (flat, carries the
   full −36% DD) vs OOS Sharpe 0.609 (−7.4% DD, 2022–2026). The two-pass framework
   won't certify an effect living entirely in the recent third → p = 0.118.
4. **Robust in sign, modest in magnitude.** 4/5 live variants positive non-ruined
   (lb_126, rb_63, downside, liq_50; liquidity filter *improves*); Sharpe clusters
   ~0.27–0.31; lb_504 starved (0 trades, data-length limit, same as M12-R2).
5. **Beta confound is the binding issue.** A long-only low-vol equity book is
   beta-dominated; 8.3% CAGR is below passive US equity 2014–2026. Alpha cannot be
   separated from market beta without a factor model (M6 ceiling) → **CRSP/Compustat is
   the unblock**. Raw-return significance already fails; beta-adjusted could only be
   stricter.
6. **Certification DEFER, platform defects None.** Not ADOPT (fails gate, beta-confounded),
   not REJECT (no defect, deployable, promising). Distinct from M12 REJECT: M12 was
   structurally broken; M13 is viable but unproven. `LowVolStrategy` long-only path kept.
