# M31 — Statistical-Validity Correctness (HAC + Purged CV)

**Certification report.** P0 milestone: closes the two research-integrity
correctness gaps found in the 2026-08-14 program audit
(`docs/RESEARCH_PROGRAM_AUDIT_2026-08-14.md`). Additive only; no interface break;
frozen `ew-momentum-exp v1.0.0` (`b69961b65bab226a500d71f45709945b`) untouched.

## Objective
1. Autocorrelation-robust significance — Newey-West/HAC standard errors. The IID
   SE (`std/√n`) overstated t-stats/p-values on serially correlated (momentum /
   overlapping-horizon) returns, biasing the promotion gate toward false positives.
2. Leak-free cross-validation — purged + embargoed K-fold and walk-forward for
   panel research where H-day-forward labels overlap across the train/test split.

## Implementation
- `research/validation/hac.py` — `auto_lag` (Newey-West 1994), `hac_long_run_variance`
  (Bartlett kernel), `hac_standard_error`, `hac_significance`.
- `research/validation/cross_validation.py` — `purged_kfold`, `walk_forward_purged`.
- `significance()` now appends `hac_se`, `hac_t_stat`, `hac_p_value`, `hac_lag`;
  all pre-existing IID fields unchanged.
- Exported from `research/validation/__init__.py`.

## Tests — `tests/validation/test_hac_and_purged_cv.py` (8, all pass)
HAC ≥ IID SE under positive AR(1); HAC == IID at lag 0; lag bounds/auto;
significance carries HAC + keeps IID intact; purged folds have zero train/test
index inside `horizon+embargo`; full test coverage; walk-forward trains only on
past with gap; invalid params raise.

## Regression
`pytest tests/validation tests/research` → **2171 passed, 2 skipped, 0 failures.**
Warnings are pre-existing `utcnow` deprecations, unrelated to this change.

## Known limitations / Skipped
Deferred to sequenced later milestones (not silently dropped, per CLAUDE.md):
- **Cross-sectional neutralization** (sector/beta/vol-neutral, residualization, §XI)
  — M32. Reason: independent scope; not a prerequisite for HAC/purge correctness.
- **Signal redundancy detector** (§XI/XII) — M32.
- **Research degrees-of-freedom ledger** feeding deflated-Sharpe `n_trials` (§XIII)
  — M33.
None are "impossible"; all are dependency-ordered after this P0 correctness root.

## Next milestone
M32 (P1): cross-sectional neutralization + signal redundancy detector.
