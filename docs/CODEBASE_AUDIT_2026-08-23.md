# Mentisrex Capital — Full System Audit

**Date:** 2026-08-23 (refreshed same day — see revision note below)
**Scope:** entire repository, now on `main` (`aidp/audit-and-pit-gaps` was fast-forwarded and pushed) — architecture, engineering, data, current strategy, and metrics.
**Method:** five parallel research passes over `src/`, `docs/`, `tests/`, `scripts/`, `campaign/`, `data/`, and git history.

**Revision note:** the original version of this audit was written before two things happened later the same day: the `Aurelius` → `Mentisrex` rename was completed everywhere (it was previously incomplete in a handful of files), and the ten-sleeve Mentisrex Programme v3.0 — built on a sibling branch, not yet on `main` at the time of the first pass — was integrated, verified (48/48 programme tests + 2893/2893 full-suite tests + a reproduced live backtest), and pushed to `main`. §5 and §8 are rewritten below to reflect that; everything else is unchanged from the original pass except the branch/package-name references.

---

## 1. Executive summary

The project has **two numbering systems layered over the same codebase**, and understanding that is the key to understanding everything else here.

1. **Platform Track ("Phase 1–27")** — the original build. Feature-frozen, lives under `src/mentisrex/{risk,construction,paper,assistant,knowledge,director,intelligence,lab,catalog}`. `PHASE_4_PRODUCTION_REVIEW.md` approved its backtest engine for production (Low Risk) back when it shipped. It is **not dead code** — later milestones reuse its `BacktestEngine` and `PerformanceCalculator` rather than rebuilding them.
2. **Canonical M-line (AIDP M1–M11 → MENTISREX M12–M24 → MENTISREX M26–M41)** — a from-scratch rebuild to institutional point-in-time (PIT) standards: no look-ahead, deterministic, reproducible, additive-only (a certified milestone is never rewritten, only extended). This is the research/data-platform line. It now lives on `main`, fast-forwarded from `aidp/audit-and-pit-gaps` the same day this audit was first written.
3. **Mentisrex Programme v3.0** (`src/mentisrex/programme/`) — a separately-designed, separately-built ten-sleeve core-satellite trading strategy, integrated into `main` after the first version of this audit. This is now **the firm's current live strategy** — see §5. It reuses the M-line's data store and the M28 paper broker but is architecturally independent of the M-line's research/factor pipeline; it did not come out of that pipeline's hypothesis backlog.

**The honest state of the firm right now:** the *engineering* is unusually far along for a solo/small operation — 30 certified M-line milestones plus a fully separate, independently-backtested trading programme, ~7,500+ tests across all three tracks, a full research-to-paper-trading pipeline. The *M-line research* is bottlenecked almost entirely on **data**, not code — every serious alpha claim out of that pipeline (M13 low-vol, M14 attribution, the India momentum candidate) is explicitly marked **DEFER**. The *programme*, by contrast, has a real backtest with a real Sharpe on the firm's own data, but has literally never placed an order — its paper-trading cron job has been silently broken since setup (see §5.4).

**Where the money almost got lost:** on 2026-08-20 a regime-gated long-short overlay was added on top of the (now-retired) long-only momentum book and it **wiped the portfolio to -101.8%** in backtest, because shorting beaten-down momentum losers ran straight into mean-reversion squeezes. It was reverted the same day. That specific book is no longer the strategy in use (superseded by the programme, §5), but the lesson — don't short pure price-momentum losers without a valuation anchor — still applies directly to the programme's own six market-neutral sleeves, several of which are momentum-based shorts.

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

