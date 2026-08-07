# AIDP Phase 11 — Institutional Multi-Period Portfolio Simulation Engine

Evolves optimized (Phase 10) portfolios into a realistic multi-year investment
history: persistent holdings, exact cash accounting, transaction costs, configurable
rebalancing, and institutional analytics. **This is not a backtester** — the alpha
and portfolio engines already exist; this is a *portfolio evolution* engine. It
never reruns research. Additive; Phases 1–10 untouched.

Module: `src/aurelius/research/simulation/`.

```python
eng = PortfolioSimulationEngine(
    config=SimulationConfig(initial_capital=1e6, sizing=SizingConfig(min_trade_notional=100)),
    execution_model=CostExecutionModel(TransactionCostModel()),        # DI
    policy=RebalancePolicy(explicit_dates=calendar_dates(timeline, "monthly")))
result = eng.run(timeline, target_provider, price_provider, adv_provider=adv)   # no rerun
validate_simulation(result)                       # accounting + Phase 9 gate
attach_simulation(registry, experiment, result)   # Phase 7 provenance
```

## Architecture

Dependency-injected, deterministic, point-in-time-safe. The spec listed ~34 module
names; consolidated into 15 coherent modules (the spec permits "better decomposition
if appropriate") — each with real responsibility, no stubs.

| Module | Role |
|---|---|
| `models` | all immutable domain dataclasses (Holding, Trade, Fill, snapshots, reports, SimulationResult) |
| `state` | `PortfolioState`, `CashLedger` — the only mutable accounting |
| `orders` | target-vs-current → executable orders (lots, buffer band, long-only, cash-aware) |
| `execution` | `ExecutionModel` ABC + cost-model / frictionless implementations (DI) |
| `rebalancing` | reuses Phase 10 `RebalanceRule` + calendar-date generation |
| `engine` | `PortfolioSimulationEngine` — the evolution loop + report assembly |
| `performance` | equity-curve metrics (reuses Phase 9 Sharpe) |
| `exposure` | exposure report + per-date risk timeline |
| `attribution` | security/sector contribution, cost/cash/turnover drag |
| `analytics` | cost / turnover / capacity report builders |
| `validation` | accounting reconciliation + Phase 9 adapter (`to_performance_metrics`) |
| `serialization` | deterministic JSON + Parquet export |
| `registry` | attach result to the Phase 7 experiment (no rerun) |
| `diagnostics` | trade/rebalance/cost/cash logs + warnings |
| `__init__` | exports |

### Data flow

```
target_provider(date) ─┐   (Phase 10 optimized portfolio, precomputed — never reruns research)
price_provider(id,date)─┼─► PortfolioSimulationEngine.run
adv_provider(id,date) ─┘        │
                                ├─ mark holdings (PIT prices)
                                ├─ RebalancePolicy.due? ─► generate_orders ─► ExecutionModel ─► apply_fill
                                ├─ PortfolioState (holdings + CashLedger, exact accounting)
                                └─ snapshots / equity / trades / rebalance events
                                         │
             performance · exposure · attribution · analytics · validation
                                         │
                                  SimulationResult ─► serialization / registry / diagnostics
```

### Dependency graph

`engine` → {state, orders, execution, rebalancing, performance, exposure,
attribution, analytics, models}. `validation`/`registry`/`serialization`/
`diagnostics` consume a `SimulationResult`. Reuses Phase 10 (`RebalanceRule`,
`TransactionCostModel`) and Phase 9 (`significance.sharpe`, `PerformanceMetrics`,
`ResearchValidator`). No Phase is modified.

## Simulation engine

For each date on the timeline: fetch the target portfolio (injected provider) and
PIT prices; mark holdings; if the rebalance policy is due, generate orders (target
vs current), execute them through the injected execution model (booking costs), and
apply fills to `PortfolioState`; then snapshot value, cash, exposures, weights.
After the loop, assemble performance/exposure/turnover/cost/capacity/risk/attribution
reports and the validation block. **No RNG, no research rerun, no hidden globals.**

## Holdings / accounting model

`PortfolioState` holds `{security_id: Holding}` + a `CashLedger`. Every fill:
- moves cash by **−(qty·price) − cost** (buy pays, sell receives, cost always paid);
- updates the position with **average-cost** booking and correct **realized P&L** for
  long adds, partial reduces, full exits, **long↔short flips**, and short covers;
- records the flow in the ledger, so the run **reconciles**: initial + Σ flows == cash.

Supports long, short, cash, fractional or integer shares, lot sizes, position
merges/reductions/exits/entries, average cost, market value, weight, and realized /
unrealized P&L. The accounting is unit-tested exhaustively (avg cost, flip, cover,
reconciliation).

## Rebalancing engine

Reuses the Phase 10 `RebalanceRule` (calendar daily/weekly/monthly/quarterly/annual,
threshold drift, volatility-triggered, hybrid) via `RebalancePolicy`, plus
`calendar_dates(timeline, freq)` to derive rebalance dates. Supports rebalance
tolerance (drift threshold), minimum trade notional (buffer band), minimum position
change, and a cash buffer.

## Execution model

Dependency-injected `ExecutionModel`. `CostExecutionModel` fills at the mark and
books the Phase 10 transaction cost (commission + spread + slippage + √-law impact,
ADV-aware); `FrictionlessExecutionModel` is the zero-cost baseline. Latency, partial
fills, and intraday (VWAP/TWAP/POV) are documented extension points — the interface
carries `adv` and returns a `Fill` a partial-fill model would subdivide.

## Performance analytics

From the realized equity curve: total return, CAGR, volatility, Sharpe (Phase 9
definition), Sortino, Calmar, Omega, max/avg drawdown, time-underwater, recovery,
hit rate, profit factor, gain/loss ratio, annualized turnover, avg holding period,
realized costs + cost drag. Plus exposures (gross/net/long/short/cash), a per-date
risk timeline (rolling vol, leverage, HHI, effective holdings), and attribution
(security/sector contribution, cost/cash/turnover drag).

## Validation integration

`validate_simulation` runs native consistency checks — ledger reconciliation, cash
consistency (material-overdraft only), portfolio value positivity, leverage,
position accounting (long-only), turnover/cost/capacity/concentration. `
to_performance_metrics` adapts the simulated equity curve + trades into a
`PerformanceMetrics`, so the **Phase 9 `ResearchValidator`** renders its full
deployment verdict on the *simulated* track record without rerunning anything.

## Experiment registry

`attach_simulation` writes the full `SimulationResult` as a hashed JSON artifact and
records realized metrics (SimCAGR, SimSharpe, SimMaxDrawdown, SimAnnualizedTurnover,
SimTotalCost, SimFinalValue) + a verdict note on the Phase 7 experiment — full
provenance, no rerun, via the existing store (no schema change).

## Performance / benchmarks

See `scripts/benchmark_simulation.py` — 504 trading days, monthly rebalance:

| Universe N | Runtime | Throughput (sec-days/s) | Peak MB | Trades |
|---|---|---|---|---|
| 100 | 0.28 s | 182,500 | 7.0 | 1,700 |
| 500 | 1.30 s | 193,600 | 30.2 | 8,495 |
| 1,000 | 2.76 s | 182,900 | 59.9 | 16,988 |
| 5,000 | 15.20 s | 165,800 | 272.0 | 84,494 |
| 10,000 | 31.69 s | 159,100 | 543.0 | 167,873 |

24 monthly rebalances over 2 years. Hundreds of names (a realistic single desk)
run in well under a second per year; 10k names × 2y complete in ~32 s.

Deterministic, linear in security-days. Memory is dominated by the price paths and
recorded snapshots/trades.

## Design decisions

- **Providers, not engines.** Targets/prices/ADV are injected callables so the
  simulation is decoupled from *how* portfolios are produced — it never reruns Phase
  8/10. A `PitPriceStore.close_as_of` adapter is the natural production `price_provider`.
- **Average-cost accounting** (not FIFO lots) — standard for institutional
  book-level P&L; lot-level/tax accounting is a documented extension.
- **Cash-relative overdraft tolerance** — a fully-invested (gross=1) target dips
  cash slightly negative from costs; only a material (>1% of value) overdraft is a
  violation. Use `SizingConfig.cash_buffer` to avoid it entirely.

## Limitations / Known gaps

- **Average-cost, single-currency, no margin/borrow/financing** — booked cleanly;
  multi-currency, margin, borrow costs, and tax-aware lots are extension points.
- **Sector/country exposures & Brinson attribution** need a classification map absent
  from the PIT stack (same SecurityMaster gap as Phases 9–10) — reported
  `insufficient_data`.
- **Parquet export needs `pyarrow`** (not installed in the current venv); JSON export
  is always available. The Parquet test skips when no engine is present.
- **`avg_holding_days` is a turnover proxy**, not a per-lot lifecycle measure
  (documented in code).
- **Daily marking is O(N·T)** in price-provider calls; large-N multi-year runs are
  linear but not parallelized (see future work).

## Future extension points (interfaces only, not implemented)

Broker APIs (Interactive Brokers, Alpaca, Zerodha, FIX), live/paper trading,
intraday simulation, VWAP/TWAP/POV & smart order routing, partial fills & latency,
multi-asset (options/futures/FX/crypto), multi-currency accounting, margin/borrow/
financing, tax-aware optimization. The provider + `ExecutionModel` seams are where
these attach.

## Institutional rationale

Renaissance/AQR/Two-Sigma-class research separates alpha, construction, and
*simulation of realized evolution* — because paper P&L only becomes trustworthy once
holdings persist, cash reconciles to the cent, and costs are booked on every trade
across thousands of rebalances. This engine is that layer: it closes
research → construction → **evolution** → attribution → validation → registry →
paper trading, with deterministic reproducibility throughout.
