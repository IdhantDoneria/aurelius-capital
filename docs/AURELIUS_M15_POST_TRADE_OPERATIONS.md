# AIDP M15 — Trade Lifecycle & Post-Trade Operations Engine

## What this is

M15 transforms executed trades into fully tracked, settled, reconciled, auditable
portfolio events — closing **Execution → Settlement → Accounting → Reporting**. It is
**not** a broker adapter, execution engine, optimizer, or alpha engine.

It is **additive** and **dependency-injected**: the single book of record is the reused
M11 `PortfolioState`; it consumes M14 `Fill`/`ExecutionReport` objects and is compatible
with M12 `BrokerAccount` for reconciliation. It duplicates no orders, fills, positions,
risk checks, or portfolio accounting.

### Package

`src/aurelius/research/post_trade/` — import as `from aurelius.research import post_trade`.

## Event flow

```
execution fill (M14)
  → book_fill        M11 accounting.apply_fill (positions, cash, realized, cost basis)
  → TradeEvent(booked) + PositionEvent            (event log + ledgers)
  → CashEvent(pending, T+N)                        (settlement-aware cash)
  → SettlementInstruction(pending)                 settle date = busday(T+N)
  → settle(as_of)    due instructions → SettlementRecord + SettlementEvent, cash settles
  → reconcile / performance / reporting
corporate actions apply at any point (dated) → position/cash impact + CorporateActionEvent
```

Every lifecycle fact is an immutable, globally-sequenced event on the `EventLog`
(`events.py`) — the replayable, point-in-time-safe spine. Re-applying events in `seq`
order reproduces the state; `fingerprint` hashes the diagnostics so two identical runs
match.

## Trade lifecycle architecture (`lifecycle.py`)

`PostTradeEngine` is the orchestrator. `LifecycleState`:

```
RECEIVED → BOOKED → POSITION_UPDATED → CASH_POSTED → SETTLEMENT_PENDING
         → SETTLED → RECONCILED → PERFORMANCE_UPDATED   (FAILED on settlement failure)
```

`book_fill(...)` books one fill; `book_fills(fills)` books a list of M14 `Fill`s;
`book_execution_report(report)` books a filled M14 `ExecutionReport` as one net trade at
its average price. Booking is pure M11 accounting — no re-implementation.

## Settlement engine (`settlement.py`)

T+N settlement on a business-day calendar (`numpy.busday_offset`, weekends + optional
holidays skipped). `SettlementConfig(default_days, per_security, holidays)` — T+0/T+1/T+2
supported, per-security overrides. Deterministic: settle dates are a pure function of the
trade date; completion is driven by an injected `as_of`, never a wall clock. Tracks
pending / completed / failed instructions and settlement exposure.

## Ledger design (`ledger.py`)

Three append-only **audit** stores — not a second accounting system:

- `TradeLedger` — every booked trade.
- `PositionLedger` — every position delta; net **must equal** M11 holdings (checked).
- `CashLedger` — every cash flow tagged with settlement status; splits M11's economic
  cash into **settled (available)** vs **pending (restricted)**.

Cash reconciliation is the key invariant: `CashLedger.economic_balance() == M11
state.cash` always (they mirror the same flows); `settled_balance ≤ economic_balance`;
`available = settled`, `restricted = pending outflows`.

## Accounting integration (`accounting.py`)

`PostTradeAccounting` is a thin adapter over the reused M11 `PortfolioState`. Trade
booking is `apply_fill` verbatim — positions, cash, realized/unrealized P&L, and cost
basis are the same certified M11 accounting used by simulation and paper trading. The
only new operations are corporate-action position adjustments (split / stock-dividend /
rename / liquidation), which reconstruct M11's own frozen `Holding` — still no
re-implemented P&L.

## Corporate action handling (`corporate_actions.py`)

`apply(engine, action)` — dated, auditable, replayable. Supported: cash dividend, stock
dividend, split, reverse split, merger, symbol change, delisting. Cash impact routes
through `post_cash` (both M11's economic ledger and the settlement-aware ledger, so they
stay reconciled). Position events are emitted from a **before/after diff per affected
security**, so even renames/mergers keep the position ledger in lockstep with M11.
Rights issues are an interface (event emitted, no position change).

## Reconciliation (`reconciliation.py`)

Cross-checks the book against five faces — execution records, portfolio state, broker
state, settlement records, cash records — and detects: missing trade, duplicate trade,
incorrect quantity, incorrect price, cash mismatch, unsettled position, failed
settlement. Reuses M11/M12 truth; only diffs, never re-accounts. Every finding is an
auditable difference dict.

