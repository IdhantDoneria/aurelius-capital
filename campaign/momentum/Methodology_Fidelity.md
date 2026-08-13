# Momentum Methodology Fidelity

**Mentisrex Capital — Momentum Research Campaign**
**Agent:** Literature Intelligence + Methodology Fidelity
**Date:** 2026-07-31
**Companion to:** `Literature_Map.md`

Cross-compares the canonical momentum papers against each other, then against
what Mentisrex's `FactorStrategy` (`src/mentisrex/research/templates.py:164`) plus
`scripts/run_jt_us_reproduction.py` actually implement. Read-only audit — nothing
is implemented here; gaps are *identified* only.

---

## 1. What Mentisrex actually does (ground truth from code)

`FactorStrategy` (cross-sectional momentum):
- **Signal:** per-symbol trailing simple return `(close[t] − close[t−lookback]) / close[t−lookback]`.
- **Cross-section:** built from `ctx.history` (bars ≤ t) over `ctx.symbols_with_data` — leak-safe.
- **Selection:** rank scores; `quantile` fraction each tail. `val >= hi` → LONG top quantile; `val <= lo` → SHORT bottom quantile (if `allow_short`); else FLAT.
- **Rebalance gate:** acts only when `len(ctx.history(symbol)) % rebalance_days == 0` — a **per-symbol modulo counter**, not a portfolio-level calendar.
- **Output:** a discrete `LONG/SHORT/FLAT` `SignalEvent` per symbol. Position sizing / weighting is downstream in the engine, not in the signal — effectively **equal binary exposure per selected name**, no rank- or vol-weighting, no decile structure, no overlapping cohorts.
- **Costs (engine, `backtesting/config.py`):** commission 10 bps/side, slippage 10 bps at 100% ADV. Applied → reported Sharpe is **net**.

JT reproduction params (`run_jt_us_reproduction.py:67`):
`lookback=126, quantile=0.1, rebalance_days=21, allow_short=True`, US-only universe
(symbols without a `.` suffix), IS/OOS 70/30 chronological split.
So: 126-bar (~6mo) formation, 10% tails, ~21-bar (~monthly) rebalance, long-short. **No skip period.**

---

## 2. Cross-paper comparison

| Dimension | JT-1993 | JT-2001 | Carhart-1997 (PR1YR) | MOP-2012 TSMOM | AMP-2013 | **Mentisrex FactorStrategy** |
|---|---|---|---|---|---|---|
| Universe screen | NYSE+AMEX | +Nasdaq; drop <$5 & tiny | US stocks | 58 futures | intl equities+assets | US or India equity; `validated_universe_filter` (history only) — **no price/size screen** |
| Formation | 3–12 mo (focus 6) | 6 mo | 11 mo | 12 mo | 12 mo | 126 bars ≈ 6 mo |
| Skip period | 0 or 1 week | 1 month | **1 month** | 0 | **1 month (12-1)** | **0 (none)** |
| Holding | 3–12 mo (focus 6) | 6 mo | 1 mo | 1 mo | 1 mo | implicit via 21-bar rebalance |
| Portfolio overlap | **overlapping cohorts** (1/K rolled) | overlapping | single monthly | single monthly | single monthly | **non-overlapping**, per-symbol modulo |
| Breadth | deciles (top/bottom 10%) | deciles | **30/30 tails** | binary sign | rank-weighted | `quantile` tails (0.1 in repro) |
| Weighting | equal-weight | equal-weight | equal-weight | **inverse-vol** | **rank-weighted** | equal binary per name |
| Gross vs net | gross | gross | gross factor | gross (net robustness) | gross | **net** (engine costs) |
| Cost treatment | discussed | discussed | fund expenses | capacity noted | later work | 10 bps comm/side + 10 bps slip |
| Liquidity treatment | (implicit CRSP) | <$5 + size screen | none | liquid futures | liquidity factor | **none** |
| Rebalance freq | monthly | monthly | monthly | monthly | monthly | ~21 bars, per-symbol counter |
| Sample construction | CRSP, survivor-aware | survivor-aware | **survivor-free** | futures | intl | **survivor-prone** 2014-26 |
| Benchmark | zero-cost W−L, risk-adj | same + reversal | 4-factor α | vol-scaled, factor span | global 3-factor | IS/OOS Sharpe, adj p-value |

**Prose.** The canonical family agrees on a tight recipe: intermediate formation
(6–12 mo), a **1-period skip** to dodge short-term reversal/microstructure, monthly
rebalance, and **overlapping cohorts** for statistical power. They diverge mainly on
*weighting* (JT decile-EW → Carhart 30/30-EW → AMP rank-weight → MOP inverse-vol) and
*universe* (single-country equity → global multi-asset). Mentisrex matches the formation
horizon and long-short spirit but departs on three structural axes: **no skip**, **no
overlapping cohorts**, and **binary equal exposure** instead of decile/rank/vol weighting.
The per-symbol modulo rebalance gate is also subtly different from a portfolio calendar —
symbols entering the panel at different times rebalance on staggered clocks.

---

## 3. Prioritized fidelity roadmap

Ranked by likely impact on results. Each: papers / Mentisrex / impact / code-or-config.

