# M14 — Factor Attribution & Beta Decomposition — Final Report

**Date:** 2026-08-06 · **Platform defects:** None · **Certification:** **DEFER**

Attribution successor to M13. M13 deferred the long-only low-vol book because its
return could not be shown to be *alpha* rather than market *beta*. M14 asks the
narrow follow-up: **does the M13 return survive after controlling for systematic
risk?** No strategy change — the certified M13 canonical book is regressed against the
risk factors that the M6 panel can construct.

---

## 1. Objective

Determine whether the M13 long-only low-vol return is explained by systematic risk
(market beta, size, value, momentum) or contains residual alpha. Attribution only:
engine, framework, execution, portfolio construction, ranking, universe all frozen.
No optimisation, no parameter search.

## 2. Portfolio under attribution

M13 canonical, **unchanged**: `LowVolStrategy(lookback=252, quantile=0.10,
rebalance_days=21, allow_short=False, equal_weight=True, min_price=5.0,
invariant_construction=True)`, `max_position_pct=1.0`, cost 10/5/10 bps, US canonical
panel. Daily portfolio returns taken from the engine equity curve (NAV, T+1 fills).
**2890 daily observations, 2015-01-05 → 2026-07-30.** Raw full-sample: CAGR 9.8%,
Sharpe 0.78 (excess-return basis), max DD −36.26% (matches engine).

## 3. Factors constructed (Phase 1)

| Factor | Buildable? | Construction | Status |
|---|---|---|---|
| Market | **Yes** | equal-weight universe daily return (breadth proxy) | mis-specified (see §7) |
| Momentum (WML) | **Yes** | 12-1 (252d skip 21d), top-decile EW minus bottom-decile, monthly | insignificant loading |
| Size (SMB) | **No** | needs market cap = shares outstanding × price | **unavailable (M6)** |
| Value (HML) | **No** | needs book value / fundamentals (Compustat) | **unavailable (M6)** |

Two of four factors are buildable from the M6 price+volume panel. **Size and Value
cannot be built** — shares-outstanding and fundamentals data do not exist in the panel
(see §11 Skipped). The market factor is an **equal-weight** breadth proxy, not
cap-weighted, because cap weights also require shares outstanding.

## 4. Single-factor market regression (Phase 2)

`(r_p − r_f) = α + β·(r_m − r_f) + ε`, 2890 obs, 95% CI via large-sample normal
approximation.

| Estimate | Value | 95% CI | t | Significant? |
|---|---|---|---|---|
| Alpha (annual) | **+4.43%** | [−3.08%, +11.93%] | 1.157 | **No** |
| Beta | **0.011** | [0.008, 0.015] | 6.51 | yes (but ≈ 0) |
| R² | **0.0145** | | | — |

The full-sample market model explains **1.45%** of portfolio variance and estimates a
beta of essentially **zero**. Alpha is +4.4%/yr but statistically **insignificant**
(CI straddles zero). Two readings are possible and only §7 resolves which.

## 5. Two-factor market + momentum (Phase 1 exposures)

| Estimate | Value | t | Significant? |
|---|---|---|---|
| Alpha (annual) | +4.55% | 1.187 | No |
| Market beta | 0.012 | 6.67 | yes (≈ 0) |
| Momentum beta | 0.001 | 1.445 | No |
| R² | 0.0152 | | |

Adding momentum changes nothing: momentum loading ≈ 0 and insignificant, R² still
1.5%, alpha still ~4.5%/yr insignificant. The book carries no measurable momentum tilt.

## 6. Rolling beta (Phase 3)

126-day rolling single-factor beta, 2765 windows:

| min | max | mean | std |
|---|---|---|---|
| 0.001 | 0.788 | **0.491** | 0.209 |

Beta is **strongly time-varying** — mean 0.49, ranging 0 → 0.79. This directly
contradicts the full-sample beta of 0.011 and is the key diagnostic (§7).

## 7. Why full-sample beta ≈ 0 but rolling mean ≈ 0.49 — proxy mis-specification

The equal-weight market proxy weights every universe name equally, so its variance is
dominated by high-volatility micro-caps. The low-vol book, **by construction, excludes
exactly those names.** On the large-magnitude market-proxy days (micro-cap driven,
high `r_m − r̄_m` leverage in the pooled regression) the low-vol book barely moves →
near-zero covariance on precisely the highest-leverage observations → the pooled beta
is dragged to ~0. Within calmer 126-day windows the ordinary co-movement (~0.49) shows
through. **The full-sample beta of 0.011 is therefore not credible as "the book has no
market exposure"** — it is an artifact of an equal-weight proxy dominated by names the
strategy does not hold. A cap-weighted market benchmark would not have this pathology,
but cap weights require shares outstanding (unavailable, M6).

