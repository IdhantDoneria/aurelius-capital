# Institutional Reproduction Report — Jegadeesh & Titman (1993), US Dataset

**Program:** Aurelius Capital — Research Reproduction Campaign
**Paper:** Jegadeesh, N. & Titman, S. (1993), *Returns to Buying Winners and
Selling Losers: Implications for Stock Market Efficiency*, Journal of Finance.
**Run date:** 2026-07-31
**Executor:** `scripts/run_jt_us_reproduction.py` (US-scoped wrapper reusing the
committed `reproduce_jegadeesh_titman.py` strategy/params/runner verbatim)
**Discipline:** single run, no tuning, no grid, strategy unchanged.

---

## 1. Executive Summary

The reproduction **did not faithfully reproduce Jegadeesh & Titman (1993)**, and
the controlling reason is a **verified platform defect in the research
evaluation harness**, not a difference of opinion about the data.

Two independent problems were found:

1. **Pre-execution — dataset contamination (remediated).** The production
   analytics store (`data/analytics.duckdb`) still contained 9 US mega-cap
   tickers written by the *old toy loader* (`load_and_run_momentum.py`) with
   synthetic 2022–2023 prices (e.g. AT&T `T` at $216, `MSFT` capped at $66) and
   only 520 bars each vs ~3,181 for real names. STEP 1's precondition ("no old
   toy dataset remains active") was **violated**. These 9 names were excluded to
   form the clean US universe before the single official run.

2. **Execution — OOS evaluation is void (proven defect).** The research
   walk-forward runs **one** backtest over the full sample and then slices it
   into in-sample (IS) and out-of-sample (OOS) windows. The strategy tripped the
   portfolio **drawdown circuit-breaker at −65.6%** (limit −60%) **inside the IS
   window (before the 2022-10-25 split)**, which permanently halts all trading
   for the remainder of the single run. Consequently the **entire OOS window
   traded 0 times** — OOS Sharpe, return, drawdown and trade count are all zero,
   and the verdict is `INCONCLUSIVE`. The platform produced **no out-of-sample
   evaluation at all**.

**Verdict: IMPLEMENTATION DEFECT** (evaluation harness; see §10).

---

## 2. Dataset Used

| Item | Value |
|---|---|
| Store | `data/analytics.duckdb` (666 MB), table `ohlcv`, `frequency='1d'` |
| Full store | 2,143 symbols, 6,457,021 rows, 2014-01-01 → 2026-07-31 |
| US selector | `symbol NOT LIKE '%.%'` (India names carry `.NS` / `.BO`) |
| Raw US | 1,016 symbols |
| Excluded (toy) | 9 symbols: `GE, JPM, KO, META, MSFT, NVDA, PG, T, XOM` |
| **Clean US universe** | **1,007 securities, 3,082,019 bars, 2014-01-02 → 2026-07-30** |
| IS window (70%) | 2014-01-02 → 2022-10-25 |
| OOS window (30%) | 2022-10-25 → 2026-07-30 |

Contamination evidence (per-symbol): the 9 excluded names carry exactly 520 bars
spanning 2022-01-03 → 2023-12-29 with prices inconsistent with reality
(`T` max $216 vs real ~$18; `MSFT` max $66 vs real ~$250–370). `AAPL/AMZN/GOOG`
were **not** excluded — they hold full real history (3,181 bars); the real
ingest overwrote their toy rows on the shared primary key `(symbol,timestamp,
frequency)`.

---

## 3. Execution Summary

| Metric | Value |
|---|---|
| Runtime — load | 45.7 s |
| Runtime — backtest | 376.7 s |
| Runtime — total | 424.7 s |
| Symbols processed | 1,007 |
| Date range processed | 2014-01-02 → 2026-07-30 |
| Portfolios / rebalances | 21-bar cadence (monthly), cross-sectional deciles |
| Traded bars (engine) | 232,686 |
| Fills logged | ~1,564 |
| Warnings / failures | 1 terminal halt: `Drawdown -65.6% exceeds limit -60.0%; halting` (trigger symbol `IRMD`, in IS window) |
| Runs | 1 (no retry, no tuning) |

