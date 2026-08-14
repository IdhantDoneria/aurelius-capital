# MENTISREX M27 — Forward Evidence Accumulation & Benchmark Comparison

**Status:** IMPLEMENTED · TESTED · REAL-DATA VERIFIED (August 2026)  
**Date:** 2026-08-14  
**Milestone:** M27  
**Depends on:** M25 (forward campaign), M26 (forward operations runner)

---

## 1. M27 Objective

M27 converts the forward paper-trading infrastructure (M25/M26) into an
**evidence-generation system**.  It does NOT optimize the strategy, add new
strategies, or deploy real capital.

M27 adds:
- SPY benchmark portfolio tracking (passive, buy-and-hold)
- Benchmark accounting isolated from strategy accounting
- Per-cycle benchmark records (sealed, immutable)
- Forward evidence report (strategy vs benchmark vs backtest)
- Backtest comparison framework (M9/SIM artifact)
- Multi-cycle accumulation tests (Aug → Sep → Oct → Nov fixtures)
- Statistical discipline: explicit INSUFFICIENT_SAMPLE labeling

---

## 2. Forward Campaign Continuation

The existing M25/M26 campaign is continued unchanged.

Campaign directory:
```
data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813/
```

August 2026 cycle remains sealed and immutable:
```
cycles/ew-momentum-exp__2026_08.json
```

The September 2026 cycle (`ew-momentum-exp__2026_09`) will be generated
automatically when the monthly cron runs in September 2026.  **DO NOT
fabricate September.**  The infrastructure is tested with fixtures.

---

## 3. September Cycle Status

| Item | Status |
|---|---|
| September infrastructure | IMPLEMENTED |
| September fixture tests | TESTED |
| September genuine forward observation | PENDING — date not yet reached |

**Why September is pending:** Today is 2026-08-14.  The genuine September
cycle requires real market data from September 2026.  Running the cron
on any date in September 2026 will produce a genuine `ew-momentum-exp__2026_09`
record with real Yahoo Finance prices.

**To run September when available:**
```bash
python scripts/forward_run/run_forward.py forward_auto --as-of 2026-09-10
python scripts/forward_run/run_forward.py forward_benchmark --as-of 2026-09-10
python scripts/forward_run/run_forward.py forward_evidence_report
```

---

## 4. Benchmark Methodology

**Benchmark:** SPY (SPDR S&P 500 ETF Trust)  
**Type:** Passive buy-and-hold  
**Initial NAV:** $1,000,000 (same as strategy)  
**Inception date:** 2026-08-13 (same as first strategy cycle)  
**Inception price:** $777.88 (real Yahoo Finance close, 2026-08-13)

**Return type:** PRICE RETURN ONLY.  Dividends are NOT captured.

**Rationale for SPY:** The strategy benchmark field in `spec.py` is `"SPY"`.
SPY is the most liquid, most widely tracked S&P 500 ETF.  It provides a
standard risk-adjusted comparison for US equity strategies.

**Why price return (not total return):**  
Yahoo Finance's `adj_close` prices are retroactively adjusted for dividends
and stock splits.  Using `adj_close` would allow a provider revision to
silently mutate a sealed forward record.  Raw `Close` prices are used
instead; the dividend limitation is explicitly documented in every
`BenchmarkCycleRecord.data_limitation` field.

---

## 5. Benchmark Accounting

Per-cycle accounting invariant:

```
cash + shares * spy_price == ending_nav   (within floating-point tolerance)
```

At inception (first cycle):
```
shares         = inception_nav / inception_price
cash           = inception_nav - shares * inception_price  (fractional residual)
ending_nav     = shares * spy_price + cash
period_return  = 0.0   (buy date; no prior price)
```

At each subsequent cycle:
```
shares         = prior.shares   (buy-and-hold; never rebalanced)
cash           = prior.cash
ending_nav     = shares * spy_price + cash
period_return  = (spy_price - spy_price_prior) / spy_price_prior
cumulative_return = (ending_nav - inception_nav) / inception_nav
```

**August 2026 benchmark record:**
```json
{
  "cycle_id":         "ew-momentum-exp__2026_08",
  "benchmark_symbol": "SPY",
  "knowledge_as_of":  "2026-08-13",
  "spy_price":        777.88,
  "shares":           1285.5453,
  "inception_nav":    1000000.0,
  "ending_nav":       1000000.0,
  "period_return":    0.0,
  "is_inception_cycle": true,
  "sealed_at":        "2026-08-14T04:20:07.353893"
}
```

---

## 6. Forward vs Benchmark Methodology

