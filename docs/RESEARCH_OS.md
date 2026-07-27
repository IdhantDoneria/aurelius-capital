# Aurelius Capital — Research Operating System (ROS)

**Owner:** Head of Quantitative Research Operations.
**Status:** Operating manual. Governs how every researcher works. Stable for years; edit only by decision-log entry (§6).
**Scope:** the *process*. The methodology it enforces lives in [`RESEARCH_PROGRAM.md`](RESEARCH_PROGRAM.md), the alpha map in [`ALPHA_TAXONOMY.md`](ALPHA_TAXONOMY.md), the idea queue in [`HYPOTHESIS_BACKLOG.md`](HYPOTHESIS_BACKLOG.md), the platform trust boundary in [`ACCEPTANCE_TEST.md`](ACCEPTANCE_TEST.md). This document does not restate them — it wires them into a repeatable operation.

**Design rule of the ROS itself:** two systems of record already exist — the **git repo** (human-readable artifacts) and **`./data/research.duckdb`** via `aurelius.research.store.ResearchStore` (queryable hypotheses + experiments + verdicts). The ROS binds them by ID. It does **not** introduce a third store. Where a stage has no DB table (papers, reviews, decisions), the git file *is* the record.

---

## Part 1 — Repository structure

### 1.1 Two systems of record, bound by ID

| System | Holds | Source of truth for |
|---|---|---|
| **git repo** (`research/…`) | markdown artifacts: paper summaries, specs, reports, reviews, decisions, meeting notes | narrative, rationale, sign-off |
| **`research.duckdb`** (`ResearchStore`) | `hypotheses` + `experiments` rows, verdicts, trial counts | metrics, verdicts, dedup, dashboard queries |

Binding key: **`hypothesis_id`** and **`experiment_id`** (the same UUIDs `ResearchStore.record_hypothesis` / `record_experiment` mint). Every markdown file names its ID in front-matter; every DB row's narrative lives at the path derived from its ID. One ID, one folder, one row. No orphans.

### 1.2 Folder tree (git)

```
research/
  papers/
    <paper-id>/                # paper-id = firstauthor-year-keyword, e.g. jegadeesh-1993-momentum
      summary.md               # Template T2
      source.txt               # DOI / URL / local PDF path — never commit the PDF
  hypotheses/
    <H###>.md                  # Template T1. Mirrors one hypotheses row + backlog entry
  experiments/
    <exp-id>/
      spec.md                  # Template T3 (pre-registration — written BEFORE the run)
      report.md                # Template T4 (backtest result)
      validation.md            # Template T5 (statistical verdict)
      run.json                 # machine record: dataset_version, params, ValidationReport dump
  risk-reviews/
    <exp-id>.md                # Template T6
  paper-trading/
    <strategy>/
      promotion.md             # Template T7 (memo that opened the window)
      journal.md               # daily live-vs-modeled log (append-only)
  production/
    <strategy>/
      promotion.md             # Template T8
      config.lock              # immutable dataset+config hash pinned at go-live
      runbook.md               # monitoring links, kill switch, on-call
  retired/
    <strategy>/
      retirement.md            # Template T9
  decisions/
    decision-log.md            # append-only; every irreversible call (§6). Never edited, only appended
  meetings/
    <YYYY-MM-DD>-<topic>.md    # Template inline in §6
  datasets/
    <fingerprint>.md           # manifest per dataset_fingerprint(): symbols, span, n_rows, source, as-of
  templates/                   # the 9 templates below, as copy-paste stubs
```

Rules:
- **Dirs are lazy.** They do not pre-exist; `mkdir -p` on first artifact. No empty `.gitkeep` scaffolding.
- **Features and datasets are not duplicated into git.** Features are *code* — `aurelius.features` library + the feature registry; a hypothesis references them by name in `features_used`. Datasets are *fingerprints* — `dataset_fingerprint(symbols, first, last, n_rows)` from `research.models`; `research/datasets/<fingerprint>.md` is a one-page manifest, not the data. The bytes live in the data store.
- **PDFs are never committed** (licensing + repo bloat). `source.txt` carries DOI/URL/local path.

