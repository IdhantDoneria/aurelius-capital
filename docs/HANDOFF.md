# Session Handoff — Aurelius Capital

**Read this, then delete it.** Ephemeral. Warm-starts one fresh session, then self-destructs. All durable content lives in the code it points to. **Delete this file (`docs/HANDOFF.md`) once read.**

Repo: `/Users/idhantdoneria/aurelius-capital` (git, branch `main`). Venv at `.venv` — **use `.venv/bin/python`, not `python`**.

---

## Operating modes (both ON, persist across session)

- **Ponytail (ultra)** — YAGNI extremist. Deletion before addition. No fix until a profiler or real dataset demands it. Climb the ladder before writing anything.
- **Caveman (full)** — terse chat prose. **Code, commits, docs, security = normal English.**

**Hard rule:** NEVER commit from HOME repo `/Users/idhantdoneria/.git` (stages entire home dir + dotfiles). Commit only inside `/Users/idhantdoneria/aurelius-capital/.git`.

---

## What this session did

**Scalability readiness audit — measure only. NO code changed. NO files written except this handoff.** Research logic was explicitly off-limits.

Micro-benchmarked on this box (single core):
- CSV parse: **~100K bar/s**
- Feature compute: **~2,400 bar/s** (18 features, ~43K feature-rows/s)
- Backtest engine: **~30K bar/s** at 20 symbols (per-bar cost grows with active symbols)

Daily bars ≈ 252/yr/symbol.

## Findings (verdict: ready ~100 symbols × ≤7yr only)

Three independent walls, each fires before runtime matters:

1. **Depth cap = 7 years, fixed window 2020–2026.** Postgres OHLCV is `PARTITION BY RANGE (timestamp)`, monthly partitions only for `range(2020, 2027)`, **no DEFAULT partition** — `src/aurelius/infrastructure/database/migrations/versions/0001_initial_schema.py:264-274`. Any bar outside → insert error. `feature_values` covers 2015–2026 but useless without OHLCV.

2. **O(symbols × total_bars) gap detection** — `src/aurelius/market_data/pipeline/ingestion.py:128-132` re-scans the whole `known_bars` list per ticker. 3000 sym × 22.7M bars ≈ 68B ops → hours. Bites at ~500+ symbols.

3. **In-memory OOM.** Every ingestion + research path holds full dataset in RAM: ingestion ~6 list copies (`ingestion.py:114-167`); `FeaturePipeline.compute_batch` returns one list + unbounded cache (`features/pipeline.py:46,91`); research re-materializes + re-sorts full set per backtest slice (`research/validation.py:44`). ~22.7M bars × ~6 copies ≈ 95 GB. Dies before ~3M bars.

Target scales: **100×10yr = PARTIAL** (pre-2020 rejected; 7yr slice fine). **500×20yr = BLOCKED** (depth + ingest degrade). **3000×30yr = BLOCKED on all axes.**

Other notes: single-thread everything (no parallel across symbols/grid/partitions); Decimal in hot loops caps feature rate; DuckDB analytics = single local file, single-writer, static partition set, no cold tier.

## Deferred fixes (reported, NOT applied — do not start unprompted)

Laziest-first, only if user asks:
1. Depth wall — add DEFAULT partition (`CREATE TABLE ..._default PARTITION OF market_data_ohlcv DEFAULT`). One line.
2. O(S×N) gap-detect — group `known_bars` by symbol once (dict/`itertools.groupby`), not S scans. ~3 lines.
3. OOM — stream ingest per-symbol instead of 6 full copies. Bigger; only at those scales.

## Then implemented (audit fixes 1 & 2 only — streaming redesign #3 left alone)

Both APIs preserved; research/experiment/feature logic untouched.

1. **Depth cap removed** — new migration `src/aurelius/infrastructure/database/migrations/versions/0002_ohlcv_default_partition.py` adds a DEFAULT partition to `market_data_ohlcv`. Arbitrary dates now insert; propagated indexes keep queries fast; hot-window (2020–2026) pruning intact. Ceiling: cold rows share one default partition (see `# ponytail:` note in the migration).
2. **O(S×N) gap detect fixed** — `src/aurelius/market_data/pipeline/ingestion.py` buckets `known_bars` by symbol in one pass (`defaultdict`) instead of re-scanning per ticker. Measured **10× / 55× / 104×** faster at 100 / 500 / 1000 symbols; identical output.

Tests: `tests/market_data/test_pipeline.py` +2 unit (multi-symbol gap attribution); `tests/market_data/test_ohlcv_partitions.py` new integration (default-partition attached + out-of-window insert routes to default). Full non-integration suite: **575 passed**.

## Uncommitted state

Nothing committed. Changed on disk: migration 0002, `ingestion.py`, `test_pipeline.py`, `test_ohlcv_partitions.py`, this handoff.
**Integration test for fix 1 NOT run here** — no Postgres/Docker in this env (port 5433 closed). Unblock: bring up the test stack (`docker compose -f docker-compose.test.yml up`), `alembic upgrade head`, then `.venv/bin/python -m pytest tests/market_data/test_ohlcv_partitions.py -q`.
