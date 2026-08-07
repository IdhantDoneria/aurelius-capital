# AIDP — Data-Layer Audit & Gap Roadmap

Scope decision (2026-08-06): the "AURELIUS INSTITUTIONAL DATA PLATFORM" spec is
largely a **rewrite of a platform that already exists and is certified** for the
current momentum/pairs research (`docs/DATA_READINESS_REPORT.md`). We do **not**
rebuild. We audit what's shipped against the spec's correctness requirements,
then close the genuinely-missing pieces. This doc = the audit + the roadmap.

## What already exists (do not rebuild)

| Spec block | Where |
|---|---|
| Raw → normalize → validate → warehouse | `market_data/{adapters,pipeline,storage}` |
| Typed access layer (research reads store, never a provider) | `market_data.storage.DuckDBStore` + `infrastructure/database/repositories` |
| Catalog: versioning, lineage, quality (6 checks), governance, monitor | `catalog/` (M22) |
| Validation: 12 categories | `validation/`, `market_data/pipeline` |
| Feature store + factor library | `features/library`, `features/store.py` |
| Reproducibility (result → dataset version) | `catalog` content-hash versioning |
| Postgres canonical model: raw price + `adjustment_factor`, `isin/cusip/figi`, `ingested_at`, UUID `symbol_id` | `infrastructure/database/models/{market,reference,fundamental}` |

The Postgres model is well-designed (stores **raw** prices + an adjustment factor,
UUID symbol ids, alt-identifier columns). The gaps below are where the **research
read path** (DuckDB) and the **ingest connectors** fall short of that model.

## Audit findings (grounded in code)

Severity: 🔴 corrupts research silently · 🟠 correctness gap · 🟡 minor.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| **P1** | 🔴 | **Retroactive-adjustment PIT leak.** Yahoo adapter runs `auto_adjust=True` → stores *today's* split/div-adjusted close. `DuckDBStore.write_bars` is `INSERT OR REPLACE`, one row per `(symbol,ts,freq)`, no ingest/known-as-of time. A later re-fetch after a split silently restates all prior closes. `cross_sectional(as_of=D)` then returns post-D-adjusted prices → **every backtest reading this store leaks future corporate actions into the past.** | `adapters/yahoo.py:61`, `storage/duckdb_store.py:89,151` |
| **P2** | 🔴 | **No bitemporal history in the research store.** No `available_date`/`ingested_at`/`revision` on the DuckDB `ohlcv` table (Postgres has `ingested_at`; research doesn't query Postgres). Cannot reconstruct "what was known as of D." Backfills/revisions overwrite with no trace. | `storage/duckdb_store.py:31-48` |
| **C1** | 🟠 | **No corporate-action store/engine.** Adjustment is delegated to the upstream vendor; no `corporate_actions` table, so splits/divs can't be audited, replayed PIT-correctly, or un-adjusted. Root cause of P1. | no `corporate_actions` table anywhere |
| **I1** | 🟠 | **Ticker-keyed research store + no identity history.** `Symbol` has `isin/cusip/figi` columns but the DuckDB store keys on `symbol` VARCHAR (the ticker), and there is no temporal alias/identity-history table (ticker→id over time). Spec's "never rely on ticker" holds in Postgres, breaks in the research path. | `reference.py:131`, `duckdb_store.py:33` |
| **F1** | 🟠 | **Fundamentals model empty — no EDGAR ingest.** `fundamental.py` (344 lines) is unused; no shares-outstanding time series → market-cap cannot be computed point-in-time. | `models/fundamental.py`, no EDGAR adapter |
| **S1** | 🟠 | **Survivorship bias.** No delisting table; `cross_sectional` sees only currently-present symbols → historical universes silently drop dead names. | no `delistings` table |
| **Q1** | 🟡 | Quality gap-check flags holidays as gaps (calendar-naive `INTERVAL '4 days'`). Acceptable heuristic; upgrade to exchange calendar if false positives bite. | `catalog/quality.py:157` |

P1/P2/C1 are one problem: the research store is **not corporate-action-aware and
not bitemporal.** Fixing that is the whole ballgame — it's the only 🔴.

## Roadmap — 5 phases, each independently testable

Ordered by dependency + severity. Each ships with ONE runnable check.

1. **M1 — PIT-correct, corp-action-aware price store** (fixes P1, P2, C1).
   Store raw prices + a `corporate_actions` event table; derive adjustment
   factors on read; add a known-as-of guard so `as_of` queries can't see later
   restatements. Additive (new tables/API) — does not break the existing `ohlcv`
   readers. *Check:* `tests/market_data/test_pit_leakage.py` (ships now, xfail →
   must pass at end of phase).
2. **M2 — Identifier master + identity history** (I1). Temporal
   `security_aliases (id, ticker, valid_from, valid_to)`; research store keys on
   internal id; ticker→id resolver is date-aware. *Check:* resolve a reused
   ticker to the correct entity at two different dates.
3. **M3 — EDGAR fundamentals + shares outstanding + PIT market-cap** (F1).
   EDGAR connector (free) → populate `fundamental`; market-cap = PIT shares ×
   PIT price. *Check:* market-cap as-of a pre-restatement date ignores later
   share-count revisions.
4. **M4 — Delisting + survivorship-free universe** (S1). `delistings`
   table; PIT universe constructor includes then-live, now-dead names. *Check:*
   universe as-of 2015 contains a since-delisted symbol.
5. **M5 — Insider transactions (EDGAR Form 4)** — spec item, free source.
   *Check:* filing_date ≠ transaction_date respected (no look-ahead).

## Known limitations / Skipped (per CLAUDE.md)

Each: what · why impossible/deferred now · what unblocks it.

- **Bloomberg, FactSet, CRSP, Compustat, Polygon, Tiingo, IBKR, Nasdaq Data
  Link, AlphaVantage connectors** — *skipped, impossible now.* No subscription,
  API key, or credentials for any of these exist in the environment (external
  system unavailable). *Unblock:* provision an account + key; each then drops
  into the existing `MarketDataAdapter` interface (`adapters/base.py`).
- **RBAC, API keys, encrypted-credential vault, read-only research role**
  — *deferred.* Single operator; no second principal or multi-tenant boundary
  exists to enforce against, so there is nothing for access control to gate
  today. *Unblock:* a second user/service account, or an external deployment.
- **Chaos testing, 10B-row scaling, distributed execution, options/futures
  data** — *deferred.* Free sources (Yahoo/FRED/Fama-French/EDGAR) yield
  ~10⁸ rows; single-box DuckDB handles that (benchmarked 256k rows/s). No
  profiler or dataset currently approaches these limits. *Unblock:* a paid
  tick/options feed or a measured bottleneck at current scale.

These are surfaced, not silently dropped. The scope choice (audit + close the 5
real gaps) is the reason they're out; none is blocked by effort.
