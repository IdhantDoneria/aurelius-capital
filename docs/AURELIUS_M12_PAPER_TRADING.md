# M12 — Paper Trading Bridge & Live-State Reconciliation

**Milestone:** M12
**Capability:** Paper Trading (see `MENTISREX_ROADMAP.md`)
**Depends on:** M7 (registry), M9 (validation), M10 (cost model), M11 (accounting core)
**Status:** DRAFT → CERTIFIED
**Branch:** `aidp/audit-and-pit-gaps`

---

## Summary

M12 extends the platform from *simulation* into a persistent **live-state loop
against an external broker**. It answers the operational questions a paper (and
later, live) deployment must answer continuously: what should we hold, what does
the broker say we hold, what trades close the gap, did they fill, does broker
state match internal state, and how far has anything drifted.

It is **additive** and **reuses** the certified core rather than rebuilding it:
portfolio accounting, order sizing, execution/cost interfaces, and the validation
gate are all M9/M10/M11 and are injected or imported — nothing is duplicated.
M12 adds only the genuinely new parts: a broker abstraction, an internal↔external
reconciliation engine, drift monitoring, and deployment-readiness validation.

**This is not a live trading system.** It is offline, deterministic, and has no
broker network connectivity or credentials. Real venues are interface-only stubs.

## Architecture

```
target (M10/M11 provider)
      │
      ▼
 PaperTradingSession.step(date, target, prices)
      │  1. mark internal book (M11 PortfolioState)   ← reused accounting
      │  2. generate_orders(target, state, prices)    ← reused M11 orders
      │  3. PreTradeRiskGate.check(...)               ← M12 (name/gross/kill)
      │  4. Broker.place_order(OrderRequest)          ← M12 broker abstraction
      │  5. Broker.poll_fills() → book.ingest_fill    ← M11 apply_fill, dedup
      │  6. reconcile(internal_state, broker_account) ← M12 reconciliation
      │  7. compute_drift(internal, external, target) ← M12 drift
      │  8. record EquityPoint + SyncEvent
      ▼
 MonitoringReport · validate_session (M9) · attach_session (M7)
```

The internal book and the broker's own book are **two independent copies of the
same M11 accounting** (`PortfolioState`). The MockBroker keeps its book with the
identical certified logic the internal book uses — so its reported account is a
genuine independent computation, not a mirror of internal state.

## Design overview

Key objects (`models.py`, all frozen): `OrderRequest`, `OrderStatus`,
`BrokerOrder`, `BrokerFill`, `BrokerPosition`, `BrokerAccount`, `PositionSnapshot`,
`AccountSnapshot`, `StateDifference`, `ReconciliationReport`, `DriftReport`,
`SyncEvent`, `ExecutionRecord`, `MonitoringReport`, `StateConsistencyReport`,
`DeploymentReadinessReport`, `PaperTradingValidationResult`. Live state:
`PaperPortfolio` (wraps the M11 `PortfolioState`).

## Major components

| Module | Responsibility |
|---|---|
| `models.py` | All frozen dataclasses + `OrderStatus` enum. |
| `broker.py` | `Broker` ABC; `MockBroker` (perfect fills), `SimulatedBroker` (seeded partial/slippage/reject frictions). Both keep their book with the reused M11 accounting. |
| `adapter.py` | Interface-only `BrokerAdapter` + IB/Alpaca/Zerodha/FIX stubs (`NotImplementedError`). No network, no creds. |
| `portfolio.py` | `PaperPortfolio` — internal book over M11 `PortfolioState`; fill ingestion with duplicate protection; paired snapshots. |
| `reconciliation.py` | `reconcile()` — pure internal↔external comparison, nine break categories. |
| `drift.py` | `compute_drift()` — six drift measures + threshold alerts. |
| `risk.py` | `PreTradeRiskGate` — name-weight / gross-leverage caps + kill switch. |
| `session.py` | `PaperTradingSession` — the `step`/`run` loop wiring all of the above. |
| `monitoring.py` | `monitoring_report()` — rolls per-tick history into a `MonitoringReport`. |
| `validation.py` | State consistency + M9 integration + deployment readiness. |
| `serialization.py` | Deterministic JSON of the session. |
| `diagnostics.py` | Flat health dict (M11-style). |
| `registry.py` | `attach_session()` — provenance into the M7 experiment, no rerun. |

