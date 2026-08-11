# AIDP M20 — Live Market-Data, Replay & Production Data-Construction Layer

The operational layer **above M19 and feeding M18**. M19 turns raw records into a PIT-validated
`MarketDataSnapshot`; M20 turns *sources* into a robust, deterministic data lifecycle around that
snapshot: adapter runtime, feed messages, ordering, arbitration, replay, historical PIT
reconstruction, snapshot lifecycle & store, incremental ingestion, operational monitoring, a
fault-injecting streaming simulator, and offline production-vendor contract boundaries.

**Package:** `src/aurelius/research/market_data_ops/` (16 modules, all additive).
**Tests:** `tests/research/test_market_data_operations.py` (154).
**Commit:** see the milestone index.

> **NO PAID MARKET-DATA CONNECTIVITY WAS CLAIMED OR REQUIRED.** M20 is fully buildable, testable,
> deterministic and certifiable without Bloomberg/Refinitiv/exchange credentials. The production
> vendor boundary is designed correctly but its transport methods raise `NotImplementedError` with
> the exact unblock — no network, no credentials, no fabricated vendor responses.

---

## 1. Objective

Make Aurelius structurally ready for an institutional data provider while proving the entire
internal data lifecycle today with free/local/fixture data. The defining property:

> Reconstruct a historically correct, provenance-complete, immutable market state from the
> information that was actually **knowable at a specified point in time** — reproducibly, and
> surviving revisions, duplicates, delays, source conflicts and replay — then feed M18 unchanged.

M20 does **not** rebuild M19 (normalization, quality, revisions, PIT builder, calibration) or M18
(valuation). It composes them.

## 2. Architecture

```
        FREE / LOCAL / FIXTURE DATA
                  │
        Source Adapter (capability model, lifecycle)      ── adapters.py
                  │  SourceMessage (immutable wire record) ── messages.py
                  ▼
        Ordering / Sequence policy                        ── ordering.py
                  ▼
        Multi-source Arbitration + Reconciliation         ── arbitration.py
                  ▼
        PIT gate (knowledge ≤ boundary, obs ≤ valuation)  ── reconstruction.py
                  ▼
   ┌────── M19 Normalizer → QualityEngine → SnapshotBuilder ──────┐   (reused unchanged)
   │              ▼                                                │
   │      M18 MarketDataSnapshot                                   │
   └──────────────┬───────────────────────────────────────────────┘
                  ▼
        Seal (lifecycle) → Store → Lineage/Registry       ── lifecycle/store/registry.py
                  ▼
        M18 valuation → M17 instruments → M13 risk         (unchanged)
```

Cross-cutting: **replay.py** (deterministic replay over a date range), **incremental.py**
(append-only state, incremental == full rebuild), **monitoring.py** (health/coverage/quality),
**simulator.py** (fault injection), **serialization.py**, **engine.py** (façade).

Every component is a small immutable, dependency-injected piece; the façade orchestrates and adds
no market-data logic of its own.

## 3. Data flow

Raw source → `SourceMessage` (wire identity preserved) → dedup/canonical ordering → per-key
arbitration across sources → admissibility filter (the PIT gate) → M19 normalize/quality/assemble →
M18 snapshot → seal → store. Historical reconstruction and live replay run the *same* pure function
of the admissible message set, which is why replay equals direct reconstruction.

## 4. PIT model

`reconstruct(valuation_date, knowledge_date)` admits a message only if:

- `knowledge_date(message) ≤ knowledge_date` (nothing knowable after the boundary), and
- `observation_date ≤ valuation_date` and `effective_date ≤ valuation_date` (no future data).

`knowledge_date(message)` is the source-timestamp's date, falling back to the observation date.
Among admissible messages, arbitration selects one winner per `(security, field, effective_date)`;
with the default policy the newest-known wins, so a later revision only appears once the knowledge
boundary reaches it. Look-ahead is therefore structurally impossible, and M18's `validate_pit`
re-checks the assembled snapshot as a second gate.

A bitemporal M19 `RevisionStore` is built in parallel over the admissible messages, so
`history` / `was_restated` / `known_as_of` audit queries survive every reconstruction.

## 5. Replay model

`MarketDataReplayEngine` replays a message log over a date range (explicit dates or the distinct
knowledge dates in range), emitting newly-knowable messages in canonical order at each date and
optionally reconstructing the PIT snapshot there. No wall-clock: the `speed` field is metadata only;
tests never sleep. A cumulative **replay fingerprint** (blake2b over emitted message fingerprints)
makes an entire replay reproducible. `knowledge_lag_days` models "value date T known as of T+lag".

## 6. Source adapters

`SourceAdapter` adds a lifecycle (`connect`/`disconnect`), subscription management, `fetch`
(historical/batch) and `poll` (streaming), a declared **capability set**, metadata and a health
probe on top of M19's raw sources. Concrete offline adapters: `LocalSourceAdapter` (wraps any M19
`MarketDataSource`), `MessageLogAdapter` (ordered log, backs replay/fixtures), `FixtureVendorAdapter`
(recorded vendor payloads for contract tests) and `ProductionSourceAdapter` (the live contract —
transport raises with an unblock).

