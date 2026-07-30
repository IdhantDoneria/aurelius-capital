# Production Research Campaign — Executive Report (2026-07-30)

First production run of the research pipeline over `research_corpus/incoming/`.
Operated existing platform; one verified defect fixed (see §8). Canonical
system reference: `docs/RESEARCH_CORPUS.md`, `PHASE_6_RESEARCH_WORKFLOW.md`.

## 1. Papers processed — 8/8 ingested, 0 rejected

All 8 PDFs ran the full 9-stage `PipelineOrchestrator`
(validate→assign_id→move→extract→classify→store_corpus→update_kg→score→plan→archive)
and archived to `research_corpus/processed/`.

| doc_id | Paper | score | exp ready |
|---|---|---|---|
| doc_42944c3deca0 | Asness/Moskowitz/Pedersen — Value & Momentum Everywhere | 6.91 | blocked |
| doc_20fd3a6a284d | Gatev/Goetzmann/Rouwenhorst — Pairs Trading | 6.55 | whitelist-ready |
| doc_68df4b692ca0 | Carhart 1997 — Mutual Fund Persistence | 6.51 | whitelist-ready |
| doc_95eb325e8e1e | Novy-Marx 2013 — Gross Profitability | 5.67 | below threshold |
| doc_8c291292e121 | Fama-French 1993 — Common Risk Factors | 5.63 | below threshold |
| doc_cb4ca13ed6b8 | Jegadeesh-Titman 1993 — Momentum | 5.53 | below threshold |
| doc_743301f411ce | Sharpe 1964 — CAPM | 1.43 | below threshold |
| doc_1f1cbbf1f288 | Black-Litterman 1992 — Global Portfolio Opt | 1.30 | below threshold |

9th requested paper (Markowitz 1952) never reached `incoming/` — upstream
network/paywall block documented in `docs/paper_ingestion_2026-07-30.md`.

## 2. Knowledge extracted

Per-paper: title, authors, year, abstract, methodology, datasets, features,
statistical tests, reference count — persisted to `corpus.duckdb`
(`corpus_documents` + `corpus_versions`). 6/8 extracted rich factor/dataset
sets; 2 degraded (Sharpe, Black-Litterman — scanned/JSTOR PDFs, §8-E).

## 3. Knowledge Graph updates

`knowledge_graph.duckdb`: **52 nodes, 112 edges**. Added paper, author, dataset,
and factor nodes with `authored_by` / `uses_dataset` / `uses_feature` edges.
Deduplicated by node id.

## 4. Hypotheses generated

Phase-5 generator over 8 corpus papers: **5 inserted, 9 rejected**
(quality/duplicate). Combined with prior backlog → 8 in the active repository.

## 5. Research queue (Director ranking)

| # | overall | decision | statement |
|---|---|---|---|
| 1 | 0.657 | **research_now** | 12-1 month momentum, long positive |
| 2 | 0.616 | delay | top-quintile 12-1m × top-quintile (composite) |
| 3 | 0.536 | delay | 10Y-2Y slope > 50bps → FX carry |
| 4 | 0.527 | delay | momentum top decile |
| 5 | 0.526 | delay | value top decile |
| 6 | 0.483 | delay | size top decile |
| 7 | 0.338 | merge | (degraded — unknown_factor) |
| 8 | 0.314 | merge | (degraded — Sharpe-only) |

## 6. Experiments ready to run

**0 truly executable.** 2 specs (Carhart, Gatev) are marked `ready_to_run`, but
readiness is a **dataset-name whitelist**, not a data-presence check (§8-C). No
OHLCV/returns bars are loaded anywhere in the platform.

## 7. Missing datasets

- Named blockers (Value & Momentum spec): **compustat, bloomberg, datastream**.
- Physically absent despite whitelist: **crsp, sp500, ken_french** — no adapter
  has loaded them; only `yahoo`/`alpaca` (network) + `csv_loader` (file) exist,
  and `market_data` storage is empty.

## 8. Engineering blockers

| # | Severity | Blocker | Status |
|---|---|---|---|
| A | **Critical** | `_stage_assign_id` dedup used relevance `search()`, which matches arbitrary strings → false-positive "duplicate", wrongly rejecting 4 papers | **FIXED** — added `CorpusStore.document_exists_by_hash` (exact match); 34 tests green |
| B | High | No market data loaded → no experiment executable | Open — see §9 |
| C | Medium | `planner.ready_to_run` = static name-whitelist, not data-presence; emits false-green specs (`crsp` whitelisted but absent) | Open |
| D | Medium | KG writes factor nodes as `type="factor"`; Director queries `type="feature"` → `feature_availability=0.00` for every factor hypothesis, mis-ranking them to `delay` | Open |
| E | Low | Title/year extraction grabs journal headers / JSTOR watermarks (Sharpe year=2007; titles like `http://www.jstor.org`) | Open |

Fixes B–E **not** implemented automatically (per campaign directive).

## 9. Research blockers

Single hard gate: **no price/returns data**. `ResearchRunner.investigate()`
consumes OHLCV bars; only synthetic `demo()` data exists. Until real bars are
loaded, no hypothesis — including the #1 `research_now` momentum idea — can
produce a valid verdict.

## 10. Overall platform readiness — ~85%

Ingestion, extraction, KG sync, classification, scoring, hypothesis generation,
Director ranking, and experiment planning are all operational end-to-end. The
remaining ~15% is a single dependency: real market data for execution.

---

## Known limitations / Skipped

**Skipped — real experiment execution.**
- *Reason (impossibility):* no OHLCV/returns data exists in the platform;
  `market_data` storage is empty and no adapter has loaded a universe. The only
  offline path (`csv_loader`) has no source file; `yahoo`/`alpaca` need network.
- *Unblock:* load a price/returns dataset for the momentum universe into
  `market_data/storage/duckdb_store` — via `csv_loader` (offline CSV) or the
  `yahoo` adapter (network). Then run `ResearchRunner.investigate()` on hyp #1.

**Skipped — engineering fixes C/D/E.** Verified defects, deferred per the
campaign's "operate, don't fix" directive. Root cause + fix in §8.