## Integration points

- **M11 accounting (`PortfolioState`)** — the internal book *and* each broker's
  book. `apply_fill`, `mark`, `weights`, `exposures`, `ledger.reconciles`.
- **M11 orders (`generate_orders`, `SizingConfig`)** — target→order sizing, reused
  verbatim (honors lot size, min-notional, long-only, cash buffer).
- **M11 execution/cost (`ExecutionModel`, M10 `TransactionCostModel`)** — the
  broker prices fills and books cost through the same injected models.
- **M9 (`ResearchValidator`, `to_performance_metrics`)** — the realized paper track
  record is adapted into a certified `PerformanceMetrics` (reusing M11's adapter
  via a 3-field shim) and passed to the M9 gate. No metric math re-implemented.
- **M7 registry** — `attach_session` writes paper metrics + a hash-recorded JSON
  artifact onto the existing experiment, preserving research→sim→paper lineage.

## Broker abstraction

`Broker` ABC — five methods: `set_prices`, `place_order`, `poll_fills`,
`get_account`, `cancel_order`. Dependency-injected into the session.

- `MockBroker` — full immediate fill at the marked price; own book via M11
  accounting. The reference "perfect broker."
- `SimulatedBroker(fill_ratio, slippage_bps, reject_every)` — seeded, deterministic
  frictions so partial fills, price divergence and rejections actually occur.
- `BrokerAdapter` + `InteractiveBrokersAdapter` / `AlpacaAdapter` /
  `ZerodhaAdapter` / `FIXAdapter` — production interfaces, `NotImplementedError`
  bodies. They fix the contract a real adapter satisfies without shipping network
  code or fabricated results.

## Reconciliation logic

`reconcile(internal_state, broker_account, …)` is a **pure function** returning a
`ReconciliationReport` with a `StateDifference` per discrepancy. Nine categories:

`missing_position`, `unexpected_position`, `wrong_quantity`, `wrong_price`,
`cash_mismatch`, `stale_order`, `duplicate_fill`, `missing_fill`,
`wrong_cost_basis`. Tolerances (`ReconciliationConfig`): qty absolute, cash
fraction-of-value, price/cost-basis in bps, stale-order age in days.

In the well-behaved loop the internal book replays exactly the broker's fills, so
reconciliation is clean every tick (the correct outcome). The engine's value is
detecting divergence from dropped/duplicated fills or broker-side adjustments —
these are tested directly on `reconcile()` with hand-built divergent states.

## Drift monitoring

`compute_drift` measures weight (per-name and max), position (gross share
mismatch), cash, execution (realized-vs-mark bps), timing (sync gap days), and
cost (actual-vs-expected). Threshold breaches (`DriftThresholds`) become alerts;
`monitoring_report` aggregates them across the run.

## Point-in-time / determinism

No RNG anywhere — `SimulatedBroker` frictions are deterministic functions of the
order sequence. Providers are injected (`target_provider`, `price_provider`), so
PIT correctness is inherited from whatever M6/M10/M11 feeds them. Identical inputs
→ identical `session.fingerprint()` (asserted in tests).

## Validation

Two layers: (1) native consistency — M11 ledger reconciliation + M12
reconciliation status + worst drift → `StateConsistencyReport`; (2) M9 gate on the
realized paper equity curve. `deployment_readiness` marks a session deployable
**only if** statistically sound (M9 PASS/PASS_WITH_WARNINGS) **and** internally/
externally consistent.

