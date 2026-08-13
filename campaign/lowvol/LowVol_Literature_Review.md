# Low-Volatility Anomaly — Literature Review (M12 Phase 1)

**Mentisrex Capital — Low-Volatility Campaign**
**Date:** 2026-08-05. Momentum campaign ARCHIVED (M11); this is an independent factor.

## 1. The anomaly

Empirically, low-volatility (and low-beta) stocks have delivered **higher
risk-adjusted returns** than high-volatility stocks — a direct violation of the CAPM
prediction that higher risk earns higher return. The effect appears as: comparable or
only slightly lower *raw* returns for low-vol stocks at **much lower risk**, hence
materially higher Sharpe; and a long-low/short-high book ("betting against beta")
with positive risk-adjusted return.

## 2. Major papers

| Paper | Universe | Signal | Construction | Reported result |
|---|---|---|---|---|
| Haugen & Heins (1975) | US | return variance | low-variance sort | low-risk stocks earned higher returns |
| Baker, Haugen, Baker (1991) / Haugen-Baker | US | total volatility | vol-sorted deciles, EW | low-vol decile > high-vol decile risk-adjusted |
| Ang, Hodrick, Xing, Zhang (2006) | US | idiosyncratic vol (FF-residual) | quintiles, VW | high-idio-vol stocks earn abnormally **low** returns |
| Blitz & van Vliet (2007) | Global | past **3-yr** volatility of weekly returns | vol deciles, EW, monthly rebalance | top-minus-bottom decile ~12%/yr Sharpe improvement |
| Frazzini & Pedersen (2014) "Betting Against Beta" | Global, multi-asset | rolling beta (vol × correlation) | rank, beta-neutralize, leverage low-beta | positive BAB return, high Sharpe |
| Baker, Bradley, Wurgler (2011) | US | total & idio vol | quintiles | "low-risk anomaly," attributed to leverage constraints + behavioral demand |

## 3. Common specification elements

- **Signal:** *trailing volatility of returns.* Most-standard = **total volatility**
  = standard deviation of (daily or weekly) returns over a trailing window. Idio-vol
  (AHX-Z) and beta (BAB) are refinements requiring a factor model.
- **Lookback:** 1–3 years (Blitz-van Vliet 36 months of weekly ≈ ~156 weeks; AHX-Z
  1-month daily; BAB 1-yr daily for vol). **1 year of daily returns (~252d)** is the
  standard, simplest total-volatility window.
- **Universe:** broad common-stock cross-section (CRSP), often ex-microcaps; price/
  liquidity screens common.
- **Construction:** rank into deciles/quintiles, **equal-weight**, **long low-vol /
  short high-vol** (or long-only low-vol), **monthly rebalance**.
- **Holding:** ~1 month (monthly rebalance), low turnover relative to momentum.

## 4. Simplest academically faithful specification (chosen baseline)

> **Rank the cross-section by the trailing standard deviation of daily simple returns
> over 252 trading days (1 year). Long the lowest-volatility decile, short the
> highest, equal-weighted, rebalanced every 21 trading days.**

**Why this specification (no optimization):**
- **Total volatility (stdev of daily returns)** is the lowest-common-denominator
  signal shared by Haugen-Baker / Blitz-van Vliet / BAB — it needs no factor model
  (unlike idio-vol/beta), so it is reproducible on the **price-only** panel (M6).
- **252d** = the standard 1-year window; a single pre-registered value, not swept.
- **Decile (0.10), equal-weight, 21d rebalance, long-low/short-high** mirror the
  canonical vol-sorted portfolio and reuse the platform's certified construction
  standards (M1 EW, M2 $5 screen, M8 bounded construction, M7 liquidity framework).
- **Downside deviation** (semi-deviation) is retained only as a Phase-5 robustness
  *estimator*, not the baseline.

## 5. Data-fidelity caveats (carried from M6/M11, honest)

- Panel is **price+volume only, 2014–2026, survivorship-biased**. Idio-vol/beta
  variants (AHX-Z, BAB) are **not** reproducible (no factor model / betas) — baseline
  uses **total** volatility, which is.
- Survivorship: low-vol stability may be *over*-stated if volatile delisted names are
  absent — direction of bias noted, not corrected (no delisting data).
- Reproduction target is *directional/first-look*, not published-magnitude (different
  era, single survivorship-biased slice), per the whole program's standard.