## 8. Residual performance after removing market (Phase 5)

Residual daily return = `(r_p − r_f) − β·(r_m − r_f)`:

| Residual CAGR | Residual Sharpe | Residual max DD | Residual total |
|---|---|---|---|
| **+3.65%** | **0.34** | −37.03% | +50.8% |

Because measured β ≈ 0, subtracting `β·market` removes almost nothing — the residual is
essentially the raw excess return. **The return does not disappear** when the market
component is stripped (it can't; the estimated component is ~zero), but the residual is
**not statistically distinguishable from zero** (α t = 1.16, §4).

## 9. Decision (5-dimension, honest)

The two clean outcomes the decision rule anticipated did **not** occur:

- **Not ADOPT** — no *statistically significant* residual alpha. α = +4.4%/yr but
  t = 1.16, 95% CI [−3.1%, +11.9%] includes zero. Point estimate is positive; evidence
  is not.
- **Not REJECT** — the return does **not** disappear after removing beta. Measured
  full-sample beta ≈ 0 (R² 1.5%), so the market model explains almost none of the
  return; there is nothing to "remove." Cannot claim the return is market beta.
- **DEFER** — **the attribution cannot be completed with available data.** The two
  factors most relevant to a low-vol book — a **cap-weighted market** and **size/value**
  — are unavailable (M6). The one available market proxy is mis-specified (§7): its
  near-zero full-sample beta is a construction artifact, contradicted by rolling
  mean 0.49. We can neither confirm significant alpha nor attribute the return to
  systematic risk. This is a **data-blocked** verdict, identical in root cause to M13.

| Dimension | Finding | Verdict |
|---|---|---|
| Residual alpha significance | α +4.4%/yr, t 1.16, CI straddles 0 | FAIL (insignificant) |
| Return explained by beta | full-sample β ≈ 0, R² 1.5% — explains ~nothing | INCONCLUSIVE |
| Benchmark adequacy | equal-weight proxy mis-specified (§7); no cap weights | FAIL (data) |
| Factor completeness | 2/4 factors; size & value unavailable | FAIL (data) |
| Internal consistency | rolling β 0.49 vs pooled 0.01 both explained by §7 | PASS |

**Certification: DEFER.** Attribution incomplete because required data is unavailable.

### Platform defects: None · Research conclusion: DEFER
The regression machinery is sound; the block is data, not code. This confirms M13's
core limitation empirically: with a price+volume panel the low-vol return **cannot** be
decomposed into alpha vs systematic risk.

## 10. Cross-campaign note

M12 REJECT (structural ruin) → M13 DEFER (deployable, unproven, beta-confounded) →
M14 DEFER (attribution data-blocked). M14 does not overturn M13; it **quantifies** why
M13 deferred: the point estimate leans toward a positive residual (+4.4%/yr) but it is
statistically insignificant and cannot be cleanly separated from systematic risk using
constructible factors. The verdict trend is stable — the low-vol book is promising and
undecided, and the deciding evidence lives behind the same data wall.

## 11. Limitations / Skipped (CLAUDE.md hard rule)

Each skip: **what · why impossible now · unblock.**

- **Size (SMB) factor — skipped.** *What:* small-minus-big size factor exposure.
  *Why:* market cap = shares outstanding × price; the M6 panel has price+volume only,
  no shares outstanding. *Unblock:* CRSP shares-outstanding (or any market-cap field).
- **Value (HML) factor — skipped.** *What:* high-minus-low book/market exposure.
  *Why:* no book value or fundamentals in the panel (Compustat absent). *Unblock:*
  Compustat fundamentals.
- **Sector attribution (Phase 4) — skipped.** *What:* decompose return into sector
  tilts. *Why:* no sector/industry classification metadata (M6). *Unblock:* GICS/SIC
  sector codes.
- **Cap-weighted market benchmark — skipped (degraded to equal-weight proxy).** *What:*
  proper cap-weighted market factor. *Why:* cap weights need shares outstanding (as
  above). *Consequence:* the equal-weight proxy is mis-specified (§7), which is itself
  a primary driver of the DEFER. *Unblock:* shares-outstanding / index membership data.

## 12. Future directions

- **CRSP + Compustat unblock** → cap-weighted market + SMB/HML/momentum four-factor
  attribution; the program-wide binding constraint (M6/M13/M14 all point here).
- Re-run M14 attribution once a proper market benchmark exists; the residual-alpha test
  becomes interpretable only then.
- Longer / walk-forward sample to tighten the alpha CI (currently ±7.5%/yr).
