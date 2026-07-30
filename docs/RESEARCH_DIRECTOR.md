# Autonomous Research Director — Phase 16

The Research Director decides **what research happens next**. It does not run
experiments, backtest, or fit models. It behaves like a Director of Quantitative
Research: it ranks the hypothesis backlog on objective evidence, schedules it
into time-boxed queues, estimates the resources each idea needs, and issues an
explicit, explained decision for every hypothesis.

Objective: **maximise long-run research output**, not any single backtest return.

---

## Architecture

```
 HypothesisStore ─┐
 ResearchStore  ──┼──► ResearchDirector ──► /director/* API ──► dashboard (HTML)
 KnowledgeGraph ──┘        (scoring + decisions + roadmap + learning)
```

The Director is **stateless**. It owns no database. Every call recomputes from
the three persisted sources, so a decision is always current and never stale:

| Source | Supplies |
|--------|----------|
| `HypothesisStore` (`hypothesis.duckdb`) | the backlog: full `HypothesisRecord`s, categories, confidence, required data/features, near-duplicates |
| `ResearchStore` (`research.duckdb`) | outcome history: experiment verdicts, trial counts, timestamps → success rates + velocity |
| `KnowledgeGraph` (`knowledge_graph.duckdb`) | availability (which datasets/features exist), gap discovery, failure/feature-family patterns |

Files: `src/aurelius/director/{scoring,director,api}.py`, dashboard at
`src/aurelius/static/director_dashboard.html`.

---

## Step 1 — Scoring methodology (`scoring.py`)

Every hypothesis gets ten factors, each normalised to `0..1` (1 = most favourable
for research). Overall priority is a weighted sum. **Weights are calibration
knobs**, not universal constants — tune per desk in `scoring.WEIGHTS`.

| Factor | Weight | Derived from |
|--------|-------:|--------------|
| economic_rationale | 0.12 | confidence + richness of the economic-intuition text |
| novelty | 0.14 | `1/(1+#near-duplicates)` blended with category saturation |
| data_availability | 0.10 | fraction of `required_datasets` present in the KG |
| feature_availability | 0.10 | fraction of `required_features` present in the KG |
| compute_cost | 0.06 | bar frequency × universe breadth × ML flag (inverted: cheap = high) |
| implementation_complexity | 0.06 | dependencies + features + validation reqs (inverted: simple = high) |
| statistical_feasibility | 0.10 | independent-sample proxy from holding period |
| estimated_research_value | 0.14 | **category track record** + novelty + rationale |
| diversification | 0.06 | `1 − category share of backlog` (under-researched = high) |
| business_impact | 0.12 | conviction × asset-class breadth |

Empty requirement lists score `0.5` (neutral/unknown), not `0` — absence of a
stated dataset is uncertainty, not a hard block. Missing-but-named inputs score `0`.

`estimated_research_value` and `diversification` are the two factors the
continuous-learning loop feeds (see Step 6).

## Step 2 — Gap analysis (`director.gap_analysis`)

- **Over-researched**: categories holding >30% of the live backlog.
- **Under-researched**: canonical category families (`_KNOWN_CATEGORIES`) with ≤1 hypothesis — unexplored opportunity. Extend the list freely.
- **Frequently failing**: categories with ≥3 experiments and ≤5% accept rate.
- **Missing datasets / disconnected clusters / successful feature families / repeated failures**: delegated to the Knowledge Graph's discovery queries (reused, not re-implemented).

## Step 3 — Roadmap (`director.roadmap`)

Actionable hypotheses (decision `research_now` or `delay`) are ranked by priority,
then greedily bin-packed into four horizons by an **experiment-minute budget**:

| Horizon | Budget |
|---------|-------:|
| daily | 8 h |
| weekly | 40 h |
| monthly | 160 h |
| quarterly | unbounded (full ranked roadmap) |

Queues nest naturally: daily ⊂ weekly ⊂ monthly ⊂ quarterly. Each queue reports
its total load in minutes. Budgets live in `director._QUEUE_BUDGET_MIN`.

