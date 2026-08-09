# AIDP M14 — Execution Management System & Order Management System

## What this is

M14 turns approved portfolio decisions into controlled, auditable, replayable
execution. It is **not** alpha, portfolio construction, or risk calculation — it is
the plumbing between a decision and a fill, with a full audit trail and post-trade
cost attribution.

It is **additive** and **dependency-injected**: it reuses the M10 cost model, M11
`Order`/accounting, the M12 broker/reconciliation/book, and the M13 risk gate. It
adds no duplicate accounting and no duplicate risk checks, and couples to no real
broker.

### Package location

The package lives at `src/aurelius/research/execution/ems/`.

M8 (Research Execution Platform) already owns `src/aurelius/research/execution/*.py`
(its `runner.py`, `scheduler.py`, `session.py`, …). To stay strictly additive and
never clobber certified M8 code, M14 nests one level down as `execution.ems`. Import
as:

```python
from aurelius.research.execution import ems
```

## Pipeline

```
Portfolio target / OrderIntents
  → OrderRequest (parent, arrival price stamped)
  → M13 Risk Gate           reject BLOCKS execution — never routed
  → OMS: create/validate/approve         lifecycle + immutable audit trail
  → ExecutionRouter         pick broker + algorithm, record RoutingDecision
  → ExecutionAlgorithm.plan child orders + ExecutionSchedule
  → ExecutionBroker.submit  M12 fill engine + M11 accounting
  → FillProcessor           dedupe → OMS fills → M12 book (ingest_fill)
  → OMS resolve             FILLED / PARTIALLY_FILLED / REJECTED / CANCELLED
  → ExecutionReport + ExecutionMetrics + CostAnalysis
```

## OMS architecture (`oms.py`)

The OMS owns the order lifecycle and its **immutable audit trail**. One mutable
`_ManagedOrder` per order lives inside the OMS; every state change appends a frozen
`OrderEvent` to an append-only, globally-sequenced log. The log is never mutated or
reordered. Illegal transitions raise `OMSError` — state cannot be silently corrupted.

Lifecycle:

```
NEW → VALIDATED → APPROVED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED* → FILLED
any non-terminal → REJECTED | CANCELLED (via PENDING_CANCEL) | EXPIRED
```

Terminal states (`FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`) accept no further
transition. `record_fill` accumulates signed quantity, computes weighted-average fill
price, and flips to `FILLED` only when cumulative fill matches the request within
tolerance. `report(order_id)` produces a frozen `ExecutionReport` carrying the audit
trail, fills, slippage, and implementation shortfall.

## EMS architecture (`ems.py`)

`EMS` is the orchestrator; `ExecutionSession` is the mutable run accumulator (OMS,
routing decisions, fills, plans). `EMS.execute(requests, market, book=…, adv_provider=…)`
runs the whole pipeline for a batch and returns the session. Nothing here
re-implements risk, accounting, cost, or fills — each is injected or imported.

Failure handling is explicit in `_resolve`: an order left `SUBMITTED`/`ACKNOWLEDGED`
with no fill is `REJECTED` (`broker_no_fill`); an unfilled remainder is optionally
cancelled (`cancel_unfilled_remainder`).

## Execution algorithms (`algorithms.py`, `execution_algorithms.py`, `scheduler.py`)

An algorithm is a **pure function** of `(OrderRequest, MarketInfo) → ExecutionPlan`
(a schedule + one child order per slice). It never touches the broker or book — the
EMS drives the plan — so algorithms are trivially deterministic, testable, replayable.

| Algo | Slicing |
|------|---------|
| `immediate` | one child = whole order, now (market/limit/stop route here) |
| `twap` | `n_slices` equal buckets |
| `vwap` | proportional to a volume profile (`market.volume_profile` or default U-shape) — the milestone's "interface": swap in a real forecast, algo unchanged |
| `pov` | participate at `participation_rate` of each interval's `market.interval_volume` until filled (guarded by `max_slices`) |