### 1.3 Database structure (already built — do not rebuild)

`ResearchStore` owns two tables. The ROS extends their *use*, not their schema:

- **`hypotheses`** (`id, statement, rationale, researcher, created_at, status`). `status` is a free VARCHAR with **no CHECK constraint** — so the ROS carries the full lifecycle stage in it at **zero migration cost**. Allowed vocabulary (§3):
  `idea → hypothesis → implemented → backtested → validated → peer_reviewed → paper_trading → production → retired`, plus terminal `rejected`.
- **`experiments`** (`id, hypothesis_id, researcher, created_at, dataset_version, strategy_name, strategy_version, features_used, params, verdict, reasons, is_sharpe, oos_sharpe, oos_return, oos_max_drawdown, oos_trades, n_trials, adjusted_pvalue`). One row per run. `find_duplicate()` already prevents rerunning an identical `(dataset_version, strategy_name, strategy_version, params)` — that is the reproducibility + anti-remining spine.

What is deliberately **not** in the DB and stays as files: papers, specs, reviews, decisions, meetings, runbooks. They are narrative, not queried numerically. Adding tables for them would be a store nobody queries — skipped.

*Gap acknowledged:* paper-trading and production live results are not yet a table (Phase-2 platform is feature-frozen per `ACCEPTANCE_TEST.md`). Until they are, `paper-trading/*/journal.md` is the record and the dashboard reads it as text. When a `live_results` table is added, it slots beside `experiments` with the same `hypothesis_id` key — no restructuring.

---

## Part 2 — Standard templates

Nine templates. Every field maps to a real `research.models` / `ResearchStore` field where one exists (named in `code`), so filling a template *is* populating the record. Copy from `research/templates/`.

### T1 — New hypothesis proposal → `research/hypotheses/<H###>.md`
```markdown
---
id:            H###                      # also the backlog id
hypothesis_id:                           # UUID from ResearchStore.record_hypothesis (fill on registration)
researcher:
created_at:
status: idea
category:                                # one of ALPHA_TAXONOMY.md §Part-1 15 categories
---
## Statement            # -> hypotheses.statement. Falsifiable, one sentence.
## Economic rationale    # -> hypotheses.rationale. WHY it should exist; works-when / fails-when.
## Source                # paper-id (research/papers/…) or "original"
## Required datasets     # dataset names + as-of need; note survivorship/point-in-time dependency
## Required features     # -> intended experiments.features_used; mark REUSE vs NEW
## Benchmark to beat     # the null this must exceed (RESEARCH_PROGRAM §benchmarks)
## Scorecard             # 10 axes from ALPHA_TAXONOMY.md §Part-3; priority score
## Kill condition        # the single result that ends this idea (pre-committed)
```

### T2 — Research paper summary → `research/papers/<paper-id>/summary.md`
```markdown
---
paper-id:  firstauthor-year-keyword
citation:
source:                                  # DOI/URL (also in source.txt)
category:                                # ALPHA_TAXONOMY category
reviewed_by:
date:
---
## Claim                 # the tradable assertion, one line
## Mechanism             # economic reason it works
## Data & universe       # what they used; is it reproducible on our data?
## Reported edge         # metric, horizon, decay
## Red flags             # in-sample only? survivorship? tiny-cap? crowded now?
## Extractable hypotheses  # H### ids this spawns (link to T1 files)
```

### T3 — Experiment specification (PRE-REGISTERED) → `experiments/<exp-id>/spec.md`
```markdown
---
experiment_id:                           # UUID (mint at spec time, before the run)
hypothesis_id:
researcher:
created_at:
status: implemented
---
## Question              # exact hypothesis under test
## Strategy & template   # class from aurelius.research.templates (or new); strategy_version
## Parameters            # -> experiments.params. Grid to be swept (declare BEFORE running)
## Features              # -> experiments.features_used
## Dataset               # -> experiments.dataset_version = dataset_fingerprint(...); the manifest path
## Split plan            # IS/OOS boundary, walk-forward folds, purge+embargo (RESEARCH_PROGRAM §6)
## Success criteria      # the ValidationCriteria to apply (defaults or per-desk override)
## Pre-committed n_trials # expected grid size — feeds the Bonferroni haircut
```
*Pre-registration rule:* spec is committed to git **before** `run.json` exists. A verdict whose spec post-dates its report is void (defeats p-hacking).

