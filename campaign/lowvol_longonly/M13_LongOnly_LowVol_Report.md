# M13 — Long-Only Low-Volatility Reproduction — Final Report

**Date:** 2026-08-06 · **Platform defects:** None · **Certification:** **DEFER**

Independent successor to M12. M12 rejected the low-vol **long-short** factor and
localized the failure to the short high-volatility leg (ruin machine, undeployable
₹0.27 cr short-leg capacity). M13 tests the separate hypothesis that the **long-only**
low-vol book is significant and deployable. Everything is frozen versus the certified
M12 baseline except `allow_short=False`.

---

## 1. Research objective

Test: *"Does a long-only low-volatility portfolio produce statistically significant
and economically deployable alpha?"* — not a rescue of the rejected long-short
strategy, an independent question about the long leg standing alone.

## 2. Original hypothesis

Low-volatility stocks earn superior risk-adjusted returns (Baker-Haugen-Baker 1991,
Blitz-van Vliet 2007). Holding the lowest-volatility decile long, with **no short
leg**, should capture the low-vol premium without the short-side ruin that killed the
M12 L/S book.

## 3. Experimental design & deviations (Phase 1)

Reproduced the published methodology as closely as the certified platform allows.

| Element | Specification | Deviation from literature |
|---|---|---|
| Ranking | trailing 252d stdev of daily simple returns | none (standard total-vol) |
| Portfolio | long lowest-vol decile (q=0.10), **long only** | none |
| Weighting | M8 bounded equal-weight (cap 10%, min 10 names) | bounded vs pure EW (M8 standard) |
| Rebalance | monthly (21 trading days) | none |
| Screen | $5 min price, US canonical panel | survivorship-biased 2014–2026 (M6) |
| Budget | full 1.0 capital long (vs 0.75 in L/S) | — |
| Costs | 10 bps comm / 5 spread / 10 slippage | engine Almgren-Chriss |

**Deviations, all documented:** (a) bounded equal-weight (M8) rather than naïve EW;
(b) survivorship-biased, price+volume-only panel (M6 data ceiling) — no factor model,
so **beta-adjusted alpha cannot be decomposed** (see §11); (c) T+1 open fills, no
look-ahead (M9). Only `allow_short=False` changed versus the frozen M12 baseline —
factor logic, engine, execution model, M8 construction, data pipeline untouched.

## 4. Canonical investigation (Phase 2)

Two bases: certified two-pass `investigate` (IS ≈70% / OOS ≈30%, adjusted p gate) and
continuous full-sample `run_backtest` (deployment economics).

| Metric | In-sample | Out-of-sample | Continuous (full) |
|---|---|---|---|
| Total return | +46.12% | +36.19% | +172.98% |
| Sharpe | 0.017 | 0.609 | 0.310 |
| Max drawdown | −36.26% | −7.40% | −36.26% |
| CAGR | — | — | 8.32% |
| Volatility | — | — | 12.48% |
| Sortino | — | — | 0.415 |
| Trades | — | 420 | 783 |
| Annual turnover | — | — | 0.190 |
| Avg holding (days) | — | — | 133.8 |
| Exposure | long-only, ~10% decile, cap 10%/name | | stable |
| **Adjusted p-value** | | | **0.1182** |
| **Verdict** | | | **reject (not significant)** |

**No ruin** — continuous DD −36.26% versus M12 L/S −103.35%. Removing the short leg
removed the ruin exactly as M12's failure-mode analysis predicted.

The IS/OOS split is the crux: IS Sharpe 0.017 (flat, and it carries the full −36% DD)
versus OOS Sharpe 0.609 (smooth, −7.4% DD). The edge is **regime-concentrated in the
2022–2026 OOS window**, not stationary — which is precisely why the adjusted p-value
sits at 0.118 and fails the 5% gate despite the strong OOS number.

## 5. Robustness experiments (Phase 3)

Continuous deployment basis; one pre-registered value per axis (robustness, not
optimization).

| Variant | Change | Return | Max DD | Sharpe | Trades | Read |
|---|---|---|---|---|---|---|
| canonical | baseline | +172.98% | −36.26% | 0.310 | 783 | positive, no ruin |
| lb_126 | lookback 126 | +153.61% | −31.66% | 0.269 | 1304 | positive, no ruin |
| lb_504 | lookback 504 | 0.00% | 0.00% | 0.00 | 0 | starved (data limit) |
| rb_63 | rebalance 63d | +159.75% | −37.70% | 0.275 | 181 | positive, no ruin |
| downside | semi-deviation | +160.40% | −34.56% | 0.285 | 701 | positive, no ruin |
| liq_50 | drop 50% illiquid | +176.23% | −31.94% | 0.312 | 226 | positive, **improves** |

**4/5 live variants clean positive and non-ruined**; the liquidity filter slightly
*improves* the book (removing illiquid micro-caps helps, opposite of the M12 short
leg). `lb_504` starves to 0 trades on the ~12-year survivorship-trimmed panel — a
data-length limitation, not a strategy failure (same finding as M12-R2). Sign and
deployability are stable across every axis; **no ruin in any variant**. What is *not*
stable is magnitude — Sharpe clusters tightly at ~0.27–0.31, uniformly modest.

## 6. Capacity findings (Phase 4)

Analytic India ₹, long low-vol decile only (no short leg), full 1.0 budget.

| Leg | ADV median | ADV p10 | Ceiling (median) | Ceiling (p10) |
|---|---|---|---|---|
| low-vol (long) | ₹77.6 cr | ₹1.14 cr | ₹830 cr | **₹12.19 cr** |

