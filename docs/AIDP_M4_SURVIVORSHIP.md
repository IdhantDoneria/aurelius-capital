# AIDP M4 — PIT Universe + Delisting Metadata Engine

Reconstruct the investable universe as of any historical date, **survivorship-free**.
`universe_as_of("2010-06-30")` returns the securities that existed and were
investable then — including companies that have since disappeared — and excludes
anything that listed later. Additive; M1–M3 unchanged.

Modules: `src/mentisrex/market_data/{delistings,universe}/`.

## Motivation

Research over today's ticker list is survivorship-biased: bankrupt/merged names
were dropped, so backtests inherit an upward bias and understate risk. A 2010
strategy must see 2010's live names (Lehman gone, Twitter not yet public); a 2026
run must not leak future listings backward. Audit gap **S1**.

## Architecture — reuse, don't duplicate

The spec's "security_listing_intervals" model **already exists** as M2's
`security_identity_history` (identical columns: `security_id, ticker, exchange,
valid_from, valid_to, reason, source`), and `set_status(as_of=…)` already closes
an interval on delist/merger. The spec explicitly forbids duplicate identity
systems, so M4 **composes over that table** instead of creating a second one.

```
DelistingStore (delisting_events, append-only)
   └─ apply_to_master() ─→ SecurityMaster.set_status(as_of=effective_date)
                              └─ closes the open listing interval
UniverseEngine.universe_as_of(date)
   └─ SecurityMaster.live_as_of(date)   (valid_from ≤ date < valid_to)
        → UniverseSnapshot
```

Only genuinely-new storage is `delisting_events` — the event detail (type/reason/
last_trade_date) the M2 status flag can't hold.

## Schemas

### `delisting_events` (new, append-only — `data/delistings.duckdb`)
`id` (seq PK) · `security_id` · `event_date` (announced/known) · `effective_date`
(listing actually ended) · `delisting_type` · `reason` · `last_trade_date` ·
`exchange` · `source` · `vendor` · `data_version` · `created_at` · `updated_at`.
Index `(security_id, effective_date)`. Types: MERGER, BANKRUPTCY, LIQUIDATION,
VOLUNTARY_DELIST, EXCHANGE_DELIST, ACQUISITION, UNKNOWN (→ mapped to master
status merged/delisted).

### Listing intervals (reused — M2 `security_identity_history`)
No new table. Examples: AAPL `1980-12-12 → open`; Lehman `… → 2008-09-15`;
Twitter `2013-11-07 → 2022-11-08`.

### SecurityMaster additions (additive read methods only)
`live_as_of(date) -> [{security_id, ticker, exchange}]` · `all_securities()`.

## PIT rules

A security qualifies on `date` iff `valid_from ≤ date < valid_to`. Consequences,
all automatic from the interval model:
- **Future IPO invisible** — interval starts after `date` → excluded.
- **Delisted name preserved** — interval covered `date` even though it later closed.
- **Future delisting isolation** — a delisting effective in 2022 sets `valid_to=2022`;
  `universe_as_of(2010)` still sees the then-open interval. Recording a later event
  never mutates an earlier universe.
- **Ticker migration** — the interval carries the ticker live on `date`
  (historical → old ticker, current → new).

## Examples

```python
eng = UniverseEngine(security_master, delisting_store=dl)
snap = eng.universe_as_of(date(2010, 6, 30))
snap.security_count            # live constituents in 2010
snap.securities                # [{security_id, ticker, exchange}, ...]
eng.universe_as_of(date(2010,6,30), with_exclusions=True).exclusions
                               # [{..., exclusion_reason: 'delisted'|'not_yet_listed'}]
```
`python scripts/audit_survivorship.py` (demo) →
```
as-of 2010-06-30: 2   current: 2
disappeared since 2010-06-30: 1   future listings excluded: 1
PASS: historical universe differs from current — survivorship-free
```

## Benchmarks (`scripts/benchmark_universe.py`, in-memory)
50,000 securities (30% delisted): `universe_as_of` **21.5 ms**, with exclusion
accounting 55.9 ms. Backed by the indexed interval predicate.

## Data loading

`scripts/backfill_delistings.py --file <csv> --vendor <name> [--apply]`. Vendor-
agnostic: any source mapping to the columns works (SEC EDGAR company history,
Yahoo inactive tickers, manual). `--apply` pushes effective dates into
SecurityMaster so universes reflect them. vendor/source stored per event.

## Limitations
- **Effective-time, not bitemporal-known-time.** Intervals use effective dates;
  a delisting announced later than it was effective isn't separately time-tracked
  (universe uses the standard effective-date convention). *Unblock:* add a
  known-date column to the identity history (M2 change — deferred).
- **Delisting data is only as complete as what's loaded.** No free source gives a
  clean full delisting feed; `delisting_events` is the interface, backfill is
  vendor-driven. Empty store → universe still correct for currently-open listings
  but under-captures dead names until backfilled.
- **`universe_as_of` is unfiltered** (all live listings). Liquidity/price filters
  (min ADV, min price) compose on top via existing research liquidity utils —
  not part of identity.
- Benchmark seeding uses row-wise inserts (slow); not a product path.

## Future data-provider integrations
SEC EDGAR `submissions` (former-names, last-filing → inferred delist) feeding the
backfill · CRSP delisting codes/returns (paid) · exchange delisting notices ·
Sharadar/Quandl inactive-ticker sets — all via the same vendor-agnostic CSV/DTO
interface, no engine change.
