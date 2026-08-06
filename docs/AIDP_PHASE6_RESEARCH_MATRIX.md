# AIDP Phase 6 — Point-in-Time Research Matrix Engine

One PIT-safe accessor over the five certified engines. Give it a date; get back a
reproducible, survivorship-free research snapshot keyed by `security_id`, every
field gated so `knowledge_date ≤ as_of`. Additive; Phases 1–5 logic untouched.

Module: `src/aurelius/market_data/research_matrix/` (`engine.py`, `schema.py`,
`feature_registry.py`, `quality.py`).

```python
m = eng.feature_matrix_as_of(date(2020, 6, 30))
m.frame            # DataFrame indexed by security_id, one column per feature
m.metadata         # as_of_date, universe_size, data_versions, generated_at
m.directions       # feature → "higher" | "lower"
```

## Architecture

Composition, not a new data layer. The engine holds the four existing engines and
routes each feature to the source that owns it:

| Source | Accessor (existing) | Identity key |
|---|---|---|
| price | `PitPriceStore.window_as_of` (new, additive) | PIT ticker |
| fundamental | `FundamentalsStore.cross_section_as_of` | CIK |
| insider | `InsiderStore.signals_as_of` (new, additive) | security_id |
| universe | `UniverseEngine.universe_as_of` | security_id |
| identity | `SecurityMaster` (under the universe/price paths) | security_id |

Per snapshot the engine computes **one bundle per source**, not one call per
feature: a price window per security, a fundamental cross-section per input
concept (whole universe in one query), a single batched insider aggregate for the
whole universe. Feature columns are then dict lookups over those bundles — so 50
columns cost essentially the same as 18 (benchmark: 3.47 s vs 3.44 s).

### Security key normalization

Rows key on `security_id`. Each source resolves its own key from it:
- **price** — the PIT ticker `SecurityMaster` already put in the universe row
  (`live_as_of`), so a rename resolves to the right price series automatically.
- **fundamental** — CIK, via a caller-supplied `cik_map: {security_id → cik}`.
  SEC filings are CIK-native and `SecurityMaster` holds no CIK, so the link is an
  explicit input, not a duplicate identity table. Missing CIK → fundamental cells
  are null (not an error).
- **insider** — `security_id` directly (the insider ledger already carries it).

No ticker join is duplicated: the one PIT ticker resolution lives in
`SecurityMaster`, and everything else keys on `security_id`/CIK.

## PIT guarantees

Every field inherits its source's `*_as_of` gate — this layer adds no new
temporal logic, so it cannot introduce look-ahead.

- **Fundamentals** gate on `period_end ≤ as_of AND filing_date ≤ as_of`. A Q1
  (period end Mar 31) filed May 10 is invisible on Apr 30, visible on May 11.
- **Insiders** gate on `acceptance_datetime ≤ as_of` — never `transaction_date`.
  A trade Jun 1 accepted Jun 3 is invisible Jun 2, visible Jun 4.
- **Prices** are split-adjusted only by actions effective `≤ as_of` and announced
  `≤ knowledge_date`; `window_as_of` reuses `close_as_of`'s certified adjustment,
  not a fork.
- **Universe** is `UniverseEngine`'s survivorship-free listing-interval set: a
  company alive on a historical date is present even if delisted today; one that
  IPO'd later is absent.

Cross-source isolation is proven end-to-end in the tests (a future fundamental
filing and a future insider filing are both invisible in the same matrix).

## Feature registry

`feature_registry.py` maps `name → (source, field, direction)`. The engine reads
the named field out of the source's bundle; adding a feature that reads an
existing bundle field is a one-line registry edit, no engine change. 18 features
ship: 5 price (close, returns, volatility, volume, dollar_volume), 8 fundamental
(market_cap, book_value, earnings_yield, cashflow_yield, roe, roa,
operating_margin, leverage), 5 insider (buy/sell/net value, insider_count,
cluster_buy). `direction` (sign of "good") rides in `matrix.directions`; no factor
optimization happens in this layer.

