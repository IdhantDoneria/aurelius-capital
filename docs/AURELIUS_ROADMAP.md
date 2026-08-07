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
  Risk Engine                            [planned / legacy platform track]
        ↓
  Paper Trading                          [proposed M12]
        ↓
  Execution (live)                       [future]
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
Pre-trade and portfolio-level risk gating (limits, stress, exposure). *Partially
present in the legacy platform track; to be consolidated under the canonical number
line in a future milestone.*

### Paper Trading
Bridge from simulated history to a live paper broker with state reconciliation and
drift monitoring. *Proposed M12.*

### Execution (live) & Production Infrastructure
Broker/FIX connectivity, smart order routing, multi-asset accounting, deployment,
monitoring. *Future.*

## Principle

> Milestones are how we ship. Capabilities are what we own. The number line only
> ever grows; the capability stack only ever deepens. See
> `AURELIUS_MILESTONE_INDEX.md` for the milestone→commit history and
> `AURELIUS_ARCHITECTURE.md` for how the capabilities compose.
