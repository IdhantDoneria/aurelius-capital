# Mentisrex Capital — Session Handoff

**Last updated:** 2026-08-21  
**Status:** 421 tests pass. M1–M41 complete. First backtest cycle completed; strategy frozen for forward campaign.

---

## What This Project Is

Institutional-grade quantitative research and trading platform. Python 3.11+, FastAPI, PostgreSQL, DuckDB, Redis.

**Canonical milestone index:** `docs/MENTISREX_MILESTONE_INDEX.md`  
**Formal trading strategy:** `docs/TRADING_STRATEGY_FORMAL.md`

Run tests: `.venv/bin/pytest -q`  
Run app: `.venv/bin/uvicorn mentisrex.main:app --reload`

---

## Current State (As of Aug 21, 2026)

### Work Completed Aug 19–21
- **Factor engine + Parquet feed fallback** — M41 area; cross-sectional strategy scaffolding
- **First backtest run recorded** — Aug 19; results captured
- **4 bugs fixed** from first backtest run
- **Volume-momentum strategy** implemented with pre-computed signals
- **Regime-gated long-short attempt** — **REVERTED**. Short book wiped portfolio to -101.8%. Root cause: anti-momentum shorts select beaten-down value names (e.g., AMZN -55% in 2022, shorted, recovered 130%, stopped out 3x). Short overlay needs P/E/P/S fundamentals data to screen value traps.
- **Current strategy: long-only 12-1 month momentum** on US liquid equities (NYSE/NASDAQ/AMEX, ≥$5M, ≥$500K ADV)
- **Frozen forward candidate:** `mom-12-1-india-cs` v1.0.0 (M41), fingerprint `823e007d57305aca21a869b3f9ee799e`, NSE top-300 cross-sectional 12-1M momentum

### Test Coverage
**421 tests pass** (per prior HANDOFF). All major components covered:
- Backtesting engine, events, portfolio accounting, execution simulator
- Market data adapters (Yahoo, Alpaca, CSV), pipeline, DuckDB storage
- Risk engine, analytics, performance metrics
- DB schemas, validators

---

## Open Blockers

### P0 — Research Integrity
1. **HAC/Newey-West standard errors absent** — t-stats overstate significance on autocorrelated momentum returns. Located in `significance.py`. Blocks formal inference.
2. **Purged/embargoed cross-validation absent** — label-horizon leakage in panel research. Blocks rigorous model validation.

### P1 — Strategy Completeness
3. **Cross-sectional neutralization** (sector, beta, vol) — unimplemented
4. **Signal redundancy detector** — absent

### P0/P1 — Data Blockers
5. **Survivorship-free fundamentals** (P/E, P/S) — needed to screen value traps in short overlay (see revert note above)
6. **Daily NSE live feed** — needed to begin sealed forward campaign cycles for `mom-12-1-india-cs`
7. **PIT universe data** — Priority-1 per `DATA_ACQUISITION_BRIEF.md`

---

## Next Steps (In Order)

1. **Fix HAC standard errors in `significance.py`** (P0 — research integrity)
2. **Implement purged cross-validation** (P0)
3. **Source fundamentals data** to enable short overlay screening
4. **Wire daily NSE feed** to begin forward campaign for `mom-12-1-india-cs`

---

## Key File Locations

| Component | Path |
|---|---|
| Backtest entry point | `src/mentisrex/backtesting/engine.py` |
| Strategy base class | `src/mentisrex/backtesting/strategy/base.py` |
| Trading strategy doc | `docs/TRADING_STRATEGY_FORMAL.md` |
| Milestone index | `docs/MENTISREX_MILESTONE_INDEX.md` |
| Significance/t-stats | `src/mentisrex/research/significance.py` |
| Market data adapters | `src/mentisrex/market_data/adapters/` |
| DuckDB store | `src/mentisrex/market_data/storage/duckdb_store.py` |
| FastAPI app | `src/mentisrex/main.py` |

---

## Architecture Notes

- **Event-driven backtest engine:** heapq with `(timestamp, EVENT_TYPE, seq, event)` for total deterministic ordering
- **Decimal everywhere for prices** — no float rounding errors in PnL accounting
- **Next-bar execution:** signals on bar T close fill at bar T+1 open (no look-ahead)
- **Execution model:** base price at open → spread → 20% ADV cap → slippage (Almgren-Chriss sqrt impact)
- **Risk engine:** permanent halt on -20% drawdown; projection checks for position size and leverage

---

## Known Warnings

11 `DeprecationWarning: datetime.datetime.utcnow()` from `<string>:16` — third-party library, harmless.

---

## Frozen Forward Candidate

**Strategy:** `mom-12-1-india-cs` v1.0.0 (M41)  
**Fingerprint:** `823e007d57305aca21a869b3f9ee799e`  
**Universe:** NSE top-300 by market cap  
**Signal:** 12-1 month cross-sectional momentum  
**Rebalance:** monthly  
**Status:** Ready for sealed forward campaign once daily NSE feed is live.
