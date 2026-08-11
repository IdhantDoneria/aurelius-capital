# Aurelius Research Platform — Canonical Milestone Index

Authoritative history of engineering milestones. The project uses **one** milestone
convention: `M1, M2, … M11`, continuing `M12, M13, …`. Never "Phase". Milestone
numbers never restart.

> **Historical note.** Recent development briefly used "Phase 10 / Phase 11"; this
> was a terminology slip, now normalized to **M10 / M11**. All milestone references
> in the AIDP research/data platform (source docstrings, docs, tests, scripts) read
> `Mn`. A separate, older *platform-track* numbering still exists in some legacy
> subsystems (see [Remaining inconsistencies](#remaining-inconsistencies)); it is
> intentionally preserved as historical pending a future reconciliation milestone.

Branch of record: `aidp/audit-and-pit-gaps`. Test suite at time of index:
**213 passed, 3 skipped, 0 regressions**.

---

## M1 — Market Data Infrastructure

- **Purpose:** PIT-correct, corporate-action-aware price store; fixes retroactive
  adjustment leak (audit P1/P2/C1).
- **Deliverables:** `market_data/storage/pit_store.py` (`PitPriceStore`, raw OHLCV +
  corporate actions, `close_as_of`, `window_as_of`); Yahoo raw+splits adapter.
- **Dependencies:** none.
- **Commit:** CERTIFIED (baseline; not individually hash-recorded in session state).
- **Status / Certification:** CERTIFIED.
- **Documentation:** `AIDP_AUDIT_AND_ROADMAP.md`.
- **Tests:** `tests/market_data/test_pit_leakage.py`, `test_storage.py`.
- **Benchmark:** n/a (store-level).
- **Current state:** production-quality, immutable.
- **Successor:** M2.

## M2 — SecurityMaster + Point-in-Time Identity

- **Purpose:** temporal security identity (per-listing `security_id` ≈ PERMNO,
  survivorship-free identity history).
- **Deliverables:** `market_data/identity/security_master.py` (`SecurityMaster`,
  `make_security_id`, identity-history intervals).
- **Dependencies:** M1.
- **Commit:** CERTIFIED (baseline).
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M2_IDENTITY.md`.
- **Tests:** `tests/market_data/test_security_identity.py`.
- **Successor:** M3.

## M3 — Point-in-Time Fundamentals Engine

- **Purpose:** EDGAR fundamentals + shares outstanding + PIT market cap (audit F1).
- **Deliverables:** `market_data/fundamentals/{store,edgar,engine,quality}.py`
  (availability-gated `fact_as_of`, `cross_section_as_of`, factor inputs).
- **Dependencies:** M1, M2.
- **Commit:** `f64a8fa`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M3_FUNDAMENTALS.md`.
- **Tests:** `tests/market_data/test_fundamentals.py`.
- **Successor:** M4.

## M4 — Point-in-Time Universe & Delisting Engine

- **Purpose:** survivorship-free universe reconstruction `universe_as_of` (audit S1).
- **Deliverables:** `market_data/delistings/store.py`, `market_data/universe/engine.py`
  (`UniverseEngine`, `DelistingStore`, listing-interval model — no duplicate identity).
- **Dependencies:** M2.
- **Commit:** `15561b0`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M4_SURVIVORSHIP.md`.
- **Tests:** `tests/market_data/test_universe.py`.
- **Successor:** M5.

## M5 — Point-in-Time Insider Transaction Engine

- **Purpose:** SEC Forms 3/4/5 insider ledger, gated on `acceptance_datetime`.
- **Deliverables:** `market_data/insiders/{store,edgar,insider_engine}.py`
  (append-only, amendment collapse, signed shares, `signals_as_of`).
- **Dependencies:** M2.
- **Commit:** `d75ba70`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M5_INSIDERS.md`.
- **Tests:** `tests/market_data/test_insiders.py` (7).
- **Benchmark:** ingest 0.19M rows/s; `transactions_as_of` 14.8 ms.
- **Successor:** M6.

## M6 — Point-in-Time Research Matrix Engine

- **Purpose:** one PIT-safe accessor unifying price/fundamental/insider/universe/
  identity into a survivorship-free feature matrix keyed by `security_id`.
- **Deliverables:** `market_data/research_matrix/{engine,schema,feature_registry,
  quality}.py` (`feature_matrix_as_of`, registry-driven, append-only-count cache).
- **Dependencies:** M1–M5.
- **Commit:** `ef7a504`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M6_RESEARCH_MATRIX.md`.
- **Tests:** `tests/market_data/test_research_matrix.py` (6).
- **Benchmark:** 10k securities × 50 cols build 3.47 s; cached 1.45 ms.
- **Successor:** M7.

## M7 — Experiment Registry & Research Lineage System

- **Purpose:** authoritative record of every experiment; reproducible from metadata
  alone (git, dataset versions, features, params) via deterministic fingerprints.
- **Deliverables:** `research/experiment_registry/{engine,models,storage,lineage,
  hashing,validation,quality}.py`.
- **Dependencies:** M6.
- **Commit:** `9f2f310`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M7_EXPERIMENT_REGISTRY.md`.
- **Tests:** `tests/research/test_registry.py` (9).
- **Benchmark:** 100k experiments — lookup 5.69 ms (< 20 ms target).
- **Successor:** M8.

## M8 — Institutional Research Execution Platform

- **Purpose:** single orchestrator; nothing calls the backtester directly. State
  machine, hooks, artifacts, failure recovery.
- **Deliverables:** `research/execution/{runner,session,pipeline,scheduler,
  state_machine,validator,metrics,artifact_manager,event_log,hooks,quality,
  exceptions}.py`.
- **Dependencies:** M6, M7.
- **Commit:** `a28f33e`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M8_EXECUTION_PLATFORM.md`.
- **Tests:** `tests/research/test_execution.py` (14).
- **Benchmark:** single-run overhead ~46 ms; artifacts 0.98 ms; logging 12.6 µs/event.
- **Successor:** M9.

## M9 — Research Validation & Diagnostics Framework

- **Purpose:** final quality gate — significance, robustness, overfitting, capacity,
  verdict (PASS / PASS_WITH_WARNINGS / REJECT / REQUIRES_REVIEW).
- **Deliverables:** `research/validation/` (20 modules: significance, bootstrap,
  monte_carlo, permutation, walkforward, overfitting, multiple_testing, capacity,
  factor_exposure, scoring, report, engine, …).
- **Dependencies:** M6, M7, M8.
- **Commit:** `de98b98`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M9_VALIDATION_FRAMEWORK.md`.
- **Tests:** `tests/research/test_validation.py` (13).
- **Benchmark:** full validation ~580 ms; bootstrap ~540 ms.
- **Successor:** M10.

## M10 — Portfolio Construction & Optimization Engine

- **Purpose:** transform validated signals into implementable portfolios; alpha
  strictly separated from construction; optimizer-agnostic (DI).
- **Deliverables:** `research/portfolio/` (engine, models, objectives, optimizer,
  constraints, costs, rebalancing, risk, diagnostics, validation, solvers/).
- **Dependencies:** M6 (signals), M7 (lineage), M8 (execution), M9 (validation).
- **Commit:** `7b63155`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M10_PORTFOLIO_CONSTRUCTION.md`.
- **Tests:** `tests/research/test_portfolio.py` (13).
- **Benchmark:** 10k securities, all simple objectives < 0.27 s (diagonal fast path).
- **Successor:** M11.

## M11 — Multi-Period Portfolio Simulation Engine

- **Purpose:** evolve optimized portfolios into a multi-year history — persistent
  holdings, exact cash accounting, transaction costs, rebalancing, analytics.
- **Deliverables:** `research/simulation/` (15 modules: engine, state, orders,
  execution, rebalancing, performance, exposure, attribution, analytics, validation,
  serialization, registry, diagnostics, models).
- **Dependencies:** M7, M9, M10.
- **Commit:** `4a285b6`.
- **Status:** CERTIFIED.
- **Documentation:** `AIDP_M11_PORTFOLIO_SIMULATION.md`.
- **Tests:** `tests/research/test_simulation.py` (46).
- **Benchmark:** 100–10k securities × 2y monthly, linear ~160–190k security-days/s.
- **Successor:** M12.

## M12 — Paper Trading Bridge & Live-State Reconciliation

- **Purpose:** persistent live-state loop against an external (paper) broker —
  internal↔external reconciliation, drift monitoring, deployment readiness. Reuses
  the M11 accounting core; not a live trading system (offline, deterministic).
- **Deliverables:** `research/paper_trading/` (14 modules: models, broker, adapter,
  portfolio, reconciliation, drift, risk, session, monitoring, validation,
  serialization, diagnostics, registry).
- **Dependencies:** M7 (registry), M9 (validation), M10 (cost), M11 (accounting).
- **Commit:** `1813176`.
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M12_PAPER_TRADING.md`.
- **Tests:** `tests/research/test_paper_trading.py` (50).
- **Benchmark:** reconcile/drift/order-gen < 8.5 ms at 10k; sync O(N)/tick, 25.6 MB.
- **Successor:** M13.

## M13 — Institutional Risk Engine Consolidation

- **Purpose:** canonical risk layer — limits, exposure, concentration, VaR/ES,
  stress, factor risk, drawdown halt, liquidity/capacity, deployment gating.
  Consolidates and supersedes the legacy Platform-Track risk engine (frozen,
  untouched). Plugs into the M12 pre-trade gate by injection.
- **Deliverables:** `research/risk/` (18 modules: models, limits, exposure,
  concentration, covariance, factor, var, stress, drawdown, liquidity, capacity,
  engine, monitoring, validation, serialization, diagnostics, registry).
- **Dependencies:** M9 (validation), M10 (covariance/risk-contrib), M11
  (drawdown/exposure), M12 (paper-trading state).
- **Commit:** `1a7b77b`.
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M13_RISK_ENGINE.md`.
- **Tests:** `tests/research/test_risk.py` (74).
- **Benchmark:** 10k securities assess 85.7 ms, 20.5 MB (no dense N×N); VaR/stress
  sub-3 ms.
- **Successor:** M14.

---

## M14 — Execution Management System & Order Management System

- **Purpose:** transform approved portfolio decisions into controlled, auditable,
  replayable execution — OMS state machine, EMS orchestration, execution algorithms
  (Immediate/TWAP/VWAP/POV), broker abstraction, routing, pre-trade validation, and
  post-trade execution analytics. Reuses M10 costs, M11 accounting, M12 state, M13 gate.
- **Deliverables:** `research/execution/ems/` (20 modules).
- **Dependencies:** M10 (costs), M11 (accounting), M12 (broker/state), M13 (risk gate).
- **Commit:** `961cbfc`.
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M14_EXECUTION_SYSTEM.md`.
- **Tests:** `tests/research/test_execution_ems.py` (122).
- **Successor:** M15.

---

## M15 — Trade Lifecycle & Post-Trade Operations

- **Purpose:** close Execution → Settlement → Accounting → Reporting — trade lifecycle,
  T+N settlement, settlement-aware cash ledger, position ledger, corporate actions,
  reconciliation, tax-lot interfaces, post-trade reporting, deterministic event log.
  Reuses M11 accounting (single book of record), consumes M14 fills/reports.
- **Deliverables:** `research/post_trade/` (18 modules).
- **Dependencies:** M11 (accounting), M12 (broker reconciliation), M14 (fills/reports).
- **Commit:** `7b5073e`.
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M15_POST_TRADE_OPERATIONS.md`.
- **Tests:** `tests/research/test_post_trade.py` (83).
- **Benchmark:** ~10k trades/s, reconcile 0.09 s over 1.36M events.
- **Successor:** M16.

---

## M16 — Multi-Currency & FX Portfolio Book

- **Purpose:** remove the single-currency assumption from the post-trade stack — trading/
  settlement/base currencies, DI FX rate providers, explicit auditable conversions,
  multi-currency cash & settlement, base valuation, FX exposure/P&L/risk/stress,
  cross-currency corporate actions, currency-aware reconciliation/reporting/tax/registry.
  Holds one reused M15 `PostTradeEngine` **per currency** — does not fork M11 accounting.
- **Deliverables:** `research/fx/` (21 modules).
- **Dependencies:** M11 (accounting), M13 (risk idea), M14 (fills), M15 (post-trade engine).
- **Commit:** `b029345`.
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M16_MULTI_CURRENCY.md`.
- **Tests:** `tests/research/test_fx.py` (140).
- **Benchmark:** valuation/reconcile linear (reconcile 0.37 s over 1.05M events), FX
  conversion sub-ms; backward-compatible with M15 (single-currency book matches
  fingerprint).
- **Successor:** M17.

---

## M17 — Multi-Asset & Derivatives Accounting

- **Purpose:** general instrument framework (equity, future, option, forward, swap, bond)
  layered additively over M11–M16. One `InstrumentBook` wraps the reused M15
  `PostTradeEngine` as the single cash/equity book of record and adds a derivative overlay —
  contract-aware positions, margin, collateral, mark-to-market, expiry/exercise/assignment —
  with dependency-injected pricing/Greeks/yield. Equities delegate straight to M15
  (byte-identical).
- **Deliverables:** `research/instruments/` (24 modules).
- **Dependencies:** M11 (accounting), M13 (risk), M14 (execution), M15 (settlement), M16 (FX).
- **Commit:** `22b4c38` (feature), `38e501b` (hash record).
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M17_MULTI_ASSET.md`.
- **Tests:** `tests/research/test_instruments.py` (123).
- **Benchmark:** 1.08M lifecycle events in 4.4 s; equity-only book matches M15 fingerprint.
- **Successor:** M18.

---

## M18 — Institutional Valuation & Market-Data Infrastructure

- **Purpose:** one canonical, deterministic, point-in-time valuation architecture supplying
  price / NPV / Greeks / yield / duration / DV01 / FX exposure to M10–M17. Immutable,
  provenance-stamped `MarketDataSnapshot` (never fetches live data); production
  Black-Scholes / Black-76 / binomial-American pricing; yield curves + discounting +
  vol surfaces; bond & swap analytics; cross-currency valuation via M16; model governance
  (model/version/fingerprints) and arbitrage diagnostics. Fills the M17 provider seams.
- **Deliverables:** `research/valuation/` (24 modules).
- **Dependencies:** M16 (FX providers), M17 (instrument model). Feeds M13 (risk authority).
- **Commit:** `0d910ae`.
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M18_VALUATION.md`.
- **Tests:** `tests/research/test_valuation.py` (171).
- **Benchmark:** 100k-instrument portfolio valuation in ~20 s (~5k/s); single valuation
  ~100 µs; analytic Greeks match finite differences; fully additive (zero M1–M17 regressions).
- **Successor:** M19.

---

## M19 — Institutional Market Data, Curve Calibration & Volatility Surface Engine

- **Purpose:** the market-data infrastructure *underneath* M18. Turns raw market sources into the
  immutable, PIT-validated `MarketDataSnapshot` M18 consumes: canonical typed observations
  (never bare floats), PIT-aware identifier mapping, business-day calendars, bitemporal
  revision/fixing stores, an auditable normalization pipeline, a no-silent-repair quality engine,
  multi-instrument curve bootstrapping (deposits/OIS/FRAs/futures/swaps), OIS/multi-curve, credit
  curves, SABR + SVI volatility-surface calibration with arbitrage diagnostics, and production
  adapter contracts (Bloomberg/Refinitiv/exchange/broker — translation only, offline). Addresses
  all six M18 deferred items.
- **Deliverables:** `research/market_data/` (23 modules).
- **Dependencies:** M16 (FX providers, reused), M18 (curves/surfaces/snapshot, produced for).
  Feeds M13 (risk authority), M17 (vol/curve providers), M18 valuation.
- **Commit:** `1db2035`.
- **Status:** CERTIFIED.
- **Documentation:** `AURELIUS_M19_MARKET_DATA.md`.
- **Tests:** `tests/research/test_market_data.py` (206).
- **Benchmark:** ~27k observations/s normalization (linear scaling to 1M); curve bootstrap ~20 ms,
  SVI surface calibration ~370 ms, credit bootstrap ~19 ms; calibration reprices inputs to
  < 1e-7. Fully additive (zero M1–M18 regressions; full suite 1707 passed, 3 pre-existing skips).
- **Successor:** M20 (proposed).

---

## Planned milestones (M20+)

Future work continues the sequence — never restarts. See `AURELIUS_ROADMAP.md` for
the capability view.

- **M20+** — live market-data & curve-construction (production feeds behind the M19 adapter
  contracts), regulatory & client reporting, production infrastructure, monitoring, deployment.

## Remaining inconsistencies

A separate, older **platform-track** milestone numbering exists in legacy subsystems
that predate the AIDP data/research rebuild and use *colliding* numbers (e.g.
risk = "Phase 7", construction = "Phase 8", paper = "Phase 9", assistant =
"Phase 10", validation = "Phase 14", knowledge = "Phase 15", intelligence =
"Phase 17", catalog = "Phase 22"). These map to different capabilities than the
canonical AIDP M-numbers above, so they were **not** mechanically renamed (doing so
would create duplicate M-numbers). They are preserved as historical and flagged for
a future governance milestone to reconcile the two tracks under one authoritative
number line. Affected areas: `src/aurelius/{risk,construction,paper,assistant,
knowledge,intelligence,catalog,…}`, `src/aurelius/research/{models,templates}.py`,
`research/validation/legacy.py`, and their tests.

The full cataloguing, classification, and resolution recommendation for this legacy
Platform Track is in **[`AURELIUS_LEGACY_TRACK_AUDIT.md`](AURELIUS_LEGACY_TRACK_AUDIT.md)**
(recommended resolution: freeze legacy "Phase N" as historical, track capabilities by
name, adopt into the M-line only as a future milestone rebuilds each capability).
