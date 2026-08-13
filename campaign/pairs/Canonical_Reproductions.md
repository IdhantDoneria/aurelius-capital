# Canonical Reproductions — Pairs Trading Campaign

**Mentisrex Capital — Workstream B**
**Date:** 2026-08-04
**Source:** every figure traces to `campaign/pairs/runs/{us,india}.jsonl`. Frozen
platform, no tuning, one OOS split per config.

## 1. Gatev, Goetzmann & Rouwenhorst (2006) — canonical

**Construction (faithful):** 12-month (252d) formation → normalize prices, rank
pairs by sum-of-squared-deviation, take top-20; trade the whole sample as one
diversified book (`MultiPairStrategy`), 2-SD entry / 0.5-SD exit, 126d spread
window; IS/OOS 70/30 chronological split. Selection screened to the 300 most-liquid
complete-history names per market (Gatev-consistent liquidity filter).

| Metric | Gatev (published, top-20) | Mentisrex US | Mentisrex India |
|---|---|---|---|
| Excess return | **≈ +11%/yr**, low beta | −5.74% (OOS, ~3.8y) | +8.72% (OOS) |
| Sharpe | high | **−1.076** | **−0.425** |
| Max drawdown | small (market-neutral) | −12.48% | −7.43% |
| OOS trades | thousands (pair-months) | **3999** | **3303** |
| Adjusted p | significant | **1.000** | **1.000** |
| Verdict | pairs profit confirmed | **REJECT** | **REJECT** |

**Outcome: FAILED to reproduce the published premium in both markets — but for a
different reason than the 2026-07-30 toy run.** That run failed on *data scale*
(1 pair, 22 trades, 12 names). This run has **genuine power** (3000+ OOS trades, a
real 20-pair book on 300 liquid names) and *still* rejects. The null here is
economic, not a sample artifact.

## 2. Why it rejects (classification per stopping rules)

1. **Market evolution — dominant. Class D.** Do & Faff (2010, 2012) predict exactly
   this: Gatev's raw profits decay toward transaction costs after ~2002 and are
   often insignificant on modern samples. 2014–2026 is two decades past Gatev's
   1962–2002 window; the distance-pairs edge has been arbitraged away. The
   market-neutral book behaves as designed (low drawdown, −7% to −12%) but earns
   no risk-adjusted premium.
2. **Sizing / leverage truncation — Class B (P5/M3).** Fixed 5%/leg × 20 pairs × 2
   legs = 200% nominal gross vs the 1.5× cap → the risk engine truncates the book,
   and truncated fills break dollar-neutrality → residual directional risk. This
   *depresses* the result uniformly; it is a fidelity gap, not a defect. Worst at
   top40 (§ Robustness). Cross-ref `../momentum/Leverage_Investigation.md`.
3. **Raw-price vs normalized/cointegration spread — Class B (P1).** The template
   z-scores the scale-balanced raw spread, not Gatev's normalized-cumulative spread
   nor a cointegrating residual. Approximation adds entry/exit timing drift.
4. **Static vs rolling monthly re-formation — Class B (P3).** Pairs picked once on
   2014–2015 and held ~11 years; Gatev re-forms every month. Pair decay makes this
   a pessimistic bound (biases against reproduction).
5. **Regime / crowding — Class D.** Khandani-Lo (2007): mean-reversion books are
   crowded and periodically deleverage. A single OOS slice can only see one draw.

**Fidelity finding:** construction is **faithful** (Gatev SSD selection + 2-SD
divergence trading + top-N portfolio, leak-safe formation/trading split). Failure
is **market evolution + sizing fidelity**, not a platform-logic defect. **0 Class-A
defects.**

## 3. Other papers — status

| Paper | Executable now? | Status |
|---|---|---|
| Gatev et al. 2006 | yes (price-only) | **RUN — REJECT** (this doc) |
| Do & Faff 2010/2012 | partial | **directional support** — our decay-to-reject *is* their finding; the industry-matched refinement is **BLOCKED** (no sector map) |
| Vidyamurthy 2004 (cointegration) | no | **BLOCKED** — no ADF/Johansen selector in the frozen template |
| Avellaneda-Lee 2010 (PCA/ETF OU) | no | **BLOCKED** — no factor series / ETF instruments |
| Kalman dynamic hedge | no | **BLOCKED** — no state-space filter |
| Cross-country / ADR pairs | no | **BLOCKED** — no cross-listing table |

## Known limitations / Skipped
- **Cointegration, PCA/ETF, Kalman, sector, cross-country variants NOT run.**
  *Reason:* frozen platform lacks the selector / data (named per row above).
  *Unblock:* each specific item. Reported honestly; no toy substitution.
- **Published magnitude not reproduced.** *Reason (not impossibility — a genuine
  empirical null):* the edge has decayed (Class D) and the frozen fixed-% sizing
  truncates the book (Class B). *Unblock to a fair retry:* rolling re-formation
  (P3) + committed-capital sizing (P5), both deferred under the freeze.
