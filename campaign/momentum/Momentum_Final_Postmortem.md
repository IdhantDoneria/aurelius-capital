# Momentum Campaign — Institutional Post-Mortem

**Aurelius Capital — Momentum Campaign, Phase-5 (M11)**
**Date:** 2026-08-05. Capstone retrospective. Decision upstream: **ARCHIVE**.

---

## 1. Original motivation

Reproduce Jegadeesh & Titman (1993/2001) cross-sectional momentum on real equity data
as the first landmark in the institutional reproduction program, and determine
whether a deployable momentum book exists on the data Aurelius actually holds
(2014–2026 daily US + India, price+volume only).

## 2. Research timeline

- **Pre-M:** literature map, methodology-fidelity map, US+India 14-run
  robustness/cross-market grid (1/14 significant), JT US reference. Established real
  data (not toy) and genuine OOS power.
- **M1** equal-weight decile baseline → **M2** $5 screen (KEEP) → **M3** overlapping
  cohorts (BLOCKED, engine) → **M4** 1-month skip (KEEP). Sequential single-change
  fidelity, each KEEP/REJECT-certified on OOS + fidelity.
- **M5** gross-vs-net reporting (KEEP; gross OOS still negative).
- **M6** investable-universe fidelity audit (prices+volume only; survivorship
  quantified; CRSP named as the unblock).
- **M7** liquidity screen → deployment blow-up (REJECT).
- **M8** portfolio invariance → bounded construction (ADOPT).
- **M9** engine reproducibility forensics → no defect (REJECT the defect hypothesis).
- **M10** capacity & deployability → not deployable (REJECT).
- **M11** termination → **ARCHIVE**.

## 3. Major discoveries

1. **The gross edge is already negative OOS** (M5). The single most important finding:
   costs were never the problem.
2. **Construction, not the factor, drove the visible failures** (M7→M8→M9). A
   universe-reducing screen concentrated / over-levered the book; bounding
   construction (M8) fixed the *risk* but revealed there was no *return*.
3. **The engine is clean** (M9): deterministic, no leakage, T+1 fills; every anomaly
   traced to construction/behavior, 0 defects across the program.
4. **Capacity and equal-weight breadth conflict** (M10): the illiquid decile tail
   caps ₹ capacity at ~₹0.4cr; removing it (liquidity filter) removes the return.
5. **Data ceiling is the binding constraint** (M6): survivorship + no
   fundamentals/PIT/exchange metadata cap fidelity; CRSP/Compustat is the unblock.

## 4. Incorrect assumptions (that the evidence overturned)

- *"Transaction costs explain the reproduction gap."* — False (M5: ~1pp wedge; gross
  still negative).
- *"The M7 blow-up was single-name concentration."* — False (M8/M9: concentration is
  negligible at 20% shrink; blow-up was construction over-leverage + async/cap
  interaction).
- *"A liquidity screen improves a real-money book."* — False here (M7): on a
  decile-size sizer it concentrates/levers into ruin.
- *"There might be an engine defect / leakage."* — False (M9).
- *"A lower-turnover variant could rescue deployability."* — False (M10: every cadence
  still breaches 100% DD).

## 5. Correct assumptions (confirmed)

- Sequential single-change fidelity isolates cause (M1–M4).
- Judge fidelity changes on OOS + mechanism, not the single-slice p-gate (M2/M4 KEPT
  despite REJECT verdicts).
- Determinism → parallelize freely with zero precision loss (grid fans).
- Quantify a suspected driver before blaming it (M5 cost wedge; M8 concentration
  probe; M9 cap on/off) — measurement repeatedly overturned a plausible story.

## 6. Platform improvements delivered (kept regardless of ARCHIVE)

- **M2 $5 screen, M4 1-month skip** — fidelity construction standards.
- **M5 dual gross/net reporting** — every result reported on both bases.
- **M8 bounded equal-weight construction** — the mandated standard for any future
  universe-reducing campaign (prevents concentration ruin).
- **M7 generic liquidity framework** — reusable metric registry (default OFF).
- **DuckDB read-only shared-lock** ingest pattern; **project-interpreter** discipline;
  crash-resumable per-label shards.
- **Forensic method:** byte-identical reproduction → config-switch isolation → decide
  defect-vs-behavior without touching the engine (M9).

## 7. Lessons for every future factor campaign

1. **Check gross before net.** If the gross OOS edge is absent, no cost/construction
   work can create alpha — stop early (M5).
2. **A higher Sharpe can be a blow-up in disguise** — always read return + max-DD next
   to any ratio; a complex/NaN ratio means equity crossed zero (M10, L18/L27).
3. **Bound construction before screening the universe** (M8): any filter that shrinks
   `n` must not be allowed to lever/concentrate the book.
4. **Reproduce byte-identical before diagnosing** (M9); isolate with config switches,
   not engine edits.
5. **Measure the suspected driver; don't assert it** (M5/M8/M9 each overturned a
   plausible narrative).
6. **Name the data ceiling honestly** (M6): distinguish "blocked by data" from
   "blocked by effort"; the former is a real STOP, the latter never is.
7. **Evaluation basis must match the question** — IS/OOS slice for generalization,
   continuous single-capital for deployability (M10, L26).

## 8. Mistakes that must never be repeated

- Do not attribute a loss to leakage — leakage *inflates* (L23).
- Do not carry a plausible mechanism from a prior report into a decision without
  re-measuring it (M7's concentration story was wrong; M9 caught it).
- Do not report degenerate ratio metrics as if meaningful once equity ≤ 0 (L27).
- Do not tune a threshold to make a REJECT disappear — a single clean pre-registered
  test is the honest result (M7/M10).
- Do not treat a confounded long-only bull-regime result as factor alpha (India).

## 9. What Renaissance Technologies would likely keep

- **The falsification discipline** — a risk-bearing hypothesis, pre-registered
  single-change tests, kill it on evidence, archive without sentiment.
- **The forensic engine audit** (M9): determinism + config-switch isolation proving
  defect-vs-behavior — exactly how a serious shop clears its infrastructure before
  blaming or trusting a signal.
- **Gross-first, cost-later accounting** (M5) and **construction-invariance** (M8) as
  permanent infrastructure.
- **The honest data-ceiling map** (M6) — knowing precisely which anomalies are
  reproducible on which data, and that CRSP/Compustat is the single highest-leverage
  acquisition.
- What they would **discard:** the price-only momentum signal itself on this dataset —
  weak, insignificant, survivorship-inflated, non-deployable. They would not fund it;
  they would fund the data and the orthogonal factors (roadmap).
