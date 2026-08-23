# Mentisrex Capital — Formal Trading Strategy (v1.0, superseded)

**Document version:** 1.0  
**Date:** August 19, 2026  
**Classification:** Internal — Strategy & Research  
**Author:** Mentisrex Research Team

> **Superseded 2026-08-23.** The firm's current strategy is the ten-sleeve
> systematic programme (v3.0) in
> [`TRADING_STRATEGY_FORMAL_V2.md`](TRADING_STRATEGY_FORMAL_V2.md). This
> document is kept as the historical record of the long-only volume-momentum
> book it describes — that book is no longer the strategy in use, but nothing
> here is factually wrong about what it was.

---

## 1. Firm Identity and Philosophy

Mentisrex Capital is a systematic quantitative investment firm. All investment decisions are derived from repeatable, data-driven processes — no discretionary overrides. The firm's edge is the disciplined execution of academically grounded factors on liquid US equities, combined with rigorous backtesting infrastructure that guards against overfitting, look-ahead bias, and survivorship bias.

**Core belief:** Markets are not fully efficient in the short to medium term. Cross-sectional price momentum, amplified by abnormal volume, provides a persistent signal that can be harvested systematically with proper risk management.

---

## 2. Investment Universe

### 2.1 Eligible Securities

- **Asset class:** US-listed common equities only
- **Exchanges:** NYSE, NASDAQ, NYSE American (AMEX)
- **Minimum price:** ≥ USD 5.00 (eliminates penny stocks and their manipulation risk)
- **Minimum liquidity:** Average daily dollar volume ≥ USD 500,000 over the trailing 25 trading days
- **Exclusions:**
  - Foreign-listed ADRs and ordinary shares with non-US exchange suffixes (`.NS`, `.BO`, `.L`, `.TO`, `.AX`, etc.)
  - Instruments with CIK-format identifiers (data integrity filter)
  - Securities with fewer than 30 days of continuous OHLCV history at the time of scoring

### 2.2 Universe Size

At any point during the 2020–2024 backtest period, the investable universe comprised approximately 500–700 US-listed names satisfying all filters on a given trading day. The strategy concentrates into a 40-name portfolio, representing roughly 6–8% of the eligible universe.

---

## 3. Signal Construction — Volume-Momentum Composite

### 3.1 Economic Rationale

Price momentum (the tendency of recent winners to continue outperforming) is one of the most robust and replicated anomalies in empirical finance (Jegadeesh & Titman 1993; Carhart 1997; Asness, Moskowitz & Pedersen 2013). However, raw momentum suffers from high turnover and sharp reversals, particularly during market stress.

Volume serves as a confirmation signal. Abnormally high volume accompanying a price trend indicates genuine institutional participation rather than thin-market drift. Conversely, momentum on low volume may reflect illiquidity rather than conviction.

The Mentisrex signal **amplifies momentum by the degree of volume abnormality**, producing a composite that is more selective and has a stronger economic interpretation than either factor alone.

### 3.2 Signal Formula

For each eligible security *i* on scoring date *t*:

```
Score(i, t) = Momentum(i, t) × VolumeMultiplier(i, t)
```

Where:

```
Momentum(i, t)         = (Close_{t-5} − Close_{t-25}) / Close_{t-25}

VolumeMultiplier(i, t) = clamp(Volume_{t-1} / AvgVolume_{t-25:t-1}, 0.5, 5.0)
```

**Lookback windows:**

| Component | Window | Rationale |
|---|---|---|
| Short price lag | 5 trading days (~1 week) | Captures recent price direction |
| Long price lag | 25 trading days (~1 month) | 20-day momentum baseline |
| Volume comparison | 1 day vs. trailing 25 days | Detects institutional accumulation |

**Clamping the volume multiplier** to [0.5, 5.0] prevents a single anomalous volume spike (corporate event, index rebalance) from dominating the composite score and prevents denominator near-zero from destroying the signal.

All prices are split- and dividend-adjusted using the adjustment factor from the Alpaca Markets data feed.

