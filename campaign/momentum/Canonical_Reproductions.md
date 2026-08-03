# Canonical Reproductions — Momentum Corpus

**Date:** 2026-08-03
**Rule:** execute the committed implementation verbatim, no tuning; classify every
difference vs the publication as **A** platform defect / **B** methodology
fidelity gap / **C** data difference / **D** market evolution / **E** statistical
variation. Only **A** justifies engineering changes. Sources: this campaign's
runs, `docs/REPRO_JT_1993_US_REFERENCE.md`, `docs/REPRODUCTION_SCOREBOARD.md`.

## 1. Reproduction scoreboard (momentum-relevant)

| # | Paper | Data on hand? | Status | Result | Eng defect |
|---|---|---|---|---|---|
| 1 | Jegadeesh-Titman 1993 (cross-sectional momentum) | ✓ US+India daily OHLCV | **RUN** | directionally reproduced (US OOS +58.8% WML, Sharpe 0.935), not significant | none |
| — | JT 2001 (persistence / sub-periods) | ✓ price only | **PARTIAL** | robustness sweep stands in for sub-period tables; overlapping-portfolio construction absent (M2) | none |
| 2 | Carhart 1997 (4-factor / fund momentum) | ✗ needs fund returns + FF factors | **BLOCKED** | — | n/a |
| 3 | Moskowitz-Ooi-Pedersen 2012 (time-series momentum) | ✗ needs futures/multi-asset + vol scaling | **BLOCKED** | — | n/a |
| 4 | Asness-Moskowitz-Pedersen 2013 (value & momentum everywhere) | ✗ needs fundamentals + global multi-asset | **BLOCKED** | — | n/a |

## 2. JT-1993 — the one executable momentum reproduction

Full record: `docs/REPRO_JT_1993_US_REFERENCE.md`. Headline (US, 1007 names,
70/30 OOS):

| Metric | Value |
|---|---|
| OOS Sharpe | 0.935 |
| OOS return (WML, zero-cost) | +58.78% |
| OOS max drawdown | −70.86% |
| OOS trades | 345 |
| Adjusted p-value | 0.161 |
| Harness verdict | REJECT (not significant at 0.05) |

**Directionally consistent** with JT's positive momentum premium; **not**
"successfully reproduced" because it is statistically insignificant on one slice
with extreme drawdown. Every remaining difference is classified **B/C/D/E — none
is a platform defect (A).** Ranked fidelity gaps (identified, not implemented
under the engineering freeze): JT-style price/liquidity/large-cap universe screens
(M6, highest impact), equal-weight deciles (M3), formation skip-period (M1),
overlapping-holding portfolios (M2), gross-return reporting (M4), research-mode
circuit-breaker disable (M5), walk-forward significance (M8).

The robustness sweep (`Robustness_Report.md`) extends this single reproduction
across formation/holding/breadth/leg axes and the cross-market run
(`Cross_Market_Report.md`) repeats it on India.

## 3. Why the other momentum papers are BLOCKED (honest stops)

Per the campaign stopping rule and CLAUDE.md "nothing silently skipped":

- **Carhart 1997** — needs mutual-fund monthly returns + the Fama-French factor
  series (Mkt-RF, SMB, HML) to regress fund alphas on a momentum factor. Neither
  a fundamentals table nor a factor-returns table/loader exists.
  *Unblock:* acquire fund-return + FF-factor panels; add a `factors` loader.
- **MOP 2012 (time-series momentum)** — needs a cross-asset-class futures panel
  (equity indices, bonds, FX, commodities) plus ex-ante volatility scaling. The
  store holds single-name equity OHLCV only.
  *Unblock:* ingest a multi-asset futures panel; add vol-scaled sizing.
- **AMP 2013** — needs global multi-asset returns **and** value fundamentals
  (book-to-market etc.). Same fundamentals gap as Carhart plus global coverage.
  *Unblock:* licensed global fundamentals + multi-asset returns.

**No toy data was substituted** to fake any of these. They are reported BLOCKED,
with the exact missing dataset and the change that would unblock each.

## 4. Engineering verdict

Momentum papers executable on the available price-only data: **1 run (JT-1993)
+ its robustness/cross-market extensions.** Papers requiring fundamentals or
multi-asset panels: **BLOCKED, data-limited, not defects.** **Platform defects
discovered across all attempts: 0.** No engineering change is justified.
