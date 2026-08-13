# Mentisrex Capital — Alpha Taxonomy, Hypothesis Factory & Research Scorecard

Companion to `RESEARCH_PROGRAM.md` (which defines the org, governance, lifecycle, promotion/retirement, knowledge management, and continuous improvement). This document is the **catalog of where alpha comes from**, the **assembly line every idea travels**, and the **numeric scorecard every experiment receives**.

---

# PART 1 — Taxonomy of alpha

15 categories. Each: economic intuition · why it should exist (who loses) · works-when · fails-when · datasets · features · statistical validation focus. Success criteria and gate thresholds are defined once in `RESEARCH_PROGRAM.md` §1/§4 and are not repeated per category.

### 1. Trend (time-series)
- **Intuition:** prices trend because information diffuses slowly and investors under-react, then over-react.
- **Why it exists:** risk transfer from hedgers/late reactors to trend followers; behavioral anchoring.
- **Works:** persistent macro regimes, crises (trend is long-vol-like), clear directional moves.
- **Fails:** choppy range-bound markets, sharp reversals, crowded CTA unwinds.
- **Datasets:** daily OHLCV across assets; futures continuous series.
- **Features:** moving-average distance, breakout channels, time-series momentum sign, volatility-scaled trend.
- **Validation:** regime-conditional performance; whipsaw/turnover sensitivity; must survive a reversal subsample.

### 2. Momentum (cross-sectional)
- **Intuition:** past relative winners keep winning over 3-12 months.
- **Why it exists:** under-reaction to firm news; slow institutional repositioning; disposition effect.
- **Works:** stable, trending, low-dispersion-of-beliefs markets.
- **Fails:** momentum crashes (post-bear rebounds, e.g. 2009); high-volatility reversals.
- **Datasets:** point-in-time price, split/dividend adjusted; survivorship-free universe.
- **Features:** 12-1 return, residual (idiosyncratic) momentum, 52-week-high proximity, momentum consistency.
- **Validation:** deflated Sharpe; drawdown vs. plain 12-1; crash-regime stress; breadth check.

### 3. Mean reversion (short-horizon)
- **Intuition:** prices overshoot on liquidity shocks and revert.
- **Why it exists:** liquidity-provision premium; overreaction to noise.
- **Works:** high-liquidity names, calm markets, intraday-to-weekly horizons.
- **Fails:** trends, gap events, during regime breaks (reversion becomes continuation).
- **Datasets:** daily/intraday OHLCV; volume.
- **Features:** short-term reversal (1-5d), distance from moving average, RSI, Bollinger position.
- **Validation:** net-of-cost survival (turnover kills it); capacity; asymmetry between up/down moves.

### 4. Value
- **Intuition:** cheap assets outperform expensive ones long-run.
- **Why it exists:** compensation for distress/illiquidity risk; correction of extrapolation errors.
- **Works:** recoveries, rising-rate/rotation regimes, wide valuation dispersion.
- **Fails:** long growth-led runs (2010s), value traps, secular disruption.
- **Datasets:** point-in-time fundamentals with reporting lag; price; survivorship-free universe.
- **Features:** B/M, E/P, FCF yield, EV/EBITDA, sales/price; sector-neutral composites.
- **Validation:** control for market/size; survive a value-drought subsample; slow decay (long horizon).

### 5. Quality
- **Intuition:** durable profitability is under-priced.
- **Why it exists:** investors under-weight persistence of margins and mis-price accruals.
- **Works:** flight-to-quality, late cycle, risk-off.
- **Fails:** junk rallies, early-cycle recoveries.
- **Datasets:** point-in-time fundamentals (ROE, gross profitability, accruals, leverage).
- **Features:** gross profits/assets, ROIC, accruals (Sloan), earnings stability, debt/equity.
- **Validation:** low correlation to value/momentum (must diversify); accrual-leakage checks.

### 6. Carry
- **Intuition:** earn the yield differential; high-yield assets outperform low-yield on average.
- **Why it exists:** premium for bearing crash/liquidity risk; hedging demand.
- **Works:** calm, low-vol, stable-rate regimes.
- **Fails:** carry unwinds / risk-off spikes (carry is short-vol; crashes are violent).
- **Datasets:** rates, FX forwards, futures curves (roll yield), dividend/borrow.
- **Features:** roll yield, forward-spot spread, rate differential, curve slope.
- **Validation:** tail-risk conditioning; drawdown in risk-off; positive across ≥2 regimes.

### 7. Volatility
- **Intuition:** implied vol systematically exceeds realized (variance risk premium); low-vol stocks earn more per unit risk.
- **Why it exists:** insurance demand (VRP); leverage constraints (low-vol anomaly).
- **Works:** VRP in calm-to-normal vol; low-vol anomaly in leverage-constrained regimes.
- **Fails:** vol spikes (short-vol blows up); low-vol underperforms in junk rallies.
- **Datasets:** options-implied vol surface; realized vol from returns; VIX-style indices.
- **Features:** implied-realized spread, vol-risk-premium, realized/idiosyncratic vol, beta, max daily return.
- **Validation:** aggressive tail stress (2018/2020); financing cost for low-vol leverage; convexity accounting.

