# Pairs Trading / Statistical Arbitrage — Literature Map

**Mentisrex Capital — Pairs Trading Research Campaign**
**Workstream A — Literature Intelligence**
**Date:** 2026-08-04
**Status:** Literature review. Every figure below is a *published* number from the
cited work, NOT an Mentisrex empirical result. Statistics not firmly grounded are
marked `[recall]`. Mentisrex reproducibility judged against the frozen platform
(price-only DuckDB panel, US + India daily 2014–2026) and `PairsStrategy` /
`MultiPairStrategy`.

---

## 1. Statistical-arbitrage families (scope map)

| Family | Spread object | Canonical anchor | Mentisrex-reproducible? |
|---|---|---|---|
| Distance (SSD) | min sum-of-squared-deviation of normalized prices | **Gatev, Goetzmann & Rouwenhorst 2006** | **Yes** — exactly `select_pairs` + `MultiPairStrategy` |
| Cointegration | stationary linear combination (Engle-Granger / Johansen) | Vidyamurthy 2004; Lin et al. 2006 | Partial — needs an ADF/Johansen selection step (not in frozen template) |
| Time-series / OU spread | Ornstein-Uhlenbeck mean-reverting residual | Avellaneda & Lee 2010 | Partial — z-score of a rolling spread approximates OU; no PCA/ETF residualization |
| Kalman / dynamic hedge | time-varying hedge ratio via state filter | Elliott-van der Hoek-Malcolm 2005; Chan 2013 | **BLOCKED** — no Kalman filter in the frozen platform (static hedge only) |
| ETF / index arbitrage | stock-vs-ETF or ETF-vs-ETF basket spread | Avellaneda & Lee 2010; Marshall et al. 2013 | **BLOCKED** — no ETF/basket instruments in the panel |
| Sector / industry pairs | within-industry relative value | Do & Faff 2010, 2012 | **BLOCKED** — no GICS/sector map in the panel |
| Cross-country / ADR | same-name dual listing, ADR-underlying | Gagnon-Karolyi 2010 `[recall]` | **BLOCKED** — no cross-listing linkage table |
| Market-neutral / long-short | dollar/beta-neutral relative value book | Khandani-Lo 2007 (the "quant quake") | Partial — pairs book is dollar-balanced by construction |

## 2. Landmark papers — extracted parameters

### Gatev, Goetzmann & Rouwenhorst (2006) — *the anchor*
- **Hypothesis:** stocks that moved together keep moving together; temporary
  divergences of minimum-distance pairs revert → market-neutral profit.
- **Dataset / period:** all liquid CRSP common stocks, **1962–2002** (daily).
- **Formation:** **12 months.** Normalize each stock to a cumulative total-return
  index (start = 1); for every candidate pair compute the **sum of squared
  deviations (SSD)** between the two normalized paths; rank ascending.
- **Selection:** trade the **top 20** (and top 5, 101–120 as controls) minimum-SSD
  pairs — a *portfolio*, not a single pair.
- **Trading:** next **6 months.** Open when the spread diverges by **2 historical
  standard deviations**; **close on convergence** (spread crosses zero). Force-close
  at end of the 6-month trading window.
