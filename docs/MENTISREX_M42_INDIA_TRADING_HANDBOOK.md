# M42 — India Momentum-Quality Programme: Trading Handbook

**Status:** Research/backtest engine, tested, not live-trading-ready. See
"Engineering maturity" (Section 9) for exactly what's still missing before
this could run with real money.

**Owner:** Idhant Doneria · **Date:** 24 August 2026 · **Package:**
`mentisrex.programme_india`

This is the complete technical reference for the India equity strategy built
across this programme's research phase: what it is, exactly how it works,
why every design choice was made, the real backtest results, two real bugs
found and fixed while verifying those results, and what is honestly not yet
built. Technical terms are used throughout (this is a trading handbook, not
a beginner's guide), but every one is explained in plain language the first
time it appears.

---

## 1. Headline

| | |
|---|---|
| **CAGR** (compound annual growth rate) | **20.4%** |
| **Volatility** (annualised) | 22.1% |
| **Sharpe ratio** (excess over the Indian repo/cash rate) | 0.68 |
| **Beta** to Nifty 50 | 0.60 |
| **Alpha** (annualised) | +14.1% |
| **Maximum drawdown** | -42.7% |
| **Leverage** | 1.5x hard cap |
| **Backtest window** | 4 Jan 2010 – 30 Mar 2026 (15.9 years, real NSE price data) |
| **$1,000,000 → ** | **$19.18 million** |

Every number above was computed by the code in `src/mentisrex/programme_india/`,
run via `scripts/run_india_programme_backtest.py`, and independently
cross-checked at least twice (Section 6 explains exactly how, including two
real bugs this process caught and fixed).

---

## 2. What this strategy actually is, in one paragraph

A **long-only** (never short), **leverage-capped at 1.5x** Indian equity
strategy. Each month it ranks the ~200 most liquid NSE stocks by a blend of
**momentum** (how strongly a stock has risen over the past year, skipping
the most recent month) and **quality** (real ROE, debt levels, and earnings
stability from actual company filings), buys the top-ranked **decile**
(roughly the strongest 20 names), sized inversely to each stock's own
volatility and capped so no single name dominates, with a **sector cap** so
no single industry can dominate either. On top of that stock-picking layer
sits a daily **exposure overlay** that scales the whole book's market
exposure between 0% and 150% of NAV based on trend and breadth signals, so
the strategy can pull back toward cash when the market looks genuinely
dangerous — not just when the headline index looks bad, but when the
broader market underneath it does too.

---

## 3. Why a new module, not an extension of the existing engine

Before building anything, the existing Mentisrex codebase was surveyed for
India-specific engineering already in place. The findings:

- `src/mentisrex/research/market_data/providers/india/adapter.py` — an
  **offline-only** data-format converter (turns pre-fetched NSE/BSE records
  into internal message objects). `fetch()` explicitly raises
  `NotImplementedError`. Not wired to any live pipeline. Referenced only by
  its own test file.
- `src/mentisrex/factors/nse.py` — a momentum-only factor engine. Imported
  by `mentisrex.factors.__init__`, but its `.compute()` method is never
  actually called anywhere in the codebase outside an assertion-only sanity
  check.
- `src/mentisrex/programme/` — the production US v3.0 ten-sleeve engine.
  **Explicitly excludes India** by name: its shared SQL filter constant
  (`_SOURCE_FILTER_SQL`) contains `AND source != 'nse_bhavcopy' AND symbol
  NOT LIKE '%.NS'`, with an inline comment: `India — out of scope.`

**Conclusion: nothing usable existed.** The two India-tagged modules are
unused stubs, and the one production-grade programme in the codebase treats
India as explicitly out of scope by design. Building this as a new package
(`mentisrex.programme_india`) rather than forcing it into `mentisrex.programme`
was the only honest option — the US engine's entire architecture (dollar-
neutral shorting via single-stock futures, a ten-sleeve combiner, 2.5x-4x
sleeve multipliers) assumes a market structure and mandate this strategy
deliberately does not have (Section 4).

---

