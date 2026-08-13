# Autonomous Research Laboratory — Phase 18

The operational layer. It coordinates every previously built framework into one
continuous research cycle and runs it, unattended, for as long as the process
lives. It **redesigns nothing** — it sequences the existing literature,
hypothesis, director, backtesting, validation, knowledge-graph, intelligence, and
paper-outcome subsystems through a single Supervisor.

**Core rule:** no subsystem calls another directly. The Supervisor is the only
component wired to all of them; it routes every hand-off through a shared
per-cycle state dict and records a complete audit trail.

---

## Architecture

```
                         ┌──────────────────────────────────────────┐
                         │              Supervisor                   │
 external scheduler ───► │  run_cycle()  → 13 ordered, gated jobs    │
 (cron / worker /        │  run_forever(interval)                    │
  POST /lab/run)         │  retry · deps · resource budget · notify  │
                         └───┬───────────────────────────────────┬───┘
                             │ (only the Supervisor talks to)     │
      ┌──────────────────────┼──────────────┬──────────┬─────────┼─────────┐
      ▼                      ▼              ▼          ▼         ▼         ▼
 LiteratureStore     HypothesisStore   Director   Runner    KnowledgeGraph  Intelligence
 (+ enrichment)      (+ dedup)         (priority) (backtest+ (ingest/QC)     (recs/reports)
                                                  validation)                 + PaperOutcomeStore
      │                                                                          ▲
      └──────────────────────────► LabJournal (append-only audit trail) ─────────┘
```

Files: `src/mentisrex/lab/{supervisor,monitor,journal,api}.py`, dashboard at
`static/lab_dashboard.html`.

## The research cycle (13 steps)

Each step reads/writes the shared cycle state, is retried on failure, and is
journalled. Steps map 1:1 onto the spec; every one calls an existing framework.

| # | Step | Calls | Notes |
|---|------|-------|-------|
| 1 | discover_literature | `paper_source()` | **seam** — skips if no source wired |
| 2 | update_literature | `LiteratureStore.upsert` + `enrichment.enrich` | enrichment skipped if no LLM |
| 3 | generate_hypotheses | `hypothesis.generator.generate` | template fallback if no LLM |
| 4 | compare_knowledge_graph | `KnowledgeGraph.search` | annotates candidates with prior art |
| 5 | remove_duplicates | `deduplication.check_duplicates` | drops exact dupes, sets `similar_to`, inserts |
| 6 | prioritize | `ResearchDirector.prioritize` | fills the cycle compute budget greedily |
| 7 | create_experiment_specs | (maps category → strategy template) | builds runnable specs |
| 8 | execute_experiments | `ResearchRunner.investigate` | **seam** — skips if no `bars_provider` |
| 9 | statistical_validation | (inside `investigate`) | summarises verdicts |
| 10 | store_results | (inside `investigate`) | confirms persistence |
| 11 | update_knowledge_graph | `knowledge.ingest.ingest_all` | full resync; live hooks already fired |
| 12 | recommendations | `ResearchIntelligence.recommendations` | evidence-cited advice |
| 13 | reports | `ResearchIntelligence.report` | writes markdown to `reports_dir` |

## Orchestration primitives

