# Aurelius Capital — Progress Tracker
<!-- SELF-DESTRUCT: First action in next session → run: rm /Users/idhantdoneria/aurelius-capital/HANDOFF_CURRENT.md /Users/idhantdoneria/aurelius-capital/PROGRESS.md -->

**Last updated:** 2026-07-28 | **Tests:** 421 | **Commit:** `4282e8e`

---

## Phase Completion

| Phase | Name | Status | Tests | Commit |
|---|---|---|---|---|
| 1 | Core Infrastructure (FastAPI, structlog, Pydantic settings) | ✅ Done | — | — |
| 2 | Database Layer (PostgreSQL, SQLAlchemy, Alembic) | ✅ Done | — | — |
| 3 | Market Data Pipeline (Yahoo, Alpaca, CSV, DuckDB) | ✅ Done | — | — |
| 4 | Production Review + Test Hardening | ✅ Done | 126 | — |
| 5 | Feature Engineering Platform | ✅ Done | ~180 | — |
| 6 | Research Workflow (ExperimentRecord, ResearchStore) | ✅ Done | ~200 | — |
| 7 | Risk Engine + Paper Trading | ✅ Done | ~220 | — |
| 8 | Portfolio Construction | ✅ Done | ~240 | — |
| 9 | Assistant (LLM reader/reviewer, no trading) | ✅ Done | ~255 | — |
| 10 | Backtesting Engine (event-driven, full OMS) | ✅ Done | 270 | `b0dbd97` |
| 11 | Literature Intelligence Framework | ✅ Done | 315 | `e9109e6` |
| 12 | Hypothesis Generation Framework | ✅ Done | 315 | `27e2386` |
| IV&V | Institutional Certification Audit | ✅ Done | 421 | `4282e8e` |
| 13 | — not scoped — | ⏳ Pending | — | — |

---

## IV&V Audit Summary (2026-07-28)

### Fixed
- 3 CRITICAL quant bugs (raw prices from Yahoo/Alpaca/DuckDB — corporate action adjustments were silently ignored)
- 1 HIGH quant bug (Sortino formula wrong — raw returns not excess returns)
- 1 HIGH quant bug (EMA cold-start bias — seeded on single point not SMA)
- 1 HIGH quant bug (random_seed declared but never consumed by engine)
- 1 MEDIUM quant bug (pstdev vs stdev in cross-sectional z-score)
- 6 HIGH code issues (utcnow deprecated, broker null dereference, _tz() pattern)
- 3 HIGH security issues (hardcoded DB password fallback, missing prod guard, broken lru_cache)
- Multiple medium/low: STOPWORDS consolidated, StrEnum migration, stale type: ignore removed, magic numbers named
- +106 tests: trading validation, market validation, cache, DuckDB feed, statistical features

### Open (Documented, Not Fixed)
- Short-side round trips dropped in `_reconstruct_trades()` — needs structural fix for L/S strategies
- `MarketDataRepository` interface never implemented
- Layer violations (risk/construction → backtesting) — low operational risk
- Docker ports on 0.0.0.0 — bind to 127.0.0.1

---

## Current Test Coverage Gaps (After IV&V)

Still low/untested (require integration fixtures or large mocks):
- `infrastructure/database/repositories/trading.py` (0%) — async SQLAlchemy
- `infrastructure/database/repositories/market.py` (36%) — async SQLAlchemy
- `market_data/adapters/yahoo.py` (0%) — yfinance mock surface
- `market_data/adapters/alpaca.py` (0%) — Alpaca SDK mock surface
- `market_data/service.py` (0%) — depends on DB repos

---

## Key Files for Next Session

| Purpose | Path |
|---|---|
| Session handoff | `HANDOFF_CURRENT.md` ← delete after reading |
| Architecture docs | `docs/LITERATURE_FRAMEWORK.md`, `docs/HYPOTHESIS_FRAMEWORK.md` |
| Research workflow | `docs/RESEARCH_OS.md`, `docs/RESEARCH_PROGRAM.md` |
| Acceptance criteria | `docs/ACCEPTANCE_TEST.md` |
| IV&V agent roles | `~/.claude/projects/-Users-idhantdoneria/memory/agent_roles_aurelius_ivv.md` |
| Developer guide | `PHASE_5_DEVELOPER_GUIDE.md` |
| Open issues | See HANDOFF_CURRENT.md → "Open Issues" section |

---

## Decisions Log

| Decision | Rationale |
|---|---|
| `LLMClient = Callable[[str], str]` — one seam | Swap model without touching core code |
| `assistant` structurally cannot trade | Research tool only; enforced by missing trading path |
| `paper_id` = sha256 deterministic | Idempotent re-ingestion |
| `HypothesisRecord.id` = UUID4 random | Statement can change without ID change |
| `data/` gitignored | DuckDB files never committed |
| Jaccard dedup with domain stopwords | No ML deps; O(n); fast at 10k hypotheses |
| Template fallback when LLM absent | Offline-capable; graceful degradation |
