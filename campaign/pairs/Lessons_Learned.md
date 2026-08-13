# Lessons Learned — Pairs Trading Campaign

**Date:** 2026-08-04. Operational + research lessons, each traceable to evidence.

## Research lessons

- **L1 — The distance-pairs edge has decayed to nothing.** 0/14 configs significant
  on 2014–2026 US+India, both markets, every axis. This is Do & Faff's (2010/2012)
  prediction confirmed on Mentisrex data: Gatev's ~11%/yr is a 1962–2002 artifact,
  arbitraged away by the modern era. *Evidence:* all adjusted p = 1.000.
- **L2 — Diversification INVERTS under fixed-% sizing + a gross cap.** Gatev's whole
  premium is diversifying across 20 pairs; here top40 is the *worst* config in both
  markets (−60% / −42% DD). The 1.5× cap truncates a 400%-nominal-gross book,
  breaking dollar-neutrality → directional risk. **More pairs made it worse.** The
  benefit cannot express without committed-capital sizing (P5). Same leverage story
  as the momentum campaign — one platform constraint, two campaigns.
- **L3 — A well-powered negative is a real result.** The 2026-07-30 toy Gatev failed
  on 22 trades (no power). This run has 591–4833 OOS trades/config — the null is
  *economic*, not a sample artifact. "Reproduced faithfully and it doesn't work" is
  a publishable institutional finding, not a failure to complete.
- **L4 — India less-efficient ⇒ less-bad, not good.** India had the higher OOS Sharpe
  on 6/7 configs and kept faint positive returns on 5, but every India config still
  REJECTs and the returns are survivorship-inflated. Efficiency gradients move the *degree* of failure, not
  the *sign* of the conclusion.
- **L5 — Sharpe is unstable for near-zero-vol books.** US top5 posted −13.54 Sharpe on
  a −1.2% return / −1.4% drawdown — a denominator artifact, not a −13× loss. Read
  tiny-book Sharpes with the return and drawdown beside them, never alone.
- **L6 — IS positive ≠ OOS positive.** India window_63 was the only positive IS Sharpe
  (+0.689) and flipped to −0.523 OOS. The 70/30 split earned its keep by catching a
  short-window overfit. Always judge on OOS.

## Operational lessons

- **L7 — Compose, don't duplicate.** `MultiPairStrategy` is 25 lines wrapping N
  `PairsStrategy` instances; on_bar concatenates their signals. One backtest yields a
  true diversified equity curve — no engine change, no logic copy. Averaging N
  separate single-pair Sharpes would have *faked* diversification and inflated the
  result. The faithful path was also the smaller diff.
- **L8 — Isolated per-config DuckDB stores enable safe parallelism.** Reused the
  momentum pattern (`research_pairs_{market}_{label}.duckdb`, read-only source open):
  4 workers ran concurrently with zero write-lock contention; results deterministic.
- **L9 — Formation window choice was the *un-blocker*, and it was faithfulness, not
  tuning.** The old toy used a 6-YEAR formation half → ~3 complete-history names. A
  12-MONTH formation (Gatev's actual design) gives 864–1127 complete names → a real
  top-N book. The more-faithful choice resolved the data blocker. Fidelity and
  feasibility aligned.
- **L10 — Runtime is bar-count-bound, not strategy-bound.** ~17 min/config is the
  engine's 3.37M-event pass (same as momentum); the 20-pair sub-loop is early-return
  cheap. Don't optimize the strategy to speed a campaign — parallelize the configs.

## What we did NOT do (discipline)

- No parameter tuned to force a positive result (governance).
- No production strategy invented from an insignificant "best" config.
- No BLOCKED variant (cointegration/PCA/Kalman/sector/ADR) faked on toy data.
- No engine change: 0 Class-A defects; the top40 blow-up is a *documented* sizing
  fidelity gap (B), not a bug.
