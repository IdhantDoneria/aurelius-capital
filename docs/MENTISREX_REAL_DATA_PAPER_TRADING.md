# Mentisrex — Real Market Data Paper Trading

**EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED**
**NO REAL CAPITAL IS DEPLOYED.**
**REAL MARKET DATA DOES NOT IMPLY REAL-TIME EXCHANGE-GRADE DATA.**

---

## 1. Architecture

```
M21 YahooFinanceSourceAdapter.convert(records, as_of)
      ↓  list[SourceMessage]                                [M20]
    extract OBSERVATION payloads
      ↓  list[dict]
    Normalizer + MarketDataQualityEngine                    [M19]
      ↓  accepted CanonicalObservations
    MarketDataSnapshotBuilder → MarketDataSnapshot          [M18]
      ↓
    PaperTradingLoop.process_snapshot(snapshot)             [M23]
      ↓
    StrategyRuntime (EqualWeightMomentumLogic)              [M22]
      ↓
    PortfolioEngine → RiskEngine → OrderRequests            [M10/M13/M14]
      ↓
    Paper Execution (MockBroker)                            [M12]
      ↓
    CycleRecord + ForwardPerformanceRecord                  [M23]
      ↓
    ForwardValidationEngine                                 [M24]
```

No provider-specific objects escape the adapter layer.
No direct provider calls are made inside M22, M23, M24, strategy logic,
portfolio, risk, or execution modules.

---

## 2. Supported Provider

**Yahoo Finance via yfinance**

- Capabilities: HISTORICAL, BARS, CORPORATE_ACTIONS
- Credentials: **none required** (yfinance is credential-free)
- Adapter: `mentisrex.research.market_data.providers.yahoo.adapter.YahooFinanceSourceAdapter`

**Limitations:**
- Yahoo Finance is a free/public data provider.
- Data may be delayed (typically 15–20 minutes for real-time; end-of-day is usually available next morning).
- Adjusted prices are applied retroactively by Yahoo; downstream PIT validation detects look-ahead.
- Yahoo Finance is NOT equivalent to Bloomberg, Refinitiv, or institutional exchange-grade data.
- Occasional data gaps, ticker changes, and price corrections are expected.

---

## 3. Data Fields

For each security in the universe, the Yahoo adapter emits:

| Field | Type | Description |
|---|---|---|
| `close` | float | Unadjusted closing price |
| `adj_close` | float | Split/dividend-adjusted close (separate SourceMessage) |
| `open`, `high`, `low` | float | OHLC (included in payload, used for future analysis) |
| `volume` | float | Daily trading volume |
| `dividends` | float | Dividend amount (REFERENCE message) |
| `stock_splits` | float | Split ratio (REFERENCE message) |

The snapshot builder uses `close`/`adj_close` for `spots`. When both differ,
both are passed to M19 — the revision resolution keeps the latest.

---

## 4. Identifier Mapping

For the current experimental universe:

```
UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "JNJ", "V"]
```

Yahoo tickers match the internal security IDs exactly. No `IdentifierMap` is
required. If a ticker-to-internal-id mapping is needed in future, pass an
`IdentifierMap` to `LiveFeedConfig.id_map` — the adapter resolves PIT-aware.

If a ticker cannot be resolved: the observation is **rejected/quarantined**,
not silently guessed. Missing securities are recorded in `FeedMetrics.missing_securities`.

---

## 5. PIT Handling

The M19 `MarketDataQualityEngine` enforces:

| Check | Action |
|---|---|
| `observation_date > as_of` (look-ahead) | **REJECT** — observation dropped |
| `observation_date < as_of - max_staleness_days` | WARNING — stale, still accepted (configurable) |
| `value ≤ 0` (non-positive price) | **REJECT** — observation dropped |
| `NaN / None value` | **REJECT** — observation dropped |

`PITPolicy.fail_closed=False` is used for paper-trading: a rejected security
is skipped rather than crashing the entire cycle. The rejection is recorded in
diagnostics and metrics.

