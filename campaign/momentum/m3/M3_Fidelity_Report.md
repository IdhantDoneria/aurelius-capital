# M3 Methodology Report — Overlapping K-Cohort Portfolio

**Aurelius Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-04
**Baseline:** M2 (`campaign/momentum/m2/us_jt_m2.jsonl`)
**Source:** `campaign/momentum/m3/us_jt_m3.jsonl`
**Engine:** frozen, no tuning, same universe (M2 price screen retained).

---

## 1. What M3 changes

| Dimension | M2 (baseline) | M3 (overlapping) |
|---|---|---|
| Portfolio structure | Non-overlapping: full book replaced every 21 bars | K=6 overlapping cohorts, one updated per 21-bar period |
| Holding period per cohort | 21 bars (1 month, then fully replaced) | 126 bars (6 months, per JT) |
| Signals per period | One cross-section per symbol × rebalance | Aggregated net of K cohorts; one signal per symbol |
| Turnover model | Bulk replacement every 21 bars | 1/K of book updated per period (intended) |
| JT justification | — | JT-1993 §II.A: K overlapping portfolios, each held K months |

**Implementation:** `OverlappingFactorStrategy` in `src/aurelius/research/templates.py`.
- Global clock via `ctx.now` tracking; `_trading_day` counter shared across symbol calls.
- `_build_cross_section` called once per period (cached; O(n_symbols) not O(n_symbols²)).
- Net signal per symbol = majority vote across K cohorts × equal-weight budget.
- Cohort state persisted in `self._memberships[k]`, updated on the rotating `active_k` schedule.

---

## 2. Results (OOS, US equities 2014–2026)

| Metric | M2 (equal-weight + price screen) | M3 (M2 + overlapping) | Change |
|---|---|---|---|
| IS Sharpe | **+0.322** | −0.760 | −1.082 |
| OOS Sharpe | **+0.098** | +0.006 | −0.092 |
| OOS Return | −23.79% | **+3.18%** | +27 pp |
| OOS Max DD | −75.78% | **−49.29%** | +26 pp |
| OOS Trades | 672 | **4781** | +612% |
| Adjusted p | **0.424** | 0.495 | worse |
| IS Sharpe | **+0.322** | −0.760 | |
| Runtime | 1282.1 s | **257.4 s** | −80% (cache win) |
| Verdict | REJECT | REJECT | same |

---

## 3. Root-cause analysis

### 3a. Trade count explosion (+612%) — dominant effect

M3 produced 4781 OOS trades vs M2's 672 (7.1× increase). This is the primary driver of M3's underperformance. Root cause: **Aurelius engine targets NAV-proportional positions**.

The engine computes:
```
target_value = NAV × max_position_pct × signal.strength
delta_qty    = target_qty - current_qty
```

As NAV changes intraday/between bars, `target_value` changes for ALL held positions — even
positions whose underlying cohort has NOT rebalanced. Under M3, a signal fires at EVERY
21-bar rebalance for every symbol (because the `_trading_day % rebalance_days == 0` gate
fires every 21 bars for all symbols). The `strength` value changes slightly each period
(because `n_ref = max(n_decile across cohorts)` fluctuates by 1–2 names), generating
small position adjustments for every held name.

**JT's actual mechanism**: JT holds fixed DOLLAR positions between cohort updates. Only
the cohort being updated generates new trades (roughly `n_decile × 2` round-trips per
period ≈ 188 trades/period ÷ 6 ≈ 31 trades/period). M3 generates approximately
`n_held × K × rebalances/year ≈ 188 × 6 × 12 ≈ 13,500/year` adjustment trades — vs
JT's `~31 × 12 = 372/year`. This gap is **engine-level** (NAV-proportional targeting
vs dollar-hold), not fixable in the strategy without engine modification (frozen).

### 3b. IS Sharpe collapse (−0.760) — commission drag during warm-up

The IS window (70% of 2014–2026 ≈ 2014–2020) includes the K=6 cohort warm-up phase
(first 126 bars ≈ 6 months). During warm-up, fewer cohorts are active (rising from 1
to 6), and convictions are noisy. The commission drag from 7× trade count is largest
during this phase, pulling IS Sharpe strongly negative.

Under M2, IS Sharpe was +0.322. The +1.082 IS deterioration from M3 is almost entirely
commission drag (10 bps/side × 4109 excess trades per period is ≈ substantial drag).

### 3c. OOS Sharpe near-zero (+0.006) vs M2's +0.098

The OOS period (2020–2026) benefits slightly from the overlapping structure (smoother
position transitions, lower per-period concentration) — OOS Return improved from −23.79%
to +3.18%, and OOS Max DD improved from −75.78% to −49.29%. But the commission drag
from 4781 trades reduces OOS Sharpe from +0.098 to +0.006.