## Tests

`tests/research/test_paper_trading.py` — **50 tests**: broker mock/lifecycle,
order flow, risk gate + kill switch, all nine reconciliation categories, six drift
measures, monitoring, serialization round-trip, determinism, registry attach, M9
validation integration, and edge cases (empty target, unpriced name, duplicate
fill idempotency, zero capital, snapshot pairing). Full suite: **788 passed,
3 skipped, zero regressions**.

## Benchmarks

`scripts/benchmark_paper_trading.py`, 12 ticks:

| N | sync/tick | order_gen | reconcile | drift | peak mem |
|---|---|---|---|---|---|
| 100 | 2.6 ms | 0.04 ms | 0.06 ms | 0.07 ms | 0.3 MB |
| 1,000 | 30.9 ms | 0.48 ms | 0.61 ms | 0.70 ms | 2.5 MB |
| 10,000 | 913 ms | 6.6 ms | 7.6 ms | 8.4 ms | 25.6 MB |

Reconciliation, drift, and order generation are all sub-10 ms at 10k. Per-tick
sync is O(N) because each order is placed individually against the broker (the
realistic cost of order-by-order paper submission); it dominates only on the
first, full-turnover tick. Memory is linear.

## Limitations / Known gaps

Honest limitations with the unblocking requirement for each:

- **No live broker connectivity.** Real adapters (IB/Alpaca/Zerodha/FIX) are
  interface stubs. *Unblock:* implement one adapter's five `Broker` methods against
  the venue API + credentials + a live market-data feed. No other M12 code changes.
- **Partial fills modelled, intraday microstructure not.** `SimulatedBroker`
  produces partial fills, slippage and rejections at the tick level; VWAP/TWAP/POV
  scheduling, latency, and queue position are not modelled. *Unblock:* an intraday
  execution model + a market-data replay feed.
- **Reconciliation loop is clean by construction.** Because the internal book
  replays the broker's own fills, the end-to-end loop never diverges; divergence is
  only exercised via direct `reconcile()` unit tests. *Unblock:* a broker adapter
  that can drop/duplicate fills or apply broker-side adjustments (real venues do).
- **Serialization is JSON only.** Parquet is available in M11 but requires
  `pyarrow`, which is not installed. *Unblock:* `pip install pyarrow`.

### Consolidated modules (not skipped — reused, per "do not duplicate")

The prompt's suggested `orders.py`, `execution.py`, `state.py`, and `sync.py` were
**deliberately not recreated**: order sizing and the execution/cost interface are
imported from M11, accounting state is the reused M11 `PortfolioState`, and the
"sync" step is the `session.step` loop. This satisfies the explicit "do not
duplicate portfolio accounting / cost logic / order models / execution interfaces"
rule. All required *objects* are implemented in `models.py`.

## Future production path

Design interfaces already present for: real broker APIs (`BrokerAdapter`
subclasses), FIX (`FIXAdapter`), partial fills (`fill_ratio` / `PARTIALLY_FILLED`
status), risk limits + kill switch (`PreTradeRiskGate` / `RiskLimits.kill`),
production monitoring (`MonitoringReport`). Remaining for live: live market data,
intraday execution/latency models, an OMS/EMS layer, margin/collateral, and venue
risk checks. Each is additive on the existing seams.

## Commit hash

`1813176` (branch `aidp/audit-and-pit-gaps`).

## Recommendation for next milestone

**M13 — Risk Engine consolidation.** M12 ships a *pre-trade* gate
(`PreTradeRiskGate`) only; the legacy Platform-Track "Risk Engine" (VaR, stress,
drawdown halt, exposure limits — see `MENTISREX_LEGACY_TRACK_AUDIT.md`) is the
natural next capability to rebuild into the canonical M-line, sitting between
portfolio construction/simulation and paper/live execution. It is the last major
gate before live deployment.
