# Momentum Literature Map

**Mentisrex Capital — Momentum Research Campaign**
**Agent:** Literature Intelligence + Methodology Fidelity
**Date:** 2026-07-31
**Status:** Literature review. Every number below is a *published* figure from the
cited paper, NOT an Mentisrex empirical result. Where an exact statistic is not
grounded in the extracted corpus or firmly recalled, it is marked `approx` or omitted.

Grounded from `research_corpus/extracted/`: JT-1993 (`ed02251ff8152b78.txt`),
Carhart-1997 (`58e49974b36d29d4.txt`), Fama-French-1993 (`f9df2e67a523c3cd.txt`).
Others are from the published literature and flagged `[recall]`.

---

## 1. Momentum families (scope map)

| Family | Signal object | Canonical anchor | Mentisrex-reproducible? |
|---|---|---|---|
| Cross-sectional (relative-strength) | rank of trailing return across names | Jegadeesh-Titman 1993/2001 | **Yes** — daily equity is exactly this |
| Time-series (absolute) | own trailing return vs zero | Moskowitz-Ooi-Pedersen 2012 | Partial — equity-only, no futures/multi-asset |
| Industry / sector | trailing return of the industry portfolio | Grinblatt-Moskowitz (Moskowitz-Grinblatt 1999) | **BLOCKED** — needs GICS/sector map |
| Residual (idiosyncratic) | momentum of factor-model residuals | Blitz-Huij-Martens 2011 | **BLOCKED** — needs factor return series to residualize |
| Factor momentum | trailing return of factor portfolios | Gupta-Kelly 2019, Ehsani-Linnainmaa 2022 | **BLOCKED** — needs factor return series |
| Momentum crash risk | conditional/dynamic momentum, bear-market beta | Daniel-Moskowitz 2016 | Partial — crashes observable, optionimal hedge needs factor betas |
| Capacity / turnover / cost | net-of-cost decay, break-even cost | Korajczyk-Sadka 2004, Frazzini-Israel-Moskowitz 2012 | Partial — engine has a cost model, no ADV/impact calibration data |
| Liquidity screens | price/size/volume filters | JT-1993 §, Hong-Lim-Stein 2000 | Partial — have volume, no market cap |
| Survivorship | free-of-survivor-bias sample | Carhart 1997 | **BLOCKED** — 2014-26 panel is survivor-prone, no delisting returns |
| International evidence | non-US cross-sections | Rouwenhorst 1998; AMP 2013 | Partial — India panel available |
| Microstructure | bid-ask/lead-lag decomposition of profits | JT-1993 §III-IV, Lo-MacKinlay 1990 | **BLOCKED** — no intraday/quote data |

---

## 2. Canonical papers

### 2.1 Jegadeesh & Titman (1993) — "Returns to Buying Winners and Selling Losers" *(grounded)*
- **Authors / year:** Jegadeesh, Titman. *Journal of Finance* 48(1), 1993, pp. 65–91.
- **Research question:** Do relative-strength strategies over 3–12 month horizons earn abnormal returns, reconciling practitioner momentum with the academic contrarian literature?
- **Hypothesis:** Buying past winners / selling past losers over intermediate horizons yields significant positive returns not explained by systematic risk or lead-lag effects.
- **Universe:** NYSE + AMEX stocks.
- **Sample:** Jan 1965 – Dec 1989 (CRSP daily returns file).
- **Data required:** monthly/daily total returns per stock. **No fundamentals.** → Mentisrex-compatible.
- **Methodology:** 16 J-month/K-month strategies (J,K ∈ {3,6,9,12}), plus 16 with a 1-week skip = 32 strategies. Rank into 10 deciles on trailing J-month return; equal-weight; buy top decile (winners), sell bottom decile (losers); zero-cost W−L.
- **Formation / holding / skip:** J ∈ {3,6,9,12} mo formation; K ∈ {3,6,9,12} mo holding; optional 1-week skip between formation and holding.
- **Weighting:** equal-weight deciles. **Overlapping** portfolios — in month *t* the strategy holds cohorts formed in *t, t−1, …, t−K+1*, revising 1/K of the book each month and carrying the rest.
- **Transaction costs:** headline results are **gross**; costs discussed but not netted into the main table.
- **Statistical tests:** t-stats on zero-cost mean returns; Bonferroni bound for the 32 tests; factor-model (systematic-risk) decomposition; serial-covariance decomposition.
- **Headline results:** best strategy = **12-month formation / 3-month holding**, **1.31%/month** with no skip, **1.49%/month** with a 1-week skip. Largest single t-stat **4.28** (12/3, skip-a-week). 6-month formation ≈ **1%/month** regardless of holding. All 32 significant except 3/3 no-skip.
- **Limitations:** ~half the year-1 abnormal return dissipates over the next 2 years (partial reversal); results concentrated outside January; no live transaction costs.
- **Key contribution:** established intermediate-horizon momentum as a robust anomaly; the founding cross-sectional momentum paper.
- **Implementation difficulty:** **Low.**
- **DATA-REQUIREMENT VERDICT:** **Reproducible on Mentisrex equity data.** (This is the paper Mentisrex already reproduces — `scripts/run_jt_us_reproduction.py`.)

