# Aurelius Capital — Session Handoff
<!-- SELF-DESTRUCT: First action in next session → run: rm /Users/idhantdoneria/aurelius-capital/HANDOFF_CURRENT.md /Users/idhantdoneria/aurelius-capital/PROGRESS.md -->

**Date:** 2026-07-28  
**Commit:** `4282e8e` — `audit(iv-v): institutional certification — Phase 13 ready`  
**Tests:** 421 passing, 0 failing  
**Status:** Phases 1–12 complete. IV&V certified. Ready for Phase 13.

---

## Active Modes

- **Caveman (full):** Always on. Terse prose, drop articles/filler/hedging. Code/commits/docs = normal English.
- **Ponytail (ultra):** Always on. YAGNI. Deletion before addition. Challenge the requirement.

---

## What This Is

Institutional quantitative research platform. Python 3.12, FastAPI, PostgreSQL (SQLAlchemy async), DuckDB, structlog. No trading execution — research pipeline only.

```
src/aurelius/
├── core/              # errors, logging
├── domain/            # entities (OHLCV, Symbol) — aspirational DIP stubs
├── application/       # interfaces/repositories.py — MarketDataRepository (unimplemented, see open issues)
├── infrastructure/    # DB connection, SQLAlchemy models, repos, Redis cache, migrations
├── presentation/      # FastAPI routes: /health, /metrics
├── market_data/       # Adapters (Yahoo, Alpaca, CSV), pipeline, DuckDB store
├── features/          # Feature registry + library (price, vol, technical, statistical, volume)
├── backtesting/       # Event-driven engine, portfolio, execution, OMS, risk, analytics
├── construction/      # Portfolio builder, sizing, exposure, aggregation, optimizer
├── risk/              # RiskEngine, RiskMonitor, stress tests
├── paper/             # Paper trading engine, broker, journal, dashboard
├── research/          # ExperimentRecord, ResearchStore (DuckDB), runner, validation, templates
├── assistant/         # LLM assistant: reads papers, reviews code, reports — CANNOT trade
├── literature/        # Phase 11: 7-source ingestion pipeline (arXiv, NBER, SSRN, JF, JFE, RFS, QF)
└── hypothesis/        # Phase 12: hypothesis generation, quality filter, dedup, store
```

---

## How to Run

```bash
cd /Users/idhantdoneria/aurelius-capital
.venv/bin/python -m pytest -q                          # 421 tests
.venv/bin/uvicorn aurelius.main:app --reload           # API server
.venv/bin/python scripts/ingest_literature.py --help   # literature ingestion
.venv/bin/python scripts/generate_hypotheses.py --help # hypothesis generation
.venv/bin/python scripts/research_dashboard.py         # research status
.venv/bin/python scripts/acceptance_validation.py      # acceptance tests
```

Python env: always `.venv/bin/python`, never system `python`.

---

## This Session — IV&V Audit (2026-07-28)

### What Was Built

Nothing new. This session was a full institutional IV&V audit across all 12 phases.

5 specialized subagents ran in parallel:
1. **Quant Validator** — backtesting math, corporate actions, risk formulas
2. **Code Quality Inspector** — static analysis, dead code, type safety
3. **Testing Auditor** — coverage gaps, missing edge cases, wrote 106 new tests
4. **Security Auditor** — secrets, injection risks, config exposure
5. **Architecture Auditor** — layer violations, interface compliance, documentation

Agent role definitions saved to:
`/Users/idhantdoneria/.claude/projects/-Users-idhantdoneria/memory/agent_roles_aurelius_ivv.md`

### Fixes Applied

**Critical (3 fixed):**
- `market_data/adapters/yahoo.py`: `auto_adjust=False → True` — raw prices produced ±100% return spikes on split dates
- `market_data/adapters/alpaca.py`: `adjustment=raw → all` — unadjusted prices from Alpaca
- `backtesting/data/feed.py` + `market_data/storage/duckdb_store.py`: `adjustment_factor` column added to DuckDB schema; OHLC now multiplied at query time

**High (5 fixed):**
- Sortino denominator: was raw returns, now excess returns `(r - rf_daily)`
- `datetime.utcnow()` (deprecated, naive) → `datetime.now(UTC)` in 6 callsites
- `broker._tz()` deferred import pattern removed; `UTC` at module level; `limit_price` asserted non-None before `_fill()`
- `BacktestEngine.__init__` now calls `random.seed(config.random_seed)` — previously declared but never consumed
- EMA cold-start: was seeded on `series[0]`, now seeded on `SMA(first span bars)`

**Security (3 fixed):**
- `migrations/env.py`: raises `RuntimeError` if `DATABASE_PASSWORD` unset (was falling back to `"dev_password"`)
- `settings.py`: production guard added for `database_password == "change_me"`
- `dependencies.py`: removed `@lru_cache` on `Depends()`-parameterized functions (broke test isolation)

