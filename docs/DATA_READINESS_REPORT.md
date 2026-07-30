# Data Readiness Report — Phase 27

Head of Data Engineering, 2026-07-30. Evidence-driven audit of the market-data
ingestion path for institutional-scale reproduction. One verified bottleneck
found and fixed; platform certified ready for the momentum/pairs papers.

Evidence: `scripts/benchmark_ingestion.py` (real `DuckDBStore.write_bars` path +
validation-coverage self-check). Reproduce with `python scripts/benchmark_ingestion.py`.

## 1. Ingestion audit (objective 1)

| Concern | Finding | Status |
|---|---|---|
| Formats | CSV (`CSVLoader`, case-insensitive headers + aliases), Yahoo/Alpaca adapters | OK |
| Schema | `ohlcv`: symbol, timestamp(TZ), frequency, OHLC, volume, vwap, trade_count, quality_score, **source**, **adjustment_factor** | OK for price papers |
| Date handling | 7 timestamp formats; naive → UTC; malformed rows skipped + counted | OK |
| Symbol handling | uppercased; unknown symbols skipped at pipeline resolution | OK |
| Corporate actions | none applied; `adjustment_factor` default 1.0 — **caller supplies adjusted close** | Documented contract |
| Missing values | non-numeric rows skipped; `detect_gaps` flags missing trading days | OK |
| Validation | `OHLCVBatchValidator` + `csv_loader` + `normalizer` — 12 categories (§4) | OK |

**Limiting assumption found:** the write path (`write_bars`) used per-row
`executemany` → **~1,130 rows/sec** (measured). See §3.

## 2. Canonical schema (objective 2)

Already normalized: all providers land in the single `ohlcv` table via
`CSVLoader`/adapters → `DuckDBStore`. Research modules read the store, never a
provider. **Provider-independence: satisfied** (Gatev/JT drivers touch only the
store + strategy templates).

Fields present cover price-based papers. **Absent:** `currency`, `exchange`,
explicit `corporate_action_flag`, fundamentals. See Known limitations.

## 3. Scalability + bottleneck (objectives 3, 6 — measured)

Benchmark, real write path, before/after the fix:

| Path | rows/sec | 37.8M-row load (5000×30y) |
|---|---|---|
| `executemany` (old) | ~1,130 | **~9.3 hours** — impractical |
| bulk DataFrame register + `INSERT OR REPLACE ... SELECT` (new) | **~256,000** | **~2.5 min** |

**~260× speedup, no new dependency** (pandas already installed). This is the one
VERIFIED engineering change this phase — justified by a measured limitation that
prevented legitimate large-dataset ingestion, per the stopping rule.

Post-fix capacity (measured medians: ~256k rows/sec, ~70–132 bytes/row):

| Target | Rows | Est storage | Est load |
|---|---|---|---|
| 100 × 10y | 252k | ~0.03 GB | ~1s |
| 500 × 20y | 2.52M | ~0.33 GB | ~10s |
| 1000 × 20y | 5.04M | ~0.67 GB | ~20s |
| 5000 × 30y | 37.8M | ~5 GB | ~2.5min |

Peak ingest memory scales with batch size (165 MB @ 200k rows); chunk very large
loads per-symbol or per-decade if RAM-bound. DuckDB is columnar single-file →
write is O(rows), no per-symbol overhead; no schema bottleneck at 37.8M rows.

## 4. Automated validation coverage (objective 4 — asserted)

`benchmark_ingestion.py --check` asserts each category fires at its real
enforcement point:

✓ zero price ✓ negative price ✓ negative volume ✓ OHLC relationship
✓ naive/malformed timestamp ✓ out-of-order ✓ split/spike >20%
✓ missing trading days ✓ malformed date row ✓ corrupt file
✓ duplicate rows (DuckDB PK + `INSERT OR REPLACE`) ✓ invalid symbol (pipeline skip)

## 5. Dataset catalog (objective 5)

Already implemented: `src/aurelius/catalog/` — `DatasetRecord` (name, provider,
coverage, date range, symbols, rows, file hashes, import date, validation status,
quality score, version), plus lineage, versioning/snapshots, governance,
monitoring, quality engine, REST api. 89 catalog/market_data tests pass. **No
work required.**

## 6. Readiness by paper type (objective 7)

| Paper type | Ready? | Why |
|---|---|---|
| Momentum (Jegadeesh-Titman) | **YES** | needs adjusted daily OHLCV only — fully ingestible + validated at scale |
| Pairs (Gatev) | **YES** | same inputs |
| Factor (Fama-French, Novy-Marx) | **NO** | needs fundamentals (size, book-to-market, gross profit) — no fundamentals table/loader exists |
| Fundamental | **NO** | same — separate dataset type |

## 7. Recommendation (stopping rule)

**Momentum + pairs papers: platform is READY.** Acquire an appropriately
licensed adjusted-OHLCV panel (≥100 symbols × ≥10 yr for JT deciles / Gatev pair
portfolio), drop it through `CSVLoader → DuckDBStore`, and **rerun
`reproduce_jegadeesh_titman.py` + `reproduce_gatev_pairs.py` unchanged**. If
results improve, the gain is data, not engine — the phase's objective.

**Next verified engineering item (factor/fundamental papers only):** a
fundamentals dataset type — schema + loader for point-in-time firm fundamentals.
Evidence: papers 4–7 cannot start without it (`REPRODUCTION_SCOREBOARD.md`).
Deferred, not built: out of scope for a market-OHLCV scale phase, and no licensed
fundamentals data is on hand to design against. Do NOT build speculatively.

## Known limitations / Skipped

**Currency / exchange / corporate-action-flag columns.**
- *Reason:* not required to ingest the target single-market adjusted-OHLCV
  datasets; adding now = speculative schema for data not on hand.
- *Unblock:* a multi-market or raw-price dataset that actually carries these;
  add columns + a corporate-action adjuster then. `adjustment_factor` already
  reserves the hook.

**Fundamentals ingestion (factor/fundamental papers).**
- *Reason:* no fundamentals table/loader; no licensed fundamentals data on hand
  to design the schema against.
- *Unblock:* acquire a licensed point-in-time fundamentals dataset; then build a
  `fundamentals` table + loader mirroring the OHLCV path.