### 2.2 Jegadeesh & Titman (2001) — "Profitability of Momentum Strategies: An Evaluation of Alternative Explanations" *[recall]*
- **Authors / year:** Jegadeesh, Titman. *Journal of Finance* 56(2), 2001.
- **Research question:** Does the 1993 momentum profit survive out-of-sample (1990s), and which explanation (risk vs behavioral) fits?
- **Hypothesis:** Momentum persists post-publication; profits reverse at long horizons, favoring behavioral over risk-based accounts.
- **Universe:** NYSE/AMEX/Nasdaq; excludes low-price (<$5) and smallest-cap stocks to rebut microstructure critiques.
- **Sample:** extends to 1998 (out-of-sample 1990–98).
- **Data required:** returns + price/size for screens. Size screen not fully replicable on Mentisrex (no market cap).
- **Methodology:** repeats the 6/6 decile design; adds long-horizon (up to 60 months) post-holding return analysis.
- **Formation / holding / skip:** 6/6 focus, 1-month skip typical.
- **Weighting:** equal-weight deciles.
- **Transaction costs:** gross headline; addresses cost/liquidity critiques qualitatively.
- **Statistical tests:** t-stats; subperiod stability; long-horizon reversal.
- **Headline results:** momentum ≈ **1.2%/month** out-of-sample in the 1990s `approx`; profits reverse over the subsequent ~13–60 months, undercutting a pure risk story.
- **Limitations:** reversal complicates risk interpretation; screens need size data.
- **Key contribution:** confirmed out-of-sample robustness and long-horizon reversal.
- **Implementation difficulty:** **Low-Medium** (price screen easy, size screen blocked).
- **DATA-REQUIREMENT VERDICT:** **Reproducible on Mentisrex equity data** for the return-only core; **partial** — the market-cap screen is BLOCKED (no fundamentals). Price (<$5) screen is doable.

### 2.3 Carhart (1997) — "On Persistence in Mutual Fund Performance" *(grounded)*
- **Authors / year:** Carhart. *Journal of Finance* 52(1), 1997.
- **Research question:** Is mutual-fund performance persistence explained by common factors, notably one-year momentum?
- **Hypothesis:** A 4-factor model (FF3 + momentum) explains most persistence; the "hot hands" effect is largely the JT momentum factor.
- **Universe:** survivor-bias-free sample of US equity mutual funds; PR1YR built from individual stocks.
- **Sample:** 1962–1993 `approx`.
- **Data required:** fund returns + FF factors (RMRF, SMB, HML) + a momentum factor (**PR1YR**). FF/SMB/HML are external series.
- **Methodology:** 4-factor time-series regression `r = α + b·RMRF + s·SMB + h·HML + p·PR1YR + e`. PR1YR = equal-weight top-30% minus bottom-30% of stocks on prior 11-month return, lagged 1 month.
- **Formation / holding / skip:** PR1YR uses **11-month formation, 1-month skip, 1-month holding** (monthly rebalanced 30/30 split).
- **Weighting:** equal-weight 30% tails.
- **Transaction costs:** studies fund expenses/turnover; factor itself is gross.
- **Statistical tests:** factor-model α t-stats; decile-of-funds sorts.
- **Headline results:** the momentum factor is the key driver of fund "hot hands"; funds do not skillfully *time* momentum. PR1YR is a large, priced zero-investment factor.
- **Limitations:** momentum factor is mechanical, not a claim funds actively harvest it.
- **Key contribution:** canonized **momentum as the 4th factor** (UMD/PR1YR); the standard momentum factor definition (11-1-1, 30/30 EW).
- **Implementation difficulty:** **Medium** — the *factor construction* (11-1 EW 30/30) is trivially reproducible on Mentisrex; the *fund-persistence study* is not (no fund data).
- **DATA-REQUIREMENT VERDICT:** **Partial.** PR1YR momentum-factor construction = **reproducible on Mentisrex equity data**. Full 4-factor attribution = **BLOCKED: needs SMB/HML factor return series** (no fundamentals to build them, no external factor file). Fund-persistence result = **BLOCKED: needs mutual-fund returns**.

