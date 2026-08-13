# Research Intelligence & Continuous Learning — Phase 17

An advisory analytics layer over the firm's accumulated research. It turns the
persisted history (experiments, hypotheses, knowledge graph) into meta-analysis,
evidence-cited recommendations, long-term trends, periodic reports, and
self-evaluation metrics.

**Advisory only.** It executes no trades, mutates no strategies, and changes no
research results. Every output is a recommendation a human acts on.

---

## Architecture

```
 HypothesisStore ─┐
 ResearchStore  ──┼─► ResearchIntelligence ─► /intel/* API
 KnowledgeGraph ──┤        ├─ meta_analysis      (Step 2)
 ResearchDirector ┘        ├─ recommendations    (Step 3, evidence-cited)
   (reused for            ├─ trends             (Step 4, time series)
    learning + gaps)      ├─ self_evaluation    (Step 6)
                          └─ report(period)     (Step 5, JSON + markdown)
```

**Stateless**: no store of its own. Every call recomputes from source, so
intelligence is always current. Where `ResearchDirector` or `KnowledgeGraph`
already compute a signal (learning stats, gap analysis, KG discovery, QC), the
engine reuses it rather than duplicating SQL. Net-new analytics — experiment-
derived meta-analysis, time-series trends, self-evaluation — live in
`intelligence/engine.py`.

File: `src/mentisrex/intelligence/{engine,api}.py`.

---

## Step 1 — Learning engine

`_experiments(since=…)` pulls the experiment frame (verdict, OOS Sharpe, features,
dataset, reasons, adjusted p-value, timestamp). `_id_to_category()` joins each
experiment to its hypothesis category. Everything downstream folds over these two.

## Step 2 — Meta-analysis (`meta_analysis`)

| Question | Method | Source |
|----------|--------|--------|
| Which categories consistently fail? | `category_performance` | experiment verdicts per category; `verdict=consistently_fails` at ≥3 experiments and ≤10% accept |
| Which feature families give the strongest evidence? | `feature_families` | features split to family prefix (`mom_12m`→`mom`), ranked by avg OOS Sharpe |
| Which statistical tests kill the most false positives? | `statistical_test_effectiveness` | reason strings on **rejected** experiments, normalised to the guard name, counted |
| Which datasets produce the highest research value? | `dataset_value` | accept rate + avg Sharpe grouped by `dataset_version` |
| Which market regimes invalidate hypotheses? | `regime_sensitivity` | **proxy** — accept rate by calendar year until regime labels are attached to experiments |

`_MIN_EVIDENCE = 3`: a category needs at least three experiments before a
"consistently fails" claim is made rather than reading noise.

## Step 3 — Recommendations (`recommendations`)

Rule-driven, and **every recommendation carries an `evidence` dict**. Types:

| Type | Trigger |
|------|---------|
| `retire` / `abandon` | category flagged `consistently_fails` |
| `expand` | productive category (≥40% accept) or under-researched category |
| `build_feature` | feature family with avg OOS Sharpe > 0.5 |
| `acquire_dataset` | dataset cited in papers but never tested (KG gap) |
| `repeat_experiment` | inconclusive verdict with OOS Sharpe ≥ 0.5 (underpowered) |
| `review_paper` | parent paper of a top-confidence active hypothesis |

Shape: `{type, action, target, rationale, evidence}`.

## Step 4 — Trends (`trends`)

Weekly ISO-bucketed time series plus structural signals:

- `research_productivity` — experiments per week
- `experiment_success_rate` — accept rate per week
- `knowledge_growth` — KG weekly node additions (reused from `KnowledgeGraph.stats`)
- `validation_quality` — mean adjusted p-value per week
- `research_diversity` — distinct active categories per week
- `technical_debt` — orphan nodes, broken edges, duplicate labels (from KG QC)
- `infrastructure_utilization` — backlog compute load (from Director resource estimates)

## Step 5 — Periodic reports (`report(period)`)

`period ∈ {daily, weekly, monthly, quarterly, annual}` → window of
`{1, 7, 30, 90, 365}` days. Returns JSON (activity, verdicts, active categories,
self-evaluation, top recommendations) **and** a rendered `markdown` field.
`GET /intel/report/{period}/markdown` returns the markdown as `text/plain`.

## Step 6 — Self-evaluation (`self_evaluation`)

