# Mentisrex Capital — Institutional Acceptance Test

**Role:** CTO, final acceptance before handing the platform to research.
**Date:** 2026-07-27.
**Method:** subsystem audit + live end-to-end validation (5 benchmark strategies actually executed through the real engine, not asserted on paper).
**Rule applied:** no new features except where required to fix an architectural correctness issue. One such issue was found and fixed (multi-symbol fill routing).

---

## PHASE 1 — Subsystem audit

Scores are 0-100. **Prod** = production readiness. **Res** = research readiness (is it trustworthy enough to base alpha decisions on *today*).

| Subsystem | Status | Prod | Res | Key gap / debt |
|---|---|---:|---:|---|
| Data ingestion | Adapters: yahoo, alpaca, csv; normalizer; ingestion pipeline | 70 | 65 | No point-in-time/bitemporal store; no survivorship-free universe; corporate-action handling is adjust-on-read, not audited |
| Data storage | DuckDB analytical store + Postgres OLTP + Redis cache | 75 | 70 | No dataset versioning/snapshot IDs surfaced to research; no as-of query API |
| Feature engineering | pipeline + library (price, technical, volatility, volume, statistical) | 75 | 70 | Features computed on demand; no leakage lint on custom features beyond assistant review |
| Feature registry | registry + store | 70 | 65 | No point-in-time feature values (feature store is not bitemporal); no lineage/versioning |
| **Backtesting engine** | event-driven, T+1 fills, cost model, OMS, risk gate | **80** | **75** | **Cross-symbol fill bug (FIXED this run).** Equity snapshot per bar-event, not per day → Sharpe mis-annualized on multi-symbol |
| Portfolio engine | construction: aggregation, sizing, optimize (numpy pinv), exposure, builder | 70 | 65 | Optimizer is projected-gradient, no covariance shrinkage (Ledoit-Wolf); no factor risk model |
| Risk engine | engine, monitor, stress; parametric VaR, tabulated z | 70 | 65 | Parametric VaR only (no historical/MC); z-scores tabulated; stress library thin |
| Paper trading | broker, engine, journal, dashboard; supervised loop | 70 | 70 | No live-vs-modeled cost reconciliation report; manual promotion |
| AI research assistant | paper parse, hypothesis gen, code review, bias detect, reports | 75 | 75 | Deterministic offline analyzers; LLM seam optional. Cannot trade (structurally enforced) — correct |
| Experiment tracking | research: runner, store, models (Verdict, ValidationCriteria), dataset_fingerprint | 70 | 70 | Store persistence is basic; no automatic trial-count budget per dataset wired into deflation |
| Monitoring | `/metrics` Prometheus endpoint (up, uptime, build_info) | 55 | 50 | No strategy-level or data-quality metrics; no alerting rules shipped |
| Logging | structlog, structured, request middleware | 80 | 75 | Good. No log-based research audit trail linking runs to experiment IDs |
| Configuration | pydantic-settings, prod hard-crash guards | 85 | 80 | Strong. Backtest reproducibility relies on config+data version discipline (not enforced by a lock file) |

**Audit headline:** the platform is a solid *single-asset* research engine. Its weakest seams for *institutional* research are all on the data side (point-in-time / survivorship / bitemporal) and multi-asset correctness — one of which (multi-asset fills) was a live bug.

---

## PHASE 2 — End-to-end validation (executed)

Harness: `scripts/acceptance_validation.py`. Five benchmarks run through the real `BacktestEngine` on deterministic seeded data (5 symbols × 300 bars, seed=42). Seven correctness checks per strategy.

### Finding (fixed): multi-symbol cross-symbol fill bug — CRITICAL
`ExecutionSimulator.try_fill(order, bar)` never checked `order.symbol == bar.symbol`, and `engine._process_bar` tried every pending order against the current bar. In a single-symbol universe (every existing test) this is invisible. In a multi-symbol universe a pending `AAA` order filled against the next chronological bar — a *different* instrument — at the wrong price, mislabeled with the wrong symbol, and on the same calendar day (defeating T+1 across symbols).

**Fix:** one-line symbol guard in `engine._process_bar` (skip non-matching bars, keep the order pending). Regression test added: `test_multi_symbol_fills_against_own_bar`. All 58 backtesting tests still pass (now 59 with the regression).

### Result after fix

```
strategy               fills      ret  sharpe   maxDD  checks
buy_and_hold               5   33.0%   -0.00   -5.8%  PASS
ma_crossover_50_200        4   10.3%   -1.58   -2.9%  PASS
xs_momentum               80   10.3%   -1.45   -3.3%  PASS
rsi_mean_reversion        24    2.1%   -1.98   -5.4%  PASS
equal_weight               5    6.6%   -4.38   -1.2%  PASS
ALL CHECKS PASS
```

(Returns/Sharpe are on random-walk synthetic data — meaningless as alpha, correct as plumbing. Purpose is accounting, not profit.)

### Verification checklist