### 2.4 Moskowitz, Ooi & Pedersen (2012) — "Time Series Momentum" (TSMOM) *[recall]*
- **Authors / year:** Moskowitz, Ooi, Pedersen. *Journal of Financial Economics* 104(2), 2012.
- **Research question:** Does an asset's *own* past return predict its future return (absolute, not relative momentum) across asset classes?
- **Hypothesis:** Past 12-month excess return positively predicts next-month return for 58 futures instruments; a vol-scaled TSMOM portfolio earns significant abnormal returns.
- **Universe:** **58 liquid futures/forwards** — equity indices, bonds, currencies, commodities.
- **Sample:** 1965–2009 `approx`.
- **Data required:** futures returns + **ex-ante volatility estimate** per instrument for position sizing. → not equity single-names.
- **Methodology:** sign of trailing 12-month excess return sets long/short; size each position at a constant volatility target (inverse-vol weighting); pooled predictive regressions.
- **Formation / holding / skip:** 12-month formation, 1-month holding, monthly rebalance; also 1–48 month lookback/holding grid.
- **Weighting:** **inverse-volatility (constant-vol targeting)**, not equal-weight.
- **Transaction costs:** discusses capacity; core results gross, some net robustness.
- **Statistical tests:** pooled t-stats; Sharpe; factor spanning vs cross-sectional momentum.
- **Headline results:** TSMOM significant and positive in every asset class; delivers a high Sharpe (`approx` ~1 for the diversified portfolio); exhibits its own crash/reversal at long lags.
- **Limitations:** multi-asset futures data intensive; vol-targeting adds estimation risk.
- **Key contribution:** defined **time-series momentum** as distinct from and complementary to cross-sectional momentum; inverse-vol construction standard.
- **Implementation difficulty:** **Medium-High.**
- **DATA-REQUIREMENT VERDICT:** **BLOCKED: needs futures / multi-asset return series** for the headline. A *single-asset-class equity TSMOM proxy* (sign of trailing return on each stock, vol-scaled) IS reproducible on Mentisrex but is NOT the paper's universe — mark any such run as a proxy, not a reproduction.

### 2.5 Asness, Moskowitz & Pedersen (2013) — "Value and Momentum Everywhere" (AMP) *[recall]*
- **Authors / year:** Asness, Moskowitz, Pedersen. *Journal of Finance* 68(3), 2013.
- **Research question:** Are value and momentum common, correlated phenomena across markets and asset classes with a shared (liquidity-risk) structure?
- **Hypothesis:** Value and momentum earn premia in every market/asset class; momentum is positively correlated across them, negatively with value; a global 3-factor model (market, value, momentum) prices them.
- **Universe:** stocks in US, UK, Europe, Japan **plus** non-equity: country indices, bonds, currencies, commodities.
- **Sample:** ~1972–2011 `approx`.
- **Data required:** international equity returns + **book-to-market (value)** + non-equity returns + a **funding-liquidity proxy**.
- **Methodology:** rank-weighted long/short factors per market; pooled/global factor regressions; correlation structure of value vs momentum.
- **Formation / holding / skip:** momentum = past **12-month return skipping the most recent month (12-1)**; monthly rebalance.
- **Weighting:** **rank-weighted** (weight ∝ cross-sectional rank), not decile equal-weight.
- **Transaction costs:** gross headline; later work (Frazzini-Israel-Moskowitz) addresses net.
- **Statistical tests:** factor α/t-stats; cross-market correlations; liquidity-beta loadings.
- **Headline results:** consistent value+momentum premia everywhere; strong common momentum factor; value and momentum negatively correlated so a 50/50 combo has a much higher Sharpe.
- **Limitations:** value leg needs fundamentals; liquidity proxy external.
- **Key contribution:** unified value+momentum as global, correlated factors; popularized **12-1 rank-weighted** momentum and the value/momentum diversification.
- **Implementation difficulty:** **High.**
- **DATA-REQUIREMENT VERDICT:** **BLOCKED for the paper as published: needs book-to-market fundamentals + multi-asset returns + liquidity proxy.** The **momentum-only, equity-only 12-1 leg** (US and India separately) IS reproducible on Mentisrex — worth running as a partial, clearly labeled.