**Capability model** (`SourceCapability`): historical, streaming, quotes, trades, bars,
reference_data, corporate_actions, rates, fx, options, curves, volatility, fundamentals. Callers
gate on capabilities instead of assuming uniform vendor semantics.

## 7. Source arbitration

`SourceArbiter` resolves conflicting observations per an explicit, fingerprinted `ArbitrationPolicy`:
`PRIMARY_SOURCE`, `SOURCE_PRIORITY` (configurable priority list — no hard-coded vendor preference),
`LATEST_VALID`, `CROSS_SOURCE_CONFIRMATION` (require ≥N sources within tolerance) and
`REJECT_ON_CONFLICT`. The policy fingerprint travels into the reconstruction fingerprint and the
sealed lineage.

## 8. Revision model

Restatements are ordinary messages with a later `knowledge_date` (and usually a higher `revision`).
Reconstruction never mutates prior records; the winner is selected by the knowledge boundary. The
parallel `RevisionStore` records the full bitemporal history so `was_restated` and `known_as_of`
answer audit questions. Deletions are `TOMBSTONE` messages that remove any winner they cover.

## 9. Snapshot lifecycle

States: RAW → NORMALIZED → QUALITY_CHECKED → PIT_VALIDATED → ASSEMBLED → SEALED (or REJECTED).
`SealedSnapshot` is a frozen record wrapping the (already immutable) M18 snapshot plus the
operational envelope: `snapshot_id` (deterministic content hash), as-of, knowledge date, source
set, input/accepted/rejected fingerprints, snapshot & reconstruction fingerprints, PIT status,
quality summary, component versions. `verify()` re-derives the fingerprints and the id → tamper
detection. Sealing is one-way (frozen dataclass).

## 10. Failure policies

Explicit, never hidden. **Ordering** (`OrderingPolicy`): STRICT (raise), REJECT (drop out-of-order,
keep in-order prefix), BUFFER (keep, diagnose only), REORDER (deterministic canonical sort,
default), LATEST_VALID (newest per key), QUARANTINE (divert). Every decision is an `OrderingEvent`.
**Arbitration** conflict → drop/insufficient-confirmation per policy. **Quality** (M19) → fail-closed
on valuation-critical rejects. **Malformed values** are non-numeric and dropped by normalization —
never silently coerced.

## 11. Data-quality monitoring

`QualityMonitor` composes the M19 quality engine (does not re-implement a rule) and rolls diagnostics
into a machine-readable `QualityHealthReport` (total/accepted/rejected, by-code, by-severity,
reject-rate). `HealthMonitor` derives per-source `FeedHealth` (CONNECTED/DEGRADED/STALE/DISCONNECTED/
ERROR) from a batch + ordering events + an **injected** `as_of` (no clock). `coverage` reports
present-vs-expected by security/field/date; missing data is listed, never read as zero.

## 12. Vendor contract boundary

`ProductionSourceAdapter` and the M19 `VendorAdapter` family define the exact live contract
(connect/subscribe/fetch/poll, field maps, raw→canonical translation) with transport methods raising
`NotImplementedError` + the precise unblock. A real deployment subclasses one, wires the transport,
and inherits the tested translation, ordering, arbitration and reconstruction.

## 13. Offline vendor testing

`FixtureVendorAdapter` serves recorded, vendor-labelled payloads; the contract tests verify message →
canonical translation, identifier mapping, unit/currency normalization, sequence handling,
provenance and fingerprints — labelled **offline contract tests**, connecting to nothing.

## 14. M18 / M19 integration

- **M19 reused unchanged:** `Normalizer`, `MarketDataQualityEngine`, `RevisionStore`,
  `MarketDataSnapshotBuilder`, PIT `validate_pit`, calibration objects, `IdentifierMap`, calendars.
- **M18 produced, not modified:** reconstruction yields an M18 `MarketDataSnapshot` the
  `ValuationEngine`/`PortfolioValuationEngine` consume with no special handling. Tested end-to-end:
  equity, option, future, bond and multi-asset portfolio value off an M20-reconstructed snapshot,
  reproducibly; FX reuses the injected M16 provider.

## 15. Performance

Deterministic, offline benchmark (`scripts/benchmark_m20_market_data_ops.py`), machine-dependent:

Message counts are the simulator's clean feed *plus* injected duplicates/revisions, so the rows are
~12k / ~120k / ~1.2M.

| messages | ingest | throughput | order | arbitrate | reconstruct | replay-emit | serialize 5k | peak (reconstruct) |
|---|---|---|---|---|---|---|---|---|
| ~12,000 | 558 ms | ~21,500/s | 119 ms | 89 ms | 1.05 s | 38 ms | 470 ms | 14.7 MB |
| ~120,000 | 5.66 s | ~21,300/s | 1.84 s | 1.12 s | 11.7 s | 663 ms | 484 ms | 148 MB |
| ~1,200,000 | 62.8 s | ~19,100/s | 25.9 s | 14.6 s | 130.3 s | 8.66 s | 493 ms | 1,468 MB |