- **Rolling:** start a new 6-month portfolio **every month** (overlapping books).
- **Risk controls:** market-neutral by construction (one long + one short leg per
  pair); wait-one-day rule (trade at next day's price) to avoid bid-ask bounce.
- **Costs:** results reported both gross and net; conservative round-trip
  transaction cost applied; one-day-wait removes most bid-ask-bounce bias.
- **Results:** **≈ 11% annualized** excess return on committed capital, low market
  beta, Sharpe far above the market; robust across sub-periods; **declines after
  ~1990** as the strategy is arbitraged away.
- **Statistical tests:** bootstrap vs random pairs; the profit is not explained by
  standard risk factors (small residual momentum/reversal loadings).
- **Limitations:** profits decay over time; sensitive to transaction costs and to
  the short rebate; concentration in utilities/financials `[recall]`.

### Vidyamurthy (2004) — *Pairs Trading: Quantitative Methods and Analysis*
- **Hypothesis:** cointegrated pairs share a stationary spread → tradeable.
- **Formation:** Engle-Granger cointegration test; hedge ratio = cointegrating
  vector (regression β), not scale balance.
- **Trading:** z-score bands on the cointegration residual; entry/exit as SD
  multiples. **Method book, not an empirical dataset** — no single canonical return.
- **Mentisrex gap:** template uses SSD selection + static scale-balance hedge, not an
  ADF-tested cointegrating β. Cointegration selection is the top ranked fidelity add.

### Avellaneda & Lee (2010) — *Statistical arbitrage in the US equities market*
- **Hypothesis:** idiosyncratic residuals (after removing common factors via PCA or
  ETF regression) are mean-reverting (OU process); trade the s-score.
- **Dataset / period:** US equities **1997–2007**, daily.
- **Formation:** estimate factor exposures (PCA or sector ETFs), residualize,
  fit an OU process, compute the **s-score** (standardized residual).
- **Trading:** enter at |s| ≈ 1.25, close near s ≈ 0.5–0.75 `[recall]`; require
  mean-reversion **speed** (half-life) below a threshold.
- **Results:** Sharpe ≈ 1.1 net after 2002 `[recall]`; higher earlier; decays with
  crowding; hurt in 2007 (the quant deleveraging).
- **Mentisrex gap:** **BLOCKED for the PCA/ETF residual variant** (no factor series /
  ETFs); the raw-spread z-score is the OU s-score's price-only cousin.

### Do & Faff (2010, 2012) — *Does simple pairs trading still work?*
- **Hypothesis:** Gatev's profitability persists but **declines**, and is
  concentrated in specific industries and in high-divergence-frequency pairs.
- **Dataset / period:** CRSP **1962–2009**, extending Gatev.
- **Method:** replicate Gatev exactly, then add **within-industry** pair
  restriction and a divergence/convergence "quality" screen.
- **Results:** post-2002 raw profits shrink toward **~ costs**; net returns often
  insignificant after 2002; **industry-matched** pairs and high-reversal pairs do
  better; sensitive to short costs and to the 2008 crisis `[recall]`.
- **Mentisrex relevance:** the decay result is the key prior — expect *thin* net
  edge on a 2014–2026 sample; the industry screen is **BLOCKED** (no sector map).

### Khandani & Lo (2007) — *What happened to the quants in August 2007?*
- **Hypothesis:** contrarian/mean-reversion equity market-neutral books are crowded;
  a simultaneous deleveraging causes a sharp, correlated drawdown then rebound.
- **Relevance:** the **failure mode** of any pairs/mean-reversion book — crowding +
  forced unwind. A robustness lens, not a reproduction target.

## 3. Cross-cutting methodology dimensions (feeds Workstream C)

| Dimension | Gatev | Vidyamurthy | Avellaneda-Lee | Do-Faff | Mentisrex frozen |
|---|---|---|---|---|---|
| Selection | SSD distance | cointegration (ADF) | OU half-life on residual | SSD + industry | **SSD distance** ✓ |
| Formation | 12 mo | rolling | 60-day est. window | 12 mo | **12 mo (252d)** ✓ |
| Hedge ratio | ~1 (normalized) | cointegrating β | factor betas | ~1 | **scale-balance mean(x)/mean(y)** |
| Spread object | normalized-price | cointeg. residual | OU residual (s-score) | normalized-price | **raw price z-score** (approx) |
| Entry | 2 SD | z-band | s ≈ 1.25 | 2 SD | **entry_z (2.0 default)** ✓ |
| Exit | convergence (0) | z ≈ 0 | s ≈ 0.5 | convergence | **exit_z (0.5 default)** |
| Trading window | 6 mo, rolling monthly | continuous | continuous | 6 mo | **single 70/30 OOS split** |
| Portfolio | top-20 (+5, control) | n pairs | many | top-20 + industry | **top-N (5/20/40)** ✓ |
| Costs | gross + net, 1-day wait | — | net | net, short cost | **engine commission (net)** |

## 4. What Mentisrex can and cannot reproduce (honest scope)

**Reproducible now (price-only, this campaign):**
- **Gatev 2006** distance selection + 2-SD divergence trading + top-N portfolio,
  US **and** India — the canonical anchor. This is Workstream B.
- Robustness sweeps: concentration (top-5/20/40), entry threshold (1.5/2/2.5),
  spread window (63/126), exit band — Workstream D.

**BLOCKED (data / platform, reported honestly — not faked):**
- **Cointegration selection (Vidyamurthy):** no ADF/Johansen step in the frozen
  template. *Unblock:* add a cointegration selector (research-layer, deferred).
- **PCA/ETF residual stat-arb (Avellaneda-Lee):** no factor series, no ETFs.
  *Unblock:* factor-return panel + ETF instruments.
- **Kalman dynamic hedge:** no state-space filter in the platform.
- **Sector/industry pairs (Do-Faff):** no GICS/sector map. *Unblock:* sector table.
- **Cross-country / ADR pairs:** no cross-listing linkage.
- **Gatev rolling monthly re-formation:** the runner does a single 70/30 split, not
  overlapping monthly books. *Unblock:* a walk-forward re-formation harness
  (deferred under the freeze; ranked in `Methodology_Fidelity.md`).

## 5. Priors that shape the campaign

1. **Diversification is the effect** (Gatev): one pair is a directional bet; the
   premium lives in the top-20 portfolio. → the top-5/20/40 axis is the core test.
2. **The edge decays** (Do-Faff): expect thin-to-negative *net* returns on a modern
   2014–2026 sample; a REJECT is the literature-consistent prior, not a defect.
3. **Crowding is the failure mode** (Khandani-Lo): drawdowns cluster; a single OOS
   slice can hide tail risk.
4. **Fidelity gaps bias against us** (raw-spread vs normalized/cointegration; static
   vs rolling formation) — they make reproduction *harder*, so any positive result
   is conservative.

## Known limitations / Skipped
- **Cointegration, Kalman, PCA/ETF, sector, cross-country variants NOT executed.**
  *Reason:* the frozen platform has no cointegration/Kalman/PCA step, no sector map,
  no ETF or cross-listing data. *Unblock:* each named above. Reported, not faked.
- Published magnitudes are cited from the papers; where a precise statistic was not
  in the extracted corpus it is marked `[recall]` rather than invented.
