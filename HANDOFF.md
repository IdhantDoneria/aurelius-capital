# Mentisrex Capital — Session Handoff

> **SUPERSEDED:** This document reflects Phase 4 (2026-07-25). For current status see `docs/ACCEPTANCE_TEST.md` and the certification report below.

**Last updated:** 2026-07-28 (Phase 12 + IV&V certification)  
**Status:** 421/421 tests pass. Phases 1–12 complete. IV&V certified.

## Current State (Phase 12)

Platform is complete through the research pipeline:
- 421 tests, 0 failures
- IV&V audit conducted 2026-07-28: all CRITICAL/HIGH issues resolved
- See `docs/ACCEPTANCE_TEST.md` for Phase 12 acceptance criteria
- See `PHASE_4_PRODUCTION_REVIEW.md` through `PHASE_5_DEVELOPER_GUIDE.md` for engineering details

---

---

## What This Project Is

Institutional-grade quantitative research and trading platform. Python, FastAPI, PostgreSQL, DuckDB. Located at `/Users/idhantdoneria/mentisrex-capital`.

Run tests: `.venv/bin/pytest -q`  
Run app: `.venv/bin/uvicorn mentisrex.main:app --reload`

---

## Completed Phases

### Phase 1 — Core Infrastructure
- FastAPI skeleton, structlog, Pydantic settings
- `src/mentisrex/infrastructure/config/settings.py` — all config including Alpaca keys, DuckDB path
- `src/mentisrex/core/errors.py`, `logging.py`
- `src/mentisrex/presentation/api/routes/health.py`

### Phase 2 — Database Layer (PostgreSQL)
- SQLAlchemy async models: `market.py`, `trading.py`, `fundamental.py`, `reference.py`, `research.py`
- Alembic migration: `0001_initial_schema.py` — full schema including `symbols`, `ohlcv_daily`, `ohlcv_intraday`, `portfolios`, `orders`, `fills`, `positions`
- Repositories: `MarketDataRepository`, `TradingRepository` with bulk insert helpers
- Validators: `OHLCVBatchValidator`, `TradeValidator` with quality scoring (0–100)

### Phase 3 — Market Data Pipeline
- **Adapters** (`src/mentisrex/market_data/adapters/`)
  - `base.py` — `RawBar` frozen dataclass (Decimal prices), `MarketDataAdapter` ABC
  - `yahoo.py` — `YahooFinanceAdapter`: wraps `yf.download` in `asyncio.to_thread`, handles MultiIndex columns, UTC conversion
  - `alpaca.py` — `AlpacaAdapter`: raw httpx REST (no SDK), paginated, 3-attempt retry, 60s sleep on 429; WebSocket streaming via `websockets.connect()`; `from_settings()` classmethod
  - `csv_loader.py` — `CSVLoader`: case-insensitive column aliases, 6 timestamp format parsers, logs up to 5 parse errors per file
- **Pipeline** (`src/mentisrex/market_data/pipeline/`)
  - `normalizer.py` — `normalize_bar()`, `detect_gaps()` (threshold 5 days), `compute_spike()` (20% threshold)
  - `ingestion.py` — `IngestionPipeline`: normalize → bulk resolve symbols → gap detect → validate → quality score → bulk insert in 5000-row chunks. `IngestionReport` dataclass with `acceptance_rate` property.
- **Storage** (`src/mentisrex/market_data/storage/duckdb_store.py`)
  - `DuckDBStore`: `:memory:` uses persistent connection; file path opens/closes per query
  - Schema: `PRIMARY KEY (symbol, timestamp, frequency)`
  - Methods: `insert_bars()`, `query_bars()`, `rolling_mean()`, `cross_sectional()`, `quality_summary()`, `export_parquet()`
- **Service** (`src/mentisrex/market_data/service.py`)
  - `IngestionService`: `asyncio.Semaphore(concurrency=5)` for concurrent symbol fetches, optional DuckDB sync

### Phase 4 — Event-Driven Backtesting Engine
- **Config** (`src/mentisrex/backtesting/config.py`)
  - `BacktestConfig`: initial_capital=1M, commission=10bps, spread=5bps half-spread, slippage k=10bps, max_fill_pct_adv=20%, max_position_pct=10%, max_gross_leverage=1.5x, max_drawdown_halt=20%, risk_free_rate=5%, trading_days=252
- **Events** (`src/mentisrex/backtesting/events/`)
  - `base.py` — `EventQueue`: `heapq` with `(timestamp, EVENT_TYPE, seq, event)` tuples for total deterministic ordering
  - `types.py` — Priorities: Fill=1, Market=2, Signal=3, Order=4. `FillEvent.signed_cash_delta()`, `SignalEvent.direction` (LONG/SHORT/FLAT), `OrderEvent` with optional limit_price/stop_price
- **Data Feed** (`src/mentisrex/backtesting/data/feed.py`)
  - `BarData` frozen dataclass; `InMemoryDataFeed` (sorts on init); `DuckDBDataFeed` (streaming cursor)
- **Portfolio** (`src/mentisrex/backtesting/portfolio/`)
  - `position.py` — weighted avg cost basis, long/short/cover logic, realized/unrealized PnL
  - `state.py` — cash, positions dict, `_peak_value` tracking, `drawdown` property, `gross_leverage`, `snapshot()`
  - `manager.py` — `apply_fill()`, `size_order()` (target_value = NAV × max_position_pct × signal_strength)