---

## 3. Additional canonical / adjacent papers

### 3.1 Rouwenhorst (1998) — "International Momentum Strategies" *[recall]*
- **Authors / year:** Rouwenhorst. *Journal of Finance* 53(1), 1998.
- **Research question:** Does JT momentum exist outside the US?
- **Universe:** ~2,190 firms across **12 European countries**. **Sample:** 1980–1995 `approx`.
- **Methodology:** JT-style deciles (diversified international portfolio), 3–12 month J/K, 1-month skip.
- **Formation/holding/skip:** ~6/6, 1-month skip. **Weighting:** roughly equal-weight; results controlled for size.
- **Transaction costs:** gross. **Headline:** an internationally diversified winner-minus-loser earns ≈ **1%/month** `approx`; momentum present in every sampled country and stronger in small firms.
- **Key contribution:** first broad out-of-US evidence — momentum is not US-data-mining.
- **DATA-REQUIREMENT VERDICT:** **Reproducible in spirit on the Mentisrex India panel** (1127 .NS/.BO names, 2014-26) as an independent international replication. Not the same countries/period, so label as *international extension*, not a reproduction of Rouwenhorst.

### 3.2 Moskowitz & Grinblatt (1999) — "Do Industries Explain Momentum?" (industry momentum) *[recall]*
- **Authors / year:** Moskowitz, Grinblatt. *Journal of Finance* 54(4), 1999.
- **Research question:** Is individual-stock momentum actually an *industry* effect?
- **Universe:** US stocks grouped into ~20 industries. **Sample:** 1963–1995 `approx`.
- **Methodology:** momentum on industry portfolios; test whether industry momentum subsumes individual momentum.
- **Formation/holding/skip:** ~6/6, 1-week/1-month skip variants. **Weighting:** value-weight industries.
- **Headline:** **industry momentum is strong and largely explains individual-stock momentum** in their tests; industry component profitable, individual component weaker once industry is controlled.
- **Key contribution:** reframed momentum as substantially an industry phenomenon.
- **DATA-REQUIREMENT VERDICT:** **BLOCKED: needs a GICS/industry classification map.** No sector map exists in Mentisrex. Unblock: ingest a symbol→sector table.

### 3.3 Blitz, Huij & Martens (2011) — "Residual Momentum" *[recall]*
- **Authors / year:** Blitz, Huij, Martens. *Journal of Empirical Finance* 18(3), 2011.
- **Research question:** Does momentum in *factor-model residuals* beat total-return momentum?
- **Universe:** US stocks. **Sample:** ~1930–2009 `approx`.
- **Methodology:** estimate FF3 residuals per stock over a rolling window; rank on standardized residual return over 12-1; long/short.
- **Formation/holding/skip:** 12-1, monthly. **Weighting:** equal-weight tails.
- **Headline:** residual momentum has **~half the volatility and ~double the Sharpe** of total-return momentum, with far smaller crash exposure (near-zero dynamic factor bets).
- **Key contribution:** showed most of momentum's dynamic risk (and crash) comes from factor exposure, not the idiosyncratic signal.
- **DATA-REQUIREMENT VERDICT:** **BLOCKED: needs factor return series (RMRF/SMB/HML) to residualize.** No factor series and no fundamentals to build them. Unblock: obtain/construct FF factor returns for US and India.