### 3.3 Implementation — SQL Window Functions

The signal is computed as a single pre-backtest SQL pass over the full OHLCV dataset, using DuckDB window functions:

```sql
LAG(adj_close, 5)  OVER (PARTITION BY symbol ORDER BY dt)  -- Close_{t-5}
LAG(adj_close, 25) OVER (PARTITION BY symbol ORDER BY dt)  -- Close_{t-25}
LAG(adj_volume, 1) OVER (PARTITION BY symbol ORDER BY dt)  -- Volume_{t-1}
AVG(adj_volume)    OVER (PARTITION BY symbol ORDER BY dt
                         ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING) -- AvgVol_25d
```

This design eliminates database cursor conflicts during the simulation loop and makes signal computation O(N) rather than O(N × rebalances).

---

## 4. Portfolio Construction

### 4.1 Rebalancing Frequency

**Weekly** — every Monday (or next trading day if holiday). This cadence is chosen deliberately:

- **Not HFT:** No intraday signals, no market microstructure exploitation
- **Not buy-and-hold:** Weekly turnover captures momentum persistence (typical momentum half-life: 2–4 weeks)
- **Practical:** ~250 rebalances over 4 years, realistic for institutional execution at mid-cap liquidity

### 4.2 Position Selection

On each rebalancing date:

1. Score all eligible securities using the composite signal for that date
2. Rank by score descending
3. Select the **top 20%** of scored names (approx. 100–140 names in a 500–700 name universe)
4. Concentrate into the **top 40 names** from that 20% cohort (the highest-conviction subset)

### 4.3 Position Sizing

**Equal-weight** within the long book:

- Target weight per name: **2.5% of NAV** (1/40)
- Maximum gross exposure: **100% of NAV** (fully invested, long-only)
- No leverage employed in live trading

Positions are sized at the open price of the day following the signal date. Equal-weight is used rather than score-weighted because:
- Score magnitude has not been calibrated to predict forward return magnitude
- Equal-weight prevents a few high-scoring names from dominating tail risk
- Simpler to execute and audit

### 4.4 Long-Only Constraint

The strategy is **long-only**. Short positions in momentum strategies carry asymmetric risk: momentum crashes (e.g., February–March 2020 COVID reversal) produce short squeezes that are many times larger than the short alpha. The long book benefits from the same crashes via cash holdings when positions are exited, recovering through the ensuing recovery.

---

## 5. Risk Management

### 5.1 Position Concentration Limit

No single position may exceed **5.0% of NAV** at order entry (2× the 2.5% target weight). This guards against:

- Signal errors placing a large bet on a single miscalculated name
- Positions grown by price appreciation far beyond target weight

Closing orders (reducing or exiting existing positions) are **exempt** from this check — a position cannot be trapped at a grown size because the risk engine refuses to close it.

### 5.2 Gross Leverage Limit

Maximum gross exposure: **2.0× NAV** at the time of order entry. This is a transient limit — set above 1.0× to accommodate the rebalancing window where new entries are initiated before prior exits settle. In steady state, gross exposure targets 1.0× (100% invested).

### 5.3 Drawdown Circuit Breaker

A configurable maximum drawdown halt (default: 99%, effectively disabled for research). In live trading, this would be set to 20–25% peak-to-trough NAV decline, after which the strategy flattens all positions and waits for PM review before re-entering.

### 5.4 Transaction Cost Model

| Cost component | Rate |
|---|---|
| Commission | 0.5 bps per side (5 bps round-trip) |
| Spread | 3 bps per side |
| Market impact | Not modeled (assumed acceptable at 40 × $500k+ ADV names) |

Total round-trip friction: approximately **16 bps** (commission × 2 + spread × 2). At weekly rebalancing, this equates to roughly **8–10% annualized drag** on gross alpha — a realistic cost hurdle the strategy must clear.

---

## 6. Execution

### 6.1 Order Types

All orders are routed as **market-on-open (MOO)** at the next trading day's opening print. This:
- Avoids look-ahead bias (signal computed on close *t*, filled on open *t+1*)
- Provides a liquid, auditable execution price
- Eliminates intraday timing decisions