Strategy executed: `FactorStrategy` (cross-sectional decile long-short
momentum), JT params `{lookback: 126, quantile: 0.1, rebalance_days: 21,
allow_short: True}` — identical to the committed reproduction script.

---

## 4. Statistical Results

| Metric | Value | Note |
|---|---|---|
| IS Sharpe | **−0.144** | in-sample, halted mid-window |
| OOS Sharpe | **0.000** | **no OOS trades** |
| OOS return (WML, zero-cost) | **0.00%** | no OOS trades |
| OOS max drawdown | **0.00%** | no OOS trades |
| OOS trades | **0** | OOS window never traded |
| Full-run total return | −32.67% | IS-halted single run |
| Full-run max drawdown | −65.01% | tripped the −60% halt |
| Full-run Sharpe | −0.144 | |
| Trials | 1 | no tuning |
| Adjusted p-value | 1.000 | |
| Verdict | `INCONCLUSIVE` | |

**Metrics requested by the campaign that the reproduction's `ValidationReport`
does not surface** (honest disclosure, not silently skipped): CAGR/annualized
return, annualized volatility, win rate, turnover, and the monthly-return
distribution are **not exposed** by the existing report object — only
Sharpe (IS/OOS), OOS return, OOS max-DD, OOS trades, trials and adj p-value are.
For this run the OOS values are all zero regardless, so no derivation is
possible. Surfacing these would require a report-schema change (out of scope for
"execute the existing implementation unchanged").

---

## 5. Methodology Fidelity Assessment

| Dimension | JT (1993) | This implementation | Faithful? |
|---|---|---|---|
| Portfolio construction | Decile winner-minus-loser, zero-cost | Decile L/S (`quantile=0.1`), zero-cost | Partial — see weighting |
| Formation period | 6 months (J), with 1-week/1-month **skip** to avoid microstructure/reversal | 126 trading days raw return, **no skip** | **No** (skip absent) |
| Holding period | 6 months (K), **overlapping** portfolios averaged | 21-bar rebalance, single book | **No** (non-overlapping, monthly) |
| Ranking | Cumulative past return | `(c[-1]-c[0])/c[0]` over 126d | Yes |
| Rebalance | Monthly | Every 21 bars (~monthly) | Yes |
| Weighting | Equal-weight within decile | Engine sizing + `max_position_pct=5%` cap | **No** (capped, not equal-weight) |
| Transaction costs | Gross (costs discussed separately) | Commissions applied per fill | **No** (net vs gross) |
| Universe | NYSE/AMEX, price/liquidity screens | All-cap US incl. micro/penny (e.g. `CLWT` $1.88) | **No** |
| Statistical test | t-stat on monthly WML (~3) | Multiple-testing-aware verdict on IS/OOS | Different framework |

**Conclusion:** even setting aside the halt, the implementation is a *momentum
family* strategy but **not a faithful JT reproduction** — the skip-period,
overlapping-holding averaging, equal-weight deciles, gross-return convention, and
NYSE/AMEX-style universe screens are all absent.

---

## 6. Gap Analysis (classified)

| # | Observed difference | Class | Evidence |
|---|---|---|---|
| G1 | OOS window traded 0 times; no OOS evaluation | **G — Implementation defect** | Halt log at −65.6% in IS; OOS trades=0; halt date < 2022-10-25 cut |
| G2 | 9 toy tickers embedded in US universe | **G — Implementation defect** (toy loader shares production DB) | 520-bar synthetic series; `T`=$216 |
| G3 | No skip-period in formation | A/G — methodology | code: raw 126d return |
| G4 | Non-overlapping monthly book vs JT overlapping-6mo | Methodology (implementation choice) | `rebalance_days=21`, single book |
| G5 | 5% position cap, not equal-weight deciles | Methodology | `research_config` `max_position_pct=0.05` |
| G6 | Commissions applied (net, not gross) | E — corporate/cost handling | fills carry `commission=` |
| G7 | All-cap incl. micro/penny universe | C — universe differences | `CLWT` $1.88, `IRMD`, `ESEA` |
| G8 | 2014–2026 sample incl. 2020 momentum crash | A/B — sample period / regime | vs JT 1965–1989 |
| G9 | US survivorship unknown (only listed names ingested) | D — survivorship bias (unquantified) | ingest is a fixed listed set |

