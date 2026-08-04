# Knowledge Graph Summary — Pairs Trading Campaign

**Date:** 2026-08-04. Campaign-level synthesis for institutional memory. All
entries trace to `us.jsonl` / `india.jsonl` and the committed reports.

## Experiment registry (14 runs)

| Market | Configs | ACCEPT | REJECT | Store |
|---|---|---|---|---|
| US | 7 | 0 | 7 | `research_pairs_us_*.duckdb` + shards |
| India | 7 | 0 | 7 | `research_pairs_india_*.duckdb` + shards |

Each run = one hypothesis, one `multi_pairs` fingerprint, one 70/30 OOS
evaluation, n_trials=1 (no tuning). Recorded via `ResearchStore.record_experiment`.

## Validation registry

- **Significant (adj p < 0.05):** 0 / 14. Every config adjusted p = 1.000.
- **Least-bad OOS Sharpe:** India exit_0.25 (−0.140), India top40 (−0.238), India
  gatev_top20 (−0.425). All negative.
- **Worst:** US top5 (−13.54, degenerate near-zero-vol Sharpe), US entry_1.5 (−1.393).

## Failure registry

| Failure | Where | Class |
|---|---|---|
| Published Gatev premium not reproduced | US+India gatev_top20 (−1.076 / −0.425) | D — market evolution (Do-Faff decay) |
| Diversification inverts (more pairs = worse) | top40 both (−60.2% / −42.5% DD) | B — sizing/leverage truncation (P5/M3) |
| Neutrality breaks under gross cap | top40, entry_1.5 wide books | B — P5 |
| IS→OOS overfit flip | India window_63 (+0.689 → −0.523) | E — short-window overfit |
| Degenerate Sharpe at near-zero vol | US top5 (−13.54) | E — small-book statistic |
| No significance on single OOS slice | 14/14 configs | D + E |

## Lessons registry

See `Lessons_Learned.md`. Headline: distance-pairs edge is **gone** from 2014–2026
US+India (0/14); `MultiPairStrategy` composes the frozen `PairsStrategy` into a
true diversified book with zero engine change; the 1.5× gross cap + fixed-% sizing
**inverts** Gatev's diversification benefit; a well-powered negative result (3000+
trades) is a real research output, not a failure to complete.

## Research decision ledger

| Decision | Rationale | Reversible? |
|---|---|---|
| Run Gatev distance pairs on real US+India via 12-mo formation | old toy blocker (data scale) resolved; 12-mo window is Gatev-faithful | — |
| Compose N pairs into `MultiPairStrategy` (not average N single-pair runs) | one backtest = genuine cross-pair diversification; averaging Sharpes fakes it | — |
| Keep Vidyamurthy/Avellaneda-Lee/Kalman/sector/ADR BLOCKED | no cointegration/PCA/Kalman/sector/ADR data or selector | yes, on data/selector acquisition |
| Do NOT change sizing/leverage after top40 blow-up | risk engine working as designed; changing = tuning + unfreeze | yes, in a future un-frozen phase |
| Emit NO production strategy | 0/14 significant; naming a config = tuning | yes, only on a significant bias-corrected result |
| Recommend not funding further pairs engineering | null is economic (D), not a Class-A defect | yes, research decision |

## What is robust / fragile / data-dependent

- **Robust (the null):** across every axis and both markets, pairs is unprofitable
  and insignificant — a stable, well-powered negative.
- **Fragile:** wide/loose books (top40, entry_1.5) — leverage-cap truncation turns
  a market-neutral book into a directional −60% loser.
- **Data-dependent:** India's faint positive *returns* (survivorship + less-efficient
  market); they vanish risk-adjusted and would worsen de-biased.
- **Methodology-dependent:** every result is bounded by fixed-% sizing (P5) and
  static formation (P3); both bias against pairs.

## Knowledge graph deltas to persist

Append to `docs/KNOWLEDGE_GRAPH.md`: (1) distance-pairs stat-arb does not survive to
2014–2026 US+India (Do-Faff decay confirmed empirically, 0/14); (2) under fixed-%
sizing + a gross cap, pair-portfolio diversification **inverts** — more pairs raise
truncation-induced directional risk (first-order design constraint for any
market-neutral book); (3) India less-efficient → less-bad but still insignificant;
(4) 0 platform defects across 14 pairs runs.
