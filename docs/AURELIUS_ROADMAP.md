# Aurelius Research Platform — Capability Roadmap

This roadmap describes the platform as **permanent capabilities**, independent of
milestone numbers. Milestones (`M1, M2, …`) *implement* capabilities; capabilities
are the enduring architecture. A capability may be delivered or extended by several
milestones over time.

## Capability stack

```
  Market Data Layer                     [M1]
        ↓
  Point-in-Time Data Infrastructure     [M2 identity · M3 fundamentals · M4 universe · M5 insiders]
        ↓
  Feature Engineering / Research Matrix  [M6]
        ↓
  Research Engine (execution)            [M8]
        ↓
  Experiment Registry & Lineage          [M7]
        ↓
  Validation & Diagnostics               [M9]
        ↓
  Portfolio Construction                 [M10]
        ↓
  Portfolio Simulation                   [M11]
        ↓
  Risk Engine                            [M13 — canonical; legacy platform track frozen]
        ↓
  Paper Trading                          [M12]
        ↓
  Execution Management (EMS/OMS)         [M14]
        ↓
  Trade Lifecycle & Post-Trade Ops       [M15]
        ↓
  Multi-Currency & FX Book               [M16]
        ↓
  Production Infrastructure              [future]
```

## Capabilities

### Market Data Layer
Raw, immutable, corporate-action-aware price and volume data. Never restated by
later actions. *Delivered by M1.*

### Point-in-Time Data Infrastructure
Every fact carries when it was **knowable**, not just when it was true — temporal
identity (M2), availability-gated fundamentals (M3), survivorship-free universe
(M4), acceptance-gated insider activity (M5). No look-ahead, ever. *Permanent
guarantee across the platform.*

### Feature Engineering / Research Matrix
One PIT-safe accessor turning the data layer into a survivorship-free feature matrix
keyed by `security_id`. Registry-driven, cached, deterministic. *Delivered by M6.*

### Research Engine
The single orchestrator that executes research experiments through a fixed,
logged, reproducible pipeline. Nothing bypasses it. *Delivered by M8.*

### Experiment Registry & Lineage
Authoritative record of every experiment; reproducible from stored metadata alone.
Deterministic fingerprints, git/dataset/parameter provenance. *Delivered by M7.*

### Validation & Diagnostics
The final quality gate before capital: statistical significance, robustness,
overfitting analysis, capacity, and a machine-reasoned deployment verdict.
*Delivered by M9.*

### Portfolio Construction
Turns validated signals into implementable portfolios — sizing, constraints, risk
allocation, costs — with alpha strictly separated from construction and the
optimizer dependency-injected. *Delivered by M10.*

### Portfolio Simulation
Evolves constructed portfolios into a realistic multi-year history: persistent
holdings, exact cash accounting, transaction costs, rebalancing, attribution.
*Delivered by M11.*

### Risk Engine
Pre-trade and portfolio-level risk gating: limits, exposure, concentration, VaR/ES,
stress, factor risk, drawdown halt, liquidity/capacity, deployment gating. *Delivered
by M13, consolidating the legacy Platform-Track risk engine (historically "Phase 7",
frozen and untouched — see
[`AURELIUS_LEGACY_TRACK_AUDIT.md`](AURELIUS_LEGACY_TRACK_AUDIT.md)). Plugs into the
M12 pre-trade gate by injection.*

> **Two tracks, by name not number.** The Platform-Track application capabilities
> (Risk Engine, Paper Trading, AI Assistant, Knowledge Graph, Research Director /
> Intelligence / Laboratory, Data-Intelligence Catalog) are referred to **by name**
> here, independent of their historical "Phase N" labels, per the legacy-track audit.

### Paper Trading
Bridge from simulated history to a live paper broker with state reconciliation and
drift monitoring. Broker abstraction (offline Mock/Simulated + real-adapter
interfaces), internal↔external reconciliation, drift alerts, deployment readiness.
Reuses the M11 accounting core. *Delivered by M12.*

### Execution Management (EMS/OMS)
Turns approved decisions into controlled, auditable, replayable execution: OMS state
machine, EMS orchestration, execution algorithms (Immediate/TWAP/VWAP/POV), broker
abstraction, routing, pre-trade validation, post-trade execution analytics. Reuses M10
costs, M11 accounting, M12 state, and enforces the M13 gate pre-route. *Delivered by M14.*

### Trade Lifecycle & Post-Trade Operations
Closes Execution → Settlement → Accounting → Reporting: trade lifecycle, T+N settlement,
settlement-aware cash ledger, position ledger, corporate actions, reconciliation, tax-lot
interfaces, post-trade reporting, deterministic event log. Reuses the M11 accounting core
as the single book of record. *Delivered by M15.*

### Multi-Currency & FX Book
Removes the single-currency assumption from the post-trade stack: trading/settlement/base
currencies, dependency-injected FX rate providers, explicit auditable conversions,
multi-currency cash & settlement, base-currency valuation, FX exposure/P&L/risk/stress,
cross-currency corporate actions, and currency-aware reconciliation/reporting/tax/registry.
Holds one reused M15 post-trade engine **per currency** — no fork of M11 accounting;
single-currency behaviour is unchanged. *Delivered by M16.*

### Execution (live) & Production Infrastructure
Broker/FIX connectivity, live rate/broker feeds, multi-asset/derivatives accounting,
regulatory & client reporting, deployment, monitoring. *Future.*

## Principle

> Milestones are how we ship. Capabilities are what we own. The number line only
> ever grows; the capability stack only ever deepens. See
> `AURELIUS_MILESTONE_INDEX.md` for the milestone→commit history and
> `AURELIUS_ARCHITECTURE.md` for how the capabilities compose.