## 4. Why this is long-only with capped leverage, not a hedged book

The original strategy specification this programme started from (a
nine-sleeve, 2.5x-levered, dollar-neutral long-short design using single-
stock futures) was revised twice at the user's explicit direction:

1. **Leverage capped at 1.5x**, not 2.5x. In India, index-futures margin
   (SPAN + exposure margin) for Nifty 50 runs roughly 10-13% of notional —
   at 1.5x exposure, only ~15-20% of NAV sits in margin, leaving 80%+ as
   free collateral. A margin call is not a realistic risk at this level
   (unlike 2.5x, which uses close to double the margin).
2. **No short book.** The original design's short leg existed specifically
   to cancel out market exposure (beta). Once the leverage ceiling dropped
   and the user explicitly asked for a beta in the 1.5-2.5 range rather
   than near zero, running a short book made no sense — it would mean
   paying real costs (borrow fees, single-stock-futures roll, ban-period
   operational complexity) to hedge away a risk the user wanted to keep.

The realised beta this backtest actually produced (0.60) came in below that
requested range — Section 6.3 explains exactly why (a real, mechanism-level
finding, not an error), and the user's explicit response was that a lower
realised beta is fine.

---

## 5. Full specification

### 5.1 Universe

The ~200 most liquid NSE stocks each month, ranked by trailing 63-day
average traded value (₹), among names with ≥280 days of price history. This
is a **liquidity proxy for F&O (futures & options) eligibility**, not the
literal, official F&O-eligible list — no historical, point-in-time F&O
eligibility archive was available this session. See Section 8 for what
would replace this.

### 5.2 Stock selection — `signals.py`

```
momentum_z  = zscore( close[t-21] / close[t-252] - 1 )     # 12-1 month return
quality_z   = 0.5·zscore(ROE) − 0.3·zscore(debt/equity) + 0.2·zscore(earnings stability)
composite   = 0.6 · momentum_z + 0.4 · quality_z
            (a name missing a quality score is scored on momentum alone,
             at full momentum weight — not dropped, not silently
             re-weighted to 100% momentum for the whole book)
```

Pick the top **decile** (10%) by composite score — roughly 20 names out of
~200. Apply a **28% sector cap**: greedily skip a candidate if its sector
already holds 28%+ of the picks-so-far, so no single industry can dominate
the book. This is a direct, mechanism-level fix for a real backtest failure
found during this programme's earlier research: a pure-momentum,
un-capped book lost ~21% in 2018 because momentum had loaded up on
highly-leveraged NBFCs (non-bank financial companies) right before the
IL&FS credit crisis — exactly the kind of concentrated, sector-driven
blowup a sector cap exists to prevent.

**Position sizing:** inverse-volatility weighted (a name with twice the
recent realised volatility of another gets roughly half the weight), capped
at `min(average_weight × 2.5, 8%)` per name, enforced by **iterative capped
redistribution** — see Section 6.2 for why a naive "clip and renormalize"
approach is a real bug, not a simplification.

### 5.3 The exposure overlay — `overlay.py`

```
trend   = average( Nifty50 > its 100-day MA,  Nifty50 > its 200-day MA )   # 0, 0.5, or 1
breadth = fraction of the ENTIRE ~1,100-name universe above its own 100-day MA
gate    = MIN(trend, breadth)          <- the fix, see 5.4
vscalar = clip( 31% / realised_63-day_volatility_of_Nifty50,  0.5,  1.5 )
exposure = clip( gate × vscalar × 1.5,  0%,  150% )
         , applied with a 2-trading-day lag (decide on day t, trade on t+2)
```

**31% is the locked target volatility**, chosen after an explicit,
documented experiment across five configurations (20%, 24%, 28%, 30%, 31%,
32% target vol; quintile vs decile stock selection; average-of-two vs
worse-of-two gating) — see Section 6.4 for the experiment table and why 31%
was where the marginal benefit of pushing further essentially disappeared.

### 5.4 Why `MIN`, not average, of the two exposure signals