### T4 — Backtest report → `experiments/<exp-id>/report.md`
```markdown
---
experiment_id:
status: backtested
---
## Run identity          # dataset_version, strategy_name, strategy_version, params (== run.json)
## Headline metrics       # is_sharpe, oos_sharpe, oos_return, oos_max_drawdown, oos_trades
## Equity & drawdown      # curve refs (per-timestamp; note ACCEPTANCE_TEST fix #1 if multi-symbol)
## Costs                  # commission + spread + slippage applied; % of gross
## Sensitivity            # metric across the param grid (SensitivityResult): mean, std, cv
## Sanity                 # look-ahead check, leakage check, reproducibility (rerun == run)
```

### T5 — Statistical validation report → `experiments/<exp-id>/validation.md`
```markdown
---
experiment_id:
status: validated
verdict:                                 # ACCEPT | REJECT | INCONCLUSIVE (research.models.Verdict)
---
## Verdict & reasons      # -> ValidationReport.verdict + reasons
## OOS evidence           # oos_sharpe vs min_oos_sharpe; IS->OOS decay vs max_is_oos_decay
## Significance           # adjusted_pvalue (Bonferroni over n_trials) vs significance_alpha
## Fragility              # param_cv vs max_param_cv
## Sufficiency            # oos_observations vs min_oos_observations (< -> INCONCLUSIVE, not a verdict)
## Deflated Sharpe / PBO  # if wired (roadmap #6); else note as manual check
## Checks table           # ValidationReport.checks dict, all must pass for ACCEPT
```

### T6 — Risk review → `risk-reviews/<exp-id>.md`
```markdown
---
experiment_id:  ;  reviewer:  ;  date:
---
## Capacity               # ADV, market-impact estimate, $ before edge decays (scorecard axis)
## Turnover & cost sens.   # break-even cost multiple; survives 2x modeled cost?
## Factor exposure        # is this orthogonal alpha or repackaged beta? (roadmap #11)
## Tail / stress           # drawdown in 2008/2020 analogues; VaR note
## Correlation             # ρ to existing live book — additive or crowding?
## Borrow / financing      # short-leg feasibility & cost (if applicable)
## Verdict                 # RISK-OK / CONDITIONS / BLOCK + conditions
```

### T7 — Promotion to paper trading → `paper-trading/<strategy>/promotion.md`
```markdown
---
strategy:  ;  experiment_id:  ;  approver:  ;  date:
---
## Why now               # validation ACCEPT + risk-OK summary (link T5, T6)
## Paper config          # sizing, universe, rebalance, cost model assumed
## Window & bar          # duration + min events to observe (RESEARCH_PROGRAM §7)
## Live-vs-modeled plan   # what journal.md tracks daily; the reconciliation metric
## Kill switch           # live conditions that abort the window early
```

### T8 — Promotion to production → `production/<strategy>/promotion.md`
```markdown
---
strategy:  ;  approver:  ;  committee_date:  ;  config_lock:  <hash>
---
## Paper-trading result   # observed vs modeled; slippage reconciliation outcome
## Production checklist    # every item in RESEARCH_PROGRAM §8, each ticked with evidence
## Capital & limits        # initial allocation, max weight, drawdown kill, correlation cap
## Monitoring              # dashboards, alert rules, on-call, kill switch (-> runbook.md)
## Rollback plan           # how to unwind; who signs
## config.lock             # pinned dataset+config hash (reproducibility, roadmap #5)
```

### T9 — Strategy retirement report → `retired/<strategy>/retirement.md`
```markdown
---
strategy:  ;  retired_by:  ;  date:  ;  final_status: retired
---
## Trigger                # which retirement criterion fired (§3 Retirement)
## Performance epitaph      # live Sharpe vs promoted expectation; decay curve
## Post-mortem              # crowded? regime change? cost drift? overfit that leaked through?
## Capital returned         # unwind summary
## Lesson -> knowledge base  # what future hypotheses must check; link the H### to flag
```