## Tax framework (`tax.py`) — interfaces only

FIFO `TaxLotBook`, `TaxLot`, `RealizedGain`, and a `JurisdictionRule` interface
(holding-period classification, default 365-day long/short split). No rates, brackets,
wash-sale, or country logic — those are jurisdiction plug-ins. `build_from_engine`
replays the trade event stream into lots.

## Performance & reporting

`performance.py` — realized/unrealized P&L (M11), turnover, total cost, implementation
shortfall proxy, cash drag, dividend impact, corporate-action impact. `reporting.py` —
`SettlementReport`, `CashReport`, `LedgerReport`, `CorporateActionReport`,
`OperationalHealthReport`, and the composite daily `PostTradeReport`. `monitoring.py` —
operational health (settlement completion, cash/ledger integrity, alerts).

## Registry (`registry.py`)

`attach_post_trade(registry, experiment, engine)` mirrors M12/M14: key operational
metrics into the experiment, full session JSON as a hash-recorded artifact — provenance
across the research/simulation/paper/execution/post-trade lineage.

## Tests

`tests/research/test_post_trade.py` — **83 deterministic tests**, all passing. Full
research-track suite: **455 passed, 1 skipped — zero regressions.**

## Benchmarks

`scripts/benchmark_m15_post_trade.py` — 10k / 100k trades and a ~1M lifecycle-event run.
See **Benchmark results** below.

### Benchmark results (offline, single core)

| trades | events | book s | trades/s | events/s | settle s | recon s | serialize s | peak MB |
|-------:|-------:|-------:|---------:|---------:|---------:|--------:|------------:|--------:|
| 10,000 | 40,000 | 0.87 | 11,488 | 33,744 | 0.32 | 0.002 | 5.17 | 148 |
| 100,000 | 400,000 | 9.52 | 10,510 | 30,222 | 3.72 | 0.026 | 54.15 | 1,462 |
| 340,000 | 1,360,000 | 33.29 | 10,214 | 29,523 | 12.78 | 0.090 | — | 740 |

Event processing is **linear** (~10k trades/s, ~30k events/s); settlement is linear;
reconciliation is very fast (**0.09 s for 1.36M events**). Serialization is the heavy
path — O(events) with full per-event dict expansion (54 s / 1.4 GB at 400k events); it is
on-demand (registry artifact), not in the booking hot path. For very large sessions,
stream the event log incrementally rather than building one JSON blob (documented
extension).

## Future extensions

Prime-broker integration, custody systems, clearing houses, multi-currency settlement,
derivatives settlement, real-time accounting, regulatory reporting. The seams already
exist: `SettlementInstruction`/`SettlementRecord` for clearing/custody, the `CashType`
enum + `post_cash` for multi-currency (add a currency dimension), the reconciliation
faces for prime-broker/custody feeds, and the event log for a real-time streaming
projection.

## Limitations / Skipped

Nothing requested in the M15 prompt was skipped. Deliberate, documented ceilings:

1. **Single currency.** Cash is one numeraire. *Reason:* multi-currency needs an FX
   book + per-currency settlement, out of scope. *Unblock:* add a currency dimension to
   `CashEvent`/`CashLedger` and an FX rate source.
2. **Tax is interface-only.** FIFO lots + holding-period classification, no rates,
   brackets, wash-sale, or country rules. *Reason:* country-specific tax logic is
   explicitly out of scope. *Unblock:* implement a concrete `JurisdictionRule` with
   rates for a jurisdiction.
3. **Rights issues are an interface.** Event recorded, no subscription economics.
   *Reason:* subscription price/ratio modelling not specified. *Unblock:* add a
   `RightsIssueEvent` with subscription terms + a cash/position handler.
4. **Settlement is deterministic/date-driven, not a live clearing feed.** No partial
   settlement, buy-ins, or fails-to-deliver beyond an explicit `fail_settlement`.
   *Reason:* offline, no clearing-house connection. *Unblock:* a clearing-house adapter
   feeding real settlement status.
5. **Corporate-action cost-basis handling is simplified** (e.g. merger cost basis scales
   with the share ratio; cash-in-lieu and spin-off basis allocation are not modelled).
   *Reason:* full basis-allocation rules are jurisdiction/deal specific. *Unblock:*
   per-action basis-allocation rules.
6. **Serialization builds one JSON blob** — O(events), heavy at 100k+ trades (54 s /
   1.4 GB at 400k events). *Reason:* full-log expansion for a self-contained artifact.
   It is on-demand, not in the booking path. *Unblock:* an incremental/streaming
   event-log writer for very large sessions.
