# Mentisrex Operations Engine — Runbook

## Overview

The Operations Engine transforms the Mentisrex platform into a continuously operating
autonomous research organization. Drop a paper in `research_corpus/incoming/` — the
engine handles everything else.

## Folder Structure

```
research_corpus/
  incoming/        ← Drop papers here (txt, md, pdf, rst, tex, json)
  processing/      ← Active pipeline (do not touch; engine owns this)
  processed/       ← Successfully ingested papers
  rejected/        ← Failed papers with error reports in metadata/
  metadata/        ← JSON job records for every processed paper
  extracted/       ← Raw text extracted from each paper
  summaries/       ← (Reserved for future summarization output)
  experiments/     ← Auto-generated experiment specification JSON files
  reports/         ← Daily pipeline reports (report_YYYY-MM-DD.json)
  logs/            ← JSONL pipeline journals (pipeline_YYYYMMDD.jsonl)
```

## Daily Workflow

1. New papers detected by `FolderWatcher` (polls every 30s)
2. Validate → assign content hash → move to `processing/`
3. Extract metadata (title, authors, abstract, datasets, features, stats)
4. Store in `CorpusStore` (auto-classifies via `CorpusClassifier`)
5. Update `KnowledgeGraph` (paper, author, dataset, factor nodes + edges)
6. Score priority (0-10 across 6 factors)
7. If score ≥ 6.0 → generate experiment spec → write to `experiments/`
8. Archive to `processed/`
9. All state journalled to `logs/` for resumability

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/operations/health` | Pipeline health snapshot |
| GET | `/operations/metrics` | Today's processing metrics |
| GET | `/operations/queue` | File counts per folder |
| POST | `/operations/ingest/path` | Ingest file by absolute path |
| GET | `/operations/experiments` | List queued experiment specs |
| GET | `/operations/reports` | List available daily reports |
| GET | `/operations/reports/{date}` | Get report for YYYY-MM-DD |
| POST | `/operations/reports/generate` | Generate today's report now |
| POST | `/operations/watcher/start` | Start folder watcher |
| POST | `/operations/watcher/stop` | Stop folder watcher |
| GET | `/operations/dashboard` | HTML monitoring dashboard (auto-refresh 30s) |

## Configuration

`OperationsConfig` defaults (override by constructing with custom values):

| Field | Default | Description |
|-------|---------|-------------|
| `corpus_root` | `research_corpus/` | Root folder |
| `poll_interval_seconds` | 30 | Watcher poll interval |
| `max_retries` | 3 | Retries per stage on failure |
| `retry_delay_seconds` | 60 | Base delay (exponential backoff) |
| `min_priority_for_experiment` | 6.0 | Score threshold for experiment generation |
| `max_concurrent_experiments` | 3 | Max parallel experiments (scheduler) |
| `daily_report_hour` | 8 | UTC hour for daily report generation |

## Self-Healing

On stage failure:
- **Fatal stages** (`validate`, `assign_id`): immediate rejection to `rejected/`
- **Retryable stages**: up to `max_retries` attempts with exponential backoff
- After max retries: paper moved to `rejected/`, metadata logged, pipeline continues
- On restart: `resume_incomplete()` finds jobs stuck in `processing/` and reprocesses

Error categories and responses:
- `file_missing` → logged, no retry (file gone)
- `db_error` → retry with backoff
- `network_error` → retry with backoff
- `permission_error` → logged, requires manual fix
- `unknown_error` → retry, then reject if exhausted

## Priority Scoring

Papers scored 0-10 across 6 weighted factors:

| Factor | Weight | Signal |
|--------|--------|--------|
| Novelty | 20% | Publication year (newer = higher) |
| Influence | 15% | Reference count + statistical tests |
| Reproducibility | 20% | Has methodology + datasets + results |
| Dataset Availability | 20% | Known available datasets mentioned |
| Expected Value | 15% | Abstract quality + features + results |
| Engineering Effort | 10% | Complexity estimate (inverted) |

Papers scoring < 6.0 are stored in the corpus but no experiment is planned.

## Monitoring Dashboard

Live at `/operations/dashboard` — auto-refreshes every 30s.

Health states:
- **healthy**: incoming < 50, processing < 10, reject rate < 30%
- **degraded**: any threshold exceeded

## Licensing Compliance

The engine only ingests:
- Files manually placed in `research_corpus/incoming/`
- Files referenced by absolute path via `/operations/ingest/path`

It does NOT automatically fetch from the internet. Open-access source connectors
(arXiv, SSRN, etc.) are already implemented in `src/mentisrex/literature/` — wire
them to `FolderWatcher.process_now()` to enable automatic discovery.

No paywalled content is fetched. If a dataset referenced in a paper is unavailable,
the experiment spec records it in `missing_prerequisites` and `ready_to_run: false`.

## PDF Support

PDF text extraction requires `pypdf`:

```bash
uv add pypdf
```

Without it, the engine processes `.txt`, `.md`, `.rst`, `.tex`, and `.json` files.
PDFs without pypdf are logged as unsupported and moved to `rejected/`.

## Token Optimization

- Pipeline state stored in compact JSONL journals (not DB)
- Metadata indexed in `research_corpus/metadata/` as individual JSON files
- No full repository reload needed for operations queries
- Dashboard reads from folder counts + journal (no DB query)
- Future prompts: load only `docs/OPERATIONS_RUNBOOK.md` + `src/mentisrex/operations/config.py` for ops context

## Known Limitations / Skipped

**Embeddings** (`research_corpus/embeddings/`):
- Folder created, no implementation.
- Requires `sentence-transformers` (optional dep) + embedding model.
- Add when semantic search across the corpus is needed.

**Summaries** (`research_corpus/summaries/`):
- Folder created, no implementation.
- Requires LLM client injection (same seam as `hypothesis/generator.py`).
- Add when executive summarization of papers is needed.

**Automatic open-access fetching**:
- Existing `literature/` module has arXiv/NBER/CrossRef extractors.
- Not wired to watcher automatically — avoids unauthorized bulk scraping.
- Unblock: call `FolderWatcher.process_now(path)` from a scheduled fetcher.

**Experiment execution trigger**:
- Specs written to `experiments/`; lab supervisor runs independently.
- Direct trigger from pipeline to lab supervisor not implemented.
- Unblock: call `LabSupervisor.run_cycle()` after spec is written.