| Property | Verdict | Evidence |
|---|---|---|
| Portfolio accounting | PASS | equity curve starts at initial capital; one snapshot per bar event |
| Transaction costs | PASS | every fill carries commission > 0; spread + slippage embedded in fill price |
| Corporate actions | PARTIAL | adapters adjust for splits/dividends on read; **not independently audited in this test** — synthetic data has none. Flagged. |
| Position sizing | PASS | every fill notional ≤ max_position_pct·NAV (within fill-move tolerance) |
| Risk metrics | PARTIAL | drawdown never positive (PASS); **Sharpe mis-annualized on multi-symbol** (per-event sampling) — required fix |
| Reproducibility | PASS | identical seed → identical final equity and fill count, per strategy |
| Look-ahead prevention | PASS | no fill on the first bar; T+1 execution held after the symbol-guard fix |
| Data leakage prevention | PASS | `StrategyContext.history` returns only bars ≤ now; assistant code-review flags leakage patterns |

---

## PHASE 3 — Research readiness verdict

**Can the platform be trusted to conduct quantitative research today?**

**Single-asset, price-based research: YES.** The engine is accounting-correct, look-ahead-safe, reproducible, and cost-aware. Trend/momentum/mean-reversion/vol on individual instruments can begin.

**Cross-sectional / portfolio / multi-asset research: NOT YET** — blockers below. (The single most dangerous one, cross-symbol fills, is now fixed; the rest remain.)

### Engineering issues that must be fixed before *portfolio* alpha research

1. **Equity curve sampled per bar-event, not per calendar day.** Multi-symbol runs over-count return periods by ~N_symbols → Sharpe/vol/drawdown-duration mis-annualized. Snapshot once per timestamp after all same-stamp events drain. **(Required.)**
2. **No point-in-time / bitemporal data.** Fundamentals and feature values must be as-of to avoid restatement and survivorship leakage. Value/quality/event research is untrustworthy without it. **(Required for those lanes.)**
3. **No survivorship-free universe / index-membership history.** Any cross-sectional study is biased until universes are reconstructed point-in-time. **(Required for cross-sectional.)**
4. **Corporate-action handling unaudited.** Split/dividend adjustment is applied but never verified end-to-end against a known case. Add one golden-case test. **(Required.)**
5. **No dataset snapshot lock.** `dataset_fingerprint` exists but reproducibility depends on discipline; a run should pin an immutable data+config hash. **(Strongly recommended.)**

Everything else is enhancement, not a trust blocker.

---

## PHASE 4 — Final engineering report

### Scores
- **Overall platform readiness: 72 / 100.**
- **Production readiness: 73 / 100.**
- **Research readiness: 70 / 100** (single-asset ~85; cross-sectional ~55 until the data-side blockers close).

### Top 20 remaining improvements (ranked)

| # | Improvement | Priority | Effort | Why |
|---|---|---|---|---|
| 1 | Per-timestamp equity sampling (fix Sharpe on multi-symbol) | Critical | S | Every multi-asset risk metric is wrong without it |
| 2 | Point-in-time / bitemporal fundamentals + feature store | Critical | L | Unlocks value/quality/event research safely |
| 3 | Survivorship-free universe + index-membership history | Critical | M | Removes the largest cross-sectional bias |
| 4 | Corporate-action golden-case test + audit | High | S | Verifies a claimed capability never actually tested |
| 5 | Immutable dataset+config snapshot lock per run | High | S | True reproducibility, not disciplinary |
| 6 | Deflated Sharpe / PBO wired into the validation gate | High | M | Kills multiple-testing false positives automatically |
| 7 | Walk-forward + purge/embargo (CPCV) harness | High | M | Standardizes OOS; today it is ad hoc |
| 8 | Ledoit-Wolf covariance shrinkage in optimizer | High | S | Stabilizes portfolio weights; cheap, high impact |
| 9 | Transaction-cost model calibration vs. paper fills | High | M | Cost model is assumed, never reconciled |
| 10 | Historical + Monte-Carlo VaR (beyond parametric) | Medium | M | Parametric VaR understates tail risk |
| 11 | Factor risk model (exposure decomposition) | Medium | L | Needed to prove alpha is orthogonal, not repackaged beta |
| 12 | Strategy-level + data-quality monitoring metrics | Medium | M | `/metrics` is infra-only today |
| 13 | Experiment store: auto trial-count budget per dataset | Medium | S | Feeds deflation; prevents dataset over-mining |
| 14 | Capacity / market-impact estimator per strategy | Medium | M | Required before any capital sizing |
| 15 | Research audit trail linking logs → experiment IDs | Medium | S | Traceability from result back to run |
| 16 | Alerting rules on the monitoring stack | Medium | S | Metrics without alerts are decoration |
| 17 | Slippage model: square-root impact law | Medium | S | Current linear impact underestimates large orders |
| 18 | Short-side borrow/financing cost model | Low | S | Needed for long-short and BAB lanes |
| 19 | Multi-frequency (intraday) data path validation | Low | M | Only if a microstructure lane opens |
| 20 | Pay down legacy mypy-strict debt (44 files) | Low | L | Advisory today; hygiene, not correctness |

### Freeze recommendation

**Conditional freeze — do NOT fully freeze yet.**

Freeze the *architecture and interfaces* now — they are sound. But keep four items open before research beyond single-asset begins: **#1 (equity sampling), #4 (corporate-action audit), plus #2/#3 (point-in-time + survivorship) for any cross-sectional work.** These are correctness, not features.

Recommended path: ship #1 and #4 immediately (both Small), then declare the **single-asset platform frozen and open for research today**. Treat #2/#3 as the gating epic that unlocks the cross-sectional lanes — research can start on trend/momentum/mean-reversion in parallel while the data-side epic lands.

The engine is trustworthy where it has been proven. It has now been proven — including by finding and fixing a bug that only a real multi-asset run would surface.