Incremental ingest (50 batches, ~120k messages): 2.13 s — same final state fingerprint as one-shot
ingest. Reconstruction is dominated by M19's per-record normalization pass (linear ~9k winners/s);
ordering and arbitration are the linear operational passes; replay-emit (canonical order +
cumulative fingerprint, no re-reconstruction) is cheap. Memory scales with retained messages —
~1.2 GB peak at ~1.2M in-process, so multi-million-message windows should batch by security/date.

## 16. Scaling analysis

- **Ingest** — O(n) with fingerprint dedup (set membership). Linear throughput.
- **Ordering / arbitration** — O(n) canonical sort + grouping (arbitration's agreement search is
  O(k²) in *sources-per-key*, which is tiny). No accidental O(n²) over the message count.
- **Reconstruction** — dominated by M19 per-record normalization (pure-Python), linear in the
  admissible winner count; snapshot fingerprint is memoized by M18.
- **Replay** — one reconstruction per replay date; cost scales with dates × admissible set.
- **Memory** — grows with retained messages. Multi-million-message replay windows are memory-bound
  in-process; batch by security/date window (each `HistoricalSource` day is independent) and cache
  sealed snapshots by fingerprint.

## 17. Limitations (Known limitations / Skipped)

Each with the exact unblock, per the project rule that nothing is silently skipped. "Impossible"
here means a dependency/credential does not exist in this offline platform — not effort.

1. **Live vendor connectivity** — `ProductionSourceAdapter.connect/fetch/poll` raise. *Reason:* no
   Bloomberg/Refinitiv/exchange credentials by mandate. *Unblock:* subclass, implement the transport
   against the real endpoint returning `SourceMessage`s; ordering/arbitration/reconstruction already
   consume them. **INTERFACE ONLY / PRODUCTION UNBLOCK REQUIRED.**
2. **Full M18-snapshot on-disk serialization** — the store persists the metadata envelope only; the
   snapshot object is reproduced from the message log (its fingerprint verifies the rebuild).
   *Reason:* full curve/surface/fx-provider graph serialization is heavy and redundant with
   deterministic reconstruction. *Unblock:* add snapshot (de)serialization to M18 and wire the store
   to it. **DEFERRED.**
3. **Real-time streaming transport** — `poll` semantics are defined and tested offline via
   `MessageLogAdapter`; there is no socket/async event loop. *Unblock:* implement a live transport
   behind `poll` on a `ProductionSourceAdapter`. **INTERFACE ONLY.**
4. **Latency/timing health in real seconds** — health uses an injected `as_of` date, not sub-day
   wall-clock latency. *Reason:* determinism for historical research. *Unblock:* inject a real clock
   in an operational deployment context. **DEFERRED.**

## 18. No-paid-data constraint

Restated for governance: M20 authenticates against no proprietary service, claims no live
connectivity, makes paid data no prerequisite, fabricates no vendor response, and uses no network in
tests. Data strategy is existing Aurelius datasets → free/local → deterministic synthetic fixtures →
recorded vendor-shaped fixtures for contract testing.

## 19. Operational runbook

1. Wire adapters (`LocalSourceAdapter` over an M19 source, or a subclassed production adapter).
2. `engine.ingest_from_adapters(as_of)` or `engine.ingest(messages)` — append-only, deduplicated.
3. `engine.health(as_of=…)` / `engine.coverage(...)` / `engine.quality_health(as_of=…)` to gate.
4. `engine.reconstruct_snapshot(valuation_date, knowledge_date, …)` → M18 snapshot for valuation.
5. `engine.build_and_seal(...)` → sealed, stored, lineage-attributed snapshot.
6. `engine.replay(ReplayConfig(...))` for historical reconstruction over a range.
7. `store.verify_all()` for integrity; `lineage_of(sealed)` for the provenance chain.

## 20. Future Bloomberg/Refinitiv/exchange implementation path

Subclass `ProductionSourceAdapter` (or an M19 `VendorAdapter`), implement `connect`/`fetch`/`poll`
against the vendor SDK returning `SourceMessage`s, register capabilities, and inject vendor holiday
calendars and identifier maps. Nothing downstream changes: the same ordering, arbitration, PIT
reconstruction, sealing and store consume the messages, and the M18 snapshot the valuation engine
sees is identical in shape. The vendor adapter is a replaceable boundary, not an architecture change.

---

## Status legend

- **IMPLEMENTED / OFFLINE TESTED:** messages, adapters (local/log/fixture), ordering, arbitration,
  reconciliation, replay, PIT reconstruction, lifecycle, store, incremental, monitoring, simulator,
  serialization, registry/lineage, engine, M18/M19 integration.
- **INTERFACE ONLY / PRODUCTION UNBLOCK REQUIRED:** live vendor transport (`ProductionSourceAdapter`).
- **DEFERRED:** full on-disk snapshot serialization; real-second latency health.