### 3.4 Daniel & Moskowitz (2016) — "Momentum Crashes" *[recall]*
- **Authors / year:** Daniel, Moskowitz. *Journal of Financial Economics* 122(2), 2016.
- **Research question:** When and why does momentum crash, and can it be hedged?
- **Universe:** US (plus international/other-asset robustness). **Sample:** 1927–2013 `approx`.
- **Methodology:** condition momentum returns on market state and volatility; document optioin-like short-call payoff in panics; build a **dynamic (vol- and state-scaled) momentum** overlay.
- **Formation/holding/skip:** standard 12-1 WML. **Weighting:** decile.
- **Headline:** momentum suffers rare, severe crashes in **panic states** (bear market + rising vol + market rebound), e.g. mid-1932 and **2009** (WML fell dramatically). A dynamically weighted momentum nearly **doubles the Sharpe** and cuts crash risk.
- **Key contribution:** characterized momentum's negative skew / crash timing and a hedge.
- **DATA-REQUIREMENT VERDICT:** **Partial.** Crash *observation* (conditional on realized market state/vol from the equity panel) is reproducible on Mentisrex. The *bear-beta hedge* / optioinality decomposition ideally uses factor betas → **BLOCKED for the full hedge: needs factor series.** The 2008-09 crash predates the 2014-26 sample, so the canonical episode is not in-window — note this limitation.

---

## 4. Cross-cutting themes

- **Capacity / cost decay** (Korajczyk-Sadka 2004; Frazzini-Israel-Moskowitz 2012): net momentum survives realistic costs at institutional scale but decays; break-even costs are non-trivial. Mentisrex has a cost model (10 bps commission/side + 10 bps slippage) but **no ADV / market-impact calibration data** → net figures are indicative, not capacity-calibrated.
- **Liquidity / microstructure** (JT-1993 §III-IV; Lo-MacKinlay 1990): part of raw short-horizon reversal profit is bid-ask/lead-lag; the 1-week skip exists to dodge it. **BLOCKED for decomposition: no quote/intraday data.**
- **Survivorship** (Carhart 1997): survivor-free samples are essential; the Mentisrex 2014-26 panel is assembled from currently-listed names → **survivor-prone, no delisting returns** — momentum profits are likely biased and this must be stated on every result.

---

## 5. Known limitations / data-blocked

Per project rule, each skipped item names (a) what, (b) why impossible now, (c) unblock.

1. **Industry/sector momentum (Moskowitz-Grinblatt).** What: sector-portfolio momentum. Why: no GICS/sector classification in Mentisrex. Unblock: ingest a symbol→sector map.
2. **Residual & factor momentum (Blitz; Gupta-Kelly).** What: momentum on FF residuals / factor portfolios. Why: no factor return series and no fundamentals to construct RMRF/SMB/HML. Unblock: obtain or build FF factor returns for US + India.
3. **TSMOM (MOP 2012) and Value & Momentum Everywhere (AMP 2013) as published.** What: multi-asset / value legs. Why: no futures/multi-asset returns, no book-to-market fundamentals, no funding-liquidity proxy. Unblock: ingest futures panels, fundamentals, and a liquidity series. (Equity-only momentum legs are reproducible as labeled partials.)
4. **Carhart 4-factor attribution + fund persistence.** What: SMB/HML α decomposition and fund result. Why: no factor series, no mutual-fund returns. Unblock: external FF factor file + fund return database. (PR1YR factor construction itself is reproducible.)
5. **JT-2001 / rank screens by market cap.** What: size-based liquidity screens. Why: no market-cap/fundamentals. Unblock: ingest shares-outstanding or market-cap data. (Price-based <$5 screen is doable.)
6. **Microstructure decomposition & Momentum-Crash hedge episode.** What: bid-ask/lead-lag split and the 2008-09 crash. Why: no quote/intraday data; 2008-09 predates the 2014-26 window. Unblock: intraday/quote data and a longer historical panel.
7. **Survivorship-clean returns.** What: unbiased momentum estimates. Why: panel holds currently-listed names only, no delisting returns. Unblock: a point-in-time membership + delisting-return dataset.