### 8. Market microstructure
- **Intuition:** short-lived edges from order flow, liquidity provision, temporary price pressure.
- **Why it exists:** impatient liquidity demanders pay providers; latency/queue advantages.
- **Works:** high-liquidity, high-frequency horizons, with low latency and tight cost control.
- **Fails:** any cost/latency disadvantage; capacity is tiny.
- **Datasets:** intraday trades/quotes, order-book snapshots (only if already ingested).
- **Features:** order-flow imbalance, bid-ask bounce, queue position, volume-clock features, VPIN.
- **Validation:** brutal cost + impact modeling; capacity estimate mandatory; latency assumptions explicit.

### 9. Event-driven
- **Intuition:** prices adjust slowly to discrete corporate events.
- **Why it exists:** limits to arbitrage (hard-to-short, index flows), under-reaction to announcements.
- **Works:** around scheduled/unscheduled events with clean timestamps.
- **Fails:** crowded event trades; when entry lags the announcement; leakage inflates backtests.
- **Datasets:** earnings dates + surprises, guidance, M&A, index reconstitution, insider filings, buybacks.
- **Features:** SUE / PEAD drift, earnings surprise, index add/delete flags, insider-buy clusters.
- **Validation:** strict point-in-time event timestamps; realistic entry (next open); event-count power.

### 10. Fundamental (cross-sectional, slow)
- **Intuition:** firm characteristics beyond value/quality predict returns (growth, investment, financing).
- **Why it exists:** mis-pricing of investment/issuance signals; agency effects.
- **Works:** long horizons, broad universes.
- **Fails:** crowded factors; data-mined characteristics with no story.
- **Datasets:** point-in-time fundamentals + issuance/buyback + capex.
- **Features:** asset growth, net share issuance, investment/assets, external financing, margin trends.
- **Validation:** orthogonality to known factors; economic-story gate is strict (data-mining risk highest here).

### 11. Alternative data
- **Intuition:** information not yet in price — text, positioning, web, satellite, card spend.
- **Why it exists:** signal is new, unevenly distributed, and slow to be arbitraged.
- **Works:** while the data edge is exclusive and cheaply actionable.
- **Fails:** once commoditized; look-ahead in timestamps; tiny sample / short history.
- **Datasets:** news/text, COT positioning, search/attention, consumer transactions (only if licensed + ingested).
- **Features:** sentiment tone, dispersion, attention spikes, positioning extremes, nowcast surprise.
- **Validation:** orthogonality to price signals; ruthless timestamp/leakage audit; short-history humility.

### 12. Options
- **Intuition:** the options surface encodes forward-looking risk-neutral info and supply/demand imbalances.
- **Why it exists:** hedging/speculative flow distorts skew and term; dealers charge for gamma.
- **Works:** liquid single-name and index options; regimes with stable dealer positioning.
- **Fails:** illiquid strikes, pin risk, vol regime breaks; expensive to trade.
- **Datasets:** full options chains (implied vol, greeks, OI), underlying price.
- **Features:** skew, term-structure slope, put-call ratio, implied-vol change, gamma exposure proxies.
- **Validation:** realistic options transaction costs; greeks accounting; dealer-positioning conditioning.

### 13. Cross-asset
- **Intuition:** signals in one asset class predict another (bond-equity, FX-commodity, credit-equity).
- **Why it exists:** slow information transmission across siloed markets.
- **Works:** when lead-lag relationships are stable across regimes.
- **Fails:** correlation regime shifts; spurious in-sample linkages.
- **Datasets:** multi-asset prices (equity, rates, FX, commodities, credit).
- **Features:** credit-spread change, yield-curve moves, FX carry, commodity momentum as equity predictors.
- **Validation:** out-of-sample across regimes; guard against multiple-testing across asset pairs.

### 14. Macro
- **Intuition:** economic-cycle risk premia — growth, inflation, policy surprises.
- **Why it exists:** compensation for cyclical risk; slow price adjustment to macro releases.
- **Works:** across full cycles with regime awareness.
- **Fails:** structural breaks; revised/lookahead macro data; few independent observations.
- **Datasets:** macro releases (point-in-time vintages, NOT revised), rates, growth/inflation nowcasts.
- **Features:** macro-surprise indices, growth/inflation nowcasts, policy-rate expectations, regime indicators.
- **Validation:** vintage data only; low effective breadth → demand very strong story; regime robustness.

