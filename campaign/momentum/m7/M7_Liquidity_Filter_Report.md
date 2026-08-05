# M7 — Institutional Liquidity Filter Implementation

**Aurelius Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-05
**Baseline:** M1+M2+M4 (net), M5 dual reporting, M6 audit binding.
**Type:** implement the ONE M6-approved universe improvement (liquidity screen from
close+volume only) + two-run experiment + KEEP/REJECT.
**Decision:** **REJECT** — feature left disabled (default OFF).
**Regression:** 596 passed, 2 skipped. Baseline reproduced byte-identical (Run A).

---

## 1. Implementation report

### Generic framework (not hard-coded)
`src/aurelius/research/liquidity.py` — a `name → (metric_fn, higher_is_more_liquid)`
registry, so the strategy screens on ANY approved metric:

| Metric | Direction | Notes |
|---|---|---|
| `dollar_volume_median` | higher = liquid | **default** |
| `dollar_volume_mean` | higher = liquid | spike-sensitive |
| `adv` | higher = liquid | ignores price level |
| `amihud` | higher = *illiquid* | divides by \$vol (fragile on 3% zero-vol bars) |

`screen(liq, pct, higher_is_more_liquid)` returns survivors after dropping the
bottom `pct` fraction by liquidity. Look-ahead-free (trailing-window metrics only).

### Default-metric selection (M6 criteria)
**Median dollar volume**, chosen on: *defensibility* (standard institutional
liquidity proxy, Amihud-2002 lineage — measures traded value directly);
*stability* (median robust to volume spikes); *availability* (needs only
close+volume; `vwap`/`trade_count` are 100% NULL per M6); *efficiency*
(O(W log W), no division that blows up on zero-volume bars). Documented in the
module docstring.

### Wiring (`FactorStrategy`)
Four new params, all defaulted OFF: `liquidity_filter=False`,
`liquidity_metric="dollar_volume_median"`, `liquidity_pct=0.0`,
`liquidity_window=21`. When enabled, the bottom `liquidity_pct` of the
cross-section is dropped BEFORE momentum ranking. **Relative** percentile cut (not
an absolute currency floor) because the panel mixes US(\$) and India(₹) ~80× apart
— an absolute threshold would delete one market.

### Baseline-unchanged guarantee
The entire screen is guarded by `if self.liquidity_filter and self.liquidity_pct
> 0`. Disabled → no volume fetch, no branch → **byte-identical** on_bar path to M4.
Locked by `test_liquidity_filter_disabled_is_identical_and_enabled_runs` (asserts
the equity curve equals the M4 baseline curve point-for-point). Proven empirically:
**Run A reproduces the committed M4 result to every digit** (§2).

### Mandatory principles — compliance
No look-ahead (trailing window, bars≤t) · no inferred market cap · no reconstructed
exchange · no synthetic survivorship · no parameter optimisation (pct=0.20,
window=21 are single pre-registered non-swept values) · no hidden strategy change ·
baseline identical when disabled. **All satisfied.**

---

## 2. Benchmark report — two runs only (net, US 2014–2026, OOS)

Run A = certified baseline (filter OFF). Run B = baseline + median-\$vol screen,
bottom quintile dropped. Nothing else differs.

| Metric | Run A (baseline) | Run B (+liquidity) | Δ |
|---|---|---|---|
| IS Sharpe | −0.1671 | −0.0321 | +0.135 |
| **OOS Sharpe** | +0.1124 | **+0.2767** | +0.164 (optically ↑) |
| **OOS Return** | −24.84% | **−95.85%** | **−71.0 pp (crater)** |
| **OOS Max DD** | −77.24% | **−115.87%** | **breaches 100% (blow-up)** |
| OOS Trades | 593 | 387 | −206 (−35%) |
| **Adjusted p** | 0.4134 | **0.2952** | −0.118 (optically ↑) |
| Verdict (engine) | reject | reject | same |

**Run A vs committed M4** (`us_jt_m4.jsonl`): identical to every digit
(−0.1671 / +0.1124 / −24.84% / −77.24% / 593 / 0.4134) — baseline unchanged,
deterministic.

### Metrics requested but not surfaced (honest skip, CLAUDE.md)
The directive lists CAGR, Sortino, Volatility, Turnover, Capacity, Average Position
Count, Bootstrap CI. **`ValidationReport` exposes only** verdict, is/oos Sharpe, oos
return, oos max DD, oos trades, adjusted p-value. The others are **not produced by
the frozen validation pipeline**. *Reason:* computing them requires extending
`PerformanceCalculator`/`ValidationReport` — an engine/statistics change explicitly
forbidden this campaign. *Unblock:* a future stats-surface phase adds them to the
report dataclass. Trade count (593→387) stands as the turnover proxy; the
adjusted p-value is the platform's resampling-based significance.

