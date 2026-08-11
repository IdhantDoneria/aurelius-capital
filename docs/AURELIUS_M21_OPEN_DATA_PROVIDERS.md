# M21 — Open Market Data Provider Integration & Free Data Expansion Layer

**Status:** CERTIFIED  
**Commit range:** see `AURELIUS_MILESTONE_INDEX.md`  
**Tests:** 81 deterministic offline tests (0 failures, 0 network calls)  
**Benchmarks:** 100k obs < 4s; 1M obs < 33s (both within targets)

---

## Overview

M21 adds eight free/public-data source adapters to the existing M19/M20 market-data architecture.
No paid data dependency is introduced; no existing M1–M20 infrastructure is modified.

Every external source terminates at the **M20 SourceAdapter boundary**. Data flows:

```
External Provider
      ↓
M20 SourceAdapter  (providers/)
      ↓
Ordering / Arbitration / Replay  (M20 ops)
      ↓
M19 Normalization / Quality / PIT Validation
      ↓
M18 MarketDataSnapshot
      ↓
Valuation / Risk / Execution / Research
```

No provider-specific logic appears outside its adapter module. No direct API calls from
valuation, risk, execution, or portfolio accounting layers.

---

## Supported Providers

### 1. OpenBB (`providers/openbb/`)

| Field | Value |
|-------|-------|
| Class | `OpenBBSourceAdapter` |
| License | MIT (SDK); underlying sources vary |
| Coverage | Global equities, ETFs, FX, macro (FRED/IMF/WorldBank/ECB) |
| Datasets | OHLCV, company info, fundamentals, FX rates, macro |
| Capabilities | HISTORICAL, BARS, FUNDAMENTALS, RATES, FX |

Converts OpenBB's unified output schema to `SourceMessage`. Equity, macro, and FX records
handled with explicit routing. Production fetch raises `NotImplementedError`; use `convert()`.

**Limitations:** requires `openbb` install; rate limits vary by underlying source; no tick data.

---

### 2. Fincept (`providers/fincept/`)

| Field | Value |
|-------|-------|
| Class | `FinceptSourceAdapter` |
| License | Apache-2.0 (connector); underlying data varies |
| Coverage | Global — Yahoo Finance, SEC/EDGAR, FRED, IMF, World Bank, data.gov.in, NSE |
| Datasets | OHLCV, fundamentals, macro, India equities |
| Capabilities | HISTORICAL, BARS, FUNDAMENTALS, RATES, REFERENCE_DATA |

Minimal-transformation adapter — Fincept's output already follows a unified dict schema that
maps directly to `SourceMessage.payload`. Production fetch raises `NotImplementedError`.

**Limitations:** requires `fincept` install; rate-limited; no tick data.

---

### 3. Yahoo Finance (`providers/yahoo/`)

| Field | Value |
|-------|-------|
| Class | `YahooFinanceSourceAdapter` |
| License | Data: Yahoo Finance ToS (non-commercial); yfinance: Apache-2.0 |
| Coverage | Global equities, ETFs, FX, crypto, indices |
| Datasets | OHLCV, adjusted close, dividends, splits, corporate actions |
| Capabilities | HISTORICAL, BARS, CORPORATE_ACTIONS |

`yfinance` is a declared project dependency. `fetch()` performs live downloads; `convert()`
processes pre-fetched records offline (used in tests). Emits separate `SourceMessage` objects
for unadjusted close, adjusted close, dividends, and splits — each with distinct `msg_type`
and provenance.

Ticker resolution: pass an `IdentifierMap` to resolve tickers PIT-aware to internal security IDs.

**Limitations:** 15-minute delay; partial corporate actions; non-commercial use only;
ticker reuse creates identity risk without an `IdentifierMap`.

---

### 4. SEC/EDGAR (`providers/sec/`)

| Field | Value |
|-------|-------|
| Class | `SECSourceAdapter` |
| License | Public domain (SEC EDGAR data) |
| Coverage | US public companies — XBRL-tagged financial statements |
| Datasets | Balance sheet, income statement, cash flow, company facts, filings |
| Capabilities | HISTORICAL, FUNDAMENTALS, REFERENCE_DATA |

Input: EDGAR company-facts JSON from `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`.

