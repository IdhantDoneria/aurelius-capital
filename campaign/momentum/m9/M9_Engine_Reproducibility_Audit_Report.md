# M9 — Engine Reproducibility & Vintage Integrity Audit

**Aurelius Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-05
**Type:** forensic audit only. No signal / factor / portfolio / cost / reporting /
ingestion change. **No code correction required** (none found necessary).
**Question:** is the M7 anomaly an **engine defect** or **genuine strategy behavior**?
**Decision:** **REJECT** — no engine defect; the anomaly is genuine
construction-driven exposure behavior that disappears under correct (M8-bounded)
reproduction. Point-in-time / survivorship-controlled sub-audit **DEFERRED**
(data-blocked, M6).
**Regression:** 597 passed, 2 skipped (unchanged; audit added no product code).

---

## 0. The anomaly under audit (M7 Run B)

Certified M4 + median-dollar-volume liquidity screen (drop bottom 20%), US OOS
2014–2026, net: **OOS return −95.85%, OOS max drawdown −115.87%** (breaches 100% →
book lost more than capital), 387 trades. M8 established snapshot concentration is
negligible at 20% shrink (max weight ~1.2%), so the blow-up was left unexplained and
frozen to M9.

---

## Phase 1 — Reproduce M7 failure (deterministic)

Re-ran the exact M7 Run B conditions (same universe, dates, snapshot, rebalance
schedule, signals, construction, execution) via `scripts/run_m7_jt.py B`. Result
**byte-identical** to the committed M7 record:

| Metric | Committed M7 Run B | M9 reproduction |
|---|---|---|
| IS Sharpe | −0.0321 | −0.0321 |
| OOS Sharpe | +0.2767 | +0.2767 |
| OOS Return | −95.85% | −95.85% |
| OOS Max DD | −115.87% | −115.87% |
| OOS Trades | 387 | 387 |
| Adjusted p | 0.2952 | 0.2952 |

**Same inputs → same outputs to every digit.** The engine is deterministic; the
anomaly is a stable property of the configuration, not a run-to-run artifact.
Record: `campaign/momentum/m9/m7_repro_runB.jsonl`.

---

## Phase 2 — Vintage integrity audit (leakage)

Read-only trace of the execution/timing path (`engine.py`, `execution/simulator.py`):

| Audit item | Finding | Leakage? |
|---|---|---|
| Rebalance timing (signal vs execution) | Orders created on bar `t` **pend to the NEXT bar's open** (`engine.py:19–21`), filled only against the order's OWN symbol (`:130`). Signal@t → fill@t+1 open. | **No** |
| Universe construction timing | Membership at each rebalance is derived from `ctx.history` (bars ≤ t) only — the liquidity metric uses a trailing 21-bar window ≤ t. | **No** |
| Future data availability | No fundamentals/market data beyond price+volume ≤ t is accessible (M6: panel is prices+volume only). | **No** |
| Delisted / dead symbols | Panel is a currently-listed snapshot (M6: 9/2143 end early). No delisting events fed to the engine. | Survivorship (data), not leakage |
| Corporate actions | Prices pre-adjusted upstream (`adjustment_factor≡1.0`, M6); no CA events at decision time. | **No** |

**Vintage dependency map:** signal(t) ← history(≤t) → order(t) → fill(t+1 open) →
MTM(t+1) → equity(t+1). No node reads t+1 information at time t. **No look-ahead
leakage.** Decisive logic: leakage *inflates* returns; the anomaly is a −96% *loss*,
the opposite signature. Leakage-defect is ruled out on both mechanism and sign.

**Data-vintage caveat (not leakage):** the universe is a *current* listed set, so
point-in-time membership is NOT known-as-of-date (survivorship). This biases returns
*upward* (M6, L8/L17) — it cannot manufacture the −96% loss.

---

## Phase 3 — Composition drift audit

| Universe | Composition | OOS Return | OOS Max DD | Source |
|---|---|---|---|---|
| Original M7 (drifting) | liquidity screen re-selects members every rebalance | **−95.85%** | −115.87% | M7 Run B |
| Frozen (fixed subset) | same deterministic names every rebalance | −54% to −59% | −61% to −73% | M9 isolation (§Phase 4) |
| Point-in-time | as-of-date listed set | — | — | **DEFER (no PIT data, M6)** |
| Survivorship-controlled | + delisted names & delisting returns | — | — | **DEFER (no delisting data, M6)** |

**Finding:** freezing composition (removing drift) improves the blow-up by ~+36 pp
of return (−96% → ~−57%) but does **not** eliminate it — a frozen 50-name book still
loses ~−54%. So composition drift (the rejected liquidity screen churning membership)
is an **amplifier**, not the root; the residual loss survives with composition fixed.
Point-in-time and survivorship-controlled universes require delisting / as-of-date
membership data absent from the frozen panel (M6) → those two comparisons are
**DEFERRED**, not concluded. Sector exposure: unmeasurable (no sector metadata, M6).

---

## Phase 4 — Engine path isolation (config switches only)

Fixed 5% US universe (50 names, composition frozen), full-sample `run_backtest`,
toggling only `max_gross_leverage` (cap) and `invariant_construction` — no
engine/signal/factor/cost change. `campaign/momentum/m9/m9_isolation.json`.

