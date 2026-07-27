# Phase 6 — Research Experiment Framework

Goal: let a researcher test hundreds of hypotheses systematically, and make it
**easy to reject bad ideas**. A failed experiment that prevents a capital
allocation is a success.

## The research workflow

```
Hypothesis            "Momentum in liquid names persists over ~3 months."
   │                   record it (researcher, date, rationale) → ResearchStore
   ▼
Feature Selection     rank registered Phase-5 features by IN-SAMPLE information
   │                   coefficient vs forward returns. Pick the signal. (no leak)
   ▼
Strategy Definition   instantiate a template (Momentum/MeanReversion/Pairs/Factor)
   │                   with parameters. Templates reuse the Phase-5 feature math.
   ▼
Backtest              one continuous run on the Phase-4 engine over the full span.
   │
   ▼
Validation            slice the equity curve: IN-SAMPLE vs OUT-OF-SAMPLE.
   │                   train/test split, walk-forward folds, rolling stability,
   │                   parameter-sensitivity grid.
   ▼
Verdict               ACCEPT / REJECT / INCONCLUSIVE from explicit guards:
   │                   OOS Sharpe floor, IS->OOS decay, multiple-testing
   │                   correction, parameter fragility, trade-count minimum.
   ▼
ResearchStore         experiment recorded with verdict + reasons. Rejected ideas
                      are queryable so nobody reruns a dead end.  → velocity.
   │  (only if ACCEPT)
   ▼
Paper Trading → Production Candidate   (Phase 7 — out of scope here)
```

## Why one continuous run, sliced

Our templates are rule-based (parameters are fixed, not fitted from data), so a
single backtest over `[train | test]` warms indicators through the train period
and lets us measure OOS performance on the test slice by re-running the public
`PerformanceCalculator` over the test portion of the equity curve. This is
correct, cheap, and needs no engine change. (For strategies that *fit*
parameters, each walk-forward fold would re-fit — noted as future work.)

## Overfitting / data-mining / over-tuning protection

These are the reason the framework exists, not add-ons:

| Threat | Guard |
|---|---|
| Overfitting | OOS is the headline number; **IS->OOS decay** guard rejects strategies whose edge collapses out of sample. |
| Data-mining bias | **Every parameter combination evaluated is counted as a trial.** The Sharpe significance p-value is Bonferroni-adjusted by the total trial count (this experiment's grid + all prior trials on the hypothesis). |
| Excessive tuning | **Parameter-sensitivity** grid: if OOS performance has high coefficient-of-variation across the grid (edge exists only at one knife-edge setting), the idea is rejected as fragile. |
| Too few observations | Trade-count minimum; too-short OOS returns INCONCLUSIVE, not a false ACCEPT. |

All thresholds live in `ValidationCriteria` (calibration knobs, not hard-coded).

## Components

| File | Role |
|---|---|
| `research/models.py` | `Hypothesis`, `Verdict`, `ValidationCriteria`, `ValidationReport`, `ExperimentRecord`, `SensitivityResult`, dataset fingerprint, Sharpe significance |
| `research/store.py` | `ResearchStore` (DuckDB): hypotheses, experiments, results, rejected ideas; trial counting; duplicate detection |
| `research/templates.py` | `MomentumStrategy`, `MeanReversionStrategy`, `PairsStrategy`, `FactorStrategy` |
| `research/validation.py` | `train_test`, `walk_forward`, `rolling_validation`, `parameter_sensitivity`, `select_features`, `evaluate` |
| `research/runner.py` | `ResearchRunner.investigate()` — the idea-to-verdict orchestrator; `demo()` |

## Experiment record (tracking + reproducibility)

Each experiment stores: id, hypothesis id, researcher, date, **dataset
fingerprint** (hash of symbols + date span + row count), features used,
parameters, strategy name+version, IS/OOS metrics, trial count, adjusted
p-value, verdict, reasons. Same fingerprint + strategy + params + version =
reproducible identity; the store detects and short-circuits duplicate runs.
