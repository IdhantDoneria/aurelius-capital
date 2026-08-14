# M32 — Cross-Sectional Neutralization + Signal Redundancy

**Certification report.** P1 milestone from `docs/RESEARCH_PROGRAM_AUDIT_2026-08-14.md`.
Additive only; frozen `ew-momentum-exp v1.0.0` (`b69961b65bab226a500d71f45709945b`)
untouched. Builds on M31's corrected statistics layer.

## Objective
- **§XI cross-sectional research**: rank / percentile / z-score, and residual
  neutralization of a signal against sector dummies and/or continuous covariates
  (beta, vol) so factor edge is measured net of known exposures. Quantile-spread /
  monotonicity / IC helpers.
- **§XI/§XII redundancy**: detect whether a "new" signal is a disguised version of
  an existing one — via raw rank correlation and via IC-collapse after residualizing
  the new signal on the existing one.

## Implementation
`research/cross_sectional.py` (pure/deterministic, numpy only, NaN pairwise-complete):
- `rankdata`, `percentile_rank`, `zscore` — NaN-preserving, average-rank ties.
- `neutralize(x, groups=, covariates=)` — OLS residual on sector dummies +
  continuous exposures (sector/beta/vol-neutral); NaN rows dropped.
- `pearson`, `spearman`, `information_coefficient`, `quantile_spread`.
- `is_disguised`, `redundancy_report` — screen new signal vs a library.

Not exported from `research/__init__.py` (import-cycle avoidance); imported by path
`from mentisrex.research.cross_sectional import ...`.

## Tests — `tests/research/test_cross_sectional.py` (12, all pass)
Tie averaging; NaN preservation; z-score moments; group-mean removal;
covariate-orthogonality of residual; NaN-row dropping; IC=1 on monotone signal;
disguise-by-correlation; disguise-by-IC-collapse; independent-signal-not-flagged;
library screen; spearman symmetry.

## Regression
`pytest tests/research tests/validation` → **2183 passed, 2 skipped, 0 failures.**

## Known limitations / Skipped
- Multi-date panel aggregation (IC time series, IC-IR, IC decay) not included — a
  thin loop over per-date cross-sections; deferred to the factor-research campaign
  layer (M34+), not impossible. Recorded here per CLAUDE.md.
- Research degrees-of-freedom ledger (§XIII) still pending → **M33** (next).

## Next milestone
M33 (P1): research degrees-of-freedom ledger → wired into deflated-Sharpe `n_trials`.
