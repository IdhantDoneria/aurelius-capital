# M34 — Factor-Research Campaign Layer

**Certification report.** First P2 breadth milestone, built on the corrected
statistics foundation (M31 HAC, M32 cross-sectional, M33 DoF). Additive; frozen
`ew-momentum-exp v1.0.0` (`b69961b65bab226a500d71f45709945b`) untouched.

## Objective (§XI)
Turn M32's single-cross-section primitives into a full multi-date factor
evaluation: IC time series, IC-IR, HAC-robust IC t-stat, long-short quantile
spread return series + Sharpe/significance, quantile return profile with
monotonicity, factor turnover, and IC decay by horizon.

## Implementation
`research/factor_research.py` (pure/deterministic, composes existing engines):
- `evaluate_factor(signals, forward_returns, groups=, covariates=, q=, ...)` →
  `FactorReport`. Dict-based per-date cross-sections keyed by security id (PIT
  universe membership changes across dates); names aligned pairwise, missing
  dropped never imputed. Optional per-date sector/beta/vol neutralization
  (`neutralize_signal=True`).
- IC series scored with **HAC** (`hac_significance`, M31) for the autocorrelation-
  robust t-stat; long-short series likewise. IC/quantile-spread/neutralize reuse
  `cross_sectional` (M32). Sharpe/significance reuse `validation` (M31).
- `ic_decay(signals, forward_returns_by_horizon)` — mean IC per forward horizon.

## Tests — `tests/research/test_factor_research.py` (7, all pass)
Positive factor → positive IC + spread + HAC t>2 + monotonic; noise factor
insignificant; IC-IR / hit-rate bounds; **sector-neutralization kills a disguised
sector bet**; misaligned names dropped; length mismatch raises; IC decays with
horizon.

## Regression
`pytest tests/research tests/validation` → **2198 passed, 2 skipped, 0 failures.**

## Known limitations / Skipped
- Factor loader from `research_matrix` (adapter turning `feature_matrix_as_of`
  DataFrames into the per-date dict panels) not included — a thin transform;
  deferred to the campaign runner (M35). Recorded per CLAUDE.md; the evaluation
  engine is complete and provider-agnostic now.
- Runner/service DoF-ledger adoption still deferred (from M33).

## Next milestone
M35: factor campaign runner — wire `research_matrix` → `evaluate_factor`, log each
factor evaluation to the M33 DoF ledger, persist `FactorReport`s, and screen new
factors against the library via M32 `redundancy_report`.
