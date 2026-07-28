# Aurelius Capital

Institutional-grade quantitative research and trading platform. Python 3.11+,
FastAPI, PostgreSQL (OLTP), DuckDB (analytical store), Redis (cache). Covers
the full research lifecycle from literature ingestion to paper trading.

---

## Architecture

```
Literature (Phase 11)       Hypothesis (Phase 12)
  arXiv / NBER / CrossRef ──► HypothesisGenerator ──► HypothesisStore
        │                               │
        ▼                               ▼
  LiteratureStore                 ResearchAssistant (Phase 10)
                                        │
     ┌──────────────────────────────────┘
     │
     ▼
  Research Experiment Framework (Phase 6)
    ResearchRunner ──► BacktestEngine ──► ValidationReport ──► ResearchStore
                            │
     ┌──────────────────────┘
     │
     ├── FeaturePipeline (Phase 5)
     │     registry · library · FeatureStore (DuckDB)
     │
     ├── RiskEngine (Phase 7)
     │     pre-trade checks · position/leverage caps · drawdown halt
     │     PortfolioRiskMonitor · StressTester
     │
     ├── PortfolioBuilder (Phase 8)
     │     signal aggregation · sizing · optimization · exposure overlay
     │
     └── PaperTrading (Phase 9)
           PaperBroker · TradingEngine · TradeJournal · replay

Infrastructure
  PostgreSQL (SQLAlchemy async) · DuckDB stores · Redis cache · Alembic
  pydantic-settings · structlog · FastAPI + Prometheus /metrics
```

**Major subsystems**

| Package | Role |
|---|---|
| `aurelius.backtesting` | Event-driven engine: T+1 fills, cost model (Almgren-Chriss), OMS, risk gate, analytics |
| `aurelius.features` | Feature registry + pipeline + DuckDB store (price, vol, technical, statistical) |
| `aurelius.research` | Experiment lifecycle: hypothesis → backtest → validation → verdict → store |
| `aurelius.literature` | Literature intelligence: fetch, parse, LLM-enrich, store papers |
| `aurelius.hypothesis` | Hypothesis generation from papers, quality filter, dedup, DuckDB store |
| `aurelius.risk` | Production risk engine: VaR, stress, drawdown, liquidity checks |
| `aurelius.construction` | Portfolio builder: signal aggregation, optimizers, exposure limits |
| `aurelius.paper` | Paper trading: supervised wall-clock loop, crash recovery, journal |
| `aurelius.assistant` | AI research assistant: paper parsing, code review, bias detection |
| `aurelius.market_data` | Ingestion adapters (Alpaca, Yahoo, CSV) + DuckDB analytical store |
| `aurelius.infrastructure` | PostgreSQL models, repositories, migrations, Redis cache, config |
| `aurelius.presentation` | FastAPI routes, health/metrics endpoints, request logging middleware |
| `aurelius.core` | Shared errors and structured logging |
| `aurelius.domain` | Pure domain entities (OHLCV, Symbol, TimeRange) and repository interfaces |

---

## Quick Start

```bash
# 1. Clone and create virtual environment
git clone <repo> aurelius-capital && cd aurelius-capital
python -m venv .venv && source .venv/bin/activate

# 2. Install (editable)
pip install -e ".[dev]"

# 3. Copy environment template and configure
cp .env.example .env
# Edit .env: DATABASE_URL, ALPACA_API_KEY, etc.

# 4. Start dependencies
docker compose up -d postgres redis

# 5. Apply migrations
alembic upgrade head

# 6. Run the API server
uvicorn aurelius.main:app --reload

# 7. Run all tests
pytest -q
```

**Python env path:** `.venv/bin/python`  
**Test command:** `.venv/bin/pytest -q`

---

## CLI Commands

```bash
# Ingest academic literature
python scripts/ingest_literature.py --source arxiv --limit 100
python scripts/ingest_literature.py --source all --since 2024-01-01 --enrich

# Generate hypotheses from ingested papers
python scripts/generate_hypotheses.py generate --source arxiv --limit 50
python scripts/generate_hypotheses.py list --status Draft --limit 20
python scripts/generate_hypotheses.py stats

# Research dashboard (read-only queries over research.duckdb)
python scripts/research_dashboard.py

# Institutional acceptance test (5 benchmark strategies, end-to-end)
python scripts/acceptance_validation.py

# Backup PostgreSQL (run from cron)
./scripts/backup.sh
```

---

## Project Structure

```
aurelius-capital/
├── src/aurelius/           # All source code (editable install)
│   ├── backtesting/        # Event-driven backtesting engine
│   ├── features/           # Feature engineering platform + registry
│   ├── research/           # Experiment tracking: runner, store, models
│   ├── literature/         # Literature ingestion + LLM enrichment
│   ├── hypothesis/         # Hypothesis generation + quality + dedup
│   ├── risk/               # Risk engine, monitor, stress tester
│   ├── construction/       # Portfolio construction: sizing, optimize
│   ├── paper/              # Paper trading engine + journal
│   ├── assistant/          # AI research assistant (reads code/papers)
│   ├── market_data/        # Adapters (Alpaca, Yahoo, CSV) + DuckDB store
│   ├── infrastructure/     # DB models, repos, migrations, cache, config
│   ├── presentation/       # FastAPI routes, middleware
│   ├── domain/             # Domain entities + repository interfaces
│   └── core/               # Shared errors + logging
├── tests/                  # 315 tests across all subsystems
├── scripts/                # CLI tools: ingest, generate, dashboard, validate
├── docs/                   # Architecture and research framework docs
│   ├── ACCEPTANCE_TEST.md  # CTO acceptance audit (Phase 12, 2026-07-27)
│   ├── ALPHA_TAXONOMY.md   # 15 alpha categories + hypothesis factory + scorecard
│   ├── DEPLOYMENT.md       # Production runbook (Docker, secrets, CI/CD)
│   ├── HYPOTHESIS_FRAMEWORK.md
│   ├── LITERATURE_FRAMEWORK.md
│   ├── RESEARCH_OS.md      # Research operating system: process, templates, KPIs
│   └── RESEARCH_PROGRAM.md # Research constitution: governance, lifecycle, gates
├── docker/                 # Dockerfile(s)
├── docker-compose.yml      # Postgres + Redis + app
├── alembic.ini             # DB migration config
└── pyproject.toml          # Package + dev dependencies
```

---

## Development Guide

See `PHASE_5_DEVELOPER_GUIDE.md` for a complete guide to writing strategies against the backtesting engine, including the Strategy ABC, StrategyContext API, signal types, position tracking, config reference, and common patterns.

See `docs/RESEARCH_OS.md` for the full research workflow — templates, lifecycle stages, and KPIs.

Key design rules:
- All prices and quantities use `Decimal` (no float drift).
- Backtesting enforces strict T+1 execution (no look-ahead).
- `aurelius.assistant` is structurally forbidden from importing any execution path.
- Every experiment is pinned to a `dataset_fingerprint`; reruns of dead ideas are auto-blocked by `ResearchStore.find_duplicate`.

---

## Status

**Phase 12 complete.** 315 tests pass. Platform readiness: 72/100 (single-asset
research ready today; cross-sectional pending point-in-time data and survivorship-
free universes — see `docs/ACCEPTANCE_TEST.md` §Phase 3 for the full blocker list).