### 15. Statistical arbitrage
- **Intuition:** temporary dislocations between related instruments revert (pairs, baskets, factors).
- **Why it exists:** liquidity/flow imbalances break cointegration temporarily.
- **Works:** stable relationships, mean-reverting spreads, adequate liquidity.
- **Fails:** structural breaks (relationship dies), crowding, cost erosion; reversion → divergence.
- **Datasets:** price panels; sometimes fundamentals for pair selection.
- **Features:** cointegration residual (z-score), spread half-life, PCA/factor residuals, correlation clusters.
- **Validation:** stability of the relationship OOS; half-life estimation; cost survival; break detection.

---

# PART 2 — The Hypothesis Factory

Every idea travels the same assembly line. A stage can only pass an idea forward or kill it. Gates and thresholds are `RESEARCH_PROGRAM.md` §4; this is the physical flow and the platform tool at each stage.

| # | Stage | Input → output | Tool / artifact | Kill condition |
|---|---|---|---|---|
| 1 | **Paper** | source → `PaperSummary` | `assistant.read_paper` | no economic mechanism sentence |
| 2 | **Hypothesis** | summary → falsifiable directional bet + null | `assistant.generate_hypotheses` → `Hypothesis` | not reducible to signal/universe/horizon/sign |
| 3 | **Feature mapping** | hypothesis → required features | `features.registry` / `library` | feature not computable from available data |
| 4 | **Implementation** | features → `Strategy` subclass | `backtesting.strategy` + `assistant.review_code` | `has_lookahead == True` (any leakage finding) |
| 5 | **Backtest** | strategy → in-sample report | `BacktestEngine` | wrong sign, or negative net-of-cost |
| 6 | **Walk-forward** | strategy → OOS track record | rolling refit + purge/embargo (CPCV) | OOS decay > 40% |
| 7 | **Statistical validation** | OOS → verdict | `research.validation` + deflated Sharpe/PBO | fails multiple-testing-corrected significance |
| 8 | **Paper trading** | verdict PASS → live-paper record | `paper.engine` + `journal` | live decay, or realized cost ≠ modeled |
| 9 | **Capital allocation** | paper PASS → staged live weight | production checklist (`RESEARCH_PROGRAM.md` §8) | any unchecked box |
| 10 | **Monitoring** | live → health metrics | `/metrics` + risk monitor | breach of pre-set kill metric |
| 11 | **Retirement** | decayed alpha → archived record | `research.store` + post-mortem | edge gone / capacity exhausted |

Every stage writes to the `ExperimentRecord` (immutable, `dataset_fingerprint`-pinned). Nothing skips a stage. Nothing re-enters without a knowledge-base check (§9 of the program) so dead ideas are never re-run by accident.

---

# PART 3 — Research Scorecard

Every experiment receives ten scores, each 0-10. Scores are recorded on the `ExperimentRecord`. They serve two purposes: **prioritize** the queue (pre-backtest, using the estimable axes) and **rank** validated candidates for capital (post-validation, using all axes).

| Axis | 0 | 10 | Measured by |
|---|---|---|---|
| **Novelty** | crowded, well-known | new signal / new data | knowledge-base similarity + literature crowding |
| **Economic rationale** | no story | named loser, durable mechanism | written mechanism, reviewed |
| **Implementation quality** | leakage risk, fragile code | clean, leakage-free, tested | `assistant.review_code` findings |
| **Statistical confidence** | marginal, undeflated | high deflated Sharpe, low PBO | deflated Sharpe, PBO, t-stat |
| **Robustness** | fragile params, one regime | stable across params/subsamples/universes | parameter CV, subsample spread |
| **Capacity** | tiny, cost-eaten | scales to target AUM | ADV participation, impact model |
| **Turnover** | very high (cost-heavy) | low, cost-efficient | annual turnover, net-vs-gross Sharpe |
| **Execution risk** | hard fills, wide spreads | liquid, easy to trade | spread, fill-rate, capacity overlap |
| **Correlation** | high ρ to live book | orthogonal | marginal contribution to portfolio IR |
| **Expected longevity** | fad / easily arbitraged | structural, slow-decaying | mechanism durability, crowding trend |

**Priority score (pre-backtest queue):** `economic_rationale × (novelty + robustness_prior + capacity + 1/turnover_prior)` — conviction is a multiplier (a story-less idea scores ~0). Matches `RESEARCH_PROGRAM.md` §3.

**Allocation rank (post-validation):** weighted sum, weights `statistical_confidence 0.25, robustness 0.20, correlation 0.20, capacity 0.15, longevity 0.10, execution_risk 0.10`. Only PASS-verdict experiments are ranked for capital. Ties break toward lower correlation (diversification first).

---

*Taxonomy tells us where to dig. The Factory makes sure every dig is done identically and reproducibly. The Scorecard decides which holes are worth capital. The 500-idea backlog (`HYPOTHESIS_BACKLOG.md`) is the map of where to dig first.*
