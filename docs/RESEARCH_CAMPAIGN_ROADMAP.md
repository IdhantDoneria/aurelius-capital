# Research Campaign 2 — Prioritized Roadmap

Planning artifact. **No papers executed in this pass** (per current priority).
Grounded strictly on the platform's actual state as of 2026-07-30. No invented
capabilities.

## 0. Platform state (verified, not assumed)

| Capability | Actual state | Source |
|---|---|---|
| Strategy templates | 4: `MomentumStrategy`, `MeanReversionStrategy`, `PairsStrategy`, `FactorStrategy` | `src/mentisrex/backtesting/strategy/templates.py` |
| Registered features | 18, **all price/volume/technical** | `src/mentisrex/features/library/*.py` |
| Fundamentals features | **0** | (none in registry) |
| Data adapters | `csv_loader`, `yahoo`, `alpaca` | `src/mentisrex/market_data/adapters/` |
| Data on hand | OHLCV only, toy (12 names × 2 yr), synthetic | `docs/MARKET_DATA_SPEC.md`, `data/analytics.duckdb` |
| Loader throughput | ~256k rows/s; 37.8M rows (5000×30yr) ≈ 2.5 min | `docs/DATA_READINESS_REPORT.md` |
| Validation | deterministic fingerprint short-circuit, IS/OOS split, multiple-testing adj | IPAT run (JT re-run hit `duplicate_experiment`) |

**Structural fact that drives all ranking:** every feature the platform can
compute is a function of OHLCV. A paper whose signal is a function of OHLCV is
*mechanically* runnable today; its only gate is data breadth × length. A paper
whose signal needs book equity / revenue / fund returns / market-cap weights is
gated on **both** a missing dataset **and** a missing feature (category C) — and
neither is built today.

## 1. Research Campaign Roadmap (phases)

Phase gating is by *input availability*, not effort.

- **Phase A — OHLCV-at-scale (unblocks now with data, zero engine change).**
  Load ≥100 names × ≥10 yr adjusted daily OHLCV via existing
  `CSVLoader → DuckDBStore`. Converts the two construction-faithful
  reproductions (JT, Gatev) to magnitude-comparison candidates and opens every
  price-only paper in the queue. **No code.**
- **Phase B — market proxy + risk-free series.** A cap-weighted (or, absent
  shares outstanding, equal-weighted — a documented approximation, category E)
  market return plus a short risk-free series. Unblocks CAPM-family papers.
  Small derived-series work, no new subsystem.
- **Phase C — fundamentals ingestion.** Book equity, revenue, COGS, total
  assets, shares outstanding (Compustat-shaped). Requires a new dataset **and**
  a fundamentals feature family (category C engineering — deferred until a paper
  is data-ready to justify it). Unblocks FF, Novy-Marx, AMP value leg.
- **Phase D — alternative datasets.** Mutual-fund monthly returns (Carhart),
  multi-asset-class panels (AMP), investor-view inputs (Black-Litterman is an
  optimizer, not a cross-sectional backtest — views are user input, not a feed).

## 2. Ranked paper queue

### Tier 1 — Executable immediately (OHLCV, features present)
| Rank | Paper | Yr | Strategy | Key feature(s) | Readiness |
|---|---|---|---|---|---|
| 1 | Jegadeesh–Titman (momentum) | 1993 | `FactorStrategy` | momentum_21d | 100% code, driver exists, deterministic |
| 2 | Gatev et al. (pairs) | 2006 | `PairsStrategy` | correlation_60, zscore_20 | 100% code, driver exists |

Both already run construction-faithful; both under-powered on toy data
(2 and 22 OOS trades). Gate = Phase A data only.

### Tier 2 — Executable after larger OHLCV (+ market/risk-free)
| Rank | Paper | Yr | Needs beyond OHLCV | Blocker category |
|---|---|---|---|---|
| 3 | Sharpe (CAPM) | 1964 | market proxy + risk-free (beta_60 exists) | A + E (market proxy approximation) |
| 4 | AMP — Value & Momentum (momentum leg only) | 2013 | multi-asset OHLCV | A + D |

