# Mentisrex Capital — Full System Audit

**Date:** 2026-08-23
**Scope:** entire repository (`aidp/audit-and-pit-gaps` branch, HEAD) — architecture, engineering, data, current strategy, and metrics.
**Method:** five parallel research passes over `src/`, `docs/`, `tests/`, `scripts/`, `campaign/`, `data/`, and git history.

---

## 1. Executive summary

The project has **two numbering systems layered over the same codebase**, and understanding that is the key to understanding everything else here.

1. **Platform Track ("Phase 1–27")** — the original build. Feature-frozen, lives under `src/aurelius/{risk,construction,paper,assistant,knowledge,director,intelligence,lab,catalog}`. `PHASE_4_PRODUCTION_REVIEW.md` approved its backtest engine for production (Low Risk) back when it shipped. It is **not dead code** — later milestones reuse its `BacktestEngine` and `PerformanceCalculator` rather than rebuilding them.
2. **Canonical M-line (AIDP M1–M11 → AURELIUS M12–M24 → MENTISREX M26–M41)** — a from-scratch rebuild to institutional point-in-time (PIT) standards: no look-ahead, deterministic, reproducible, additive-only (a certified milestone is never rewritten, only extended). This is the authoritative forward line and where almost all current work happens. It has never been merged to `main` — it lives on `aidp/audit-and-pit-gaps`, which is also the branch you're currently checked out on.

**The honest state of the firm right now:** the *engineering* is unusually far along for a solo/small operation — 30 certified milestones, ~4,600+ tests across the two tracks, a full research-to-paper-trading pipeline. The *research* is bottlenecked almost entirely on **data**, not code. Every serious alpha claim (M13 low-vol, M14 attribution, the India momentum candidate) has been explicitly marked **DEFER** because the underlying data can't support the statistical claim — not because the pipeline is broken. You are data-blocked, not build-blocked.

**Where the money almost got lost:** on 2026-08-20 a regime-gated long-short overlay was added on top of the working long-only momentum book and it **wiped the portfolio to -101.8%** in backtest, because shorting beaten-down momentum losers ran straight into mean-reversion squeezes. It was reverted the same day. This is the single most important cautionary data point in the whole repo — see §5.

---

## 2. Architecture

### 2.1 Data flow (canonical M-line)

```
Raw sources (EDGAR, Alpaca, Yahoo, NSE bhavcopy, FRED, ...)
        │
        ▼
Data Layer — PIT price / identity / fundamentals / universe / insider stores  (M2–M6)
        │
        ▼
Research Matrix — unified PIT feature accessor, feature_matrix_as_of()        (M6)
        │
        ▼
Research Platform — experiment registry, ResearchRunner orchestrator,
                     ResearchValidator (statistical gate: bootstrap, PSR,
                     deflated Sharpe, PBO/CSCV, HAC/Newey-West, purged CV)     (M7, M9, M31)
        │
        ▼
Portfolio Layer — construction (optimizer) + multi-period simulation          (M10, M11)
        │
        ▼
Experiment Registry — provenance record only, never reruns                    (M7)
        │
        ▼
Paper Trading Bridge — MockBroker / AlpacaPaperBroker, reconciliation,
                        drift monitoring, deployment readiness gate           (M12, M22, M23, M28)
        │
        ▼
Forward Validation — observational-only diagnostics, backtest-vs-paper drift  (M24, M29)
```

Every arrow is one-directional. Upper layers never reach into a sibling's internals — components depend on interfaces (dependency injection), not concrete engines. This is a real, consistently-applied design discipline, not aspirational.

### 2.2 Package layout (`src/aurelius/`)

```
application/interfaces/     repository interfaces (ports)
assistant/                  research assistant glue
backtesting/                event-driven engine: engine.py, execution/, oms/, portfolio/, risk/, analytics/
catalog/                    dataset lineage, versioning, quality monitor, governance
construction/               portfolio optimizer: builder, optimize, sizing, exposure, aggregation
corpus/ discovery/          research-ideation stack: literature ingestion, hypothesis generation,
hypothesis/ intelligence/   knowledge graph, "lab" supervision, "director" orchestration
knowledge/ lab/ director/
domain/                     entities, exceptions
features/                   factor/feature library, pipeline, registry, store
infrastructure/             DB (Postgres+DuckDB), cache (Redis), config, migrations
market_data/                adapters (Alpaca, Yahoo, CSV), storage (DuckDB), ingestion pipeline
operations/                 pipeline health, extractor, healer, journal, planner, scorer, watcher
paper/                      paper broker (local sim + Alpaca paper API), journal, dashboard
presentation/                API routes, middleware
research/                   validation, runner, portfolio_construction, liquidity models
risk/                       pre-trade gate: engine, models, monitor, stress
```