An earlier version of this overlay averaged the large-cap trend signal with
the broad-market breadth signal. In 2018, the Nifty 50 (dominated by a
handful of mega-caps) stayed "above its 200-day average" essentially all
year while the broader market — where a momentum/quality book actually
invests — was collapsing underneath it (real, verified data: the Nifty
Midcap 50 fell ~28% peak-to-trough over that period while the Nifty 50 was
flat-to-up). Averaging a real danger signal (breadth, correctly reading
~19% by mid-2018) with a false all-clear (trend, near 100%) diluted the
warning into a "stay invested" signal. **`MIN` means the worse of the two
signals governs — a real warning from either one can no longer be
masked by the other.**

### 5.5 Costs — `costs.py`

| Cost | Rate |
|---|---|
| STT (securities transaction tax) + brokerage + modelled market impact | 12.5 bps, one-way |
| Additional realistic execution slippage | +5 bps, one-way (17.5 bps total) |
| Cost applied to any change in the exposure overlay's leverage level | 20 bps |
| Net financing drag on the levered (>100%) portion of the book | 0.8%/year |
| **Flat "operational error" haircut** — a late rebalance, a fat-finger correction, a missed exit before a circuit halt | **0.20%/year, every year, win or lose** |

None of these are modelled as zero. The operational-error line specifically
exists because no backtest naturally captures the real-world cost of human
execution error, and pretending it's zero would understate what this
strategy actually costs to run.

---

## 6. Verification — two real bugs found, and exactly how they were caught

This section exists because the user's explicit standard for this
programme was: **nothing gets reported without being independently
double-checked, and nothing gets hidden if a check fails.** Both of the
following were caught by that process, not by luck.

### 6.1 The CAGR off-by-one bug

**The bug:** building a NAV (net asset value) series as
`start_capital × (1 + returns).cumprod()` makes the *first* element of that
series already reflect day one's return — not the untouched starting
capital. Computing CAGR as `(nav[-1] / nav[0]) ** (1/years) − 1` therefore
silently drops day one's return from the whole calculation.

**How it was caught:** every CAGR in this programme is now computed two
independent ways — the endpoint-ratio method and an independent log-return-
mean method — and `metrics.cagr_from_returns()` raises `CagrMismatchError`
if they disagree by more than 1e-4. The two methods disagreed on every
backtest run until the NAV construction was fixed (Section 6, `nav_series()`
now prepends an explicit day-zero value of `1.0` before compounding, so
`nav[0]` is guaranteed to be the real starting capital). A regression test
(`tests/programme_india/test_metrics.py::TestCagrBugRegression`) reproduces
the exact original bug pattern and asserts the two methods now agree.

**Actual impact:** small for any single buy-and-hold series (~0.02-0.05
percentage points on a ~4,000-day series) — confirmed by recomputing every
benchmark in Section 7 with the fixed formula: they came back essentially
unchanged from the figures reported earlier in this programme's research
(Nifty 50: 10.9% → 10.88%; HDFC Bank: 15.9% → 15.86%). This bug was real,
but it was not the dominant source of error — the next one was.

### 6.2 The position-sizing cap bug — this one materially changed the headline number

**The bug:** the inverse-volatility position sizing capped each name's
weight, then renormalized the whole book to sum to 100% by dividing every
weight by the new total. When most or all held names' raw weights already
sat close to the cap (exactly the situation in a concentrated ~20-name
decile book with similar-volatility constituents), clipping brought them
all down together — and renormalizing then scaled them straight back up,
past the cap, converging on something close to **equal weighting while
still claiming to be inverse-volatility-weighted and capped.**

**How it was caught:** a unit test
(`tests/programme_india/test_signals.py::TestInverseVolWeights`) asserted
that no weight could exceed the configured cap after construction. It
failed — five names, all landing at exactly 20% each (the equal-weight
outcome) despite an 8% cap. Investigating why led directly to the
clip-then-renormalize flaw.