Per the rule "only classify as defect with objective evidence": **G1 and G2 are
the only items proven as defects.** G3–G9 are genuine methodology/data
differences that would move the number but are **not** proven defects.

---

## 7. Root Cause Analysis

The `INCONCLUSIVE`, all-zero-OOS outcome is **primarily explained by a genuine
platform defect (G1)**, with a data-hygiene defect (G2) as a secondary,
remediated factor:

- **Not** "better dataset" — the dataset is larger/cleaner than the toy set, but
  that is irrelevant to the OOS void.
- **Not** primarily "different period/regime" — although 2014–2026 momentum
  (incl. the 2020 crash) is weaker than JT's 1965–1989 sample, the −65% IS loss
  only *triggers* the defect; it does not *explain the void*. A weak IS result
  should still yield a measurable OOS result; here it yields none.
- **Root cause of the void (G1):** `ResearchRunner.train_test` executes **one**
  backtest over the whole sample and slices it. The drawdown circuit-breaker
  (`BacktestConfig.max_drawdown_halt`, a **live-trading safety** feature) fires
  once and halts trading **permanently**. When it fires in-sample, the OOS
  window inherits a halted engine and can never trade → OOS is structurally
  empty for any strategy that draws down past the limit in-sample. `research_config`
  already loosened the halt to 0.60 (from the stricter live default), which
  proves the authors knew this interaction — but 0.60 still trips.
- **Root cause of the IS loss magnitude (−65%):** a mix of **C (all-cap/penny
  universe), E (transaction costs), and methodology gaps G3–G5** — *not proven*
  as defects, and not separable without a second run (forbidden by mandate).

---

## 8. Engineering Observations

Defect reproduced, isolated and measured (no code modified — per mandate):

- **Reproduced:** the single run halts at −65.6% and returns 0 OOS trades.
- **Isolated:** `src/aurelius/research/validation.py::train_test` runs one
  backtest and windows it; the halt in `BacktestConfig` is permanent and applies
  across the IS/OOS boundary.
- **Impact:** total loss of out-of-sample evaluation for any strategy that
  breaches the drawdown limit in-sample — i.e. the harness cannot certify or
  reject such strategies at all.
- **Smallest recommended fix (not applied):** run IS and OOS as **two
  independent backtests** (fresh engine per window) inside `train_test`, so an
  IS halt cannot zero the OOS book. Equivalent-smaller alternative: disable the
  circuit-breaker for research evaluation (`max_drawdown_halt = None/1.0` in
  `research_config`), since it is a live-trading safety, not a research
  constraint. Recommend the former (preserves the safety in live paths).
- **Secondary fix (data hygiene):** point the toy loader
  `load_and_run_momentum.py` at a **separate** DuckDB file, or add a min-history
  quality gate to the reproduction loader, so toy rows can never enter a
  production reproduction universe. (This run remediated it by explicit
  exclusion.)

---

## 9. Research Observations

- Even with a corrected harness, the current strategy is **not** a faithful JT
  reproduction (see §5). A faithful reproduction needs: a formation skip-period,
  overlapping-portfolio holding-period averaging, equal-weight deciles, a
  gross-return reporting convention, and a large-cap/liquidity-screened universe.
- The all-cap universe (penny names like `CLWT` at $1.88) injects
  microstructure noise that JT's screens were specifically designed to remove;
  this alone can flip the sign of a naive momentum book.
- Reporting CAGR, volatility, turnover, win-rate and the monthly distribution
  requires extending `ValidationReport`; today the harness reports Sharpe-centric
  fields only.

---

## 10. Final Verdict

### IMPLEMENTATION DEFECT

Objective evidence (halt log at −65.6% in the in-sample window + `OOS trades = 0`
+ IS/OOS split at 2022-10-25) proves the research evaluation harness cannot
produce an out-of-sample result when the in-sample trips the drawdown
circuit-breaker. The reproduction therefore yielded no faithful JT result. A
second, remediated defect (toy-data contamination of the production universe) was
found in pre-execution audit and excluded before the run.

No parameters were tuned, no strategy was modified, and the run was executed
exactly once. Recommended fixes are stated in §8 and were **not** applied.