### 2.3 Milestone status at a glance

| Track | Milestones | Status | Notes |
|---|---|---|---|
| AIDP | M2–M11 | ✅ Certified, all green, unmerged to `main` | PIT identity, fundamentals, survivorship, insiders, research matrix, registry, validation, construction, simulation |
| AURELIUS | M12–M24 | ✅ Certified, additive on AIDP core | Paper trading bridge, risk engine, EMS/OMS, post-trade ops, multi-currency, multi-asset, valuation, market data ops, open-data providers, strategy deployment, continuous paper runtime, forward validation |
| MENTISREX | M13–M15 (attribution) | 🟡 **DEFER** — certified as *correctly rejected*, not shipped | Low-vol book, factor attribution: both statistically inconclusive, data-blocked |
| MENTISREX | M25–M33 | ✅ Certified | Real forward paper-trading infra, Alpaca paper broker, HAC errors, purged/embargoed CV, cross-sectional neutralization |
| MENTISREX | M34–M41 | ✅ Certified (research), 🟡 forward-untested | Factor campaign → net-of-cost momentum candidate frozen, **zero forward cycles run** |
| Platform (legacy) | Phase 1–27 | Feature-frozen, load-bearing | Original backtest engine + performance calculator still used by M8, M10, M11 |

---

## 3. Engineering assessment

### 3.1 What's solid

- **PIT discipline is real, not decorative.** No-look-ahead is enforced at multiple layers (next-bar-open fills in the backtest engine, `acceptance_datetime`-gated insider filings, append-only fundamentals ledger, temporal security identity).
- **Test volume is large**: ~4,600+ tests cited across milestone docs (M9: 154, M10: 167, M11: benchmarked to 10k names, M17: 1,330 all-green, M18: 1,501, M19: 1,707). `tests/` has 114 files, 19 subdirectories.
- **Additive-only discipline is followed**, not just stated: M16 verified backward compatibility to M15, M17 verified equity behavior byte-identical to pre-M17, etc.
- **Credential handling is clean**: no hardcoded secrets found; Alpaca keys via env/`.env`, pydantic-settings hard-crashes on bad config rather than silently defaulting.
- **Research-ideation stack** (`corpus/`, `discovery/`, `hypothesis/`, `knowledge/`) is the best-tested corner of the codebase relative to its size — 3–6 test files per module, no stubs found.

### 3.2 Where it's thin

| Area | Problem | File evidence |
|---|---|---|
| `construction/` (portfolio optimizer) | Only 1 test file for 5 source files. Highest numerical-risk code (optimization convergence) is the least tested. | `construction/optimize.py:83` — documented: "fixed step/iteration cap, no line search" |
| `risk/` | Only 1 test file for 4 source files — thin for a risk-critical, capital-protecting module | — |
| `paper/` | Only 1 test file for 6 source files | `paper/broker.py:18` — margin explicitly deferred |
| `research/validation.py` + `validation/` package | 1 test file for 8 source files | — |
| No live broker beyond Alpaca **paper** API | No real order routing exists anywhere in the codebase | `market_data/adapters/base.py:54` — `NotImplementedError` by design |
| Per-name risk contribution | Scale-safe O(N) diagonal model, not full correlation-aware | M13 doc |
| Sector/factor classification map | Doesn't exist anywhere in the stack — blocks Brinson attribution, factor exposure limits | Recurring gap through M9–M11 |

### 3.3 Legacy-track resolution (already decided, worth knowing)

Two milestone-numbering systems collide at low numbers (Platform Phase 7 = Risk Engine, AIDP M7 = Experiment Registry) but are unrelated capabilities. The adopted policy: **freeze Phase-N as historical**, never rename; track Platform-Track capabilities **by name** going forward; absorb a legacy capability into the M-line only when a future milestone actually rebuilds it (as M13 did for risk). No mass renumbering will ever happen — don't ask for one.