### 2.2 Package layout (`src/mentisrex/`)

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
programme/                  Mentisrex Programme v3.0 — ten-sleeve strategy core (NEW, §5)
research/                   validation, runner, portfolio_construction, liquidity models
risk/                       pre-trade gate: engine, models, monitor, stress
```

### 2.3 Milestone status at a glance

| Track | Milestones | Status | Notes |
|---|---|---|---|
| AIDP | M2–M11 | ✅ Certified, all green, unmerged to `main` | PIT identity, fundamentals, survivorship, insiders, research matrix, registry, validation, construction, simulation |
| MENTISREX | M12–M24 | ✅ Certified, additive on AIDP core | Paper trading bridge, risk engine, EMS/OMS, post-trade ops, multi-currency, multi-asset, valuation, market data ops, open-data providers, strategy deployment, continuous paper runtime, forward validation |
| MENTISREX | M13–M15 (attribution) | 🟡 **DEFER** — certified as *correctly rejected*, not shipped | Low-vol book, factor attribution: both statistically inconclusive, data-blocked |
| MENTISREX | M25–M33 | ✅ Certified | Real forward paper-trading infra, Alpaca paper broker, HAC errors, purged/embargoed CV, cross-sectional neutralization |
| MENTISREX | M34–M41 | ✅ Certified (research), 🟡 forward-untested | Factor campaign → net-of-cost momentum candidate frozen, **zero forward cycles run** |
| Platform (legacy) | Phase 1–27 | Feature-frozen, load-bearing | Original backtest engine + performance calculator still used by M8, M10, M11 |
| **Programme** | **v3.0** | ✅ Backtested + integration-verified, 🔴 paper cron broken | Ten-sleeve strategy, independent of the M-line. 48/48 own tests + 2893/2893 full suite pass. Never placed an order — see §5.4 |

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

## 5. Current strategy — Mentisrex Programme v3.0

### 5.1 What's actually live now

**`src/mentisrex/programme/`, config fingerprint `5252d1fc94eca6e2` (recommended rung).** A daily-rebalanced core-satellite programme: four directional sleeves trading SPY exposure (trend, vol-managed beta, breadth timing, panic reversal) plus six market-neutral cross-sectional sleeves (12-1 momentum, residual momentum, information-discreteness momentum, illiquidity premium, relative volume, conditional reversal), combined under a hard gross cap with a real financing model (margin interest, borrow fee, short rebate — the first strategy in this repo to price the cost of carrying leverage at all).

Backtest, this firm's own data, 2017–2026, `recommended` rung: **CAGR 28.8%, Sharpe 1.10, max drawdown -28.6%, deflated Sharpe 0.996** (10,000-path bootstrap). At the recommended *starting* rung, `deploy` (1.00x gross): CAGR 13.1%, Sharpe 1.18, max drawdown -15.0% — Sharpe is actually higher at lower leverage here, because cost/financing drag scales faster than return as gross rises.

This **replaces** the two things described below (§5.2), which are no longer the operative strategy. Full detail: `docs/TRADING_STRATEGY_FORMAL_V2.md`.

### 5.2 What it replaced (historical — kept for context, not current)

Before 2026-08-23, two things coexisted, neither of which is the current strategy:

1. **`mom-12-1-india-cs v1.0.0`** (frozen M41, 2026-08-15, M-line research track) — monthly cross-sectional 12-minus-1-month price momentum, top-300 liquid NSE names, long top quintile / short bottom quintile. Backtest (survivorship-suspect): net long-short Sharpe 0.67. **Zero forward cycles ever ran; still true today.** This candidate still exists in the M-line as a research artifact but was never promoted to live/paper status.
2. **A long-only US volume-momentum composite** (`docs/TRADING_STRATEGY_FORMAL.md`, 2026-08-19, now marked superseded) — 5d/25d momentum × volume multiplier, top-40 equal-weight. This was the strategy the -101.8% short-book blowup (§5.3) happened to.

### 5.3 Timeline (the pivot from §5.2 to §5.1)

| Date | Event |
|---|---|
| 2026-08-06 | M13 (long-only low-vol) certified **DEFER**: removes short-leg ruin (drawdown -36% vs L/S -103%), but adjusted p=0.118 fails the 5% significance gate. M14 (factor attribution) certified **DEFER**: residual alpha insignificant (t=1.16), no factor model exists to decompose it. `Research_Roadmap_v2.md` written same day — central thesis: "information gain is data-limited." |
| 2026-08-12/13 | M25–M26: forward paper-trading infra stood up, repo renamed Mentisrex→Mentisrex, real market data wired into the paper loop |
| 2026-08-14 | M27–M33 sprint: `AlpacaPaperBroker` built (paper-only, live-execution locked), HAC errors + purged/embargoed CV added, cross-sectional neutralization, DoF ledger |
| 2026-08-15 | M34–M41: factor-panel adapter, signal ensembling, India factor sweep (later found mixing US/India data — fixed), net-of-cost evaluation confirms `mom_12_1` survives at Sharpe 0.62–0.67 net; `rev_1m` demoted below significance; **M41 freezes `mom-12-1-india-cs`** |
| 2026-08-19 | Separate US backtest built from scratch (volume-momentum). **4 bugs fixed in one session**: COVID drawdown-halt bug, CAGR complex-number crash on portfolio-to-zero, foreign-stock/CIK-symbol contamination causing a spurious -101% return, closing-order leverage trap. `TRADING_STRATEGY_FORMAL.md` written. |
| 2026-08-20 | **Regime-gated long-short overlay added** to the volume-momentum book (short bottom-quintile momentum names, 10% stop-loss, vol-regime gate). **The short book wiped the portfolio to -101.8%** — shorting beaten-down momentum losers ran directly into violent mean-reversion squeezes (simulated case: a name at -55% squeezed to +130%, stopping the short out three times over). **Reverted same day.** |
| 2026-08-20/22 | Independently, on a sibling branch: the ten-sleeve v3.0 programme built from an external specification, end to end — 4,504 production lines, 48 tests, real defects found and fixed (quality gate checking wall-clock instead of last-bar date; risk gate hard-coded to a zero daily return, disarming the loss breakers; `effective_breadth` NaN-poisoned by zero-variance sleeves). Backtested against this firm's own `data/analytics.duckdb`, not synthetic data. A standing (broken, see §5.6) cron job configured to paper-trade it. |
| **2026-08-23** | The v3.0 programme integrated onto `main`: package renamed `aurelius.programme` → `mentisrex.programme`, one real API-drift break found and fixed against the M28-hardened Alpaca broker, verified with 48/48 own tests + 2893/2893 full-suite tests + a reproduced live backtest. `Aurelius`→`Mentisrex` rename completed everywhere. This is now the current strategy (§5.1). |

**Read on the -101.8% event**: this was not a code bug — the backtest engine, cost model, and risk gate all behaved correctly. It was a strategy-design failure: shorting pure price-momentum losers with no valuation anchor is a well-known short-squeeze trap, and the backtest surfaced it honestly rather than hiding it. **This lesson carries forward directly to the current strategy**: three of the programme's six market-neutral sleeves (S5 momentum, S6 residual momentum, S7 information-discreteness momentum) short the losing side of a momentum ranking, exactly the pattern that caused the blowup. The programme's own stress tests show blocked/unavailable shorts *raise* return and *worsen* drawdown, meaning the current backtest numbers (§5.1) already assume every short is borrowable — an optimistic assumption, not a proven one (§5.5 item 2).

### 5.4 Every DEFER/blocked item in the M-line, with its exact unblock condition

Unchanged by the programme integration — these belong to the separate M-line research track (§5.2 item 1), not to the current strategy:

| Item | Reason blocked | Unblocks with |
|---|---|---|
| M13 long-only low-vol | p=0.118, edge concentrated in one regime (2022–26) | Cap-weighted market factor for decomposition |
| M14 factor attribution | Alpha/beta undecomposable; rolling beta (0.49) contradicts pooled beta (~0) — smells like a proxy artifact | Real shares-outstanding → cap-weighted market module |
| M39/M40 factor sweep (all India results) | "Survivorship-suspect" — no delisting data in the panel | CRSP delisting returns (or equivalent) |
| M41 `mom-12-1-india-cs` | Zero forward cycles; short leg infeasible in NSE cash segment | Live NSE feed + F&O-eligible universe, or a long-only variant |
| ~110 Value/Quality/Investment/Size hypotheses | No fundamentals/shares-outstanding data | Compustat (or equivalent) |

### 5.5 What's unresolved in the current strategy (programme v3.0)

Carried forward from the programme's own build report, confirmed still current:

| Item | Reason blocked | Unblocks with |
|---|---|---|
| Point-in-time universe/delisting data | Store is survivor-constituted, no vendor feed | CRSP/Sharadar/Norgate (~$500/yr) — same gap as the M-line, one purchase fixes both tracks |
| Live short-borrow availability | `shortable()` raises `NotImplementedError` by design rather than assuming | Wire Alpaca's `GET /v2/assets/{symbol}` and test against a real paper account |
| Realized fill history | `fills()` raises for the same reason; realized cost can't be measured, `COST_DIVERGENCE` breaker can't fire | Wire Alpaca's `GET /v2/orders?status=closed&after=<ts>` |
| Corporate-action adjustment | Every row has `adjustment_factor = 1.0`, believed but unverified pre-adjusted | Same vendor feed, or a spot check against known splits |
| Deflated-Sharpe dispersion assumption | The external spec's DSR table only reproduces under an unstated 0.229 dispersion; Lo's conventional ~0.415 gives a materially worse picture (0.99 → as low as 0.04 at high trial counts) | A human decision on which convention to quote — not a data or engineering gap |

### 5.6 Paper trading / broker status — including a live bug

`AlpacaPaperBroker` is certified (M28), paper-only, **live execution is locked at the code level** — not a flag, not wired to a live-order path at all. The programme's own broker adapter reuses it rather than duplicating it.

**The standing paper-trading cron job has never run.** A system crontab entry (`0 19 * * 1-5`, weekdays 19:00 IST) was configured on 2026-08-22 to run the programme in `--mode paper`, but its working-directory path has a typo (`ponytai-ultra-49cf7e`, missing the `l` in `ponytail`) and points at a directory that doesn't exist. No log file has ever been produced. **`--mode paper` and `--mode live` have never been executed by this code, on any branch, as of this writing.** Flagged, not fixed — it touches system-level config outside the repo.

**No path to real capital exists in the codebase today** — by design, not by oversight. That's a feature of the "additive, gated" discipline this project follows, not a gap to rush past.

---

## 6. Metrics summary

- **Tests**: 2,893 passed / 0 failed across the full offline suite (verified this session), up from the 421 cited in the original audit pass — the jump is the 48 new `tests/programme/` tests plus test growth elsewhere between passes. `tests/` now includes a dedicated `programme/` subdirectory alongside the 19 M-line subdirectories.
- **Data footprint**: `data/parquet/` ≈ 904MB (dozens of per-milestone research outputs); market_data + validation dirs together < 1MB — i.e. almost all stored data is *derived research output*, not raw market data. Raw price panel: 6.4M bars, 2,143 symbols, ~99.6% survivors (biased) — this is the same store both the M-line and the programme read from.
- **Hypothesis backlog**: 500 structured hypotheses across 15 alpha categories, 0-10 value-scored, S/A/B/C tiered, in the M-line track. None validated yet. Not the source of the current strategy (§5.2).
- **Current strategy backtest** (programme v3.0, recommended rung, this firm's own data 2017–2026): CAGR 28.8%, Sharpe 1.10, max DD -28.6%, deflated Sharpe 0.996. At the deploy (starting) rung: CAGR 13.1%, Sharpe 1.18, max DD -15.0%.
- **Best M-line backtest result to date**: `mom_12_1` net Sharpe 0.62–0.67, net HAC t 2.30, turnover 0.23 — survivorship-suspect, unvalidated forward, not the live strategy.
- **Worst backtest result to date**: the retired volume-momentum book's regime-gated long-short overlay, **portfolio return -101.8%**, reverted same day.
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
8. **Programme v3.0 live short-borrow availability** — skipped because the firm's paper broker has no shortability lookup and inventing one untested would risk running an unintended directional bet. Unblocks with Alpaca's `GET /v2/assets/{symbol}` wired and tested against a real paper account (§5.5).
9. **Programme v3.0 realized fill history** — skipped for the same class of reason; no fills-since-timestamp query exists in the broker layer yet. Unblocks with Alpaca's `GET /v2/orders?status=closed&after=<ts>` (§5.5).
10. **Programme v3.0 paper-trading cron job** — not skipped, *broken*: a path typo (§5.6) means it has silently done nothing since 2026-08-22. Unblocks with a one-line crontab fix — flagged to you rather than silently corrected, since it's outside the repository.

---

## 8. What's actually next, given the current state

The original version of this audit proposed pivoting toward the retired long-only volume-momentum book; that's now moot — the programme replaced it. Given where things actually stand:

- **Fix the cron typo, or run the deploy rung by hand.** This is the single highest-leverage next action: the strategy is built, tested, and backtested, but has never placed one order. The four-quarter deployment ladder in `TRADING_STRATEGY_FORMAL_V2.md` §2.3 already specifies starting at `deploy` (1.00x), not `recommended` — that plan can't start until the cron actually fires or you run it manually.
- **Don't wire the short legs live until borrow-availability is real.** The programme's own S5/S6/S7 sleeves short the losing side of momentum, the exact pattern that caused the -101.8% blowup in the retired book. `shortable()` currently raises `NotImplementedError` rather than silently assuming borrowability — that's the safe default; keep it until Alpaca's asset-shortability endpoint is actually wired (§5.5).
- **The CRSP/Sharadar/Norgate purchase (~$500/yr) is still the single highest-leverage data move, and now unblocks both tracks at once**: it fixes the M-line's M13/M14 recertification *and* the programme's point-in-time/delisting gap *and* removes the "believed but unverified" adjustment-factor assumption underneath every backtest in this repo, including the 28.8% CAGR number in §5.1. This was true in the original audit and remains true now with a second, larger strategy depending on it.
- **Resolve the deflated-Sharpe dispersion question (§5.5) before quoting the 28.8%/1.10 numbers to anyone outside this session.** The programme's own documentation is explicit that the headline DSR of 0.996 depends on which standard-error convention you use, and the two conventions disagree by an order of magnitude at realistic trial counts.
- **The M-line research pipeline (hypothesis backlog, factor campaign) is now a secondary track, not blocking.** It can keep running in the background — short-term reversal is still the cheapest next hypothesis to test (EIG=7.5) — but nothing there gates the current strategy going live in paper mode.

---

*Compiled from parallel audits of `src/`, all `docs/AIDP_*`, `docs/MENTISREX_*`, `docs/Research_Roadmap_v2.md`, `docs/TRADING_STRATEGY_FORMAL.md`, `docs/TRADING_STRATEGY_FORMAL_V2.md`, `docs/PROGRAMME_V3_BUILD_REPORT.md`, `docs/PROGRAMME_V3_BACKTEST_RESULTS_2026-08-22.md`, `docs/RESEARCH_PROGRAM_AUDIT_2026-08-14.md`, `docs/HYPOTHESIS_BACKLOG.md`, `docs/DATA_ACQUISITION_BRIEF.md`, `docs/DATA_READINESS_REPORT.md`, root PHASE_4/5/6 docs, `tests/`, `scripts/`, `campaign/`, `data/`, and git history on `main`. Refreshed 2026-08-23 same-day to reflect the programme integration and rename completion.*
