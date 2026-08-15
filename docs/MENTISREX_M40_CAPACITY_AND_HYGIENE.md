# M40 — Capacity Engine + Data-Hygiene Baseline

**Certification report.** P2. Two things: (a) fixed the M38 market-mix
contamination, (b) built the capacity engine (§XXII). Additive; frozen
`ew-momentum-exp v1.0.0` (`b69961b65bab226a500d71f45709945b`) untouched.

## Data hygiene (the M38 correction)
`analytics.duckdb` = **1127 India `.NS` + 1016 US/ETF** names, both to 2026. The
M38 top-500-by-dollar-volume sweep silently mixed them → US megacaps dominated.
`scripts/factor_lab.py` now evaluates **one market at a time**. All numbers remain
**survivorship-suspect** until Priority-1 data (see `DATA_ACQUISITION_BRIEF.md`).

### Clean India-only wide sweep (9 signals, top-300, 4.5 bps cost)
| signal | IC | IC t | net LS Sharpe | net t | turnover | note |
|---|---|---|---|---|---|---|
| mom_12_1 | 0.033 | 2.23 | **0.67** | **2.30** | 0.23 | best candidate |
| mom_12m  | 0.028 | 1.85 | 0.60 | 2.02 | 0.22 | same momentum bet |
| high_52w | 0.029 | 2.06 | 0.08 | 0.33 | 0.33 | IC but no LS spread |
| low_vol_6m | 0.029 | 2.20 | −0.26 | −0.86 | 0.25 | IC/LS sign conflict |
| rev_1m / mom_1m / mom_3m/6m | weak | <1.6 | — | — | — | not significant net |

The momentum horizons collapse to **one bet** (redundancy screen working). Net of
costs, **mom_12_1 (12-1 momentum) is the only economically meaningful survivor**:
net LS Sharpe 0.67, net HAC t 2.30 — modest, plausible (momentum is the most
robust global equity anomaly), survivorship-suspect.

## Capacity engine
`research/capacity_curve.py`, `capacity_curve(signals, forward_returns, adv, cost_model, aum_levels)`:
equal-weight top/bottom quantile, per-name order = leg notional / n, participation
= notional / ADV, √-law impact (Almgren 2005) via `TransactionCostModel.impact_coef`.
Returns AUM → net-Sharpe curve + half-Sharpe capacity.

### Real result — mom_12_1 India (INR, impact_coef 0.1)
| AUM (INR) | net Sharpe |
|---|---|
| 1M | 0.65 |
| 100M | 0.57 |
| 1B (~$12M) | 0.39 |

Half-Sharpe capacity **not reached within ₹1B**. At realistic starting capital
impact is negligible — the binding constraint is the edge's marginal size, not
capacity.

## Tests — `tests/research/test_capacity_curve.py` (3, all pass)
Sharpe decays monotonically with AUM; deeper ADV → more capacity; half-capacity
detected.

## Known limitations / Skipped (per CLAUDE.md)
- **Survivorship still uncontrolled** — all numbers survivorship-suspect until
  Priority-1 data lands.
- **Redundancy "canonical" factor is run-order dependent** — the SET of independent
  bets is correct, but which correlated horizon is labelled canonical depends on
  evaluation order. Reporting artifact, not a research error. Unblock = cluster-then-
  pick-highest-IC pass.
- US-market sweep not certified — the US half mixes ETFs and stocks; needs an
  instrument-type filter first.

## Next
- On data: load Priority-1 survivorship data → re-run, expect ICs to fall.
- On code: register mom_12_1 as an isolated forward paper campaign (start the clock).
