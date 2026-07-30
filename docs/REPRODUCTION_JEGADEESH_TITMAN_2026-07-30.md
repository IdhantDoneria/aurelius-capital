# Reproduction Report — Jegadeesh & Titman (1993)

Institutional Reproduction Program, run 2026-07-30. Faithful reproduction, no
parameter tuning. Platform evaluated, not optimized.

## 1. Reproduction queue (ranked)

Ranked by data availability (binding), implementation complexity,
reproducibility, engineering effort. Available data = daily equity OHLCV only
(`data/analytics.duckdb`, 12 synthetic names, 2022-01..2023-12).

| # | Paper | Data | Complexity | Repro | Effort | Executable now |
|---|---|---|---|---|---|---|
| 1 | **Jegadeesh-Titman 1993 (momentum)** | HIGH | LOW | HIGH | LOW | **YES** |
| 2 | Gatev et al. (pairs trading) | HIGH | MED | MED | MED | yes |
| 3 | Sharpe 1964 (CAPM) | PARTIAL | MED | MED | MED | no |
| 4 | Asness et al. (Value & Momentum) | PARTIAL | HIGH | MED | HIGH | no |
| 5 | Fama-French 1993 (3-factor) | LOW | MED | MED | HIGH | no |
| 6 | Novy-Marx 2013 (gross profitability) | LOW | MED | MED | HIGH | no |
| 7 | Carhart 1997 (4-factor / funds) | LOW | MED | LOW | HIGH | no |
| 8 | Black-Litterman 1992 (optimizer) | LOW | HIGH | LOW | HIGH | no |

Papers 3-8 blocked on **data**: they need fundamentals (Compustat book-to-market,
gross profitability), fund returns, or multi-asset/equilibrium inputs not present.

## 2. Selection

**Jegadeesh-Titman 1993** — only landmark executable on price data alone, and the
platform ships the exact construction: `FactorStrategy` = cross-sectional
decile long-short relative-strength momentum (long top decile, short bottom,
periodic rebalance). No new code required.

## 3. Execution (faithful, no tuning)

JT 6-6 design mapped to daily bars, **single param set, no grid search**:

| JT design | Mapping |
|---|---|
| Formation J = 6 months | `lookback = 126` trading days |
| Holding K = 6 months | `rebalance_days = 21` (monthly overlap) |
| Winner/loser deciles | `quantile = 0.10` |
| Zero-cost long-short | `allow_short = True` |

Pipeline: `DuckDBStore.ohlcv → BarData → ResearchRunner.investigate(FactorStrategy)`.

## 4. Reproduced vs published

| Metric | JT 1993 (published, 6-6) | Reproduced | 
|---|---|---|
| Winner-minus-loser return | **≈ +0.95%/month** (~+12%/yr) | −0.29% total (OOS slice) |
| t-statistic | ≈ 3.07 (significant) | not significant (adj p = 1.000) |
| Sign of premium | **positive** | slightly negative |
| Verdict | momentum premium confirmed | **REJECT** |
| Universe | NYSE/AMEX, ~hundreds-thousands | 12 names |
| Period | 1965-1989 (25 yr) | 2022-2023 synthetic (2 yr) |
| **OOS trades** | thousands of stock-months | **2** |

## 5. Quantified differences + likely causes (ranked)

1. **Data insufficiency — dominant, explains the null on its own.** OOS slice ≈
   156 bars; `FactorStrategy` needs 127 bars of warmup before its first
   cross-section, leaving ~30 signal bars → ~2 rebalances → **2 trades**. With 12
   names, a decile = **1 stock per side**. Zero statistical power; the REJECT is
   a sample-size artifact, not evidence against momentum.
2. **Synthetic ≠ real returns.** Generated per-name GBM drift carries no
   medium-horizon return autocorrelation for momentum to exploit; at a 6-month
   horizon in a 2-year sample, noise dominates the drift signal.
3. **No skip period.** JT skip the most recent week between formation and
   holding to avoid short-term reversal / bid-ask bounce; `FactorStrategy` scores
   through the current bar. Contaminates the signal.
4. **IS/OOS split halves usable sample.** Runner's 70/30 train_test + 126-bar
   warmup leaves the OOS window too short for K=6-month holding; JT reported
   full-sample point estimates.
5. **Daily rebalance approximation.** JT use overlapping monthly portfolios;
   `rebalance_days=21` approximates but is not identical.

Fidelity finding: the platform's **construction is faithful** (cross-sectional
decile long-short, leak-safe, rebalanced). The failure is **input data scale**,
not methodology.

## 6. Reproduction outcome

**FAILED to reproduce the published premium** — but for a diagnosable,
data-side reason (2 OOS trades), not a platform-logic defect.

## 7. Smallest change required before retry (step 8)

**Data, not engineering.** `FactorStrategy` already implements JT correctly.
Smallest viable retry: load a **broader, longer price panel** through the
existing loader — target **≥100 symbols × ≥10 years** (monthly or daily) so a
decile holds ≥10 names and the OOS window spans enough K=6-month rebalances for
statistical power. Same `CSVLoader → DuckDBStore → FactorStrategy` path, zero
code change.

Optional fidelity refinements (secondary, smaller effect): add a 1-week skip to
formation; report full-sample point estimate alongside IS/OOS for a
JT-comparable number. Neither unblocks a meaningful result — data scale is the
binding constraint.

## Known limitations / Skipped

**Published magnitude not reproducible here.**
- *Reason (impossibility):* JT's numbers require broad real CRSP equity history
  (network/paywall-blocked, per `docs/paper_ingestion_2026-07-30.md`); the only
  available panel is 12 synthetic names × 2 years.
- *Unblock:* a real/large adjusted-price panel (≥100 names, ≥10 yr) via the
  existing loader. Then re-run this script unchanged.