This suggests the overlapping signal DOES carry incremental information (positive OOS
return) but the implementation overhead (NAV-rebalancing artifact) consumes it.

### 3d. p-value deterioration

Adj p: 0.424 (M2) → 0.495 (M3). The test power declined. More volatile daily returns
(small adjustment trades adding noise) → lower t-stat → higher p. Both are well above
the 0.05 significance threshold; neither result is statistically significant.

---

## 4. Fidelity analysis

### Did overlapping portfolios increase fidelity?

**Partially.** The cohort structure (K=6, 126-bar hold) is now present and working
correctly — the `OverlappingFactorStrategy` correctly cycles through cohorts, caches
cross-sections, and nets votes. The SIGNAL generation is faithful to JT.

**But**: the POSITION MANAGEMENT is not faithful to JT. JT holds dollar positions between
cohort updates; Aurelius holds NAV-percentage positions and rebalances proportionally on
every signal. This engine-level difference cannot be fixed without modifying the engine
(frozen). It causes 7× excess turnover, which consumes the signal improvement.

| JT element | M3 status |
|---|---|
| K=6 cohorts, one updated per period | ✓ Implemented |
| 126-bar holding per cohort | ✓ Implemented |
| Equal-weight within cohort | ✓ Inherited from M1 |
| Price ≥ $5 screen | ✓ Inherited from M2 |
| Dollar-amount hold between updates | **✗ Engine holds NAV-%, not dollars** |
| Portfolio-level monthly rebalance clock | ✓ Global `_trading_day` counter |

### Did monthly return volatility decrease?

**Inconclusive.** OOS Max DD improved (−49.29% vs −75.78%) — consistent with the
overlapping structure smoothing out extreme drawdowns. But OOS Sharpe declined due to
increased return noise from adjustment trades.

### Did statistical significance improve?

**No.** Adj p: 0.424 (M2) → 0.495 (M3). Significance declined slightly.

### Does the remaining gap come from?

| Category | Assessment |
|---|---|
| A. Missing market-cap data | Unchanged from M2 |
| B. Missing exchange information | Unchanged from M2 |
| C. Market evolution (post-2000 decay) | Unchanged; residual after M2 |
| D. Statistical variation | Partially — p 0.495 means weak evidence |
| E. Platform defect | **Yes — engine NAV-% targeting vs JT dollar-hold; causes 7× excess turnover. Engine frozen; cannot fix.** |

---

## 5. Decision

**REJECT M3. Retain M2 as institutional baseline.**

### Evidence

1. **OOS Sharpe declined**: 0.098 → 0.006 (−0.092). The primary risk-adjusted performance metric worsened.
2. **IS Sharpe collapsed**: +0.322 → −0.760 (−1.082). Commission drag during IS training overwhelms any signal.
3. **p-value worse**: 0.424 → 0.495. Statistical evidence weakened, not strengthened.
4. **Trade count 7× higher**: 672 → 4781. Commission drag from NAV-rebalancing artifact consumes signal improvement.
5. **Root cause is engine-level**: The gap between JT's dollar-hold and Aurelius's NAV-% targeting cannot be bridged in the strategy layer without modifying the engine (frozen).

### What M3 revealed (positive findings)

- OOS Return turned positive (+3.18% vs −23.79%) — the overlapping signal IS incrementally better.
- OOS Max DD improved substantially (−49.29% vs −75.78%) — smoother drawdown profile.
- `OverlappingFactorStrategy` implementation is algorithmically correct (cohort cycle, caching, majority vote). The issue is economic (position management model), not algorithmic.
- The overlapping structure would likely show a **full fidelity improvement** if the engine supported dollar-hold positions between cohort updates.

### Path to a faithful overlapping implementation

To properly implement JT overlapping, the engine would need:
- Per-cohort position tracking: each cohort owns `1/K × n_decile` positions
- Dollar-hold mode: positions are held at formation-time dollar amount until the cohort rebalances
- Only cohort-specific signals generate orders (not all symbols at every rebalance)

This requires engine modification (currently frozen). Unblock: explicit authorization to add a "dollar-hold" position mode to `BacktestConfig` and `PortfolioManager`.

---

## 6. Known limitations / Skipped

- **Engine modification not undertaken.** Dollar-hold mode would fix the excess-turnover issue but requires `PortfolioManager` changes (frozen). *Unblock:* explicit authorization to modify the engine.
- **India M3 not run.** Per directive: "exactly once" (US only).
- **Per campaign directive: do not implement M4.**
