# Cross-Market Report — Momentum, US vs India

**Date:** 2026-08-03. Same frozen engine (`FactorStrategy` + `ResearchRunner`),
identical params per label, identical 70/30 OOS split. Only the universe differs.
Every number traces to `campaign/momentum/runs/us.jsonl` and `.../india.jsonl`.
Reproduce: `python scripts/run_momentum_grid.py {us|india} out.jsonl`.

**Shared caveat (both markets):** results are produced under the 1.5× gross
leverage cap, which admits ~30 of ~200 intended decile names each rebalance (see
`Leverage_Investigation.md`, Category B / M3). This truncates every L/S book
uniformly, so the US↔India comparison stays fair, but no L/S figure reflects the
full decile spread.

## 1. Side-by-side (OOS)

| Config | US Sharpe | US ret | US p | India Sharpe | India ret | India p |
|---|---|---|---|---|---|---|
| JT_6-1-6_decile (L/S) | **0.935** | **+58.8%** | 0.161 | **−1.424** | −46.1% | 1.000 |
| form_3m (L/S) | 0.622 | −48.0% | 0.315 | 0.542 | −147.5% | 0.351 |
| form_9m (L/S) | 0.573 | −85.0% | 0.268 | −0.630 | −145.1% | 1.000 |
| form_12m (L/S) | −0.685 | −62.0% | 1.000 | 0.043 | −28.1% | 0.479 |
| hold_3m (L/S) | 0.921 | −241.8% | 0.152 | −0.432 | −196.6% | 1.000 |
| tercile (L/S) | 0.596 | −113.5% | 0.304 | 0.603 | −144.6% | 0.291 |
| **long_only** | 0.522 | +99.0% | 0.155 | **1.012** | **+416.5%** | **0.026 ✓** |

✓ = the single ACCEPT (adj p < 0.05) across all 14 configs.

## 2. The two markets tell opposite stories

**US — momentum lives in the long/short decile spread.** The reference 6-1-6
decile L/S is the standout (+58.8% WML, Sharpe 0.935), directionally consistent
with JT. The long-only book is weaker (+99% but Sharpe 0.52). Momentum in the US
sample is a *relative-strength* effect: winners minus losers.

**India — momentum lives entirely in the long leg; the short leg is a wrecking
ball.** Every L/S India config is negative (JT decile −1.42 Sharpe, −46% ret),
yet long-only is the best result in the whole campaign: **Sharpe 1.012, +416.5%,
significant at p=0.026.** Interpretation from evidence:

- India 2014–2026 was a strong, broad **bull market**. Being long high-momentum
  names rode the trend (long-only +416%).
- Shorting past losers in that regime is a persistent drag: losers rebounded, so
  the short leg bled in every L/S config — flipping the decile spread negative
  (Cause: momentum-crash asymmetry, amplified by the bull tape).
- The leverage cap (§ caveat) hits the L/S book, not the pure-long book, so
  long-only expresses its signal more fully → part of why only it clears
  significance.

## 3. Formation / breadth behavior differs

- **US** is single-peaked at 6-month formation (only 6m posts positive WML).
- **India** L/S is negative at nearly every formation; the least-bad L/S is
  form_12m (−0.28 ret) — the opposite tilt from the US. On a bull tape, longer
  formation just means longer-held longs dragged by their paired shorts.
- Tercile vs decile: both markets lose the spread when broadened (US +59%→−114%,
  India already negative). Consistent: the premium is a tail, not a middle, effect.

## 4. Statistical significance

13 of 14 configs REJECT. The lone ACCEPT (India long_only, p=0.026) is also the
one with the most trades (959) → most OOS power. The US best configs (p≈0.15–0.16)
are directionally right but underpowered on a single slice. **Momentum's
statistical footprint in this data is: significant only as a long-only trend book
in India; directional-but-insignificant everywhere else.**

## 5. Market-specific drivers (evidence, not narrative)

| Effect | US | India | Evidence |
|---|---|---|---|
| Regime | mixed (incl. 2020 crash, 2022 drawdown) | strong bull | long_only +99% vs +416% |
| Where the alpha is | L/S decile spread | long leg only | US decile L/S +59% vs India L/S all negative |
| Short-leg contribution | risk (−71% DD) | pure drag (flips spread negative) | India L/S Sharpe all ≤ +0.60, mostly negative |
| Significance | none (best p 0.15) | long_only only (p 0.026) | jsonl adj_pvalue |
| Survivorship bias | present | **stronger** (currently-listed only, big bull) | inflates India long-only upward |

## 6. Bottom line

Momentum is **not one phenomenon** across these markets. In the US it is a weak,
insignificant relative-strength (long/short) effect concentrated at 6-month
formation. In India 2014–2026 it is a **strong, significant long-only trend
effect** whose apparent strength is inflated by a one-directional bull tape and
unquantified survivorship bias, and whose long/short version is destroyed by the
short leg. Any production design must treat the India long-only result with the
survivorship + single-regime caveats front and center (see `Production_Strategy.md`).