The Yahoo adapter also pre-filters at the adapter level:
- Records dated after `as_of` are dropped in `_one()` before normalization.

---

## 6. Snapshot Generation

```python
from mentisrex.research.paper_trading.live_feed import LiveFeedBuilder, LiveFeedConfig
from datetime import date

config = LiveFeedConfig(
    universe=("AAPL", "MSFT", "GOOGL", ...),
    fetch_window_days=5,       # fetch last 5 calendar days from Yahoo
    max_staleness_days=5,      # reject observations >5 days old
    provider_name="yahoo_finance",
)
builder = LiveFeedBuilder(config)
result = builder.fetch_snapshot(date.today())
snapshot = result.snapshot  # MarketDataSnapshot: as_of, spots, fingerprint()
```

For offline/test use:
```python
result = builder.fetch_snapshot_from_records(fixture_records, as_of)
```

---

## 7. Scheduling

The strategy `ew-momentum-exp v1.0.0` uses `rebalance_frequency="monthly"`.

`PaperTradingLoop.process_snapshot()` passes the snapshot through
`RebalanceScheduler.is_due()`. If the strategy already evaluated this month,
the cycle is skipped (recorded as `skip_reason="not_due"`).

Run `run_live_cycle(as_of)` once per day (or per desired observation cadence).
The scheduler ensures evaluation only occurs at the right frequency.

---

## 8. Paper Execution

All execution is paper-only via `MockBroker`:

- `M14 OrderRequest` → `MockBroker.place_order()` → `BrokerFill` (immediate, perfect fill at marked price)
- No order reaches any broker, exchange, live EMS, or real-money account.
- Position accounting via `PaperPortfolio` (M11).
- Reconciliation via `reconcile()` after every cycle.

**Alpaca integration status:** No Alpaca adapter was found in the codebase.
Live broker connectivity is out of scope for this integration. Paper execution
uses `MockBroker` only.

---

## 9. Configuration

`LiveFeedConfig` fields:

| Field | Default | Description |
|---|---|---|
| `universe` | (required) | Tuple of ticker/security IDs |
| `fetch_window_days` | 5 | Days of history to fetch from Yahoo |
| `max_staleness_days` | 5 | Reject observations older than N days |
| `provider_name` | `"yahoo_finance"` | Provider label in provenance |
| `timezone` | `"America/New_York"` | Yahoo timezone |
| `id_map` | `None` | IdentifierMap for PIT-aware ticker→id mapping |
| `pit_fail_closed` | `False` | If True, raise on any rejected close price |

No credentials or API keys are required. No secrets are committed.

---

## 10. Manual Smoke Test (Real Data)

```bash
cd mentisrex-capital
python scripts/forward_run/run_forward.py \
    --mode PAPER_LIVE_FEED \
    --as-of $(date +%Y-%m-%d)
```

The script reports:
```
REAL MARKET DATA: YES
PAPER EXECUTION: YES
LIVE EXECUTION: NO
NO REAL CAPITAL DEPLOYED.
NO STRATEGY PARAMETERS WERE OPTIMIZED USING FORWARD DATA.
```

For a specific date:
```bash
python scripts/forward_run/run_forward.py --mode PAPER_LIVE_FEED --as-of 2026-08-13
```

The cycle will be skipped (logged as `not_due`) if the strategy already
evaluated for the current month. This is correct behavior.

---

## 11. Failure Handling

| Failure | Response |
|---|---|
| yfinance network failure | Returns `None`; cycle skipped; metrics updated |
| Provider returns empty data | Returns `None`; no fabricated prices |
| Security missing from provider | Observation rejected; `missing_securities` logged |
| Non-positive / NaN price | Observation rejected by quality engine |
| Look-ahead (future-dated observation) | Rejected by adapter + PIT validation |
| Stale observation (> max_staleness_days) | WARNING diagnostic; stale count incremented |
| Snapshot build failure (all prices rejected) | `None`; no cycle recorded |
| Reconciliation failure | Cycle recorded; CRITICAL logged; **do not continue** |