- **OMS** (`src/mentisrex/backtesting/oms/`)
  - `order.py` — `Order` with `apply_partial_fill()` (weighted avg fill price), `from_event()` classmethod
  - `manager.py` — `OrderManager`: submit, track lifecycle, `apply_fill()`
- **Risk Engine** (`src/mentisrex/backtesting/risk/engine.py`)
  - Checks (in order): permanent halt flag → drawdown > max_drawdown_halt (sets halt permanently) → projected position size > 2× limit → projected leverage > limit
  - `RiskCheckResult(passed, reason)`, `reset()` to unhalt
- **Execution** (`src/mentisrex/backtesting/execution/`)
  - `models.py` — `CommissionModel(rate)`, `SpreadModel(half_spread_bps)`, `SlippageModel` (Almgren-Chriss sqrt impact: `bps = k × sqrt(Q/ADV)`)
  - `simulator.py` — `ExecutionSimulator.try_fill()`: base price at open → spread adjustment → 20% ADV partial fill cap → slippage impact → FillEvent. LIMIT buy fills if `bar.low <= limit_price` at `min(bar.open, limit_price)`. STOP sell fills if `bar.low <= stop_price`.
- **Strategy** (`src/mentisrex/backtesting/strategy/base.py`)
  - `StrategyContext`: `history(symbol, lookback)`, `close_series()`, read-only `portfolio`, `now`
  - `Strategy` ABC: `on_bar()` → `list[SignalEvent]`, optional `on_start()`, `on_end()`
- **Analytics** (`src/mentisrex/backtesting/analytics/`)
  - `performance.py` — `PerformanceCalculator.compute()`: CAGR, Sharpe, Sortino, max drawdown, Calmar, volatility, win rate, profit factor, avg holding period, turnover. FIFO round-trip matching. Returns `PerformanceMetrics` with `equity_curve` and `drawdown_series`.
  - `report.py` — `BacktestReport`: `summary()` text table, `to_dict()` JSON-serializable, `to_json()`
- **Engine** (`src/mentisrex/backtesting/engine.py`)
  - `BacktestEngine.run()`: per-bar loop → fill pending orders at bar open → push MarketEvent → drain queue → record equity
  - Next-bar execution: signals on bar T close fill at bar T+1 open (no look-ahead)
  - Partial fill remainder creates new OrderEvent carried to next bar

---

## Architecture Decisions to Know

| Decision | Why |
|---|---|
| `heapq` with `(ts, EVENT_TYPE, seq, event)` | Total ordering — ties broken by event priority then insertion order |
| `pending_orders` outside EventQueue | Prevents fills at signal bar; orders sit in list until next bar's open |
| httpx for Alpaca (not alpaca-py SDK) | Already installed; avoid extra dependency |
| DuckDB `:memory:` persistent connection | `duckdb.connect(":memory:")` each call = fresh DB; one connection = persistent |
| `CSVLoader` not a `MarketDataAdapter` subclass | Doesn't fit `fetch_ohlcv(symbol, start, end)` interface |
| Decimal everywhere for prices | No float rounding errors in PnL accounting |

---

## Next Phases (Not Started)

### Phase 5 — Strategy Library
Implement concrete strategies in `src/mentisrex/backtesting/strategy/`:
- `sma_crossover.py` — already tested via inline class in `test_engine.py`
- `momentum.py` — 12-1 month momentum, rebalance monthly
- `mean_reversion.py` — z-score based pairs or single-name
- `stat_arb.py` — cointegration-based pairs
- Factor models, ML model wrappers

### Phase 6 — FastAPI Research Endpoints
Extend `src/mentisrex/presentation/api/routes/`:
- `POST /backtests` — run backtest, return report JSON
- `GET /backtests/{id}` — retrieve stored report
- `GET /market-data/{symbol}` — query OHLCV from DuckDB/Postgres
- `POST /market-data/ingest` — trigger ingestion run

### Phase 7 — Live Trading (Alpaca Paper)
- Wire `AlpacaAdapter` WebSocket stream into a live engine variant
- Order routing via Alpaca REST
- Position reconciliation on startup

---

## Test Coverage

```
tests/
  backtesting/
    test_analytics.py    — PerformanceCalculator metrics (14 tests)
    test_engine.py       — End-to-end BacktestEngine with SMA/BuyAndHold (12 tests)
    test_events.py       — EventQueue ordering (7 tests)
    test_execution.py    — ExecutionSimulator, models (13 tests)
    test_portfolio.py    — Position accounting, PortfolioState (13 tests)
  market_data/           — adapters, pipeline, DuckDB store (68 tests)
  [core, db tests]       — schemas, validators (5 tests)
Total: 126 passed
```

---

## Known Warnings

11 `DeprecationWarning: datetime.datetime.utcnow()` from `<string>:16` — third-party library at runtime, not our code. Harmless.

---

## Key File Locations

| Component | Path |
|---|---|
| Backtest entry point | `src/mentisrex/backtesting/engine.py` |
| Strategy base class | `src/mentisrex/backtesting/strategy/base.py` |
| Backtest config | `src/mentisrex/backtesting/config.py` |
| Market data adapters | `src/mentisrex/market_data/adapters/` |
| DuckDB store | `src/mentisrex/market_data/storage/duckdb_store.py` |
| Ingestion pipeline | `src/mentisrex/market_data/pipeline/ingestion.py` |
| DB models | `src/mentisrex/infrastructure/database/models/` |
| Settings | `src/mentisrex/infrastructure/config/settings.py` |
| FastAPI app | `src/mentisrex/main.py` |
