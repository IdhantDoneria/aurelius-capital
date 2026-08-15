# M35 — Factor Campaign Runner

**Certification report.** P2. Closes the research loop over M31–M34. Additive;
frozen `ew-momentum-exp v1.0.0` (`b69961b65bab226a500d71f45709945b`) untouched.

## Objective
End-to-end orchestrator for evaluating a candidate factor: evaluate → log DoF
trial → screen redundancy → assign status → persist immutably.

## Implementation
`research/factor_campaign.py`:
- `FactorCampaign.run(name, family, signals, forward_returns, ...)`:
  1. `evaluate_factor` (M34) → `FactorReport`.
  2. Logs a `Trial` to `DoFLedger` (M33) → family `n_trials` stays honest.
  3. `screen_redundancy` — nearest existing factor by **long-short return**
     correlation (Spearman on overlapping prefix); two factors with highly
     correlated return streams are one bet regardless of formula.
  4. Status: `INSIGNIFICANT` (|HAC ic_t_stat| < t_min), `REDUNDANT` (return-dup of
     a library factor), else `PROMISING`.
  5. Persists to a DuckDB factor library (immutable rows).
- `library(status=)`, `n_trials(family)`, `screen_redundancy(ls_series)`.

## Tests — `tests/research/test_factor_campaign.py` (6, all pass)
Promising factor (HAC t>2, 1 DoF); insignificant noise factor; **redundant
near-duplicate flagged with `redundant_with`**; DoF ledger accumulates 5 variants →
5 DoF; library listing + status filter; independent factor not flagged redundant.

## Regression
`pytest tests/research tests/validation` → **2204 passed, 2 skipped, 0 failures.**

## Known limitations / Skipped
- **research_matrix adapter** (turning `feature_matrix_as_of` DataFrames + a price
  source into the per-date signal/forward-return dict panels) not included: needs
  price-based forward-return construction, a real data-plumbing step. Deferred to
  **M36**. Runner is provider-agnostic and complete on the panel contract now.
  Recorded per CLAUDE.md.
- Runner/service DoF-ledger adoption still deferred (M33).

## Next milestone
M36: research_matrix → panel adapter (PIT forward returns from prices) so the
campaign runs on real universe data, then a first live factor sweep across the
M32 feature families with the DoF-corrected significance gate.