### 6.2 Broker and Data Infrastructure

| Component | Vendor |
|---|---|
| Market data (OHLCV, fundamentals) | Alpaca Markets API |
| Paper trading broker | Alpaca Markets Paper Account |
| OHLCV storage | DuckDB (`data/analytics.duckdb`) |
| Backtest engine | Mentisrex internal (`src/mentisrex/backtesting/`) |
| Signal computation | DuckDB SQL window functions (pre-backtest) |

### 6.3 Rebalancing Procedure

1. EOD signal computation (pre-computed offline, or recomputed nightly)
2. Current holdings retrieved from OMS
3. Target portfolio constructed from top-40 selection
4. Delta computed: new positions to open, existing positions to close/trim, unchanged positions left
5. MOO orders submitted for all deltas before 9:28 AM ET
6. Fills confirmed and portfolio state updated

---

## 7. Performance Expectations and Risk Metrics

### 7.1 Benchmark

**SPY (S&P 500 ETF)** — the long-only US equity market beta. The strategy must demonstrate meaningful Sharpe-adjusted outperformance over SPY to justify active management costs.

### 7.2 Expected Return and Risk Profile

These ranges are forward-looking estimates based on the academic literature and the 2020–2024 backtest:

| Metric | Target range |
|---|---|
| Net CAGR | 12–20% |
| Annualized volatility | 18–28% |
| Sharpe ratio (net of costs) | 0.60–1.10 |
| Maximum drawdown | −25% to −40% |
| Annual turnover | 200–400% of NAV |
| Average holding period | 5–15 trading days |

The strategy carries **higher volatility than the S&P 500** (typical market vol: 15–18%) because it concentrates in momentum names that exhibit higher idiosyncratic volatility. This is the source of its potential excess return.

### 7.3 Known Strategy Risks

| Risk | Description | Mitigation |
|---|---|---|
| Momentum crashes | Sharp reversals during market panics (COVID Feb–Mar 2020, GFC Oct 2008) cause drawdowns 2–3× market magnitude | Long-only constraint eliminates short-squeeze exposure; drawdown halt limits capital loss |
| Crowding | Many quant funds run similar momentum signals; crowded exits amplify drawdowns | Volume filter selects names with ongoing institutional participation, not already-crowded trades |
| Transaction costs | High turnover at 200–400% pa consumes gross alpha | Cost model explicitly deducted; net Sharpe is the headline metric |
| Data quality | Alpaca feed historically contained non-US suffixes and CIK-format IDs | Universe filters (`NOT LIKE '%.NS'`, `NOT LIKE 'CIK%'`, etc.) applied at signal computation |
| Survivorship bias | Backtest uses point-in-time data; dead companies excluded | Alpaca feed includes delisted stocks in historical data; signal construction does not require the stock to exist today |

---

## 8. Research Roadmap and Planned Improvements

### 8.1 Near Term (Q4 2026)
- **Volatility-scaled sizing:** Replace equal-weight with inverse-volatility weighting (target 1% annualized contribution per name). Reduces concentration of risk in high-vol momentum names.
- **Factor decay monitoring:** Weekly IC (information coefficient) tracking to detect regime changes where momentum signal degrades.
- **Sector neutrality:** Cap sector allocation at 25% of portfolio to prevent industry bubble concentration.

### 8.2 Medium Term (2027)
- **Multi-factor composite:** Add short-term reversal (1-day lag) to filter out signal noise; add earnings momentum (SUE) as a fundamental anchor.
- **Capacity analysis:** Formal market impact modeling for larger AUM. Current strategy capacity estimated at USD 50M–150M before impact costs exceed signal alpha.
- **Live paper trading forward test:** 6-month paper trading validation before any capital deployment.

### 8.3 Long Term
- **Options overlay:** Sell covered calls on concentrated positions at high Sharpe to monetize volatility premium.
- **International expansion:** Extend universe to developed-market equities (EAFE) using same signal structure once data quality is validated.