---

## Part 3 — Experiment lifecycle

Nine stages. Each has a **gate** (mandatory checkpoint) and **exit criteria** — you cannot enter the next stage until they pass. Stage is carried in `hypotheses.status`; the artifact that proves the gate is named. A failed gate routes to **REJECT/RETIRE**, recorded in `experiments` (verdict) or `retired/`, and the idea enters the knowledge base so it is never silently retried (`ResearchStore.rejected_ideas`, `find_duplicate`).

```
Idea → Hypothesis → Implementation → Backtest → Validation → Peer Review
     → Paper Trading → Production → Monitoring → Retirement
```

| # | Stage | `status` | Gate (checkpoint) | Exit criteria | Artifact |
|---|---|---|---|---|---|
| 1 | **Idea** | `idea` | Has an economic mechanism, not just a pattern | Passes the "why does this exist / who is on the other side" test | T1 draft |
| 2 | **Hypothesis** | `hypothesis` | Registered + scored | Falsifiable statement, kill condition set, priority score ≥ desk cutoff; `record_hypothesis` run | T1 committed |
| 3 | **Implementation** | `implemented` | Spec pre-registered | Reuses a `templates.py` class or new strategy reviewed for look-ahead/leakage; `n_trials` declared | T3 before any run |
| 4 | **Backtest** | `backtested` | Ran through the real `BacktestEngine` | Accounting-correct, costed, reproducible rerun matches; `record_experiment` written | T4 + `run.json` |
| 5 | **Validation** | `validated` | Passed the guard, not the eye | `Verdict.ACCEPT`: `oos_sharpe ≥ min_oos_sharpe`, decay ≤ `max_is_oos_decay`, `adjusted_pvalue ≤ significance_alpha`, `param_cv ≤ max_param_cv`, `oos_observations ≥ min_oos_observations`. Below sufficiency → INCONCLUSIVE (back to 3, more data). Any fail → REJECT | T5 |
| 6 | **Peer Review** | `peer_reviewed` | A second researcher reproduces from `spec.md` alone | Independent rerun reproduces verdict; reviewer signs; bias check (survivorship/look-ahead/crowding) clean | review note in `validation.md` + T6 risk-OK |
| 7 | **Paper Trading** | `paper_trading` | Live but no capital | Window length + min events met (RESEARCH_PROGRAM §7); live-vs-modeled slippage within tolerance; no kill-switch trip | T7 + `journal.md` |
| 8 | **Production** | `production` | Committee sign-off | Full §8 checklist ticked; `config.lock` pinned; limits + rollback set | T8 + `config.lock` |
| 9 | **Monitoring** | `production` | Continuous | Live Sharpe within decay band; correlation to book under cap; costs as modeled | `runbook.md`, dashboard |
| — | **Retirement** | `retired` | Any retirement trigger | Unwound, post-mortem written, lesson filed to knowledge base | T9 |

**Mandatory checkpoints (cannot be skipped):**
1. **Pre-registration** (gate 3): spec committed before results exist.
2. **Guard verdict** (gate 5): the machine `ValidationReport`, not human judgement, decides ACCEPT/REJECT.
3. **Independent reproduction** (gate 6): a different person, from the spec, same verdict.
4. **Committee sign-off** (gate 8): production needs a second signature + `config.lock`.

**Retirement triggers (any one):** live Sharpe below floor for the review window; drawdown breaches kill limit; correlation to book exceeds cap (crowding); realized cost drifts past the break-even multiple; the economic mechanism is invalidated (regime/structural change). Retirement is normal, not failure — the epitaph feeds the next hypothesis.

---

## Part 4 — Research dashboard

**Design:** the dashboard is **queries over the two systems of record**, not a new service. Everything below is a read against `research.duckdb` (or a `grep`/count over `research/`). A one-file CLI (`scripts/research_dashboard.py`) that prints these panels is the entire build; a Grafana/Metabase panel can point at the same DuckDB file later. No new store, no new schema.