- **Scheduling** — `run_cycle()` (one pass) or `run_forever(interval_s, max_cycles)`. External process supervision (systemd/cron/worker) owns process lifetime; each cycle is independent so a restart resumes on the next tick.
- **Job orchestration** — steps run in declared order; each produces a `JobResult` (status, attempts, duration, summary, reason/error).
- **Retry logic** — a step raising a normal exception retries up to `retries` (default 2) with capped exponential backoff.
- **Dependency management** — steps declare hard deps; if a dep is `skipped`/`failed`, the dependent step is skipped with `dependency X was <status>`.
- **Resource management** — step 6 bin-packs the actionable backlog into `cycle_budget_min` experiment-minutes (via the Director's per-hypothesis resource estimates).
- **Failure recovery** — a failed non-critical step is recorded and the cycle **continues**; `run_forever` never lets a crashed cycle kill the loop.
- **Monitoring** — `LabMonitor.snapshot()` (see below).
- **Notifications** — `notifier(level, event, **data)`, default = structured log. Inject a Slack/email/PagerDuty sink to route alerts.
- **Audit trail** — `LabJournal` writes one JSON line per job + cycle boundary to `lab_journal.jsonl`. Months of operation are reconstructable from this file alone.

## Monitoring (`LabMonitor.snapshot`)

Every metric the spec names:

| Key | Source |
|-----|--------|
| research_throughput | hypothesis store totals + status mix |
| experiment_throughput | Director learning stats (count, per-week, accept rate) |
| knowledge_growth | KG node totals + weekly growth |
| system_health | KG QC + last-cycle failures + job failure rate → ok/degraded |
| research_failures | job failure rate + experiment reject rate |
| queue_health | Director backlog size + duplicate rate + cycles observed |
| resource_utilization | backlog runtime vs cycle budget (budget pressure) |

## API

| Endpoint | Purpose |
|----------|---------|
| `POST /lab/run` | run one full cycle synchronously; returns audit summary |
| `GET /lab/status` | config (which seams are wired) + last cycle |
| `GET /lab/monitor` | full monitoring snapshot |
| `GET /lab/cycles?n=` | recent cycle summaries |
| `GET /lab/audit?cycle_id=` | full audit trail for a cycle |
| `GET /lab/dashboard/view` | HTML operations dashboard (pipeline + monitoring) |

## Data flow (one cycle)

1. Supervisor mints a `cycle_id`, journals `cycle_start`.
2. Steps 1–13 run in order; each hand-off goes through `state`, never subsystem→subsystem.
3. Every job appends a `job` record to the journal; failures notify.
4. `cycle_complete` is journalled with ok/skipped/failed tally; `last_cycle` cached.
5. `LabMonitor` reads stores + journal on demand for the dashboard.

## Running continuously

- **Worker mode**: a process calling `Supervisor(...).run_forever(interval_s=3600)`.
- **Scheduler mode**: cron/systemd-timer hitting `POST /lab/run` on a cadence.
- Point `report_periods=("daily","weekly","monthly")` and schedule cadence so the right report lands each run.
- Wire `notifier` to your alerting so `lab_step_failed` / `lab_cycle_crashed` page a human.

## Extension points

- **`paper_source`** — `Callable[[], list[Paper]]`: an arXiv/SSRN/RSS fetcher. Unblocks step 1.
- **`bars_provider`** — `Callable[[spec], Sequence[BarData]]`: real market data per spec. Unblocks step 8.
- **`llm`** — an `LLMClient` for real enrichment + hypothesis generation (template fallback otherwise).
- **`notifier`** — route notifications to Slack/email/PagerDuty.
- **Strategy mapping** — `_CATEGORY_STRATEGY` maps research category → backtest template; extend as templates grow.
- **Budgets / caps** — `cycle_budget_min`, `max_new_hypotheses`, `retries`.

## Skipped / not built (per project hard rule)

- **Literature discovery source (step 1)** — SKIPPED, impossible now.
  - *Reason*: the platform ships no paper-fetching client (no arXiv/SSRN/RSS integration exists in `literature/`). Fabricating "discovered" papers would poison the research record.
  - *Unblock*: implement a fetcher returning `list[Paper]` and inject it as `paper_source`. The step is fully wired to consume it.

- **Live market-data execution (step 8)** — SKIPPED by default, deliberately.
  - *Reason*: no default market-data provider is bound, and backtesting on synthetic bars would not be reproducible research. The step refuses synthetic data rather than fake results.
  - *Unblock*: inject `bars_provider` backed by the `market_data` service (or a vendor feed). Verified end-to-end with synthetic bars in the supervisor self-check.

- **Step 11 full-resync store binding** — partial.
  - *Reason*: `knowledge.ingest.ingest_all` opens the default on-disk store paths, not arbitrary injected store instances, so in-memory test stores aren't resynced by it. In a normal (file-backed) deployment this is correct; live KG hooks keep the graph current regardless during steps 5/10.
  - *Unblock*: parameterise `ingest_all` with explicit store paths if you need it to target non-default stores.

## Self-checks

- `python -m mentisrex.lab.journal` — audit trail read/filter/summary.
- `python -m mentisrex.lab.supervisor` — **full 13-step cycle** end-to-end with an injected paper source + synthetic bars; asserts 0 failures, hypotheses inserted, experiments executed, audit trail written.
- `python -m mentisrex.lab.monitor` — snapshot contains every required metric key.