**The fix:** `signals.inverse_vol_weights()` now enforces the cap through
**iterative capped redistribution** — excess weight taken from any
over-cap name is redistributed only among names still under their cap,
repeating until stable (or, if the cap is mathematically infeasible for
that many names — e.g., 5 names can never all be held under an 8% cap,
since 5 × 8% = 40% < 100% — falling back explicitly to equal weighting
rather than silently violating the cap).

**Actual impact: this is the one that mattered.** Rerunning the final,
locked configuration (decile selection, 31% target vol, 1.5x leverage cap)
through the fixed code changed the headline CAGR from a previously-reported
**22.22%** down to the verified, correct **20.42%** — a real, ~1.8
percentage-point correction, entirely attributable to this bug, not the
CAGR-formula one. **This is stated here exactly as prominently as the good
news elsewhere in this document, per the standard this whole programme was
held to.**

### 6.3 Why realised beta (0.60) came in below the user's stated 1.5-2.5 target

Not a bug — a real, understood mechanism, explained here because the user
was told about it and explicitly accepted it. The `MIN`-gate exposure
overlay (Section 5.4) is, by construction, conservative: broad-market
breadth rarely sits near 100% even in healthy markets (typically 40-70%),
and since exposure is gated on the *worse* of breadth and trend, average
realised exposure lands around 85-92% of NAV rather than near the 150%
ceiling most of the time. The same design choice that protects against a
repeat of 2018 mechanically suppresses average leverage utilisation, and
therefore realised beta, well below what a less conservative gate (e.g.
averaging the two signals) would produce. The user's explicit response,
verbatim: *"it's good that beta stays below 1, I don't mind it."*

### 6.4 How 31% became the locked target volatility

A small, literature-grounded experiment, not a blind parameter search —
each change tested one specific, well-documented mechanism:

| Configuration tested | CAGR | Max drawdown | Rationale |
|---|---|---|---|
| Quintile picks, 24% vol target (original design) | 18.7% | -36.3% | Baseline |
| Quintile, 28-32% vol target | 19.2-19.7% | -36.8% | Tests whether the leverage cap was under-utilised |
| **Decile picks (10%, not 20%)**, 24% vol target | 21.3% | -44.0% | Jegadeesh & Titman (1993) and every replication since: momentum's edge concentrates in the most extreme decile |
| Decile + 28-32% vol target | 21.8-22.3% (later corrected to ~20.0-20.4% after the Section 6.2 fix) | -44.8% (~-42.7% after the fix) | Combining both validated levers |
| **Decile + 31% vol target (LOCKED)** | **20.4%** (corrected) | **-42.7%** (corrected) | Marginal CAGR gain per +1% vol target had fallen to ~0.13pp by 30-31%, essentially flat by 32% — diminishing returns reached |

The experiment was deliberately stopped here. Pushing concentration or the
vol target further would mean optimizing against this one 15.9-year
historical path rather than a validated, general mechanism — exactly what
the user explicitly instructed against.

---

## 7. Full comparison table (identical $1,000,000 start, identical 4 Jan 2010 → 30 Mar 2026 window, all figures independently recomputed with the fixed CAGR formula)

| | CAGR | Ending value | Max drawdown |
|---|---|---|---|
| **This strategy** | **20.42%** | **$19.18M** | **-42.7%** |
| Nifty 50 (dividends included) | 10.88% | $5.16M | -38.3% |
| Sensex (blue chips) | 10.60% | $4.96M | -37.9% |
| Nifty IT (tech sector) | 11.91% | $5.98M | -36.9% |
| Nifty 100 (large-cap proxy) | 11.15% | $5.37M | -38.0% |
| Nifty Smallcap 250 (small-cap proxy) | 12.56% | $6.56M | -59.8% |
| Nifty Midcap 50 (mid-cap proxy) | 12.75% | $6.74M | -47.7% |
| Reliance Industries | 12.62% | $6.62M | -44.9% |
| TCS | 13.60% | $7.60M | -47.3% |
| **HDFC Bank** (best individual blue chip) | **15.86%** | $10.38M | -40.9% |
| Infosys | 10.13% | $4.63M | -38.0% |
| ICICI Bank | 14.92% | $9.12M | -51.7% |