Per-cycle comparison fields:
```python
@dataclass
class CycleComparison:
    cycle_id: str
    evaluation_date: date
    strategy_return: float          # strategy gross_return for the cycle
    benchmark_return: float         # SPY price return for the cycle
    excess_return: float            # strategy_return - benchmark_return
    strategy_nav: float
    benchmark_nav: float
    strategy_cumulative_return: float
    benchmark_cumulative_return: float
    cumulative_excess_return: float  # strategy_cum - benchmark_cum
```

**Relative drawdown:** Not separately computed at n=1.  Will be computed
when n >= 2 cycles are available.

---

## 7. Forward vs Backtest Methodology

**M9/SIM backtest artifact:**
```
manifest_hash: 696a411bed6731a997c399584bfa9c4f
experiment_id: SIM
overall_verdict: PASS
confidence_score: 88.1
n_observations: 729 daily (~3 years)
sharpe_annualized: 2.120
annualized_return: 10.69%
annualized_volatility: 5.04%
p_value: 0.000332
annual_turnover: 0.467
```

**Comparison validity by observation count:**

| Forward obs | Comparison validity |
|---|---|
| < 12 | INSUFFICIENT_SAMPLE |
| 12–23 | PRELIMINARY |
| 24+ | STRONGER_EVIDENCE_BASE |

**Backtest data must NOT be recalibrated using forward results.**  The
`BacktestSnapshot` dataclass is frozen and loaded from the sealed validation
artifact at `data/validation/SIM/validation_report.json`.

---

## 8. Statistical Limitations

**CRITICAL:**  With n=1 forward observation (August 2026), no performance
inference is valid.

```
n=1 monthly forward observations are insufficient to establish economic validity.
```

Evidence milestones (not guarantees of statistical validity):

| Cycles | Evidence stage |
|---|---|
| 1 | OPERATIONAL_EVIDENCE_ONLY — system confirmed operational |
| 2–3 | EARLY_DIAGNOSTIC_ONLY — insufficient for performance inference |
| 6 | PRELIMINARY_DIAGNOSTIC — preliminary forward-performance diagnostic |
| 12 | FIRST_ANNUAL_COMPARISON — first serious forward-vs-backtest comparison |
| 24+ | STRONGER_EVIDENCE_BASE — substantially stronger evidence base |

Even at 24+ cycles, forward evidence does NOT guarantee future performance.

---

## 9. Data Provenance

**Strategy data:** Yahoo Finance via yfinance (universe: AAPL, MSFT, GOOGL, AMZN,
META, NVDA, TSLA, JPM, JNJ, V).

**Benchmark data:** Yahoo Finance via yfinance (SPY raw Close, not Adj Close).

**Known Yahoo limitation:**
- Free/public, not institutional/exchange-grade.
- Retroactive adjustments possible (but sealed records are immutable).
- Dividend treatment: NOT represented in benchmark.

**Immutability guarantee:** Once a cycle record is sealed (written to
`cycles/*.json` or `benchmark/*.json`), it is never overwritten, even if
Yahoo later revises the price.

---

## 10. PIT Handling

Point-in-time (PIT) constraint:

- Strategy prices: enforced by `LiveFeedBuilder` (prices <= as_of only).
- Benchmark prices: raw Yahoo Close for the as_of date or the most recent
  prior trading day.  Future prices are never used.
- Sealed `knowledge_as_of` field records the PIT boundary for every record.

---

## 11. Research-Data Isolation

Forward observations are **NOT** automatically fed into:
- Backtest datasets
- Strategy optimization
- Parameter fitting
- Model training
- Hypothesis generation

The forward campaign directory (`data/forward_campaign/`) is separate from
the research pipeline.  Importing forward observations into research requires
an explicit, documented action after the evaluation period is considered closed.

`EvidenceReportBuilder.build()` and all ledger classes are read-only with
respect to forward records — they never modify sealed files.

---

## 12. Evidence Accumulation Plan

| Target date | Milestone |
|---|---|
| 2026-08-13 ✅ | Cycle 1 (genuine) — August 2026 |
| 2026-09-~10 | Cycle 2 (pending) — September 2026 |
| 2026-10-~08 | Cycle 3 (pending) — October 2026 |
| 2026-11-~05 | Cycle 4 (pending) — November 2026 |
| 2027-02 | 6 cycles: preliminary diagnostic |
| 2027-08 | 12 cycles: first annual comparison |
| 2028-08 | 24 cycles: stronger evidence base |

---

## 13. Evidence Interpretation Rules

1. Return in month T is the strategy NAV change from T−1 to T.  Month 1 (August)
   has return=0 because the portfolio was just initiated at current prices.

