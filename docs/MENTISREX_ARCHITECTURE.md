# Mentisrex Research Platform — Architecture Overview

Authoritative architecture reference. Describes system boundaries, module
responsibilities, the dependency graph, data flow, and the guarantees every
milestone inherits. Milestone → module mapping is in `MENTISREX_MILESTONE_INDEX.md`;
capability view in `MENTISREX_ROADMAP.md`.

## Design philosophy

The platform is engineered to institutional research standards. Five properties are
non-negotiable and hold across every layer:

- **Point-in-time correctness** — every read answers "what was knowable as of date
  D?", never "what happened?". No look-ahead is possible by construction.
- **Determinism** — same inputs → identical outputs. No hidden RNG; all randomness
  is seeded and injected.
- **Offline reproducibility** — the full research path runs offline from stored
  metadata; results are reproducible years later.
- **Additive development** — new milestones extend; they never rewrite certified
  ones. Interfaces are stable.
- **Dependency injection** — components depend on interfaces (solvers, execution
  models, providers, estimators), never concrete engines or globals.

## Layered architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Data Layer                                                        │
│    market_data/storage      PitPriceStore (raw OHLCV + actions)    │  M1
│    market_data/identity      SecurityMaster (temporal identity)    │  M2
│    market_data/fundamentals  availability-gated facts             │  M3
│    market_data/universe      survivorship-free universe            │  M4
│    market_data/delistings    delisting events                      │  M4
│    market_data/insiders      acceptance-gated Forms 3/4/5          │  M5
├──────────────────────────────────────────────────────────────────┤
│  Research Matrix Layer                                             │
│    market_data/research_matrix  feature_matrix_as_of (PIT accessor)│  M6
├──────────────────────────────────────────────────────────────────┤
│  Research Platform Layer                                          │
│    research/experiment_registry  provenance + fingerprints         │  M7
│    research/execution            orchestrator + state machine      │  M8
│    research/validation           quality gate + verdict            │  M9
├──────────────────────────────────────────────────────────────────┤
│  Portfolio Layer                                                  │
│    research/portfolio            construction + optimization (DI)   │  M10
│    research/simulation           multi-period evolution + accounting│ M11
└──────────────────────────────────────────────────────────────────┘
```

## Module responsibilities & boundaries

- **Data layer** owns raw truth and its temporal availability. It never computes
  research features; it exposes `*_as_of` reads. Boundary: everything above reads
  through these, nothing rebuilds them.
- **Research matrix** is the *only* place the data sources are unified into features.
  It never mutates upstream data. Boundary: portfolio/validation consume the matrix,
  never the raw stores directly.
- **Registry** records; it never computes research. Boundary: engines write results
  to it, and reproduce configs from it, but no engine imports another engine's state.
- **Execution platform** is the single orchestrator. Boundary: nothing calls the
  backtester directly — only through an injected executor.
- **Validation** judges; it never re-runs a backtest (re-fitting probes take an
  injected evaluator). Boundary: it reads realized results, emits a verdict.
- **Portfolio** turns signals into weights; **simulation** turns weights into a
  realized history. Boundary: simulation never reruns research — targets/prices are
  injected providers.

## Dependency graph

```
M1 ─► M2 ─► M3
        └─► M4 ─┐
        └─► M5 ─┤
M1 ─────────────┴─► M6 ─► M7
                         └─► M8 ─► M9
                                   └─► M10 ─► M11
```

Every arrow is a one-way dependency. No cycles. Upper layers never import from a
sibling's internals; cross-layer access is through published `*_as_of` / provider
interfaces. `research/{models,templates}.py` and the legacy subsystems
(`risk`, `construction`, `paper`, `assistant`, `knowledge`, `intelligence`,
`catalog`) belong to an older platform track and are not part of this dependency
graph (see the milestone index's *Remaining inconsistencies*).

## Data flow (research → simulation)

```
raw prices / fundamentals / insiders / universe / identity   (M1–M5, PIT stores)
        │  *_as_of reads
        ▼
feature_matrix_as_of(date)                                   (M6)
        │  signal column
        ▼
ResearchRunner.run  ──►  BacktestEngine (via injected executor)   (M8)
        │  realized returns / trades
        ▼
ResearchValidator.validate  ──►  ValidationReport (verdict)   (M9)
        │  PASS
        ▼
PortfolioEngine.construct(signals, constraints, objective)    (M10)
        │  target weights
        ▼
PortfolioSimulationEngine.run(timeline, target/price providers)  (M11)
        │  equity curve, holdings, costs, attribution
        ▼
Experiment Registry (provenance, no rerun)                    (M7)
```

## Point-in-time guarantees

- Prices: split-adjusted only by actions effective ≤ as_of AND announced ≤
  knowledge_date. No future action leaks.
- Fundamentals: `period_end ≤ as_of AND filing_date ≤ knowledge_date`.
- Insiders: gated on `acceptance_datetime`, never `transaction_date`.
- Universe: survivorship-free listing intervals — a name alive on a historical date
  is present even if delisted today.
- The research matrix and everything above inherit these gates; validation and
  simulation add no new temporal logic, so look-ahead cannot be introduced downstream.

## Determinism guarantees

No unseeded RNG anywhere in the research/portfolio/simulation path. Bootstrap, Monte
Carlo, and permutation tests take an explicit seed. Registry fingerprints are
order-independent hashes. Portfolio solvers are analytic or deterministic iterations.
Simulation is pure arithmetic over injected providers. Same inputs → byte-identical
artifacts.

## Dependency-injection philosophy

Interfaces, not implementations:
- **Solvers** (`portfolio/solvers/Solver`) — swap analytic / scipy / cvxpy.
- **Covariance & expected-return models** (`portfolio/optimizer`) — sample /
  shrinkage / Black-Litterman / Bayesian.
- **Execution models** (`simulation/execution/ExecutionModel`) — cost / frictionless
  / future latency / partial-fill / broker.
- **Providers** (simulation) — target / price / ADV / sector, precomputed so the
  simulation never reruns research.
- **Evaluator** (validation) — re-fitting probes inject the execution seam.

## Validation pipeline

`ResearchValidator.validate` → statistical (t/p, bootstrap, Monte Carlo, permutation)
· overfitting (Deflated/Probabilistic Sharpe, PBO, Reality Check) · multiple testing ·
robustness (walk-forward, sensitivity, stability) · capacity · factor exposure →
diagnostics flags → 7-component weighted score → verdict with machine-generated
reasoning. Portfolio and simulation both feed this gate.

## Simulation pipeline

Per rebalance date: fetch target (provider) → mark holdings (PIT prices) → policy
due? → generate orders (target vs current) → execute (book costs) → apply fills
(exact avg-cost accounting, ledger reconciles) → snapshot. Post-loop: performance,
exposure, attribution, cost/turnover/capacity reports, validation, registry attach.

## Future extensibility

The provider and `ExecutionModel` seams are where live/paper trading, broker APIs
(IB/Alpaca/FIX), intraday (VWAP/TWAP/POV), partial fills, and multi-asset accounting
attach — without touching the certified core. The optimizer's solver/estimator seams
absorb constrained QP, factor covariance, HRP, and Black-Litterman.

## References

- `MENTISREX_MILESTONE_INDEX.md` — milestone → commit history.
- `MENTISREX_ROADMAP.md` — capability view.
- `MENTISREX_ENGINEERING_PRINCIPLES.md` — the rules every milestone obeys.
- `AIDP_Mn_*.md` — per-milestone deep-dive documents.
