# MentisRex — Data Acquisition Brief (what YOU must provide)

Prepared 2026-08-15. Audience: you (the principal). Purpose: list the exact data
and decisions I **cannot** produce myself — because they require external sources,
paid feeds, accounts, or business/legal choices — so the research engine can move
from "marginal, survivorship-suspect numbers" to trustworthy, tradeable evidence.

I will not fabricate any of this. Every item below is a real dependency. Where I
can work in parallel without it, that is noted at the end.

---

## 0. The single most important fact

Your current price data (`analytics.duckdb`, 6.4M bars, 2143 symbols) is **~99.6%
survivors**. Delisted/dead companies are essentially absent. It is also a **mixed
bag**: Indian `.NS` names running to 2026 plus some US tickers (XOM, MSFT, KO…)
that stop in 2023. Any backtest on this data is biased upward and internally
inconsistent. **This is a data problem, not a code problem — I cannot fix it
without the datasets below.**

---

## 1. PRIORITY 1 — Survivorship-free universe (the #1 blocker)

Without this, every IC / Sharpe / t-stat stays suspect-high. Pick ONE path.

### Option A (best): Historical index constituents
Monthly (or reconstitution-event) membership of a broad index, going back as far
as possible.
- **India:** NIFTY 500 / NIFTY Total Market historical constituents. Sources: NSE
  index reconstitution history (published on nseindia.com), or a vendor (CMIE
  Prowess, Bloomberg, Refinitiv/LSEG). CMIE Prowess is the standard India academic
  source and includes delisted firms.
- **US:** S&P 500 / Russell historical membership. Sources: CRSP (gold standard,
  academic access), Sharadar (cheap, survivorship-free), Bloomberg.

### Option B: Delisting + corporate-actions feed
Every security that ever traded, with listing and delisting dates + reasons.
- **India:** archived **NSE daily bhavcopy** files (each day's bhavcopy contains
  ALL names that traded that day → archiving them back-reconstructs the true
  universe including now-dead names). Also NSE/BSE corporate-action and
  delisting circulars.
- **US:** Sharadar `TICKERS` + `ACTIONS` tables, or CRSP events.

**Schema I need (either option), CSV or Parquet:**
```
constituents.csv   : index_name, security_id, ticker, date_added, date_removed
securities.csv     : security_id, ticker, isin, exchange, country, currency,
                     asset_class, first_listing_date, delisting_date, status,
                     delisting_reason
corporate_actions  : security_id, action_type(split|dividend|merger|ticker_change),
                     ex_date, effective_date, ratio_or_amount, details
```
`security_id` = any stable permanent id (ISIN preferred). Once I have these, I load
them into the existing (currently empty) `SecurityMaster` + `DelistingStore` and
switch the sweep to `UniverseEngine.universe_as_of` — code already built.

---

## 2. PRIORITY 2 — Clean, single-market price panel

Even before survivorship, the price data must be one market, one currency,
adjusted correctly.
- **What I need:** daily OHLCV, **split- and dividend-adjusted** (or raw + an
  actions table so I adjust PIT-correctly), one market at a time.
- **India source (free-ish):** NSE bhavcopy archives; libraries `jugaad-data` /
  `nsepy`; or a vendor for clean adjusted history.
- **US source (free):** **Alpaca** (you already have a paper account) gives free US
  equity daily history — a clean, survivorship-*imperfect* but consistent second
  market to add breadth.
```
prices.csv : security_id, date, open, high, low, close, volume, adj_close, currency
```

---

## 3. PRIORITY 3 — Fundamentals (for value/quality factors)

Your feature engine supports value/quality/growth families, but the fundamentals
store is not populated for this panel. Cross-sectional value/quality is where a lot
of real equity edge lives.
- **What I need:** point-in-time fundamentals with **report + publication dates**
  (so no look-ahead): earnings, book value, revenue, cash flow, shares outstanding.
- **India:** CMIE Prowess, Refinitiv, or screener.in exports (rougher).
- **US:** Sharadar `SF1` (point-in-time fundamentals, cheap), or SEC EDGAR (free,
  more work).
```
fundamentals.csv : security_id, report_date, publication_date, metric, value
```
The **publication_date is critical** — without it fundamentals leak the future.

---

## 4. PRIORITY 4 — Shortability / borrow (for long-short realism)

You asked whether you can short Indian mid-caps. Mostly **no**: Indian cash-segment
has no overnight shorting; only F&O-listed names are effectively shortable
(intraday cash, or via futures/options). This is a hard structural limit.
- **What I need (one of):**
  - The **F&O-eligible list over time** (NSE publishes it) → restrict short book to
    shortable names, or
  - A borrow-availability / borrow-fee feed (vendors; rare/expensive in India).
- **Decision from you:** do we (a) go **long-only** on India (realistic, simpler),
  (b) restrict long-short to the **F&O universe**, or (c) use **US** (freely
  shortable) as the long-short market? My recommendation: **US long-short via
  Alpaca for shorting research, India long-only** until borrow data exists.

---

## 5. Non-data decisions I need from you

1. **Markets to prioritise:** India-only, US-only, or both? (US is easier: free
   data via Alpaca, real shorting, survivorship-free sets available cheaply.)
2. **Long-only vs long-short** per market (see #4).
3. **Budget for data:** are you willing to pay for a survivorship-free set?
   Cheapest good option: **Sharadar via Nasdaq Data Link (~US$ tens/month)** for US
   survivorship-free prices + fundamentals + actions. India clean history is
   harder/pricier (Prowess is institutional).
4. **Capital reality:** own money only, or eventual outside capital? (Changes the
   legal/compliance path later — not needed for research now.)

---

## Recommended acquisition order (cheapest, highest-leverage first)
1. **Sharadar (Nasdaq Data Link) US bundle** — survivorship-free prices +
   fundamentals + actions, ~US$ tens/month. Instantly unblocks #1, #2, #3 for a
   real, shortable market. **Highest ROI single action.**
2. **Archive NSE bhavcopies** (free, ongoing) — start now so India survivorship
   reconstructs over time.
3. **NSE F&O historical list** (free) — enables realistic India long-short.
4. India fundamentals (Prowess) — only if you commit to India as a primary market.

Give me any one of these in the schemas above and I load + re-run immediately.

---

## What I am doing IN PARALLEL (no new data needed)
1. **Data hygiene:** split the current panel by market/currency, drop the US/India
   contamination, produce a clean **India-only baseline** so numbers are at least
   internally consistent.
2. **Wide signal battery:** expand from 3 to ~15–20 signals across horizons
   (1w/1m/3m/6m), all through the DoF-corrected, net-of-cost gate.
3. **Impact + capacity:** wire √-law market impact (uses the volume you already
   have) and an AUM→Sharpe capacity curve into the sweep.
4. **Forward paper harness:** register any surviving factor as an isolated,
   paper-only forward campaign so the track-record clock starts now.

These sharpen the machine. They do **not** remove survivorship bias — only the
data in Priority 1 does. I will label every result produced before Priority 1 lands
as "survivorship-suspect."

— MentisRex research engine