### P1 — Missing skip period *(HIGH impact)*
- **Papers:** JT-2001, Carhart, AMP all skip 1 month (JT-1993 offers a 1-week variant that *raised* returns 1.31→1.49%/mo).
- **Mentisrex:** skip = 0. Formation window ends at the same bar the position is taken.
- **Impact:** overstates short-horizon reversal/microstructure contamination — inflates or destabilizes the signal, exactly the effect the skip exists to remove. Directionally biases the reproduction away from JT's clean estimate.
- **Fix:** **Code.** `FactorStrategy` scores `c[-1]` vs `c[0]`; needs a `skip` param so the score window ends `skip` bars before *t* (`c[-1-skip]`). Small, localized change.

### P2 — Non-overlapping vs overlapping portfolios *(HIGH impact on inference)*
- **Papers:** overlapping cohorts (hold K vintages, roll 1/K per month) — central to JT's statistical power.
- **Mentisrex:** single position per symbol, refreshed on the modulo gate; no cohort layering.
- **Impact:** fewer effective observations → wider CIs, noisier Sharpe/t-stats; also changes turnover profile. Doesn't bias the *mean* much but weakens significance — matters for the adj p-value verdict.
- **Fix:** **Code.** Overlapping cohorts are a portfolio-construction change (engine/runner), not a one-line signal tweak. Larger.

### P3 — Weighting scheme *(MEDIUM-HIGH)*
- **Papers:** decile-EW (JT), 30/30-EW (Carhart), rank-weight (AMP), inverse-vol (MOP/Daniel-Moskowitz for crash control).
- **Mentisrex:** binary equal exposure per selected name (sizing left to engine).
- **Impact:** binary top/bottom-quantile EW is a fair match to JT decile-EW **if** quantile≈0.1 (it is, in the repro) — so low fidelity gap vs JT specifically. Gap is large only vs AMP (rank) / MOP (vol) styles, and vol-weighting materially changes crash exposure.
- **Fix:** **Config** to match JT (already ~decile via `quantile=0.1`). **Code** to add rank- or vol-weighting for AMP/MOP fidelity.

### P4 — Liquidity / price / size screens *(MEDIUM)*
- **Papers:** JT-2001 drops <$5 and smallest-cap; standard hygiene against microstructure-driven pseudo-alpha.
- **Mentisrex:** only a history-adequacy filter; penny stocks and illiquid India names can dominate the tails.
- **Impact:** unscreened tails likely **inflate** raw momentum via illiquid names that are untradeable net of real cost — optimistic bias.
- **Fix:** **Config-ish → Code.** Price (<$5) screen is easy (close available). Size screen **BLOCKED: no market cap**. A volume/turnover screen is a code addition using available volume.

### P5 — Survivorship *(MEDIUM, structural)*
- **Papers:** Carhart insists on survivor-free samples.
- **Mentisrex:** 2014-26 panel = currently-listed names, no delisting returns.
- **Impact:** upward bias in momentum profits (dead losers pruned). Systematic, not fixable in-strategy.
- **Fix:** **Neither code nor config** — a **data** gap. Needs point-in-time membership + delisting returns. Flag on every result until then.

### P6 — Rebalance-clock semantics *(LOW-MEDIUM)*
- **Papers:** single portfolio-level monthly calendar.
- **Mentisrex:** per-symbol `len(history) % rebalance_days` — symbols with different start dates rebalance on staggered clocks; cross-section isn't refreshed synchronously.
- **Impact:** minor timing smear in the cross-section; usually second-order, but can desync the long/short legs.
- **Fix:** **Code.** Switch the gate to a shared calendar (bar-date modulo) rather than per-symbol history length.

### P7 — Gross vs net reporting parity *(LOW)*
- **Papers:** headline gross.
- **Mentisrex:** net (10+10 bps). Actually *stricter* than the papers.
- **Impact:** Mentisrex numbers will sit **below** published gross figures — a reporting-comparability issue, not an error. When comparing to JT's 1.31%/mo, compare gross-to-gross.
- **Fix:** **Config.** Optionally report a gross variant (zero-cost engine config) alongside net for apples-to-apples literature comparison.

**Not applicable to cross-sectional fidelity** (would be new strategies, not fidelity fixes):
inverse-vol TSMOM sizing, residualization, industry grouping, value leg — all **data-blocked** (see Literature_Map §5).

---

## 4. Known limitations / data-blocked

1. **Size-based screens (P4) & survivorship (P5).** Why: no market-cap/fundamentals and no delisting returns in the 2014-26 panel. Unblock: ingest fundamentals + point-in-time membership with delisting returns.
2. **Full weighting fidelity to AMP/MOP (P3).** Rank-weighting is pure code, but inverse-vol *TSMOM* fidelity is a different strategy needing multi-asset data — out of cross-sectional scope.
3. **Overlapping-portfolio construction (P2).** Not blocked by data — blocked by engineering scope; flagged as code, not done here (identify-only mandate).
4. **This document changes no code.** Every gap above is *identified*; per the task, nothing is implemented. Closing P1/P2/P6 requires touching `FactorStrategy` / runner; P3/P4-price/P7 are largely config or small code; P5 is a data acquisition, not a code change.
