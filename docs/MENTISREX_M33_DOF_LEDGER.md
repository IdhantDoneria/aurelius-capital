# M33 — Research Degrees-of-Freedom Ledger

**Certification report.** P1 milestone from `docs/RESEARCH_PROGRAM_AUDIT_2026-08-14.md`
(§XIII). Additive; frozen `ew-momentum-exp v1.0.0`
(`b69961b65bab226a500d71f45709945b`) untouched.

## Problem
`ResearchStore.trial_count` counts experiments *per hypothesis id*. One mechanism
tested across N separate hypothesis ids yields `prior_trials≈0` on each →
deflated-Sharpe / Bonferroni haircut under-corrects → data-snooping false
positives leak through. No cross-hypothesis (family-level) DoF accounting existed.

## Implementation
`research/dof_ledger.py` — self-contained DuckDB store (same pattern as the other
research stores):
- `Trial` (family, hypothesis_id, variant, dataset_id, period, params, selection_note).
- `record(trial)` — fingerprint dedup so honest re-runs don't inflate; returns
  whether newly counted.
- `effective_trials(family)` — distinct trials in a family (the `n_trials` value).
- `breakdown(family)` — §XIII search-axis counts: distinct hypotheses, variants,
  datasets, periods, parameter sets, trials.
- `n_trials_for(family, grid_size)` — family history + current grid, the DoF-aware
  replacement for the runner's per-hypothesis `prior_trials + grid_size`.

## Tests — `tests/research/test_dof_ledger.py` (8, all pass)
Record/count; identical-trial dedup; params differentiate trials; **cross-hypothesis
snooping counted (50 ids → 50 DoF)**; breakdown axis counts; family listing;
`n_trials_for` feeds `deflated_sharpe_ratio` and discounts DSR as trials rise;
unknown family → 0.

## Regression
`pytest tests/research tests/validation` → **2191 passed, 2 skipped, 0 failures.**

## Known limitations / Skipped
- **Runner/service adoption deferred.** `runner.py:81` and `validation/service.py:197`
  still compute `n_trials = prior_trials + grid_size` from the per-hypothesis
  `ResearchStore.trial_count`. Rewiring them to `DoFLedger.n_trials_for(family, ...)`
  changes `n_trials` on existing experiment outputs and would churn many
  experiment-output assertions — a bounded but real regression pass that belongs in
  its own milestone. **Unblock:** M34a — add a `family` field to the research config,
  swap the two call sites, re-baseline affected experiment fixtures. Recorded here
  per CLAUDE.md; the mechanism + feed (`n_trials_for`) are complete and tested now.

## Next milestone
M34: factor-research campaign layer (multi-date IC time-series / IC-IR / decay over
the M32 cross-sectional primitives) — first P2 breadth work on the corrected stats
foundation (M31–M33).
