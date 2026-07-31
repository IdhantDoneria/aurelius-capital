# JT 1993 — Reference Institutional Reproduction (Aurelius Capital)

**Date:** 2026-07-31
**Status:** first fully valid run on the corrected harness + validated dataset.
This run is the platform's reference implementation.
**Executor:** `scripts/run_jt_us_reproduction.py` (strategy/params/costs unchanged).
**Verdict:** IMPLEMENTATION READY — METHODOLOGY DIFFERENCES REMAIN.

---

## 1. Pre-run certification

| Check | Result |
|---|---|
| Production DuckDB only | ✓ `data/analytics.duckdb` |
| Clean production universe | ✓ 1007 US equities |
| No toy contamination | ✓ 0 toy survivors (validated filter, threshold 521) |
| Independent IS/OOS execution (G1) | ✓ two separate backtests |
| Momentum implementation unchanged | ✓ `FactorStrategy` |
| Parameters unchanged | ✓ `{lookback:126, quantile:0.1, rebalance_days:21, allow_short:True}` |
| Transaction-cost assumptions unchanged | ✓ engine defaults (commissions applied) |

All certifications passed. Run executed exactly once, no retry, no tuning.

## 2. Execution record

| Item | Value |
|---|---|
| Symbols | 1007 (clean US) |
| Bars | 3,082,019 |
| Date range | 2014-01-02 → 2026-07-30 |
| IS / OOS split | 2014-01-02 → 2022-10-25 / 2022-10-25 → 2026-07-30 |
| Runtime | load 84.6 s, backtest 833.5 s, total 923.5 s |
| Trials | 1 (no tuning) |

### In-sample (independent backtest, run_id acf22df5)
| Metric | Value |
|---|---|
| Sharpe | −0.144 |
| Total return | −32.67% |
| Max drawdown | −65.01% |
| Traded bars | 232,686 |
| Note | tripped drawdown breaker at −65.6% (`IRMD`) — halts IS run only |

### Out-of-sample (independent backtest, run_id b265e84c)
| Metric | Value |
|---|---|
| Sharpe | **0.935** |
| Return (WML, zero-cost) | **+58.78%** |
| Max drawdown | −70.86% |
| Trades | **345** |
| Traded bars | 274,674 |
| Approx CAGR | ~13.1% over 3.76y (pre-halt realized; breaker fired at −60.5% `GYRE`) |
| Adjusted p-value | 0.161 |
| Verdict (harness) | REJECT (not significant at 0.05) |

**Metrics not surfaced by the harness** (honest disclosure — not silently
skipped): annualized volatility, turnover, and monthly-return distribution are
not exposed by `ValidationReport`; surfacing them needs a report-schema change,
which is out of scope under the engineering freeze. CAGR is derived, not
reported by the harness, and is approximate because the OOS run halted early.

## 3. Comparison to the previous (defective) run

| | Previous run | This run |
|---|---|---|
| Universe | 1016 (9 toy leaked) | **1007 clean** |
| OOS trades | **0** (IS halt bled into OOS) | **345** |
| OOS Sharpe | 0.000 | **0.935** |
| OOS return | 0.00% | **+58.78%** |
| Verdict | INCONCLUSIVE (harness void) | REJECT (real evaluation) |

G1 and G2 are both objectively resolved: the OOS window now executes as an
independent backtest with its own fresh circuit-breaker (evidenced by two
distinct `run_id`s and two independent breaker events), and the contaminated
universe is gone.

## 4. Methodology review — remaining differences

| # | Difference vs JT (1993) | Class | Evidence |
|---|---|---|---|
| M1 | No formation skip-period (JT skips ~1 week/month) | **B — fidelity gap** | code: raw 126d return |
| M2 | Non-overlapping monthly book vs JT overlapping 6-mo portfolios averaged | **B — fidelity gap** | `rebalance_days=21`, single book |
| M3 | 5% position cap, not equal-weight deciles | **B — fidelity gap** | `research_config` `max_position_pct=0.05` |
| M4 | Commissions applied (net) vs JT gross | **B — fidelity gap** | fills carry `commission=` |
| M5 | Drawdown circuit-breaker clips each window (JT has none) | **B — fidelity gap (config)** | breaker events at −65.6% / −60.5% |
| M6 | All-cap incl. micro/penny vs NYSE/AMEX price/liquidity screens | **C — data difference** | penny names (e.g. `CLWT` $1.88) |
| M7 | Sample 2014–2026 (incl. 2020 crash) vs 1965–1989 | **D — market evolution** | ingested span |
| M8 | Single 70/30 OOS slice; adj p 0.161 not significant | **E — statistical variation** | one trial, wide CI |
| M9 | US listed-only ingest; survivorship unquantified | **C — data difference** | fixed listed set |

**No item classified as a platform defect (A).** All are methodology fidelity
gaps, data differences, market evolution, or statistical variation.

## 5. Root cause (evidence only)

- The OOS momentum premium is **positive** (Sharpe 0.935, +58.78% WML),
  **directionally consistent** with JT's finding.
- It is **not statistically significant** (adj p 0.161) and carries an extreme
  −70.86% drawdown. Evidence-based drivers: the all-cap/penny universe (M6) with
  no JT liquidity screens injects high-variance names; the absence of the
  skip-period (M1) and overlapping-holding averaging (M2) raises noise; the
  circuit-breaker (M5) truncates each window's tail. These are configuration and
  data differences, not platform faults.
- The **in-sample** loss (−32.67%) reflects the weak 2014–2022 momentum regime
  incl. the 2020 crash (D/M7) amplified by the same universe/methodology gaps.

## 6. Engineering decision

**NO VERIFIED ENGINEERING CHANGES REQUIRED.** No new objectively reproducible
platform defect was discovered. G1 and G2 remain resolved.

## 7. Final verdict

### IMPLEMENTATION READY — METHODOLOGY DIFFERENCES REMAIN

The platform is defect-free and produces a valid, independent OOS evaluation
showing a directionally-correct positive momentum premium. It is **not**
SUCCESSFULLY REPRODUCED because the result is statistically insignificant with
extreme drawdown — a consequence of methodology/data differences, not defects.

### Prioritized methodology fidelity improvements (identified, NOT implemented)

1. **M6 — universe screens.** Apply JT-style price/liquidity/large-cap filters
   (drop penny/illiquid names). Highest expected impact on fidelity and DD.
2. **M3 — equal-weight deciles.** Replace the 5% position cap with equal-weight
   within each decile.
3. **M1 — formation skip-period.** Add a ~1-week/1-month skip between formation
   and holding.
4. **M2 — overlapping holding portfolios.** Average K overlapping monthly
   cohorts rather than a single rebalanced book.
5. **M4 — gross-return reporting.** Report gross alongside net to match JT’s
   headline convention.
6. **M5 — disable circuit-breaker for research evaluation** (keep it live-only),
   so windows are not tail-clipped.
7. **M8 — robustness.** Report walk-forward / multiple sub-periods instead of a
   single 70/30 slice for significance.