---

## 9. Governance

### 9.1 Change Management
All strategy parameter changes (lookback windows, position limits, universe filters) require:
1. Documentation in the experiment registry (`docs/AIDP_M7_EXPERIMENT_REGISTRY.md`)
2. Full backtest re-run on the full 2020–2024 period
3. Commit to version control with conventional-commit message

No undocumented strategy changes. No data-mined parameter tweaks without out-of-sample validation.

### 9.2 Backtest Anti-Overfitting Protocol
- **No in-sample optimization of lookback windows:** 5-day and 25-day lags are fixed from the Jegadeesh-Titman (1993) literature. Not tuned to this dataset.
- **Single backtest per hypothesis:** Each signal variant is tested once on the full period. No repeated testing with adjusted parameters until the result "looks good."
- **Transaction costs always included:** Gross return is never reported as a headline metric.
- **Full-period reporting:** Results reported for the full 2020–2024 window. Sub-period analysis is supplemental, not used for parameter selection.

### 9.3 Model Risk
This is a research-stage system. No real capital is deployed. All live trading decisions are paper-traded for a minimum of 6 months before any capital commitment. The codebase and this document are subject to independent audit before live deployment.

---

## Appendix A — Backtest Configuration Summary

| Parameter | Value |
|---|---|
| Backtest period | 2020-01-02 to 2024-12-31 |
| Universe | US equities, price ≥ $5, ADV ≥ $500k |
| Signal | Volume-momentum composite (5d/25d × vol ratio) |
| Rebalancing | Weekly (every Monday) |
| Position count | 40 |
| Position size | 2.5% NAV equal-weight |
| Direction | Long-only |
| Commission | 0.5 bps/side |
| Spread | 3 bps/side |
| Max drawdown halt | 99% (disabled for research) |
| Data source | Alpaca Markets (DuckDB) |
| Engine | `src/mentisrex/backtesting/engine.py` |
| Script | `scripts/run_backtest.py` |

---

## Appendix B — Key Bugs Identified and Fixed During Development

The following engineering issues were discovered and remediated during backtest development. They are documented here because each represents a class of backtest implementation error that can silently corrupt results.

| Bug | Symptom | Root Cause | Fix |
|---|---|---|---|
| DuckDB cursor corruption | Backtest stopped at March 2020 | `momentum_signal()` opened a second DuckDB connection while feed cursor was streaming | Pre-compute all signals before `iter_bars()` starts |
| Drawdown circuit breaker | Backtest stopped at March 2020 | COVID crash hit 20% drawdown; `_halted = True` permanently rejected all orders | Set `max_drawdown_halt = 0.99` for research mode |
| CAGR complex number | `ValueError: Unknown format code '%' for complex` | `(end/start)^(1/n)` where `end < start < 0` produces complex | Guard `ratio <= 0 → cagr = -1.0` |
| Foreign stocks in universe | −101% total return | Alpaca feed includes `.NS`/`.BO` Indian stocks; volatile momentum signal selected them | `NOT LIKE '%.NS'`, `NOT LIKE '%.BO'`, etc. filters |
| Penny stocks | Portfolio wiped | No price floor; sub-$1 stocks dominated signal | `c25 >= 5.0 AND adj_close >= 5.0` |
| CIK-format symbols | Nonsense instruments traded | Fundamentals store leaked CIK IDs into OHLCV | `NOT LIKE 'CIK%'` filter |
| Closing orders rejected | Grown positions trapped | Position-size check applied to all orders; `is_closing` branch never implemented | Detect closing orders; exempt from size limit |
| Rebalancing leverage spike | Core names (AAPL, AMZN) rejected | Entries and exits in same rebalance bar caused transient leverage > 1.1× | Raise `max_gross_leverage` to 2.0× |
| Per-fill debug logging | 4+ hour runtime | structlog debug lines serialized stdout I/O at every fill | `configure_logging(log_level="WARNING")` |

---

*Mentisrex Capital — Systematic Quantitative Strategies*  
*For internal research use only. Not an offer to invest.*