---

## 3. Statistical report

- **OOS Sharpe rose** (+0.112 → +0.277) and **adjusted p fell** (0.413 → 0.295) —
  both engine-REJECT still (nothing clears α=0.05; single-slice power limit, L7).
- **The ratio improvement is an artifact, not support.** OOS *return* collapsed to
  **−95.85%** and OOS *max drawdown* breached **−115.87%** — the book lost ~all
  capital and drew down past 100% (leveraged loss exceeding NAV). A Sharpe computed
  on a return path that terminates in near-total capital destruction is not a
  measure of a deployable edge; the ratio rose because the periodic-return
  volatility structure shifted, not because the strategy made money.
- No look-ahead: the screen uses only trailing-window close+volume; Run A's exact
  baseline reproduction confirms no leakage was introduced anywhere.

### Root cause of the blow-up (mechanism, not defect)
Dropping the bottom 20% by liquidity **shrinks the cross-section** `n`. The
equal-weight decile count is `_count = max(1, int(quantile · n))`, and per-name
strength is `0.75/_count` (L/S). Smaller `n` → smaller `_count` → **larger per-name
weight** → a more concentrated book. Under the frozen **1.5× gross-leverage cap** +
short leg, that concentration is exactly the Category-B fragility documented in
**L5 / M3 / Leverage_Investigation.md** — now *triggered by universe shrinkage*. The
liquidity screen did not add alpha; it thinned the book into a concentrated,
cap-truncated, blow-up-prone configuration. **0 platform defects** — the cap is a
deliberate risk control; the screen’s interaction with decile-size sizing is the
cause.

---

## 4. Decision log

**KEEP requires ALL of:** scientifically defensible · statistically supported · no
look-ahead · no regression failures · no degradation of research integrity.

| Gate | Result | Evidence |
|---|---|---|
| Scientifically defensible | ✅ | median \$vol, Amihud lineage, no look-ahead |
| No look-ahead | ✅ | trailing window; Run A exact baseline reproduction |
| No regression failures | ✅ | 596 passed, 2 skipped |
| **Statistically supported (economically)** | ❌ | OOS return −95.85%, DD −115.87% (blow-up) |
| **No degradation of research integrity** | ❌ | adopting a >100%-DD capital-destroying config would misrepresent a Sharpe/p artifact as improvement |

Two gates fail → **REJECT.** The feature remains **default OFF**; the certified
baseline stays **M1+M2+M4** unchanged. The generic framework is **retained in code
(disabled)** — it is correct and reusable; only its *interaction with the current
decile-size sizing + leverage cap* makes it unsafe to enable here.

### Why REJECT despite the higher Sharpe
The decision rule is conjunctive by design: a liquidity screen that lifts the
risk-adjusted *ratio* while destroying the *book* (−96% return, −116% DD) is the
textbook trap the rule guards against. Sharpe/p are necessary, not sufficient;
economic viability and integrity gates dominate.

---

## 5. Known limitations / Skipped (CLAUDE.md)

- **CAGR / Sortino / Volatility / Capacity / Avg Position Count / Bootstrap CI** —
  not computed. *Reason:* not exposed by the frozen `ValidationReport`; producing
  them needs a `PerformanceCalculator`/stats change forbidden this campaign.
  *Unblock:* a stats-surface phase extends the report dataclass.
- **Liquidity screen viability under fixed-N sizing** — not tested. *Reason:* the
  engine sizes on decile count (NAV-%), so any universe shrinkage concentrates the
  book (§3); a fair test of the screen needs **dollar-hold / fixed-N sizing** — the
  same unblock as M3 (engine unfreeze). *Unblock:* dollar-hold position mode, then
  re-run M7. Until then the screen is correctly REJECTED for this engine.
- **Threshold not swept** — deliberately. pct=0.20/window=21 are single
  pre-registered values; sweeping would be the forbidden optimisation. A single
  clean REJECT is the honest result, not a search for a pct that survives.

---

## 6. Certification

| Condition | Status |
|---|---|
| Generic liquidity framework implemented | ✅ (`liquidity.py`, 4 metrics) |
| Default OFF | ✅ (`liquidity_filter=False`) |
| Baseline unchanged | ✅ (Run A = M4 byte-identical) |
| Regression tests pass | ✅ (596 passed, 2 skipped) |
| Statistical validation completed | ✅ (§3, two runs) |
| Decision supported by evidence | ✅ **REJECT** (§4) |

**M7 CERTIFIED — REJECT.** Liquidity framework shipped and disabled; certified
baseline remains M1+M2+M4. STOP — M8 not begun.