---

## 4. Data — the actual bottleneck

This is the single most important section. Nearly every "DEFER" in the research program traces back to one of these four gaps.

| Gap | Why it matters | What's blocked |
|---|---|---|
| **No survivorship-free universe** | Current price panel (`analytics.duckdb`, 6.4M bars, 2,143 symbols) is ~99.6% survivors — delisted names are essentially absent | Every backtest is upward-biased; M39/M40 results explicitly labeled "survivorship-suspect" |
| **No point-in-time fundamentals with real publication dates** | Needed to avoid look-ahead in value/quality factors | ~110 of the 500 backlogged hypotheses (Value, Quality, Investment, Size families) |
| **No cap-weighted market / shares-outstanding data** | Can't build a proper Fama-French style market factor | M14 factor attribution — residual alpha vs beta literally undecomposable |
| **No shortability/borrow data** | Indian cash-segment names generally can't be shorted (only F&O-eligible names can); US short-side needs valuation data to avoid squeezes | Both the India L/S candidate's short leg and the reverted US regime-gated short overlay |

Two other gaps flagged as P0 in `RESEARCH_PROGRAM_AUDIT_2026-08-14.md`:
- **HAC/Newey-West standard errors were absent** — t-stats on autocorrelated momentum returns were overstated. (Since fixed at M31.)
- **Purged/embargoed cross-validation was absent** — label-horizon leakage risk. (Since fixed at M31.)

`Research_Roadmap_v2.md`'s single highest-priority call: **acquire CRSP (delisting returns + shares outstanding) and build a cap-weighted market module, then re-run FF/Carhart attribution and re-certify M11–M13.** This is stated as the one move that unblocks the most currently-frozen work. A secondary, parallel Compustat acquisition unblocks the largest untapped hypothesis block (Value/Quality/Investment, ~110 ideas).

**This is the concrete, non-negotiable "impossible right now" item, per your own CLAUDE.md rule**: the fix is not more engineering — it's a paid data source (CRSP and/or Compustat, or a comparable licensed provider). Nothing in the codebase can substitute for it.

---

## 5. Current strategy — what's actually live, and the near-miss

### 5.1 Two frozen candidates coexist

1. **`ew-momentum-exp v1.0.0`** — original frozen baseline, used as a regression-check anchor throughout M27–M40. Not a live trading candidate.
2. **`mom-12-1-india-cs v1.0.0`** (frozen M41, 2026-08-15) — monthly cross-sectional 12-minus-1-month price momentum, top-300 liquid NSE names, long top quintile / short bottom quintile, equal-weight. Backtest (survivorship-suspect): **net long-short Sharpe 0.67, net HAC t 2.30, turnover 0.23**. **Zero forward cycles have run.** Short leg is currently infeasible (no NSE overnight short in the cash segment).

Separately, the US paper-trading track (`docs/TRADING_STRATEGY_FORMAL.md`, 2026-08-19) formalizes the **operative live strategy**: a long-only volume-momentum composite (5d/25d momentum × clamped volume multiplier), weekly rebalance, top-40 equal-weight names, 2.5% NAV per name.

### 5.2 Timeline of the last two weeks (the pivot you asked about)

| Date | Event |
|---|---|
| 2026-08-06 | M13 (long-only low-vol) certified **DEFER**: removes short-leg ruin (drawdown -36% vs L/S -103%), but adjusted p=0.118 fails the 5% significance gate. M14 (factor attribution) certified **DEFER**: residual alpha insignificant (t=1.16), no factor model exists to decompose it. `Research_Roadmap_v2.md` written same day — central thesis: "information gain is data-limited." |
| 2026-08-12/13 | M25–M26: forward paper-trading infra stood up, repo renamed Aurelius→Mentisrex, real market data wired into the paper loop |
| 2026-08-14 | M27–M33 sprint: `AlpacaPaperBroker` built (paper-only, live-execution locked), HAC errors + purged/embargoed CV added, cross-sectional neutralization, DoF ledger |
| 2026-08-15 | M34–M41: factor-panel adapter, signal ensembling, India factor sweep (later found mixing US/India data — fixed), net-of-cost evaluation confirms `mom_12_1` survives at Sharpe 0.62–0.67 net; `rev_1m` demoted below significance; **M41 freezes `mom-12-1-india-cs`** |
| 2026-08-19 | Separate US backtest built from scratch (volume-momentum). **4 bugs fixed in one session**: COVID drawdown-halt bug, CAGR complex-number crash on portfolio-to-zero, foreign-stock/CIK-symbol contamination causing a spurious -101% return, closing-order leverage trap. `TRADING_STRATEGY_FORMAL.md` written. |
| **2026-08-20** | **Regime-gated long-short overlay added** (short bottom-quintile momentum names, 10% stop-loss, vol-regime gate). **The short book wiped the portfolio to -101.8%** — shorting beaten-down momentum losers ran directly into violent mean-reversion squeezes (simulated case: a name at -55% squeezed to +130%, stopping the short out three times over). **Reverted same day.** Short overlay is explicitly deferred until fundamentals data (P/E, P/S) exists to distinguish genuine deterioration from an oversold bounce candidate. |