**Honest read:** the strategy beats every row here, including the best
individual stock (HDFC Bank), by a real, cost-inclusive margin of ~4.6
percentage points of CAGR a year. That is a genuine edge. It is a smaller
edge than the 22.2% figure this programme reported before Section 6.2's fix
was found — stated exactly that plainly.

**On the "best mutual fund" comparisons the user asked for:** the small/mid/
large-cap NSE category indices above stand in for those, because this
session's web-search and web-fetch tools failed consistently across every
attempt (a backend outage, not a search-quality issue) — no live, current
mutual fund performance data could be pulled. Real top-decile funds in each
category typically track a few points above or below their category index;
treat the rows above as a reasonable reference band, not the literal single
best fund in India today.

---

## 8. Known limitations — nothing silently skipped

| Limitation | Why it's real | What would unblock it |
|---|---|---|
| Universe is a liquidity proxy, not the true historical F&O-eligible list | No point-in-time F&O eligibility archive exists in this repo or anywhere reachable this session; `scripts/fetch_fo_eligible.py` only captures *today's* list going forward | Archive NSE's F&O eligibility circulars going forward (the script already does this from today), or buy a vendor feed with historical membership |
| Quality factor only has real data for FY2022-2026 | yfinance's annual financials only retain 5 fiscal years; no fundamentals exist anywhere reachable this session for 2010-2021 | A point-in-time fundamentals vendor (CMIE Prowess, or a paid Sharadar-style feed) — the same gap Mentisrex's own `docs/DATA_ACQUISITION_BRIEF.md` already flags independently |
| No tail-hedge / options overlay in the coded backtest | No real options-pricing/implied-vol data available this session to model a hedge honestly | An options chain or implied-vol data feed |
| No true historical corporate-action verification | The source price panel's `adjustment_factor` field is uniformly `1.0` (unverified); ~160 clearly-corrupted data points were found and removed as a precaution during this programme's earlier research, but smaller undetected errors could remain | A corporate-actions (splits/bonus/dividend) reference feed |
| Sector tags cover 388 of ~1,127 symbols (the ones that appeared in either backtest window's top-300 by liquidity) | Fetching `yfinance.Ticker.info` for the full 1,127-symbol universe was not run this pass; only the names that could plausibly matter to a top-200-liquidity book were fetched | Rerun `scripts/step8_fetch_sectors.py`-equivalent against the full universe if the liquidity universe definition ever changes materially |
| No `ruff`/`mypy` lint pass on the new module | This session's virtualenv does not have the project's dev-extras (`ruff`, `mypy`) installed | `uv sync --extra dev` (blocked in this session by an unrelated pre-existing dependency conflict in `pyproject.toml` — see Section 9) |

---

## 9. Engineering maturity — what this is, and is not

This package is a **tested research/backtest engine**, not a production
trading system. Explicitly, it does **not** have:

- A CLI (`mentisrex.programme` has `mrx programme run/backtest/status`; this
  package has one runnable script, `scripts/run_india_programme_backtest.py`)
- Broker integration or order execution of any kind
- State persistence across runs (drawdown-peak tracking, ramp state, sleeve
  health) — the circuit-breaker levels in the earlier stress-test document
  (drawdown warn/de-risk/halt thresholds) are **specified but not coded
  as enforced logic** anywhere in this package
- Live risk-gate enforcement — the leverage cap and beta ceiling are
  respected by construction in the backtest math, but nothing would stop a
  live version from breaching them without the risk-gate layer
  `mentisrex.programme.risk` has for the US engine
- A test suite anywhere near `mentisrex.programme`'s coverage (that package
  has 48 dedicated tests across `data.py`, `signals.py`, `allocator.py`,
  `risk.py`, `execution.py`, `state.py`; this package has 32 tests covering
  `signals.py`, `overlay.py`, and `metrics.py` — `backtest.py`'s
  orchestration logic itself is exercised only end-to-end via the real-data
  script, not unit-tested against synthetic panels)