### Tier 3 — Requires fundamentals (dataset + feature family, category C)
| Rank | Paper | Yr | Fundamental inputs |
|---|---|---|---|
| 5 | Fama–French 3-factor | 1993 | market cap (shares×price) + book equity |
| 6 | Novy-Marx (gross profitability) | 2013 | revenue − COGS, total assets |
| 4b | AMP value leg | 2013 | book/price across asset classes |

### Tier 4 — Requires alternative data / not a backtest
| Rank | Paper | Yr | Input | Note |
|---|---|---|---|---|
| 7 | Carhart (fund persistence) | 1997 | mutual-fund monthly returns + FF+MOM factors | alt dataset |
| 8 | Black–Litterman | 1992 | mkt-cap equilibrium weights + covariance + **investor views** | optimizer; views are user input, no strategy template maps to it |

### Proposed acquisitions to fill the next-20 queue (NOT in corpus)
Marked explicitly as proposals — planning targets, not present papers. Chosen to
match the platform's OHLCV+technical strength (Tier-1-shaped, lowest eng risk):

| # | Proposed paper | Yr | Why it fits current capability |
|---|---|---|---|
| 9 | Jegadeesh — short-term reversal | 1990 | OHLCV; reuses MeanReversion/Factor |
| 10 | De Bondt–Thaler — long-term reversal | 1985 | OHLCV, long lookback |
| 11 | Lehmann — return reversals | 1990 | OHLCV weekly |
| 12 | Lo–MacKinlay — variance ratio / RW | 1988 | OHLCV, statistical features |
| 13 | Moskowitz–Ooi–Pedersen — time-series momentum | 2012 | OHLCV (futures panel); momentum_21d |
| 14 | Amihud — illiquidity | 2002 | OHLCV volume; relative_volume_20 |
| 15 | Ang–Hodrick–Xing–Zhang — idiosyncratic vol | 2006 | OHLCV + market model (beta_60, hist_vol_20) |
| 16 | Baker–Bradley–Wurgler — low-volatility anomaly | 2011 | OHLCV vol features |
| 17 | Barroso–Santa-Clara — momentum has its moments | 2015 | OHLCV, vol-scaled momentum |
| 18 | Daniel–Moskowitz — momentum crashes | 2016 | OHLCV + market state |
| 19 | Frazzini–Pedersen — betting against beta | 2014 | beta_60 + market (partial: leverage) |
| 20 | Fama–French 5-factor | 2015 | fundamentals (Tier-3 shape) |

Ordering rationale: 9–18 are OHLCV-only → highest readiness, zero-to-low eng
risk, directly exercise the proven momentum/reversal/pairs machinery. 19–20
deliberately last (need market-leverage handling and fundamentals).

## 3. Dataset acquisition roadmap

| Priority | Dataset | Shape | Unblocks | Effort | Path |
|---|---|---|---|---|---|
| P0 | Broad adjusted daily OHLCV | ≥100 names (ideally ≥1000) × ≥10 yr (ideally 30) | Tier 1 magnitude; queue 9–18 | load only, ~mins | `CSVLoader → DuckDBStore`, zero engine change |
| P1 | Risk-free short rate + market proxy | daily series | CAPM (3), BAB (19) | small derived series | new derived table |
| P2 | Fundamentals (Compustat-shaped) | shares out, book equity, revenue, COGS, assets, quarterly | FF (5), Novy-Marx (6), AMP value (4b), FF5 (20) | dataset + feature family (cat C) | new adapter + features — **deferred until data-ready** |
| P3 | Mutual-fund monthly returns | fund × month | Carhart (7) | alt dataset | new adapter |
| P3 | Multi-asset panels (bonds/FX/commodities) | daily | AMP (4) | alt dataset | new adapter |
| n/a | Investor views + covariance | user-supplied | Black-Litterman (8) | not a data feed — needs optimizer path decision | — |

## 4. Feature coverage matrix

Rows = papers; columns = the signal inputs each needs; cell = platform status.
`OK` = registered feature exists; `DERIVE` = computable from OHLCV, not yet a
named feature; `MISSING` = needs data the platform does not have.

