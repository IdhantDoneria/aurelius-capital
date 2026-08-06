# AIDP Phase 5 — Point-in-Time Insider Transaction Engine

Institutional insider-activity ledger from SEC Forms 3/4/5, gated so queries
answer *"what insider ownership changes were publicly known as of date X?"* —
never *"what happened historically?"*. Additive; Phases 1–4 untouched.

Module: `src/aurelius/market_data/insiders/` · Store: `data/insiders.duckdb`.

## SEC Forms 3 / 4 / 5

- **Form 3** — initial statement of beneficial ownership, filed when a person
  first becomes an insider (officer, director, >10% holder). Holdings, not trades.
- **Form 4** — changes in ownership; the workhorse. Due within **2 business days**
  of the transaction → the transaction_date and the availability date differ.
- **Form 5** — annual statement of transactions deferred/exempt from Form 4.

## Core principle: three timestamps, gate on availability

| Timestamp | Meaning |
|---|---|
| `transaction_date` | when the insider traded |
| `filing_date` | date the filing was submitted |
| `acceptance_datetime` | **when SEC accepted it → when it became public** |

Research is gated by `acceptance_datetime <= query_time`, **never** by
`transaction_date`. A purchase on Jan 1, accepted Jan 3 18:00, is invisible to a
strategy running Jan 2 (and to one running Jan 3 morning). This is the whole
point — insider filing lag is a classic look-ahead trap.

## Schema — `insider_transactions` (append-only)

PK `transaction_id` (deterministic hash of accession + table + row index).
Fields: security_id · cik · insider_name · insider_role · insider_type
(officer/director/tenpercent/other) · transaction_date · filing_date ·
**acceptance_datetime** · transaction_code (P/S/A/M/F/G…) · shares (signed:
disposals negative) · price · value · ownership_after · ownership_type
(direct/indirect) · accession · form_type · source · vendor · data_version ·
created_at · updated_at. Indexes: `(security_id, acceptance_datetime)`,
`(cik, acceptance_datetime)`.

### Schema decisions
- **Append-only, amendments preserved.** A Form 4/A arrives as a new
  `transaction_id` (new accession). Nothing is overwritten. `transactions_as_of`
  collapses to the latest *accepted* version per logical transaction
  (`cik, insider_name, transaction_date, transaction_code, ownership_type`), so a
  restatement wins **only once it was itself public**.
- **Signed shares.** Acquired (`A`) positive, disposed (`D`) negative; `value`
  keeps the positive magnitude. Lets `ownership_change` sum directly.
- **security_id nullable.** Filings are CIK-native; the Phase 2 link is optional
  and resolvable via SecurityMaster.

## PIT methodology / filing-delay handling

`transactions_as_of(security_id, query_time)`:
```sql
WHERE security_id = ? AND acceptance_datetime <= <cutoff>
-- then ROW_NUMBER() per logical key ORDER BY acceptance_datetime DESC → latest known
```
A bare date cutoff = end-of-day (`23:59:59`), so a filing accepted that day is
known; a `datetime` cutoff gives intraday precision. `insider_position_as_of`
and the engine inherit the same gate.

## APIs

**Store** — `write_transactions`, `transactions_as_of`, `insider_position_as_of`,
`latest_transactions` (operational, ungated).
**EDGAR** — `parse_form3` / `parse_form4` / `parse_form5` (pure; take a parsed
ownership dict + filing metadata), `fetch_submissions` (network).
**Engine** — `InsiderEngine.insider_signal_as_of(security_id, as_of) →
InsiderSignal` (purchases, sales, buy/sell value, net_value, insider_count,
ownership_change, cluster_buy) and `resolve_security(ticker, as_of)` via
SecurityMaster. Signal counts open-market P/S codes; grants/exercises stay in the
ledger but out of buy/sell pressure.

## Examples
```python
store.transactions_as_of(sid, date(2026, 1, 4))          # only filings public by Jan 4
eng = InsiderEngine(store, security_master=sm, cluster_threshold=3)
sid = eng.resolve_security("AAPL", date(2026, 1, 1))     # ticker → security_id (PIT)
sig = eng.insider_signal_as_of(sid, date(2026, 1, 4))
sig.cluster_buy, sig.net_value, sig.insider_count
```

## Benchmarks (`scripts/benchmark_insiders.py`, 1,000,000 rows / 10,000 securities)
- ingest **0.19M rows/s** (5.3 s)
- `transactions_as_of` **14.8 ms** (windowed collapse, one security)
- `insider_position_as_of` **2.2 ms**

## Quality gate
`tests/market_data`: **81 passed, 2 skipped** (was 74; +7 insider tests), zero
regressions. Repo swept: no insider read gates on `transaction_date` — all on
`acceptance_datetime`.

## Limitations
- **Live XML parse needs `xmltodict` + network** (backfill only); the parsers
  themselves are pure over an already-parsed dict, so tests are deterministic.
- **Cluster/signal use codes P and S only.** 10b5-1 plan sales aren't
  distinguished from discretionary sales (SEC flag exists on newer filings —
  additive later).
- **Derivative transactions are parsed but folded into the same ledger**; option
  economics (strike, expiry) aren't modeled — future extension.
- **security_id not auto-linked** on backfill; resolve via SecurityMaster or a
  later CIK→security_id enrichment pass (additive).
- No dedup of a Form 5 restating Form 4 items beyond the logical-key collapse.

## Future commercial data integration
Same append-only ledger + `acceptance_datetime` gate accepts richer feeds without
schema change: 2iQ / Washington Service / Sharadar SF3 (normalized insider data,
10b5-1 flags, cleaned identities) via a vendor adapter writing the same rows;
`vendor`/`source`/`data_version` already distinguish provenance.