| Metric | Definition |
|--------|-----------|
| research_efficiency | accepts / total experiments |
| experiment_throughput_per_week | from Director learning stats |
| avg_validation_quality | mean adjusted p-value across experiments |
| knowledge_reuse_rate | features used in >1 experiment / distinct features |
| duplicate_research_rate | hypotheses with `similar_to` set / all hypotheses |
| hypothesis_quality | promotion rate + avg confidence of promoted vs rejected |
| decision_signal_lift | accept-rate(confidence≥0.7) − accept-rate(<0.7); >0 means researcher confidence predicts outcomes |
| data_mining_pressure_avg_trials | avg trials per experiment |

---

## API

| Endpoint | Returns |
|----------|---------|
| `GET /intel/meta` | full meta-analysis |
| `GET /intel/recommendations` | evidence-cited recommendations |
| `GET /intel/trends` | time-series + structural trends |
| `GET /intel/self-evaluation` | self-evaluation metrics |
| `GET /intel/report/{period}` | periodic report (JSON incl. markdown) |
| `GET /intel/report/{period}/markdown` | report markdown as text |
| `POST /intel/paper-outcome` | record a paper-trading outcome for a hypothesis (validation→live loop) |
| `GET /intel/paper-outcomes` | all recorded paper-trading outcomes |
| `GET /intel/dashboard/view` | HTML intelligence dashboard |

## Paper-trading feedback loop (built)

`PaperOutcomeStore` (`src/mentisrex/paper/outcomes.py`, `paper_outcomes.duckdb`) is
the durable home for what happened *after* validation said "accept" and a
strategy went to paper trading. Keyed by `hypothesis_id`, each record carries the
live `regime`, paper Sharpe/return/drawdown, backtest Sharpe (for decay), and an
`outcome` ∈ {running, confirmed, degraded, failed}.

The live/paper system (or an operator) writes via `POST /intel/paper-outcome`;
the engine consumes it in:
- `paper_trading_reliability()` — **real** validation false-positive rate (accepts that failed live) + Sharpe decay.
- `self_evaluation.validation_false_positive_rate`.
- `regime_sensitivity.by_paper_regime` — **real** regime-conditioned failure rate.
- `recommendations` — `retire_strategy` on failed outcomes, `scale_strategy` on confirmed.

## Storage model

None owned. Reads:
- `research.duckdb` — experiments (primary meta-analysis source)
- `hypothesis.duckdb` — categories, confidence, status, near-duplicates
- `knowledge_graph.duckdb` — gaps, discovery, QC, growth (via Director/KG)

## Data flow

1. `_experiments()` + `_id_to_category()` build the joined frame.
2. Meta-analysis folds the frame into per-category/feature/dataset/guard aggregates.
3. `recommendations()` composes meta-analysis + KG gaps + backlog into cited advice.
4. `trends()` buckets the frame by week and layers KG growth/QC/Director load.
5. `report()` windows the frame by period and renders JSON + markdown.

## Extension points

- **Regime analysis** — attach regime labels to experiments, replace the calendar-year proxy in `regime_sensitivity`.
- **New meta-question** — add a fold over `_experiments()` and surface it in `meta_analysis`.
- **New recommendation rule** — add a `rec(...)` block; keep the `evidence` dict mandatory.
- **Thresholds** — `_MIN_EVIDENCE`, the 0.4/0.1 accept-rate bands, feature-family Sharpe cutoff.
- **Report periods** — `_PERIOD_DAYS`.
- **Feature family grouping** — currently the token before the first `_`; swap for a registry taxonomy if features aren't prefix-encoded.

## Self-check

`python -m mentisrex.intelligence.engine` seeds a productive and a failing category
in-memory and asserts: failing category detected, guard-effectiveness ranks the
Sharpe floor, a `retire` recommendation with evidence is emitted, and
`decision_signal_lift > 0`.

## Known limitations / skipped (per project hard rule)

- **Backtest-experiment regime labels** — SKIPPED, impossible now.
  - *Item*: attaching a market-regime label to each historical backtest experiment (`regime_sensitivity.by_backtest_year` is a coarse calendar-year proxy).
  - *Reason*: experiment records persist no tested-window dates — only a `dataset_version` hash and the run's `created_at`. Without the tested date range, the regime of the data cannot be recovered, and fabricating one would be wrong.
  - *Unblock*: add `data_start`/`data_end` columns to `ResearchStore.experiments`, then classify that window against a market-data regime timeline. Live paper-trading regime is already real (`by_paper_regime`), because the live system knows the prevailing regime at record time.

- **Production-monitoring feed** — partial.
  - *Item*: ingesting live production (not just paper) monitoring outcomes.
  - *Reason*: no production monitoring store exists yet keyed by hypothesis/strategy; only paper outcomes are captured.
  - *Unblock*: production monitor writes to a store with the same shape as `PaperOutcomeStore`, then add a consumer mirroring `paper_trading_reliability`.
