# M38 — Real-Data Cross-Sectional Factor Sweep

**Certification report.** First real-data run of the M31-M37 machine. Additive;
frozen `ew-momentum-exp v1.0.0` (`b69961b65bab226a500d71f45709945b`) untouched and
its forward results not used.

## Objective
Run genuine factors through the full pipeline on `analytics.duckdb` OHLCV (Indian
equities, daily, 2014-2026, 2143 symbols) and record **real** statistics — no
fabricated numbers.

## Method
`scripts/m38_factor_sweep.py`: daily closes → month-end panels (151 months);
universe per rebalance = top-500 by trailing-12m dollar volume among names with
≥13 months of history (liquidity screen, no forward info). Signals: `mom_12_1`
(12-1 skip-month), `rev_1m` (1-month reversal), `low_vol_6m` (−6m realized vol).
Forward label = next-month return. Each factor run through `FactorCampaign`
(HAC-robust IC t-stat, DoF logging, redundancy screen); PROMISING factors
ensembled equal-weight.

## Results (real, 138 rebalances × ~500 names)
| Factor | IC mean | IC-IR | HAC t | p | hit | LS Sharpe | turnover | status |
|---|---|---|---|---|---|---|---|---|
| mom_12_1  | 0.0253 | 0.167 | 2.10 | 0.038 | 0.60 | 0.63 | 0.22 | PROMISING |
| rev_1m    | 0.0242 | 0.165 | 2.19 | 0.030 | 0.55 | 0.46 | 0.80 | PROMISING |
| low_vol_6m| 0.0238 | 0.154 | 2.14 | 0.034 | 0.56 | −0.28| 0.25 | PROMISING |

Ensemble (equal weight, 3 factors): Sharpe 0.56, HAC t 2.02, **effective bets
2.71**, avg pairwise corr **−0.15**, diversification ratio **2.06**.

## Interpretation (sober)
- All three ICs are small (~0.024-0.025) with HAC t-stats just above 2 — modest,
  borderline-significant edges, not a high-Sharpe fantasy. The HAC correction
  (M31) and DoF logging (M33) keep the claim honest.
- **`low_vol_6m` flags a genuine research inconsistency**: positive rank IC but a
  *negative* long-short Sharpe — the monotone rank relationship and the
  tail-driven Q1/Q5 spread disagree. A real falsification lead, surfaced not
  hidden.
- The three factors are near-uncorrelated (−0.15), so the equal-weight ensemble
  buys real diversification (2.71 of 3 possible bets) even though each standalone
  edge is weak — the intended "portfolio of independent edges" behaviour.

## Known limitations / Skipped (per CLAUDE.md)
- **No survivorship / delisting reconstruction on this panel.** `identity.duckdb`
  (security master) and the delisting store are not populated for this dataset, so
  the universe is symbol-keyed over names *present in the price table*. Surviving
  names are over-represented → the ICs likely carry an **upward survivorship
  bias**. The engine's purge/HAC/DoF controls are applied; the universe control is
  not. **Unblock:** populate `SecurityMaster` + `DelistingStore` for this data and
  swap `universe_at` for `UniverseEngine.universe_as_of`.
- No transaction costs applied to the long-short Sharpe (gross); `rev_1m`'s 0.80
  turnover would be hit hardest. Cost model exists (`research/simulation`); wiring
  is M39.
- Factor library DuckDB is a local data artifact (gitignored), reproduce via the
  script.

## Regression
Pipeline modules unchanged since M37 (`2218 passed`); this milestone adds a script
+ report only. Script is reproducible against the committed engine.

## Next milestone
M39: (a) populate the security master + delisting store for this panel and re-run
under `universe_as_of` to quantify the survivorship haircut, and (b) apply the
existing cost model to the long-short returns for net-of-cost significance.
