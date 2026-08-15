# M37 — Signal Ensembling

**Certification report.** P2, capstone of the factor-research arc (M31–M37).
Additive; frozen `ew-momentum-exp v1.0.0`
(`b69961b65bab226a500d71f45709945b`) untouched.

## Objective (§XX)
Combine the independent, non-redundant edges in the factor library (M35) into one
composite return stream — the "portfolio of independent sources of edge" thesis.
Diagnostics (correlation, diversification ratio, effective bets) rank alongside
combined Sharpe; the objective is robustness, not max historical Sharpe.

## Implementation
`research/ensemble.py`:
- `combine(series_map, method=)` → `Ensemble`. Methods: `equal` (no estimation),
  `inverse_var` (down-weight noisy factors), `ic_weight` (lean on stronger
  predictors). HAC t-stat (M31) on the composite.
- `correlation_matrix`, `diversification_ratio` (weighted-avg vol / portfolio vol),
  `effective_bets` (exp-entropy of correlation eigenvalue spectrum, Meucci-style:
  K uncorrelated → K, rank-1 redundant → 1).
- `FactorCampaign.return_series(status=)` exposes the library's long-short streams
  as ensemble inputs.

## Tests — `tests/research/test_ensemble.py` (9, all pass)
Equal weights sum to 1; independent factors → diversification ratio > 1.5 and
effective bets > 3; **three redundant copies → effective bets ~1, avg corr > 0.99**;
inverse-var down-weights the noisy factor; ic_weight requires + uses ic_map; empty
raises; correlation-matrix shape; single-factor bets = 1; end-to-end from a
`FactorCampaign` library (two independent edges → > 1.5 bets).

## Regression
`pytest tests/research tests/validation` → **2218 passed, 2 skipped, 0 failures.**

## Known limitations / Skipped
- `effective_bets` is the portfolio-agnostic PCA form (correlation eigenvalues),
  not the weight-dependent Meucci torsion. Correct for ranking factor-set
  diversification; a weight-aware version belongs with portfolio construction
  (already built in `research/portfolio/`). Recorded per CLAUDE.md.
- Regime-dependent / Bayesian ensembling (§XX) not built — needs a regime-label
  series; deferred until a regime classifier exists. Not impossible; unblock =
  a dated regime-state series to condition weights on.
- Runner/service DoF-ledger adoption still deferred (M33).

## Arc summary (M31–M37)
A complete cross-sectional factor-research machine on the corrected statistics
core: HAC + purged CV (M31) → neutralization + redundancy (M32) → DoF ledger (M33)
→ multi-date factor evaluation (M34) → campaign runner + dedup library (M35) →
PIT panel adapter from real data (M36) → ensemble of independent edges (M37).

## Next milestone
M38: live factor sweep over the real universe (requires populated PIT price +
research-matrix stores) OR M33-adoption (wire the DoF ledger into runner/service).
Pick per data availability — do NOT fabricate a sweep if stores are unpopulated.