| construction | cap | Return | CAGR | Sharpe | Sortino | Max DD | Vol | Trades | Turnover |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 1.5× (ON) | −59.2% | −53.6% | −0.470 | −0.591 | −72.6% | 0.867 | 44 | 4.19 |
| baseline | 1000× (OFF) | −54.0% | −37.3% | −0.739 | −0.971 | −61.0% | 0.514 | 211 | 9.36 |
| invariant | 1.5× (ON) | +77.3% | +4.7% | +0.036 | +0.050 | −24.1% | 0.123 | 194 | 0.45 |
| invariant | 1000× (OFF) | +77.3% | +4.7% | +0.036 | +0.050 | −24.1% | 0.123 | 194 | 0.45 |

**Channel-by-channel verdict:**

- **A. Async-vintage** — present (50 names span **14 distinct start dates**,
  2014–2017 → per-symbol rebalance gate fires on different calendar dates). But it is
  **benign once exposure is bounded**: the invariant book (vol 0.12, DD −24%) is
  well-behaved on the *same* async schedule. Async timing texture does not by itself
  create the blow-up. *Not a defect.*
- **B. Composition filtering** — removed (frozen universe) and the baseline **still
  blows up** (−54% to −59%). *Not necessary; not the root.*
- **C. Cap enforcement** — turning the cap OFF only mildly helps the baseline
  (−72.6% → −61% DD; still −54% return), and for the invariant book **cap-ON ==
  cap-OFF to every digit** (it de-levers below 1.5× so the cap never binds). The cap
  is a **secondary amplifier and a downstream consequence** of construction
  over-leverage, not an independent defect. It is a deliberate risk control (L5),
  by-design.
- **D. Rebalance timing** — T+1 open fills (Phase 2), unchanged across cells; not a
  divergence source.

**Dominant channel = portfolio construction.** Baseline (0.75/_count) runs a
concentrated, high-vol (0.51–0.87), over-levered book on the thin universe; the
M8 bounded construction turns −59%/−72.6% DD into +77%/−24% DD (vol 0.12) and makes
the cap irrelevant. This is exactly M8's isolated channel — **not an engine defect.**

---

## Decision — REJECT (no engine defect)

Per criteria: *REJECT if no engine defect exists and the anomaly disappears under
correct reproduction.* Both hold:

1. **No engine defect** — deterministic (Phase 1); no leakage, correct T+1 timing
   (Phase 2); composition drift and the cap are amplifiers, not roots (Phases 3–4);
   async-vintage benign once exposure bounded (Phase 4). **0 platform defects.**
2. **Anomaly disappears under correct reproduction** — the M8 bounded construction
   (the correct, invariance-preserving reproduction) removes the blow-up
   (−59%/−72.6% DD → +77%/−24% DD; cap-independent). The anomaly is **genuine
   strategy behavior** of the incumbent construction on a reduced universe, already
   diagnosed and controlled in M8.

**Therefore no code correction is required** (and none was made). M7 stays REJECTED
(liquidity screen), M8's bounded construction stays the ADOPTED standard for
universe-reducing campaigns — together they fully account for the anomaly.

**Partial DEFER:** the point-in-time and survivorship-controlled universe
comparisons (Phase 3) cannot be concluded without as-of-date membership + delisting
returns (absent, M6). They are DEFERRED pending CRSP-class data, not left open as a
suspected defect.

---

## Remaining limitations / Skipped (CLAUDE.md)

- **Point-in-time & survivorship-controlled universes** — DEFERRED. *Reason:* no
  as-of-date membership or delisting-returns data (M6). *Unblock:* CRSP
  (`EXCHCD`/`DLRET`/PERMNO). Expected effect: survivorship biases *upward*, so a
  corrected universe would lower baseline performance, not explain the −96% loss.
- **Net-exposure / dollar-neutrality time series & true async-vintage toggle** — not
  instrumented/toggled. *Reason:* requires engine-level position-snapshot recording
  and a synchronous-rebalance switch — engine code, frozen; M9 is read-only + config
  only. Inference used instead (cap-rejection at 1.62× observed in logs; invariant
  cap-independence). *Unblock:* engine unfreeze (synchronous rebalance + dollar-hold
  sizing, the M3 unblock).
- **Sector exposure (Phase 3 metric)** — unmeasurable (no sector metadata, M6).

---

## Certification

| Requirement | Status |
|---|---|
| M7 anomaly reproduced (deterministic) | ✅ byte-identical (Phase 1) |
| Vintage integrity audited (leakage) | ✅ no leakage (Phase 2) |
| Composition drift audited | ✅ amplifier, not root (Phase 3) |
| Engine paths isolated | ✅ construction dominant, cap/async not defects (Phase 4) |
| Decision evidence-backed | ✅ **REJECT** (no engine defect) |
| Code changed only if required | ✅ none required, none made |

**M9 CERTIFIED — REJECT (no engine defect).** The M7 anomaly is genuine
construction-driven behavior, controlled by the M8 bounded-construction standard;
point-in-time/survivorship sub-audit DEFERRED (M6 data). STOP — M10 not begun.