Deployable capacity **₹12.19 cr** at the p10 (least-liquid held) name, ≤10% ADV
participation. This is the M12 long-leg ceiling (₹16.25 cr) scaled by the 1.0/0.75
budget change — internally consistent. Crucially there is **no ₹0.27 cr short-leg
bottleneck**: the undeployability that sank the M12 L/S book is gone. 1075-name India
universe, 107-name decile, per-name weight 0.93%.

## 7. Deployment findings

Fully deployable as a long book: no ruin (DD −36%), low turnover (0.19 annual,
~134-day holds → low cost drag), ₹12 cr capacity floor, smooth OOS behavior
(−7.4% DD). Nothing in execution, liquidity, or capacity breaks it — the opposite of
M12.

## 8. Statistical evidence (Phase 5)

- **Adjusted p-value = 0.1182** (multiple-testing-gated) → **fails** the 5% gate.
  Not significant, but ~3× closer than M12's 0.366.
- IS Sharpe 0.017 → effectively zero risk-adjusted return in-sample (2014–~2022).
- OOS Sharpe 0.609 → strong, but concentrated in one ~4-year regime.
- Robustness summary: sign positive and non-ruined in 4/5 live variants; magnitude
  uniformly modest (Sharpe ~0.3); 1 starved by data length.
- **Interpretation:** the two-pass framework will not certify an edge whose entire
  strength lives in the recent third of the sample. The number is promising, not
  significant.

## 9. Failure-mode / confound analysis

- **No structural failure.** Removing the short leg removed the ruin; there is no
  blow-up mechanism in the long-only book. This is the clean confirmation of M12's
  short-leg diagnosis.
- **Beta confound (the binding issue).** A long-only low-vol equity book is
  dominated by market beta. The +172.98% continuous return is mostly market exposure,
  not alpha; 8.32% CAGR is below a passive US-equity benchmark over 2014–2026. Without
  a factor model (M6 ceiling) the low-vol *alpha* cannot be separated from market
  *beta* — the raw-return significance test (p=0.118) already fails, and a
  beta-adjusted test could only be stricter.
- **Non-stationarity.** IS-flat / OOS-strong shows the effect is regime-dependent, not
  a persistent premium on this panel.

## 10. Decision rationale (5-dimension certification)

| Dimension | Finding | Verdict |
|---|---|---|
| 1. Statistical significance | adjusted p = 0.1182 > 0.05; IS Sharpe 0.017 | FAIL (marginal) |
| 2. Economic significance | CAGR 8.3%, Sharpe 0.31, positive Sortino — but beta-confounded, alpha undecomposable | MARGINAL |
| 3. Deployment viability | no ruin (DD −36%), ₹12.19 cr capacity, turnover 0.19 | PASS |
| 4. Robustness | 4/5 live variants positive non-ruined; magnitude modest; lb_504 starved | PASS (sign) |
| 5. Internal consistency | IS-flat/OOS-strong = regime dependence; coheres with failed gate | PASS |

**No single metric dominates.** The statistical gate fails, but deployment,
robustness and consistency pass and the book is economically live — materially better
than the M12 L/S that failed every positive dimension.

- **Not ADOPT** — fails the significance gate; IS Sharpe ~0; return is beta-confounded
  and cannot be shown to be alpha with current data.
- **Not REJECT** — no defect, no ruin, deployable, sign-stable, economically live.
  Rejecting would discard a viable, non-broken book on a single failed gate.
- **DEFER** — promising and deployable but statistically uncertified and
  alpha-vs-beta unresolved. This is the honest, evidence-weighted verdict.

### Platform defects: None · Research conclusion: DEFER
The engine is sound (M9); the long-only book behaves exactly as designed and the
short-leg diagnosis from M12 is confirmed. The deferral is a *research* conclusion
about evidence sufficiency, not a platform issue.

## 11. Limitations

- **Alpha-vs-beta not decomposable** — no factor model (M6). A long-only low-vol book
  is beta-dominated; without CRSP/Compustat + a factor model the low-vol premium
  cannot be isolated from market exposure. **Binding unblock.**
- **Survivorship bias** — 2014–2026 panel excludes delisted names; biases performance
  upward (M6/M9), caveat only.
- **Regime-concentrated OOS** — the entire risk-adjusted edge lives in the 2022–2026
  window; a longer OOS is needed to confirm it is not a single regime.
- **lb_504 starved** — long warm-ups exhaust the trimmed panel (0 trades); reported,
  not silently skipped.
- **Single market for economics** — capacity in India ₹; return economics on US
  canonical (M1–M9 continuity). Both labeled.

## 12. Future research directions

- **CRSP/Compustat unblock** → factor model to decompose low-vol alpha from market
  beta and test BAB / beta-neutral construction (the program-wide binding constraint).
- **Vol-scaled / target-vol construction** to convert the modest raw Sharpe into a
  cleaner risk-adjusted signal.
- **Longer OOS** (or walk-forward) to test whether the 2022–2026 strength persists.
- **Beta-neutralized long-only** (hedge the market leg) to isolate the premium once a
  factor model exists.

---

### Cross-campaign note
M12 (L/S) → REJECT (structural ruin, undeployable). M13 (long-only) → DEFER
(deployable, promising, statistically uncertified, beta-confounded). Removing the
short leg fixed everything M12 diagnosed *except* the one thing this data cannot
settle: whether the surviving return is alpha or beta.