| Paper | Price/return | Vol/risk | Cross-sec rank | Pairs/coint | Market/beta | Fundamentals |
|---|---|---|---|---|---|---|
| JT 1993 | OK (momentum_21d) | OK | OK (Factor) | — | — | — |
| Gatev 2006 | OK | OK | — | OK (correlation_60, zscore_20) | — | — |
| Sharpe 1964 | OK | OK | — | — | OK (beta_60) + DERIVE market proxy | — |
| AMP 2013 | OK | OK | OK | — | — | MISSING (value leg) |
| FF 1993 | OK | — | OK | — | DERIVE market | MISSING (size, B/M) |
| Novy-Marx 2013 | OK | — | OK | — | — | MISSING (gross profit) |
| Carhart 1997 | OK | — | — | — | DERIVE | MISSING (fund returns + factors) |
| Black-Litterman 1992 | OK | OK (cov) | — | — | DERIVE (mkt weights) | MISSING (views, mkt cap) |

**Single biggest feature gap:** a fundamentals family (size, book-to-market,
gross profitability). It blocks 4 corpus papers. Per the engineering rule it is
**not** built now — no paper is yet data-ready to reproduce/isolate/measure the
need. Built in Phase C when P2 data lands.

## 5. Estimated platform readiness after each paper

Readiness = fraction of the 8-paper corpus that is *faithfully operationalized*
(construction-faithful + deterministic + validated + differences explained). It
rises with **data**, not code, until Phase C.

| Milestone | Corpus operationalized | Δ | Driver |
|---|---|---|---|
| Now | 2/8 construction-faithful, 0/8 magnitude | — | toy data |
| After Phase A (P0 OHLCV) | 2/8 magnitude-comparable + queue 9–18 opened | +2 quality tier | data load, no code |
| After Phase B (P1) | +CAPM (3) → 3/8 | +1 | derived series |
| After Phase C (P2 + fundamentals features) | +FF (5), Novy-Marx (6), AMP (4) → 6/8 | +3 | dataset + cat-C features |
| After Phase D (P3) | +Carhart (7) → 7/8 | +1 | alt dataset |
| Black-Litterman (8) | needs optimizer-path decision, not just data | — | out of current backtest scope |

Ceiling on current architecture without an optimizer path: **7/8**.

## 6. Highest-impact next paper (after larger OHLCV acquired)

**Recommendation: re-run Jegadeesh–Titman 1993 at institutional scale first.**

Why it wins over any new paper:
1. **Directly tests the one verified blocker.** The scoreboard's sole open
   hypothesis is "magnitude gap = data scale, not defect." JT at ≥100×≥10yr
   confirms or refutes it with a controlled, single-variable change (data only).
2. **Zero engineering risk.** Driver exists, ran deterministically, hits the
   fingerprint short-circuit. Only the input table changes.
3. **Maximum information per unit effort.** If JT's decile spread turns positive
   and significant at scale, it validates the *entire* price-paper pipeline in
   one run — de-risking queue items 1–4 and 9–18 at once. If it does not, that
   is a real category-D signal justifying investigation.

Second: Gatev 2006 at scale (same logic, more OOS trades already → faster power
confirmation). New papers (Time-Series Momentum #13) come only after the scale
hypothesis is settled — testing a new methodology and a new data regime
simultaneously would confound the result.

## Failure Registry (open items)

| ID | Observation | Category | Action |
|---|---|---|---|
| F-1 | JT/Gatev magnitude gap vs publication | B (stat power) / A (data) | Phase A re-run; no code |
| F-2 | Metadata extractor mis-parses PDF headers (JT title = "http://www.jstor.org", Gatev year 2002) | D (defect, low sev, non-blocking) | fix only if it blocks a run; currently cosmetic — bibliographic fields corrected by hand in IPAT report |
| F-3 | 6/8 corpus papers cannot start | A (data) | Phases B–D acquisition |

## Lessons Learned

- Every current feature is an OHLCV function → data breadth, not new code, is
  the binding constraint for 2/8 today and the whole price-only queue.
- The anti-fabrication rule and the engineering rule agree: do not run papers on
  toy/faked data to fake completion, and do not build the fundamentals feature
  family before a real fundamentals dataset exists to reproduce the need.
- Highest-leverage next move is a **data load**, not a paper — and the highest-
  value first execution after that load is re-running an already-proven driver
  to isolate the data-scale variable.