| Panel | Definition | Source |
|---|---|---|
| **Active hypotheses** | count by lifecycle stage | `SELECT status, COUNT(*) FROM hypotheses GROUP BY status` |
| **Completed experiments** | experiments with a verdict | `SELECT COUNT(*) FROM experiments` (+ split by `verdict`) |
| **Success rate** | ACCEPT ÷ (ACCEPT+REJECT) | `SELECT avg(verdict='accept') FROM experiments WHERE verdict<>'inconclusive'` |
| **Rejected ideas** | the graveyard | `ResearchStore.rejected_ideas()` — hypothesis, strategy, params, reasons, oos_sharpe |
| **In paper trading** | strategies in window | `hypotheses WHERE status='paper_trading'` + `paper-trading/*/journal.md` |
| **Live strategies** | production book | `hypotheses WHERE status='production'` + `production/*/` |
| **Research velocity** | experiments recorded per ISO week | `SELECT date_trunc('week',created_at), COUNT(*) FROM experiments GROUP BY 1` |
| **Research backlog** | unstarted ideas | `hypotheses WHERE status IN ('idea','hypothesis')` vs the 500 in `HYPOTHESIS_BACKLOG.md` |
| **Compute utilization** | run cost vs budget | backtest wall-clock/CPU from `run.json` timing, summed per week ÷ available compute (`ponytail:` proxy until a scheduler exists — the honest metric is "runs/week × mean runtime"; wire real cgroup stats only if a compute queue is built) |

Refresh: the CLI is run on demand and pinned in the weekly research meeting. It is read-only — it never writes to the store.

---

## Part 5 — KPIs

Every KPI is **computable from the two systems of record** — no manual tallies. Definition, formula, and target below. The alpha-*outcome* KPIs already live in `RESEARCH_PROGRAM.md §10`; these are the **operational** layer that measures whether the *process* is healthy.

| KPI | Formula (source) | Target |
|---|---|---|
| **Experiments completed / week** | `experiments` rows per ISO week | ≥ desk capacity (set at first quarterly review; track trend, not vanity volume) |
| **Average validation time** | mean(`experiment.created_at` − `hypothesis.created_at`) for validated ideas | trend ↓ ; flag any idea idle > 30d |
| **Hypothesis acceptance rate** | confirmed ÷ (confirmed + rejected) hypotheses | 5–15% (much higher ⇒ under-testing / p-hacking; near-zero ⇒ weak sourcing) |
| **Feature reuse rate** | Σ reused feature-uses ÷ Σ total feature-uses across `experiments.features_used` | ≥ 60% (low reuse ⇒ feature sprawl, leakage risk) |
| **Strategy promotion rate** | production strategies ÷ ACCEPT experiments | small & stable; sudden spike ⇒ gate erosion |
| **Research reproducibility** | audited reruns matching original verdict via `find_duplicate` identity | 100% — any miss is a P0 bug, freeze new promotions |
| **Out-of-sample success rate** | ACCEPT ÷ experiments reaching validation gate 5 | monitor; the honest denominator is *pre-registered* specs, so p-hacking cannot inflate it |
| **Paper→prod survival** | strategies still live after N months ÷ promoted | ≥ 60% at 6 months (else paper-trading gate too weak) |

**Two guardrails these KPIs exist to catch:**
- **Over-mining:** acceptance rate climbing while `n_trials` per hypothesis rises means the Bonferroni haircut is being out-run. `find_duplicate` + `trial_count` bound it structurally; the KPI makes the drift visible.
- **Reproducibility rot:** the moment "research reproducibility" drops below 100%, verdicts are noise. It is the one KPI with a hard stop, not a trend.

---

## Change control

This manual is stable by design. Amend only via an appended `research/decisions/decision-log.md` entry stating: what changed, why, who approved, date. No silent edits — the process that governs research is itself under the process.

**Meeting note stub** (`research/meetings/<date>-<topic>.md`): `Attendees · Decisions (→ decision-log ids) · Stage transitions approved · Actions (owner, due)`.