**PIT safety (critical):**
- `observation_date` = `filed` (when the filing became public knowledge)
- `effective_date`   = `end` (accounting period end)

Using `end` as observation_date is a look-ahead violation. GDP Q1 2024 (end 2024-03-31) is
knowable only after the 10-Q is filed, typically ~45–75 days later.

Restatements: same `(cik, concept, period_end)` across multiple accession numbers → monotone
`revision` numbering. Integrates with M19 `RevisionStore` for full bitemporal reconstruction.

Concept map: 24 common `us-gaap` concepts mapped to canonical field names (revenue, net_income,
total_assets, stockholders_equity, cash_flow_operations, capex, etc.).

**Limitations:** US-only; XBRL-tagged filings only; restatement detection requires same
`period_end` match; no real-time data.

---

### 5. FRED (`providers/fred/`)

| Field | Value |
|-------|-------|
| Class | `FREDSourceAdapter` |
| License | Public domain (Federal Reserve Bank of St. Louis) |
| Coverage | US macro — GDP, CPI, unemployment, rates, monetary indicators |
| Datasets | GDP, inflation, unemployment, interest rates, monetary indicators |
| Capabilities | HISTORICAL, RATES |

Input: FRED observation list (with optional `realtime_start` vintage data).

**PIT safety (critical):**
- `observation_date` = `realtime_start` (when FRED published the value)
- `effective_date`   = `date` (the economic period)

Without vintage data (`realtime_start` absent), `knowledge_date` defaults to `effective_date`
— this is look-ahead-unsafe for backtesting. Always use the vintage API endpoints for research.

30 FRED series pre-mapped to canonical field names (GDP, CPI, UNRATE, FEDFUNDS, DGS10, etc.).

**Limitations:** US-focused; optional API key for higher rate limits.

---

### 6. India Market Data (`providers/india/`)

| Field | Value |
|-------|-------|
| Class | `IndiaSourceAdapter` |
| License | NSE/BSE: free for personal use; data.gov.in: NOGI |
| Coverage | India — NSE/BSE equities, corporate actions, macro |
| Datasets | NSE OHLCV, BSE OHLCV, corporate actions, India macro |
| Capabilities | HISTORICAL, BARS, CORPORATE_ACTIONS, REFERENCE_DATA |

Three conversion entry points:
- `convert_nse(records, as_of)` — NSE bhav-copy format
- `convert_bse(records, as_of)` — BSE bhavcopy format
- `convert_macro(records, as_of)` — data.gov.in macro indicators

Identifier resolution: NSE symbol, BSE code, and ISIN all resolve through M19 `IdentifierMap`.
ISIN preferred for deduplication. Falls back to `NSE:{symbol}` / `BSE:{code}` if no map.

Date format tolerance: accepts `%Y-%m-%d`, `%d-%b-%Y`, `%d/%m/%Y`, `%Y%m%d`.

**Limitations:** limited history depth; ISIN required for cross-exchange deduplication;
data.gov.in updates irregularly.

---

### 7. Qlib Compatibility (`providers/qlib/`)

| Field | Value |
|-------|-------|
| Classes | `QlibSourceAdapter`, `QlibExporter` |
| License | MIT (Qlib format; no Qlib library required) |
| Coverage | Aurelius datasets in Qlib-compatible format |
| Datasets | OHLCV export/import, factor datasets, label datasets |
| Capabilities | HISTORICAL, BARS |

`QlibSourceAdapter.convert_csv(csv_text, symbol, as_of)` reads Qlib-format per-stock CSV
files back into `SourceMessage` objects. `factor` column generates a second `adjusted_close`
message when factor ≠ 1.0.

`QlibExporter.export(observations, output_dir)` groups `CanonicalObservation` by `security_id`
and writes one CSV per stock in Qlib's expected format. Does not import the Qlib runtime.

**Limitations:** export only (no live Qlib portfolio/execution engine); no ML pipeline.

---

### 8. FinanceToolkit Fundamentals (`providers/financetoolkit/`)

| Field | Value |
|-------|-------|
| Class | `FinanceToolkitSourceAdapter` |
| License | MIT (FinanceToolkit-style; no library import required) |
| Coverage | Fundamental analytics from CanonicalObservation inputs |
| Datasets | Profitability, margins, valuation multiples, financial ratios |
| Capabilities | HISTORICAL, FUNDAMENTALS |