If the snapshot cannot be safely produced: the cycle is skipped and the
failure is recorded in `FeedMetrics`. No stale data is silently reused.

---

## 12. Limitations

1. **Yahoo Finance is free/public data.** Not suitable for production deployment
   decisions. Suitable for research paper-trading forward observation.

2. **End-of-day data only.** Yahoo Finance provides daily OHLCV. No intraday
   data is available via this adapter. Monthly strategy cadence is appropriate.

3. **Retroactive adjustments.** Yahoo applies split/dividend adjustments
   retroactively. Prior snapshot fingerprints may differ if Yahoo revises
   historical prices. M19 PIT validation detects look-ahead at build time.

4. **No real-time streaming.** This is a polling-based feed. Each call fetches
   a narrow window of recent data. Not described as real-time streaming.

5. **IdentifierMap not populated for this universe.** Tickers are used directly
   as security IDs. For a production system, a PIT-aware IdentifierMap with
   ISIN, CUSIP, and FIGI mappings would be required.

6. **SIMULATION forward run ≠ economic evidence.** Prior 12-cycle SIMULATION
   run used synthetic prices. Real forward evidence requires real market data.

---

## 13. Historical Replay vs Genuine Forward Operation

**Historical replay** (SIMULATION mode, `--mode SIMULATION`):
- Uses synthetic deterministic prices
- Useful for: integration testing, deterministic debugging, regression tests
- **NOT** economic evidence
- Labeled as "SIMULATION" in all outputs and records

**Genuine forward operation** (PAPER_LIVE_FEED mode, `--mode PAPER_LIVE_FEED`):
- Uses real Yahoo Finance market observations
- Snapshots are built from actual market data, timestamped to their
  observation date
- Each observation was not available to the strategy before its knowledge
  timestamp
- Evidence is observational (not replayed/simulated)
- Still requires extended sample before economic conclusions

The actual forward run MUST consume observations that were not available
to the strategy before their observation/knowledge timestamp.

---

## 14. How to Start the Forward Run

**One-time setup:**
```bash
cd mentisrex-capital
pip install yfinance  # already in dependencies
```

**Daily operation (run each trading day):**
```bash
python scripts/forward_run/run_forward.py \
    --mode PAPER_LIVE_FEED \
    --as-of $(date +%Y-%m-%d)
```

The M23 scheduler ensures the strategy only evaluates monthly. Daily runs
that fall outside the rebalance window are logged as `not_due` and skipped.

**Accumulate until sufficient sample:**
- M24 `INSUFFICIENT_DATA` threshold: n_cycles ≥ 20
- Monthly strategy: ~20 months minimum for M24 to exit `INSUFFICIENT_DATA`
- Economic conclusions: substantially more than 20 cycles required

**Review progress:**
```bash
# Run M24 diagnostics on accumulated records
python - << 'EOF'
import sys; sys.path.insert(0, "src"); sys.path.insert(0, "scripts/forward_run")
from run_forward import build_registry, build_loop, CHECKPOINT_PATH
from mentisrex.research.paper_trading.checkpoint import load_checkpoint, _restore_checkpoint
from mentisrex.research.forward_validation.engine import ForwardValidationEngine
from spec import SPEC

registry = build_registry()
loop = build_loop(registry)
_restore_checkpoint(loop, load_checkpoint(str(CHECKPOINT_PATH)))
fpr = loop.forward_record(SPEC.strategy_id)
artifact = ForwardValidationEngine().analyze(fpr, SPEC)
print(f"status: {artifact.status}")
print(f"n_cycles: {artifact.n_cycles}")
print(f"sample_adequacy: {artifact.sample_adequacy}")
EOF
```

---

**NO REAL CAPITAL IS DEPLOYED.**

**FORWARD RESULTS ARE OBSERVATIONAL EVIDENCE.**

**REAL MARKET DATA DOES NOT IMPLY REAL-TIME EXCHANGE-GRADE DATA.**
