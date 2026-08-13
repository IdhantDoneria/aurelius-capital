# Executive Summary — Pairs Trading Research Campaign

**Mentisrex Capital, 2026-08-04.** One-page answer to the campaign question, from 14
backtests on real US + India equities (2014–2026), frozen platform, no tuning.

## The question

> Under what conditions does statistical arbitrage through pairs trading exist, how
> faithfully can Mentisrex reproduce the literature, and is Mentisrex Capital ready to
> deploy a production pairs strategy?

## The answer

**1. Under what conditions does pairs trading exist?**
On this data — **it doesn't.** Across 7 configurations × 2 markets, **0 of 14** were
statistically significant (every adjusted p = 1.000, every OOS Sharpe negative). No
formation window, entry threshold, exit band, or pair count produced a profitable,
significant book. The distance-pairs edge Gatev documented over 1962–2002 has
**decayed to below transaction costs** by 2014–2026 — exactly Do & Faff's (2010,
2012) prediction. The one structural condition we *can* name is negative: **pair
diversification inverts** under the platform's fixed-% sizing + 1.5× gross cap
(top-40 pairs is the worst config in both markets, −60%/−42% drawdown), because
truncating an over-levered book breaks its market-neutrality.

**2. How faithfully can Mentisrex reproduce the literature?**
**Faithfully, with genuine power — and it still rejects.** The canonical Gatev
construction (12-month SSD formation, top-N portfolio, 2-SD entry / convergence
exit) reproduces exactly; the 2026-07-30 data blocker (12 toy names, 22 trades) is
**resolved** — this run forms a real 20-pair book on 300 liquid names and executes
3000+ OOS trades per canonical config. The failure is **economic (market
evolution, Class D), not a platform defect.** Cointegration (Vidyamurthy), PCA/ETF
OU (Avellaneda-Lee), Kalman, sector, and cross-country variants are **BLOCKED** on
absent selectors/data (reported honestly, no toy substitution). **0 platform
defects** across all 14 runs.

**3. Is Mentisrex ready to deploy?**
**NO — and there is nothing to deploy.** Unlike the momentum campaign (one
significant, paper-tradeable config), pairs yields **zero**. Naming a "best" config
would be tuning to a backtest — forbidden. The least-bad book (India, tight exit:
−0.14 Sharpe, +13.8% return) is still losing, insignificant, and survivorship-
inflated. **No production pairs strategy is justified by the evidence.**

## Recommended action

- **Deploy nothing.** No live capital, no paper trading of any pairs config.
- **Fund no further pairs engineering** under current data — the null is economic
  (Class D), not a Class-A defect fixable by code.
- **If pairs is ever revisited,** gate it behind two research-layer additions (both
  unbuilt under the freeze): committed-capital sizing (P5, so diversification can
  express) and rolling monthly re-formation (P3, faithful test) — plus a
  delisting-returns dataset — and pre-register a kill criterion. Expected value
  remains low (Do-Faff).

## Go / No-Go

| | Verdict |
|---|---|
| Pairs edge exists in the data | **NO** (0/14 significant) |
| Mentisrex reproduces Gatev faithfully | **YES** (0 defects, 3000+ trades) |
| Reproduces the broader stat-arb literature | **BLOCKED** (data/selector, not engine) |
| Live-capital ready | **NO** |
| Paper-trade ready | **NO** (nothing significant to trade) |

The campaign's value is the **well-powered negative**: a faithful demonstration
that distance pairs do not pay on modern US+India data. Full evidence:
`Pairs_Campaign_Report.md`, `Canonical_Reproductions.md`, `Robustness_Report.md`,
`Cross_Market_Report.md`, `Production_Strategy.md`.
