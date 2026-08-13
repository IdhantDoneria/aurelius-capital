# Executive Summary — Momentum Research Campaign

**Mentisrex Capital, 2026-08-03.** One-page answer to the campaign question, from
14 backtests on real US + India equities (2014–2026), frozen platform, no tuning.

## The question

> Under what conditions does momentum exist, how faithfully can Mentisrex reproduce
> the academic literature, and is Mentisrex ready to deploy a momentum strategy on
> objective evidence?

## The answer

**1. Under what conditions does momentum exist?**
Narrowly, and differently by market. It requires **~6-month formation, extreme
deciles, and monthly rebalancing**; it decays or reverses outside that window
(12-month formation flips negative; tercile breadth and 63-day holding destroy
it). In the **US** it is a weak, statistically **insignificant** long/short
relative-strength effect (best: +58.8% WML, Sharpe 0.935, p 0.161). In **India**
it is a strong, **significant long-only trend** effect (+416.5%, Sharpe 1.012,
p 0.026) — but its long/short version is wiped out by the short leg, and its
strength is inflated by a one-directional bull market and survivorship bias.
**The short leg is the liability in both markets.**

**2. How faithfully can Mentisrex reproduce the literature?**
**Directionally, yes; magnitude-faithfully, not yet — bounded by data, not the
engine.** Jegadeesh-Titman 1993 reproduces with the correct sign and decile
structure. Carhart 1997, MOP 2012, AMP 2013 are **BLOCKED** on absent
fundamentals / multi-asset data (reported honestly, no toy substitution). Known
fidelity gaps (skip-period, overlapping portfolios, equal-weight sizing, liquidity
screens, gross reporting, walk-forward) are identified and ranked, not
implemented. **0 platform defects** across all 14 runs plus a leverage
investigation.

**3. Is Mentisrex ready to deploy?**
**NO — not with live capital. YES — for paper trading + a bias-corrected
re-test.** Exactly one of 14 configs cleared significance (India long-only), and
it carries three disqualifying caveats:

- **Survivorship bias** (delisted losers absent) inflates the one positive result.
- **Single regime / single OOS slice** — significance rests on one 3.8-year bull.
- **Two fidelity pieces unbuilt** (equal-weight sizing M3, liquidity screen M6),
  so the recommended book's own weighting is unvalidated.

## Recommended action

Deploy **Momentum v1** (long-only, 6-1(skip)-1, top-decile, equal-weight, monthly,
single liquid market, ≤1× gross) to **paper trading only**. Before any live risk,
resolve in a future un-frozen phase: (1) ingest delisting returns to de-bias, (2)
build equal-weight-within-budget sizing, (3) add JT liquidity/large-cap screens,
(4) walk-forward significance across bull *and* bear OOS windows.

## Go / No-Go

| | Verdict |
|---|---|
| Momentum exists in the data | **YES**, narrowly + market-specifically |
| Mentisrex reproduces JT directionally | **YES** (0 defects) |
| Reproduces the broader literature | **BLOCKED** (data, not engine) |
| Live-capital ready | **NO** |
| Paper-trade + re-test ready | **YES** |

Full evidence: `Momentum_Campaign_Report.md`, `Cross_Market_Report.md`,
`Robustness_Report.md`, `Production_Strategy.md`, `Leverage_Investigation.md`.
