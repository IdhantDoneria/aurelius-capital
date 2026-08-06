# AIDP Phase 3 — Point-in-Time Fundamental Data Engine

Institutional PIT fundamentals from SEC EDGAR: every value reconstructable
exactly as it was known on any historical date, no future filing leaking
backwards. The input layer for value/quality/profitability/investment factor
models. Fully additive — Phases 1 and 2 unchanged.

Module: `src/aurelius/market_data/fundamentals/` · Store: `data/fundamentals.duckdb`.

## Core idea: an append-only fact ledger

Everything hangs on one immutable table, `fundamental_facts`. Each XBRL data point
carries **`filing_date`** (EDGAR `filed`) — the day it became known. Facts are
never overwritten; a restatement is simply a later row (new `accession`, later
`filing_date`) for the same period. So:

> value **as known on** `knowledge_date` **for period ending ≤** `as_of`
> = latest row with `period_end ≤ as_of AND filing_date ≤ knowledge_date`.

That single predicate delivers delayed-filing correctness, restatement history,
and no-look-ahead — no special cases.

### Table consolidation (8 → 3, deliberate)

The spec lists 8 tables (facts, shares_outstanding, fundamental_values,
restatements, filing_history, …). Seven of those are **queries over one ledger**:
shares = facts where `unit='shares'`; restatements = periods with >1 accession;
filing_history = distinct accessions. Splitting them into physical tables would
denormalize and risk divergence. We keep three physical tables:

| Table | Role |
|---|---|
| `fundamental_facts` | the immutable ledger (facts + shares + values + restatements + history) |
| `filings` | filing-level metadata (accession, form, filing_date, acceptance, period_end) |
| `ingestion_log` | one row per backfill run |

Every table carries `created_at, updated_at, vendor, source_document, data_version`.

### `fundamental_facts` schema
`cik` · `security_id` (Phase 2 link, nullable) · `taxonomy` · `concept` · `unit` ·
`period_start` · `period_end` · `fiscal_year` · `fiscal_period` · `value` (float64) ·
`form` · `accession` · `filing_date` · `frame` · vendor/source/version/timestamps.
**PK** `(cik, concept, unit, period_end, accession)` — accession in the key is what
preserves restatements. Indexes: `(cik, concept, period_end, filing_date)` (PIT
lookups), `(security_id, concept, period_end)`.

## Data flow

```
EDGAR companyfacts JSON
   → parse_company_facts()          (pure; restatements preserved)
       → FundamentalsStore.write_facts()  (append-only)      ┐
       → FundamentalsStore.record_filings()                  ├─ data/fundamentals.duckdb
   FundamentalsEngine.*_as_of()  ← fact_as_of (PIT predicate) ┘
       ├─ SecurityMaster.historical_identifier()  → PIT ticker   (Phase 2)
       └─ PitPriceStore.close_as_of()             → PIT price    (Phase 1)
```

## Knowledge timeline & restatements

`fact_as_of(cik, concept, as_of, knowledge_date=None)` — `knowledge_date`
defaults to `as_of`. Set it explicitly to ask "what did we know on date X about
period Y". Example (Apple FY2019 Assets, original 338.516B filed 2019-10-31,
amended 338.000B filed 2020-02-01):
- known 2019-12-01 → 338.516B (original)
- known 2020-03-01 → 338.000B (amendment)
- `as_of=2020-03-01, knowledge_date=2019-12-01` → 338.516B (time-travel)

## APIs

**Store** — `write_facts`, `record_filings`, `log_ingestion`, `fact_as_of`,
`series_as_of` (full period history as-known), `cross_section_as_of` (all
companies as-of, one set-based query — the factor-model path).

**Engine** — `fundamental_as_of` (friendly-name → us-gaap concept resolution),
`shares_as_of`, `book_value_as_of`, `market_cap_as_of` (shares × PIT price,
resolving the PIT ticker from SecurityMaster when only a `security_id` is given),
`enterprise_value_as_of` (mkt cap + debt − cash), `factor_inputs_as_of` →
book-to-market, price/book, price/sales, earnings & cash-flow yield, EV/EBITDA,
debt/equity, current ratio, ROE, ROA, gross profitability, operating margin,
accruals, asset growth. All PIT; `None` where an input is unavailable as-of.

**Quality** — `check(store, cik)` → `QualityReport`: negative shares, duplicate
filings, unit mismatch, restated-period count, missing required concepts.

**EDGAR** — `parse_company_facts` (pure), `fetch_company_facts` (network, needs
SEC User-Agent).

## Migration notes

`python scripts/backfill_fundamentals.py <CIK…> --user-agent "Name email"`.
Idempotent, additive, logs each run. Facts land with `security_id=NULL`; link to
Phase 2 later (CIK→security_id) — additive, no reingest. No existing table changed.

## Benchmarks (`scripts/benchmark_fundamentals.py`, in-memory)
3,000,000 facts (10,000 companies × 20y × 15 concepts):
- ingest **0.25M rows/s** (11.9 s)
- `fact_as_of` point **7.9 ms**
- cross-section via naive per-company loop: 819/s → **use `cross_section_as_of`**
  (one windowed query) for factor-model cross-sections.

## Quality gate result
Full `tests/market_data` suite green. Repo swept for direct fundamental reads:
the only matches (`corpus/taxonomy.py`, `discovery/generator.py`) are descriptive
strings, not data reads. No research path read fundamentals before this phase
(audit gap F1), so "every read routes through the PIT engine" holds by
construction.

## Known limitations / Skipped
- **Concept coverage is a curated us-gaap subset** (`engine.CONCEPTS`). Companies
  using non-standard tags need additions. *Unblock:* extend the map; ledger stores
  every tag regardless, so no reingest.
- **EBITDA is derived** (operating income + D&A), not a reported tag. Documented
  approximation.
- **No fiscal-calendar normalization / TTM.** `fact_as_of` returns the latest
  single reported period. TTM aggregation is a future, additive layer.
- **`security_id` not backfilled onto facts** yet (CIK-keyed today); market-cap
  works via ticker or SecurityMaster resolution. CIK→security_id mapping is
  additive.
- **Point cross-sections need the batch method**; per-company loops don't scale.

## Future extensions
CIK→security_id enrichment on the ledger · TTM/fiscal-calendar layer · EDGAR
`submissions` for former-names/tickers feeding the Phase 2 identity-change API ·
segment/footnote XBRL · non-us-gaap taxonomies (IFRS for 20-F/6-K filers).