Adding a feature backed by a *new* bundle field is two lines (extractor + registry
row); a genuinely new source is the only case that touches engine wiring.

## Caching

Deterministic in-memory cache keyed by
`(as_of, universe_hash, feature_set, data_versions)`.

- `universe_hash` = blake2b of the sorted `security_id`s.
- `data_versions` = per-source **row counts**. All five stores are append-only, so
  a count is a monotonic version signal: any ingest changes the count, changes the
  key, misses the cache. No manual version bump, no stale reads.

Cached retrieval is a dict hit (1.4 ms for 10k × 50), so repeated backtest passes
over the same as-of date pay the build once.

## Quality checks

`quality.check(matrix)` reports structural integrity only — PIT correctness is
enforced upstream, nothing to re-verify. Flags duplicate `security_id`s (the only
real corruption) and lists all-null columns (informational: missing data is legal,
a security may simply lack fundamentals). Missing data in one row never touches
another — proven by `test_missing_data_isolated`.

## Benchmarks (`scripts/benchmark_research_matrix.py`, 10,000 securities)

| | Result | Target |
|---|---|---|
| initial build (50 cols) | **3.47 s** | < 10 s |
| cached retrieval | **1.45 ms** | < 500 ms |
| matrix memory | 6.4 MB | — |

The batched fundamental cross-section and batched insider aggregate are what make
the target: the naive per-security point path was ~108 s (fundamentals alone
~85 s). Column count is near-free (18 cols → 3.44 s, 50 cols → 3.47 s).

## Tests (`tests/market_data/test_research_matrix.py`, 6, all offline)

1. future fundamental filing not visible · 2. future insider filing not visible ·
3. delisted company included historically / excluded now · 4. ticker migration
resolves to the same security_id · 5. reproducibility (same inputs → identical
frame; cache returns the same object) · 6. missing data isolated + `check` clean.

Full `tests/market_data`: **87 passed, 2 skipped** (was 81; +6), zero regressions.

## Known limitations / Skipped

- **`cik_map` is a required input for fundamental features.** SEC filings are
  CIK-native and `SecurityMaster` stores no CIK, so security_id→CIK cannot be
  resolved internally. Unblocked by a CIK column/enrichment pass on
  `SecurityMaster` (additive, Phase 2 extension) — then `cik_map` becomes optional.
- **`returns` = trailing-window total return; `volatility` = daily-return pstdev**
  over the price window (default 252 calendar-day lookback). Not annualized, no
  factor-model residualization — these are inputs, not finished factors.
- **50-column benchmark uses aliases onto the 18 real bundle fields.** Only 18
  distinct features exist; the alias padding honestly measures column-assembly
  cost (which is near-zero), not 50 independent computations.
- **`asset_growth` and `ev_ebitda`** (in `factor_inputs_as_of`) are not exposed as
  matrix columns — they need a prior-period query per security that the batched
  cross-section path skips. Add via a two-period cross-section if required.
- **No persistence of the matrix** — cache is per-process, in-memory. A parquet /
  versioned catalog write is the ML feature-store step below.

## Future ML feature-store migration path

The matrix is already the right shape for a feature store: a dense, versioned,
PIT-safe `(security_id × feature)` frame stamped with `data_versions`. To migrate:
1. Persist each `feature_matrix_as_of` to a partitioned parquet/Delta table keyed
   by `(as_of_date, data_versions)` — the cache key becomes the storage key, so
   materialized snapshots are reproducible and immutable.
2. Register features (name, source, direction, dtype) in the existing
   `feature_registry` — it's already the schema of record; a training pipeline
   reads it to assemble label-aligned feature sets.
3. Point-in-time training joins become "read the snapshot whose `data_versions`
   were current at `as_of`" — no leakage, because the gate is baked into the
   stored frame, not reapplied at train time.

No ML infrastructure is built here (out of scope, YAGNI): the engine stays a pure
PIT accessor; the feature store is a thin persistence layer over it when a model
actually needs one.