`scheduler.py` holds the shared slicing math; the **last slice absorbs rounding** so
Σ child qty == parent qty exactly — no shares created or lost. Algorithms self-register
in a name→class registry (`get_algorithm`, `available`).

## Broker abstraction (`broker.py`, `adapter.py`)

`ExecutionBroker` (ABC) exposes the 7-method OMS-facing surface: `submit_order`,
`cancel_order`, `replace_order`, `get_order_status`, `get_fills`, `get_positions`,
`get_account` (+ `set_prices`).

The two offline implementations **wrap the certified M12 brokers** — the fill
simulation and M11 accounting are M12's, not re-implemented:

- `MockExecutionBroker` → M12 `MockBroker` (perfect immediate fills at mark).
- `SimulatedExecutionBroker` → M12 `SimulatedBroker` (seeded partial fills, slippage,
  rejects) — realistic divergence for reconciliation.

`adapter.py` provides interface-only stubs for **Interactive Brokers, Alpaca, Zerodha,
FIX** (mirroring M12's five venues). They raise `NotImplementedError` and carry a
`capabilities` map (native algos / order types) the router can constrain against. No
credentials, no network.

## Order routing (`router.py`)

`ExecutionRouter` picks broker + algorithm and records a `RoutingDecision`. Default
policy: honour an explicit per-order `algo` override, else map order type → algo;
high-urgency parents collapse to `immediate`. Smart order routing, venue selection and
liquidity-aware splitting are documented extensions — `RoutingDecision` and the broker
registry are their seams.

## Cost attribution (`transaction_costs.py`, `slippage.py`)

Reuses the M10 `TransactionCostModel` (commission + half-spread + slippage + √-law
impact) — the estimator is not re-implemented, only **attributed** into components.

- **Arrival slippage** (`slippage.py`): signed so >0 always means adverse (buy above /
  sell below arrival), in bps, notional-weighted when aggregated.
- **Implementation shortfall** (`transaction_costs.py`): `(avg_fill − arrival)·qty +
  explicit cost` over filled notional, in bps.
- `CostAnalysis` breaks realised/modelled cost into commission / spread / slippage /
  impact plus arrival-slippage and IS bps.

## Monitoring & post-trade analytics (`monitoring.py`)

`metrics(session) → ExecutionMetrics`: fill rate, cost bps, avg slippage, avg
implementation shortfall, counts, alerts (duplicate fills, rejected orders, over-fills).
`by_algorithm(session)` / `by_broker(session)` give algorithm-performance and
broker-performance attribution.

## Reconciliation (`reconciliation.py`)

Two layers, no duplicate accounting:

- **execution-layer** (`reconcile_execution`): EMS fills/orders vs broker fill record —
  duplicate / missing / orphan fills, non-terminal (stale) orders. This is the piece M12
  doesn't do.
- **state-layer** (`reconcile_state`): internal M12 book vs broker account — delegated
  straight to M12's certified `reconcile(...)`.

## M12 integration

Fills flow into the M12 book via `PaperPortfolio.ingest_fill` (idempotent), so all
portfolio accounting stays M11/M12. `FillProcessor` adds a second duplicate guard at
the execution layer so a duplicate never reaches the OMS audit trail either. Cash,
holdings, and the ledger reconcile after execution (tested).

## M13 integration

Every execution request passes the M13 risk gate **before routing**. `EMS` accepts any
gate with the `.check(orders, state, prices)` contract — the M13 `RiskEngine.as_gate()`
or the M12 `PreTradeRiskGate`. Rejected orders are marked `REJECTED` in the OMS and
never routed or sent. (A gate with no internal book to project against cannot screen and
allows through — supply a `book` to enforce.)

## Registry (`registry.py`)

`attach_execution(registry, experiment, session)` mirrors M12 `attach_session`: writes
key execution-quality metrics (`ExecFillRate`, `ExecTotalCostBps`, `ExecAvgSlippageBps`,
`ExecImplementationShortfallBps`, …) into the experiment and records the full session
JSON as a hash-stamped artifact — full provenance, no rerun.

## Serialization & determinism (`serialization.py`, `diagnostics.py`)

`to_json` emits sorted-key, stable, round-trip-stable JSON. `fingerprint(session)` is a
blake2b content hash over the diagnostics — two runs of identical inputs produce the same
hash (`validate.check_determinism` asserts it, incl. the simulated broker).

## Tests

`tests/research/test_execution_ems.py` — **122 deterministic tests**, all passing.
Coverage: order-type factories, OMS lifecycle + every illegal transition, audit-trail
immutability/sequencing, scheduler slicing (uniform/profile/POV + rounding), algorithms,
routing, broker mocks (full/partial/slippage/reject/cancel/status/account), EMS pipeline,
M13 risk-gate integration, M12 book integration + duplicate-fill protection, cost /
slippage / implementation shortfall, monitoring + by-algo/by-broker, reconciliation
(execution + state), validation, serialization round-trip, diagnostics/fingerprint,
registry attach, determinism, and edge cases (empty batch, sells, unpriced, 200-name
book, POV runaway guard).

Full research-track suite: **372 passed, 1 skipped — zero regressions.**

## Benchmarks

`scripts/benchmark_m14_execution.py` — 100 / 1,000 / 10,000 parent orders end-to-end,
plus one parent fanned to 100,000 TWAP child slices.

### Benchmark results (offline, single core)

| scenario | seconds | orders/s | µs/order | fills | peak MB |
|----------|--------:|---------:|---------:|------:|--------:|
| 100 parent orders | 0.011 | 9,181 | 108.9 | 100 | 0.4 |
| 1,000 parent orders | 0.100 | 10,005 | 100.0 | 1,000 | 3.4 |
| 10,000 parent orders | 1.318 | 7,587 | 131.8 | 10,000 | 33.9 |
| 100,000 child orders (1 TWAP parent) | 8.189 | 12,211 | 81.9 | 100,000 | 153.3 |

Throughput is **linear** in order count (~100 µs/order, ~82 µs/child); memory scales
linearly with the working set. An early O(N²) — the broker re-marking its whole book on
a per-order `set_prices` — was fixed by publishing marks once per batch (10k orders:
271 s → 1.3 s, ~200×).

## Future production path

- Real venue adapters (IB / Alpaca / Zerodha / FIX) — implement the `BrokerAdapter` ABC
  against each SDK/FIX session; the EMS is unchanged.
- Smart order routing / venue selection / dark pools — extend `ExecutionRouter`;
  `RoutingDecision` already records the seam.
- Real intraday scheduling with a wall clock, latency simulation, and market
  microstructure — algorithms already emit time-sliced schedules.
- Native broker algos — `capabilities` on each adapter already declares them.
- Options / futures execution — new order types + fill semantics on the broker layer.

## Known limitations / Skipped

Nothing requested in the M14 prompt was skipped. Deliberate, documented ceilings:

1. **Real broker connectivity is interface-only.** `adapter.py` raises
   `NotImplementedError`. *Reason:* live venues need auth, sessions, rate limits, and
   order-state callbacks — none present in the deterministic offline platform.
   *Unblock:* implement the `BrokerAdapter` ABC against a specific venue SDK/FIX session
   with credentials.
2. **Fills are simulation-first, synchronous.** The wrapped M12 brokers fill at the
   published mark on submit, so there is no resting-order book, no queue position, and
   no intraday clock — `cancel`/`replace` act on the unfilled remainder.
   *Reason:* matches the offline, deterministic mandate (no market data feed).
   *Unblock:* a time-driven matching engine or a live venue.
3. **Stop orders are an interface.** `STOP` is carried as a price on the sim broker but
   not triggered by a price path. *Reason:* no intraday price path offline.
   *Unblock:* an intraday tick source + a trigger evaluator.
4. **VWAP profile is a static shape**, not a live volume forecast. The interface accepts
   an injected profile; the default is a U-shape. *Unblock:* inject a real intraday
   volume forecast — no code change.