## Step 4 — Resource estimation (`director.estimate_resources`)

Heuristic per hypothesis — runtime, memory, CPU cores, GPU count, storage, and
concrete dependency list. Runtime scales with bar frequency, universe breadth,
and feature count; ML-flagged ideas (feature/statement keyword match) get a 4×
runtime multiplier and 1 GPU. This is a **calibration surface**: replace the
constants with measured per-experiment telemetry once available.

## Step 5 — Decision engine (`director._decide`)

Rules evaluated in order; first match wins. Every decision carries a text
explanation naming the driving/limiting factors.

| Decision | Trigger |
|----------|---------|
| `archive` | status already Rejected or Promoted |
| `merge` | has near-duplicates **and** novelty < 0.35 → fold into `similar_to[0]` |
| `reject` | category has ≥3 trials at ≤5% accept (repeatedly failing area) |
| `delay` | required datasets or features not yet in the platform (blocked) |
| `research_now` | priority ≥ 0.65 |
| `delay` | priority in [0.45, 0.65) — queue behind higher work |
| `escalate` | researcher confidence ≥ 0.80 but computed priority < 0.45 (conflict) |
| `reject` | priority < 0.45 and no conflict — low expected value |

Thresholds: `director._RESEARCH_NOW_MIN`, `_DELAY_MIN`, `_MERGE_NOVELTY_MAX`,
`_DEAD_CATEGORY_*`, `_ESCALATE_CONF`.

## Step 6 — Continuous learning (`director.learning_stats`)

Derived from recorded experiment outcomes, no separate model:

- overall + per-category accept rate → feeds `estimated_research_value` next pass
- average trials per experiment → data-mining pressure signal
- research velocity (experiments per ISO week)
- verdict distribution

The loop is closed: better categories accrue higher `category_success`, which
raises their research-value factor, which lifts future ranking. **Paper-trading
false-positive rate is not yet wired** — add it when the paper-trading journal
links results back to hypothesis IDs.

## Step 7 — Dashboard

`GET /director/dashboard/view` — self-contained HTML (no build step, no libs).
Shows KPI cards (backlog, research-now count, escalations, daily load, velocity,
accept rate), decision breakdown, ranked top priorities with explanations, the
four research queues, and gap analysis.

---

## API

| Endpoint | Returns |
|----------|---------|
| `GET /director/priorities?include_terminal=&limit=` | ranked backlog + decisions |
| `GET /director/gaps` | gap analysis |
| `GET /director/roadmap` | daily/weekly/monthly/quarterly queues |
| `GET /director/learning` | continuous-learning stats |
| `GET /director/dashboard` | aggregate JSON for the dashboard |
| `GET /director/dashboard/view` | the HTML dashboard |

## Data flow

1. `_load_context()` builds a `ResearchContext` (known datasets/features from KG,
   category counts from the backlog, per-category accept rates from ResearchStore).
2. `prioritize()` scores + decides every open hypothesis, sorts by priority.
3. `roadmap()` bin-packs the actionable subset into budgeted queues.
4. `dashboard()` composes the above with KG growth + QC health.

## Extension points

- **Factor weights / new factors** — edit `scoring.WEIGHTS` and add a term in `score_hypothesis`.
- **Decision rules / thresholds** — the `_*_MIN` constants and `_decide` ordering.
- **Resource model** — swap the heuristic in `estimate_resources` for measured telemetry.
- **Category taxonomy** — extend `director._KNOWN_CATEGORIES`.
- **Queue budgets** — `director._QUEUE_BUDGET_MIN`.
- **Paper-trading feedback** — join journal outcomes into `_category_outcomes` to compute a real false-positive rate.

## Self-checks

`python -m aurelius.director.scoring` and `python -m aurelius.director.director`
run assertion-based smoke tests (duplicate scores lower novelty, missing dataset
→ delay, near-duplicate → merge, ranking monotonic).