**Read on the -101.8% event**: this was not a code bug — the backtest engine, cost model, and risk gate all behaved correctly. It was a strategy-design failure: shorting pure price-momentum losers with no valuation anchor is a well-known short-squeeze trap, and the backtest surfaced it honestly rather than hiding it. That's the system working as intended. The lesson for any pivot: **don't re-add a short leg without a valuation-based (not momentum-based) trigger.**

### 5.3 Every DEFER/blocked item, with its exact unblock condition

| Item | Reason blocked | Unblocks with |
|---|---|---|
| M13 long-only low-vol | p=0.118, edge concentrated in one regime (2022–26) | Cap-weighted market factor for decomposition |
| M14 factor attribution | Alpha/beta undecomposable; rolling beta (0.49) contradicts pooled beta (~0) — smells like a proxy artifact | Real shares-outstanding → cap-weighted market module |
| M39/M40 factor sweep (all India results) | "Survivorship-suspect" — no delisting data in the panel | CRSP delisting returns (or equivalent) |
| M41 `mom-12-1-india-cs` | Zero forward cycles; short leg infeasible in NSE cash segment | Live NSE feed + F&O-eligible universe, or a long-only variant |
| ~110 Value/Quality/Investment/Size hypotheses | No fundamentals/shares-outstanding data | Compustat (or equivalent) |
| Short overlay on the US momentum book | Momentum-only shorts have no way to avoid squeeze traps | Valuation data (P/E, P/S) as a co-trigger |

### 5.4 Paper trading / broker status

`AlpacaPaperBroker` is certified (M28), paper-only, **live execution is locked at the code level** — it is not a flag you flip, it's not wired to a live-order path at all. The full pipeline (Yahoo Finance adapter → quality engine → snapshot builder → `PaperTradingLoop` → strategy runtime → portfolio/risk → broker execution → forward validation) runs on a 10-name US universe on free/delayed data, and is explicitly labeled in its own doc: **"EXPERIMENTAL — NOT PRODUCTION APPROVED, NO REAL CAPITAL DEPLOYED."** The India candidate hasn't started a forward cycle at all.

**No path to real capital exists in the codebase today** — by design, not by oversight. That's a feature of the "additive, gated" discipline this project follows, not a gap to rush past.

---

## 6. Metrics summary

- **Tests**: 114 files across 19 `tests/` subdirectories in the current `src/aurelius/` package; milestone docs separately cite 4,600+ passing tests across the certified M-line (M9 154, M10 167, M11 to 10k names, M17 1,330, M18 1,501, M19 1,707, M13 862, M14 372, M15 455, M16 595).
- **Data footprint**: `data/parquet/` ≈ 904MB (dozens of per-milestone research outputs); market_data + validation dirs together < 1MB — i.e. almost all stored data is *derived research output*, not raw market data. Raw price panel: 6.4M bars, 2,143 symbols, ~99.6% survivors (biased).
- **Hypothesis backlog**: 500 structured hypotheses across 15 alpha categories, 0-10 value-scored, S/A/B/C tiered. None validated yet.
- **Best backtest result to date**: `mom_12_1` net Sharpe 0.62–0.67, net HAC t 2.30, turnover 0.23 — survivorship-suspect, unvalidated forward.
- **Worst backtest result to date**: regime-gated long-short overlay, **portfolio return -101.8%**, reverted same day.
- **PHASE_4_PRODUCTION_REVIEW.md verdict** (legacy engine, historical): APPROVED FOR PRODUCTION, Risk: LOW, on the backtest engine specifically — not an endorsement of any current strategy.