**Medium/Low (many fixed):**
- `aggregation.py`: `pstdev` → `stdev` (ddof=1) for cross-sectional z-score
- `risk/monitor.py`: `_TRADING_DAYS = 252` named constant replaces bare literals
- `hypothesis/_utils.py`: new file — `STOPWORDS` consolidated (was duplicated in `quality.py` and `deduplication.py`)
- `DuplicateStatus(str, Enum)` → `StrEnum` (consistent with codebase)
- `demo` removed from `__all__` in 4 packages (risk, construction, paper, assistant)
- SQL injection safety comment added to `hypothesis/store.py`
- 5× stale `# type: ignore[arg-type]` removed from `csv_loader.py`
- 3× stale `# type: ignore[assignment]` removed from `trading.py`
- Health-check exception logging: `str(exc)` → `type(exc).__name__` (no DSN leak in logs)
- `README.md` rewritten from 19-byte stub to full documentation
- `HANDOFF.md` updated (was 8 phases out of date)

**New Tests (+106, 315 → 421):**
- `tests/infrastructure/test_trading_validation.py` — 30 tests (was 0% coverage)
- `tests/infrastructure/test_market_validation.py` — 35 tests
- `tests/infrastructure/test_cache.py` — 18 tests
- `tests/backtesting/test_data_feed.py` — 11 tests
- `tests/features/test_statistical_features.py` — 15 tests

---

## Open Issues (Intentionally Unresolved)

These are documented, not forgotten. Fix in Phase 13 or when the pain point hits.

| Issue | File | Priority | Why deferred |
|---|---|---|---|
| Short-side `_reconstruct_trades()` drops short P&L | `backtesting/analytics/performance.py:203` | HIGH — fix before L/S strategies | Structural: needs `short_lots` deque |
| `MarketDataRepository` interface never implemented | `application/interfaces/repositories.py` | MEDIUM | Delete or implement — zero-cost to defer |
| `train_test()` warm-start contaminates OOS | `research/validation.py:83` | MEDIUM — adaptive strategies only | Document the constraint in docstring |
| `aurelius.risk` → `backtesting.portfolio.state` coupling | `risk/engine.py` | LOW | Extract `PortfolioState` to domain layer |
| `aurelius.construction` → `backtesting` coupling | `construction/builder.py` | LOW | Same fix |
| Docker ports bound `0.0.0.0` | `docker-compose.yml` | LOW | Bind to `127.0.0.1` for cloud deployments |
| `/metrics` endpoint unauthenticated | `presentation/api/routes/metrics.py` | LOW | Network-restrict or add APIKey dep |
| `domain/exceptions/` is empty dead code | `domain/exceptions/__init__.py` | LOW | Delete or populate |
| `RESEARCH_PROGRAM.md` missing ValidationCriteria thresholds | `docs/RESEARCH_PROGRAM.md` | LOW | Add reference table |

---

## Key Architecture Decisions (Never Change These)

1. **`LLMClient = Callable[[str], str]`** — the only AI seam in `assistant`, `literature.enrichment`, `hypothesis.generator`. Zero SDK imports in core. Swap model by passing different callable or `None`.

2. **`aurelius.assistant` cannot trade.** Reads papers, generates hypotheses, reviews code, detects bias, writes reports. Enforced structurally — no trading path exists.

3. **`paper_id` = `sha256(f"{source}:{source_id}")[:32]`** — deterministic, idempotent ingestion. Re-ingesting same paper is a no-op.

4. **`HypothesisRecord.id` = UUID4** — random, not content-derived. Allows updating `testable_statement` without ID change.

5. **`data/` directory** is gitignored. Contains `research.duckdb`, `literature.duckdb`, `hypothesis.duckdb`. Never commit.

6. **Never commit from `~/.git`** — always commit inside `/Users/idhantdoneria/aurelius-capital/.git`.

---

## Phase 13 — What Comes Next

Not scoped yet. Natural candidates based on current state:

- **Experiment Execution Layer** — wire `HypothesisRecord → ExperimentRecord → BacktestRunner → ResearchStore`; the research pipeline is fully built but hypothesis → experiment handoff is manual
- **Fix short-side analytics** — `_reconstruct_trades()` for L/S strategies
- **Live data ingestion scheduler** — cron/APScheduler for periodic `ingest_literature.py` + `generate_hypotheses.py`
- **Research dashboard web UI** — FastAPI route exposing hypothesis queue, research status, equity curves

Wait for user instruction before starting Phase 13.

---

## Git Log (Recent)

```
4282e8e audit(iv-v): institutional certification — Phase 13 ready
27e2386 feat: Hypothesis Generation Framework (Phase 12)
e9109e6 feat: Literature Intelligence Framework (Phase 11)
b0dbd97 fix(test): correct golden-case return threshold for position sizing
```