2. Benchmark return in month T is SPY price change from T−1 to T.  Month 1 has
   benchmark_return=0 for the same reason.

3. Excess return = strategy_return − benchmark_return.  A single positive
   excess return does not constitute evidence of alpha.

4. Any metric labeled `INSUFFICIENT_SAMPLE` must not be reported as a
   performance conclusion.

5. Forward observations that are replayed from fixtures (for testing) must be
   clearly distinguished from genuine forward observations in all reports.

---

## 14. Known Limitations

| Item | Status | Unblock |
|---|---|---|
| SPY dividends not captured | DOCUMENTED LIMITATION | Add total-return provider (institutional data) |
| September genuine observation | PENDING | Date not yet reached (2026-09) |
| Sharpe comparison | INSUFFICIENT_SAMPLE | Need ≥ 24 monthly cycles |
| Annual return comparison | INSUFFICIENT_SAMPLE | Need ≥ 12 monthly cycles |
| Relative drawdown | NOT COMPUTED at n=1 | Available at n ≥ 2 |
| Adj close avoided | DOCUMENTED — protects sealed records | Acceptable until institutional provider added |

---

## 15. Remaining Blockers for M28

1. September 2026 genuine forward observation (blocked by calendar).
2. Institutional data source to capture SPY total return with dividends.
3. Extended forward observation period (minimum 6 cycles for first diagnostic).

---

## Files Added / Changed

### New files (M27)

| File | Purpose |
|---|---|
| `src/mentisrex/research/forward_campaign/benchmark.py` | BenchmarkCycleRecord, BenchmarkLedger, BenchmarkPortfolio, fetch_spy_price |
| `src/mentisrex/research/forward_campaign/evidence_report.py` | BacktestSnapshot, CycleComparison, ForwardEvidenceReport, EvidenceReportBuilder |
| `tests/research/test_m27_benchmark.py` | 76 M27 tests (17 categories) |
| `docs/MENTISREX_M27_FORWARD_EVIDENCE.md` | This document |

### Modified files (M27)

| File | Change |
|---|---|
| `src/mentisrex/research/forward_campaign/__init__.py` | Export M27 classes |
| `scripts/forward_run/run_forward.py` | Add `forward_benchmark`, `forward_evidence_report` subcommands |

### Data files created (real-data)

| File | Contents |
|---|---|
| `data/forward_campaign/.../benchmark/ew-momentum-exp__2026_08.json` | August 2026 SPY benchmark record (SPY=$777.88, genuine) |
| `data/forward_campaign/.../forward_evidence_report.json` | August 2026 evidence report JSON |

---

## 16. Classification

| Item | Status |
|---|---|
| Benchmark implemented | IMPLEMENTED |
| Benchmark isolated from strategy | TESTED |
| Benchmark accounting reconciles | TESTED (76 tests pass) |
| Excess return calculation | TESTED |
| Forward ledger extended | IMPLEMENTED |
| Forward vs backtest comparison | IMPLEMENTED |
| Insufficient-sample rules enforced | TESTED |
| Research-data isolation | TESTED |
| PIT constraints preserved | TESTED |
| Provider revision semantics | TESTED |
| Multi-cycle tests pass | TESTED (Aug → Nov fixture) |
| M25 tests pass | PASS (2606 total, 3 pre-existing skips) |
| M26 tests pass | PASS (included in full suite) |
| Full repository suite | PASS (2606 passed, 3 skipped, 0 regressions) |
| Real-data verification | REAL-DATA VERIFIED (August 2026, SPY=$777.88) |
| Strategy fingerprint unchanged | VERIFIED (b69961b65bab226a500d71f45709945b) |
| September genuine observation | PENDING — date not yet reached |
| September infrastructure | IMPLEMENTED + TESTED |
| Documentation | COMPLETE |

---

## 17. Governance

```
REAL MARKET DATA:             YES (Yahoo Finance, SPY price confirmed $777.88 on 2026-08-13)
GENUINE FORWARD OBSERVATION:  YES (August 2026 cycle 1)
PAPER EXECUTION:              YES
LIVE EXECUTION:               NO
REAL CAPITAL:                 NO
STRATEGY MODIFIED:            NO (fingerprint b69961b65bab226a500d71f45709945b unchanged)
RESEARCH DATA ISOLATED:       YES
```

**n=1 monthly forward observations are insufficient to establish economic validity.**

The August cycle confirms the system is operational.  Economic conclusions
require extended forward observation (minimum 12 cycles for first annual
comparison, 24+ for a substantially stronger evidence base).