---

## 7. Known limitations / skipped items (per project's own disclosure rule)

Consolidated from the docs above — each with reason and unblock, as required:

1. **Real broker/live execution routing** — skipped because no capital has been approved for deployment and the project's own gating discipline requires forward-validated paper evidence first. Unblocks when a strategy clears forward validation (M24/M29) and a live broker (IB/Alpaca live/Zerodha) integration is explicitly commissioned.
2. **Survivorship-bias-free price history** — skipped because no licensed survivorship-free data source (CRSP, Sharadar, or NSE full bhavcopy archive with delistings) has been acquired; free sources don't carry delisted names. Unblocks with a paid data subscription.
3. **Point-in-time fundamentals with real filing/publication dates** — skipped for the same reason (Compustat or equivalent licensed source needed); EDGAR-only PIT fundamentals exist but with curated/limited concept coverage.
4. **Cap-weighted market factor / Fama-French attribution** — skipped because shares-outstanding history isn't available from free sources at the needed fidelity. Unblocks with CRSP or equivalent.
5. **Short-side momentum overlay** — skipped after the 2026-08-20 -101.8% blowup; not an engineering gap, a deliberate strategy-risk decision. Unblocks with a valuation-based short trigger (needs fundamentals data — same gate as #3).
6. **Sector/factor classification map** — skipped, no data source wired; blocks Brinson attribution and sector exposure limits across M9–M11. Unblocks with a classification data source (GICS/ICB or equivalent) and a small mapping module.
7. **Full correlation-aware risk contribution** — currently a diagonal O(N) approximation (M13). Unblocks with a covariance-matrix estimation module; deferred as an effort/priority tradeoff, not a hard data block — flagged here for completeness even though it doesn't meet the "impossible" bar.

---

## 8. Pivot ideas, given what the data actually supports

You asked for ideas to pivot the existing strategy toward something you can paper trade now and scale to real capital later. Given the audit above, here's what's actually buildable without waiting on CRSP/Compustat:

- **Ship the long-only US volume-momentum book as-is into continuous paper trading** (M23 runtime already exists for this). It's the only strategy in the repo that is (a) long-only, so immune to the short-squeeze failure mode you just hit, (b) already formalized in `TRADING_STRATEGY_FORMAL.md`, and (c) has a working paper-trading path (M28 Alpaca paper broker). This is the fastest real "strategy running in the market" outcome available today.
- **Don't resurrect the short leg until fundamentals data lands.** The -101.8% event is a repeatable failure mode (momentum-only shorts vs. squeeze risk), not bad luck — any pivot that re-adds shorting on price signals alone will hit the same wall.
- **Treat the India `mom-12-1-india-cs` candidate as long-only-only for now**, given the NSE cash-segment shorting constraint is a real market rule, not a data gap — it can run forward in paper mode on the long side alone while you decide whether to pursue F&O-eligible shorting later.
- **The single highest-leverage engineering-adjacent move is a data purchase, not a build**: CRSP unblocks M13/M14 recertification and the survivorship problem across every existing result. This is worth pricing out concretely before writing more strategy code — you have more strategy logic built than you have licensed data to validate it against.
- **Short-term reversal** is flagged in the roadmap as the highest immediate expected-information-gain hypothesis that's cheap to test with current data (EIG=7.5) — a reasonable next research task to keep the pipeline warm while a data acquisition decision is pending.

---

*Compiled from parallel audits of `src/`, all `docs/AIDP_*`, `docs/AURELIUS_*`, `docs/MENTISREX_*`, `docs/Research_Roadmap_v2.md`, `docs/TRADING_STRATEGY_FORMAL.md`, `docs/RESEARCH_PROGRAM_AUDIT_2026-08-14.md`, `docs/HYPOTHESIS_BACKLOG.md`, `docs/DATA_ACQUISITION_BRIEF.md`, `docs/DATA_READINESS_REPORT.md`, root PHASE_4/5/6 docs, `tests/`, `scripts/`, `campaign/`, `data/`, and recent git history on `aidp/audit-and-pit-gaps`.*