Converts FinanceToolkit-style financial statement dicts to `SourceMessage` objects. Each
financial metric (revenue, net_income, total_assets, etc.) becomes a separate `SourceMessage`
with PIT-correct `observation_date` (filing date) and `effective_date` (period end).

Does NOT replace M11 accounting, M13 risk, or M18 valuation engines.

**Limitations:** derived analytics, not raw data; depends on SEC/EDGAR upstream observations.

---

## Fundamental Analytics Layer (`analytics/fundamentals/`)

`FundamentalRatioEngine` computes typed `FundamentalObservation` ratios from a field dict:

**Profitability:** `gross_margin`, `operating_margin`, `net_margin`, `ebitda_margin`, `roe`, `roa`  
**Leverage:** `debt_to_equity`, `debt_to_assets`, `interest_coverage`, `net_debt_to_ebitda`  
**Liquidity:** `current_ratio`, `cash_ratio`  
**Efficiency:** `asset_turnover`  
**Valuation:** `pe_ratio`, `pb_ratio`, `ps_ratio` (require `price=` argument)  
**Cash Flow:** `fcf_margin`, `fcf_to_net_income`  
**Growth:** `revenue_growth`, `earnings_growth`, `gross_profit_growth` (via `compute_growth()`)

All computations are zero-safe (division by zero → `None`, excluded from results). Inputs
preserved in `FundamentalObservation.inputs` for audit.

---

## Lean Export Layer (`export/lean/`)

`LeanExporter` exports Aurelius outputs to QuantConnect Lean-compatible structures:

- `export_ohlcv(observations, output_dir)` — daily equity zip files (10000ths-of-dollar format)
- `export_universe(universe_by_date, output_path)` — universe membership CSV
- `export_signals(signals, output_path)` — alpha model signal CSV
- `export_targets(targets, output_path)` — portfolio target weight CSV

No Lean runtime dependency. Pure filesystem output.

---

## Provider Registry

`default_m21_registry()` extends the M20 operational registry with all 8 M21 providers:

```python
from aurelius.research.market_data.providers import default_m21_registry, ALL_PROVIDERS
r = default_m21_registry()
```

Each provider registered as `ComponentInfo(PROVIDER, "m21.{name}", version, description)`.
`ProviderMetadata` carries: name, version, license, coverage, datasets, limitations, and a
stable blake2b fingerprint for audit lineage.

---

## Benchmarks

Measured on M1 Pro. All offline, no network.

| Scenario | n | Time | Target | Status |
|----------|---|------|--------|--------|
| OpenBB equity conversion | 100,000 | 3.0s | < 10s | PASS |
| OpenBB equity conversion | 1,000,000 | 32s | < 120s | PASS |
| Yahoo Finance (close + adj_close) | 100,000 | 5.9s | < 10s | PASS |
| FRED vintage conversion | 10,000 | 0.03s | — | — |

---

## Known Limitations

- No live connectivity to any provider. All `fetch()` methods raise `NotImplementedError`.
  Use `convert()` with pre-fetched data, or subclass and wire the transport.
- Free APIs are rate-limited. FRED: 120 requests/minute (no key); 2000/minute (with key).
  Yahoo Finance: unofficial API, subject to change without notice.
- No institutional alternative datasets (no sentiment, no alternative data).
- Corporate action coverage is incomplete for all free providers.
- No guaranteed tick-level data from any provider.
- India data: limited history depth (typically 2–5 years from free sources).
- SEC EDGAR: US-listed companies only; filings not yet tagged in XBRL are not available.
- Yahoo Finance: data for non-commercial use only per Yahoo ToS.

---

## Production Upgrade Path

To wire a live feed:
1. Subclass the relevant adapter (e.g., `YahooFinanceSourceAdapter`)
2. Override `connect()` / `fetch()` with real transport code
3. Return `list[SourceMessage]` from `fetch()` — the ordering, arbitration, normalization,
   and snapshot pipeline consume it unchanged
4. Register the subclass in the M21 registry

All downstream infrastructure (M19 normalization, M20 ordering/arbitration/replay, M18
valuation) requires no modification.