**What blocked going further this pass, stated plainly:** `uv run` fails
repo-wide right now on an unrelated, pre-existing dependency conflict
(`jugaad-data` version resolution for a Windows/Python-3.15 marker in
`pyproject.toml`) — this predates this programme's work and was worked
around by using `.venv/bin/python3` directly with `PYTHONPATH=src`, which
is why `ruff`/`mypy` (dev-extras) could not be run against the new code
this pass. Fixing the `uv` resolution is a pre-existing, unrelated repair,
not part of this programme's scope, and is flagged here rather than
silently worked around forever.

**Recommended order for closing this gap, if this strategy is to go live:**
1. Fix the `pyproject.toml` dependency conflict blocking `uv sync --extra dev`; run `ruff`/`mypy` against this package.
2. Buy or archive the two data gaps in Section 8 (F&O membership history, deeper fundamentals) before trusting the backtest as more than indicative.
3. Build the risk-gate and state-persistence layer, mirroring `mentisrex.programme.risk` / `state.py`'s pattern.
4. Paper-trade against one of the three sources in Section 10 for at least one full quarter before committing real capital, exactly as the original strategy specification's own go-live plan required for the US engine.

---

## 10. Recommended free paper-trading API sources for forward-testing

Three genuinely free (no monthly API fee) Indian broker APIs commonly used
for algorithmic/forward testing, based on established, well-known industry
reputation. **This could not be verified live this session** (web-search/
web-fetch tools failed on every attempt) — confirm current terms and exact
sandbox/paper-trading capabilities on each provider's own developer portal
before relying on any of them:

1. **Finvasia Shoonya API** (`shoonya.finvasia.com`) — genuinely free API
   access tied to a free-brokerage account; well known specifically for
   that zero-cost positioning among Indian retail algo traders.
2. **Upstox Developer API** (`upstox.com/developer`) — free tier,
   well-documented, explicitly positioned by Upstox as a free alternative
   to attract algorithmic traders.
3. **Angel One SmartAPI** (`smartapi.angelbroking.com`) — free API access
   tied to a trading account, large user base, extensive community
   documentation and example code.

**An important structural caveat, not specific to any one broker:** unlike
some US brokers (e.g. Alpaca), most Indian broker APIs do not have an
official, exchange-connected sandbox that executes simulated trades against
live prices. The realistic "paper trading" path with any of the three above
is what this whole programme has been doing already — pull real market data
through the free API, run your own strategy logic against it, and log
simulated fills yourself — rather than expecting the broker to run the
simulation for you. Confirm this directly with whichever provider's current
docs before assuming otherwise.

---

## 11. Reproducing this backtest

```bash
cd /Users/idhantdoneria/mentisrex-capital
PYTHONPATH=src .venv/bin/python3 scripts/run_india_programme_backtest.py \
    --cache-dir ~/Documents/Indian-Equity-Strategy-Backtest/cache \
    --start 2010-01-01 --end 2026-03-31 --capital-usd 1000000
```

The `--cache-dir` must contain `nse_panel.parquet`,
`nse_panel_extension_2010_2014.parquet`, `nifty50.csv`,
`fundamentals_real.csv`, and `sector_map.csv`. These are NOT bundled in this
repository (too large, too fast-changing for git; `data/` is gitignored).
They were built during this programme's research phase from: Mentisrex's
own `data/analytics.duckdb` (the 1,127-symbol NSE price panel, read-only),
yfinance (extended price history back to 2008, real fundamentals, real
sector tags, the Nifty 50 benchmark, live USD/INR), and are regenerable from
scratch via the same sources — see the git history of
`~/Documents/Indian-Equity-Strategy-Backtest/scripts/` for the exact
extraction/cleaning scripts, which live outside this repository per the
user's original instruction to keep the exploratory research separate from
Mentisrex until a final design was locked in.

Run the test suite:

```bash
.venv/bin/python3 -m pytest tests/programme_india/ -v
```

32 tests, all passing, fully offline (no network, no database — synthetic
panels only).
