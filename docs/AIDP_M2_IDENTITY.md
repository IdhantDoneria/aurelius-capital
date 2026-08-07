# AIDP M2 — Temporal Security Identity Layer

Institutional (CRSP/Compustat-style) security identity. Ticker stops being an
identity and becomes a time-versioned *attribute*; the stable reference is
`security_id`. Additive — no existing store or engine was rewritten.

Module: `src/aurelius/market_data/identity/` · Store: `data/identity.duckdb`.

## Why

Every research/backtest/feature path keys on the ticker string
(`BarData.symbol`, `feature_values(symbol,…)`, `DuckDBDataFeed.symbols()`).
Tickers rename (FB→META), get reused decades apart (GOOG), migrate exchanges,
and delist. Ticker-as-identity silently maps the wrong instrument. Finding I1 in
`AIDP_AUDIT_AND_ROADMAP.md`.

## Model

`security_id` ≈ CRSP **PERMNO**: identifies a *listing*, deterministic +
idempotent (`make_security_id`). Key priority: FIGI (already exchange-specific)
→ `(ISIN, exchange)` → `(ticker, exchange, first_date)`. ISIN is
*instrument*-level and is the cross-listing link (≈ PERMCO) via `by_isin`, so a
dual listing is two `security_id`s sharing one ISIN.

### `security_master` (current state, one row per listing)
`security_id` (PK) · isin · cusip · figi · sedol · ticker (current) · exchange ·
country · currency · asset_type · primary_listing · status
(`active|delisted|merged|renamed`) · created_at · updated_at

### `security_identity_history` (temporal, one row per interval)
`security_id` · ticker · exchange · `valid_from` · `valid_to`
(`9999-12-31` = open) · reason · source. Every ticker/exchange change closes the
open interval and opens a new one. Intervals are half-open `[valid_from, valid_to)`.

Indexes: `history(ticker, valid_from, valid_to)`, `history(security_id, valid_from)`,
`master(isin)`, `master(figi)`.

## Resolution is deterministic

`resolve_as_of(ticker, as_of)` selects the interval with
`valid_from ≤ as_of < valid_to`. Disjoint reuse (old GOOG 1998–2001, new GOOG
2014–) resolves by date; a query in the gap returns `None`. No ambiguity.

## API

| Method | Purpose |
|---|---|
| `register(Security, valid_from, reason, source)` | create/upsert a listing + open its first interval (idempotent) |
| `add_identity_change(security_id, new_ticker, exchange, valid_from, reason)` | rename / exchange migration |
| `set_status(security_id, status, as_of=None)` | delist / merge (optionally close interval) |
| `resolve_as_of(ticker, as_of) -> security_id?` | deterministic PIT lookup |
| `resolve_universe(tickers, as_of) -> {ticker: security_id}` | **batch** — the research path |
| `lookup_by_ticker(ticker) -> [security_id]` | every entity that ever used a ticker |
| `lookup_by_security_id(id) -> Security` | full record |
| `current_identifier(id)` / `historical_identifier(id, as_of)` | current / as-of ticker |
| `by_isin(isin) -> [security_id]` | dual listings / share classes |

### Example
```python
sm = SecurityMaster("data/identity.duckdb")
fid = sm.register(Security(security_id=make_security_id(isin="US30303M1027", figi=None,
        ticker="FB", exchange="XNAS", first_date=date(2012,5,18)),
        ticker="FB", exchange="XNAS", isin="US30303M1027"), valid_from=date(2012,5,18))
sm.add_identity_change(fid, new_ticker="META", exchange="XNAS",
        valid_from=date(2022,6,9), reason="rebrand")
sm.resolve_as_of("FB",   date(2015,1,1)) == fid   # True
sm.resolve_as_of("META", date(2023,1,1)) == fid   # True — same entity
```

## Migration guide (non-breaking)

1. `python scripts/backfill_security_master.py --source data/analytics.duckdb --table raw_ohlcv`
   — registers one security per distinct ticker, interval from first observed bar.
   Idempotent. Enrich ISIN/CUSIP/FIGI later from Postgres `Symbol` or a vendor.
2. Research/backtest keep passing tickers. To become PIT-correct, resolve the
   universe once per rebalance date:
   `ids = sm.resolve_universe(tickers, as_of)` and carry `security_id` alongside.
3. No schema of the existing `ohlcv`/`raw_ohlcv`/`feature_values`/backtest paths
   changed. Nothing to re-run; 30+ existing research DBs are untouched.

## Performance

100k listings (`scripts/benchmark_identity.py`): `resolve_universe` 100k as-of =
**270 ms (0.4M resolutions/s)** — the path research uses. Point `resolve_as_of`
≈ 500 µs/call (DuckDB per-query fixed cost); resolve universes in one batch call,
not N point calls.

## Known limitations / Skipped

- **No automatic corporate-identity feed.** Renames/mergers/spin-offs are
  recorded via API, not auto-detected. *Why:* free sources don't publish a clean
  identity-change feed. *Unblock:* SEC EDGAR former-names + a vendor mapping
  (CRSP/OpenFIGI) in M3+.
- **Backfill has no ISIN/CUSIP/FIGI** (price stores carry only tickers); ids fall
  back to `(ticker, exchange, first_date)`. Enrichment is a follow-up, additive.
- **Engines not rekeyed to `security_id`.** Deliberate: rekeying `BarData`,
  `feature_values`, and every research query is a breaking change to 30+ derived
  DBs, and the spec mandates no breaking changes. The resolver + shim make ticker
  deterministically resolvable — the actual goal. A full rekey, if wanted, is its
  own breaking phase. Remaining ticker-keyed spots are enumerated in the M2
  commit's "remaining assumptions".
- **ADR↔ordinary and parent↔spin-off linkage** are separate `security_id`s with
  no explicit relationship edge yet. *Unblock:* a `security_links` table (future).

## Future extensions

`security_links` (ADR/ordinary, parent/spin-off, pre/post-merger) · EDGAR
former-name auto-ingest · OpenFIGI enrichment · `security_id` as an additive
column on `raw_ohlcv`/`feature_values` for opt-in native keying.
