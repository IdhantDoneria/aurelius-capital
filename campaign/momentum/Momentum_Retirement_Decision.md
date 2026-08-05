# Momentum Retirement Decision

**Aurelius Capital — Momentum Campaign, Phases 2–4 (M11)**
**Date:** 2026-08-05. Archival synthesis; no code, no new experiments.
**Decision: ARCHIVE.** The hypothesis is rejected; research retired.

---

## Phase 2 — Falsification analysis (Popper)

**Hypothesis H:** *"Cross-sectional price momentum on the current 2014–2026 Yahoo
price-only dataset is a deployable source of alpha."*

A scientific claim is retained only while it survives genuine attempts to falsify it.
H makes a risk-bearing prediction: a faithfully constructed momentum L/S book should
show **positive, significant, deployable** returns.

### Evidence *supporting* H
- US JT WML **+58.8%** directional over one OOS slice (M-prior).
- M4: the JT skip **improved** OOS risk-adjusted return (Sharpe +0.098→+0.112) and cut
  turnover — the mechanism behaves as the literature predicts.
- India long-only decile **significant** (+416%, p 0.026).

### Evidence *against* H
- **0/14** configs significant at α=0.05 (best adj p ~0.15).
- **M5: gross OOS return is NEGATIVE (−23.76%)** — with *zero* transaction costs.
- **M10: continuous deployment ruins** (>100% drawdown); the only risk-controlled
  (liquidity-filtered) configs are **negative** (−10% → −42%); cost drag (~4pp) is
  trivial versus an −81.5% gross loss.
- Survivorship bias *inflates* the current book (L8/L17), yet it is still negative —
  the true (survivorship-free) figure is lower.

### Direct falsifiers of H
1. **M5 gross OOS negative.** "Deployable *alpha*" requires positive gross return
   before costs. There is none OOS. This alone falsifies the alpha claim.
2. **M10 deployment ruin + negative liquidity-filtered returns.** Falsifies
   "deployable."
3. **0/14 significance.** Falsifies "a source of alpha" in the statistical sense.

### Inconclusive observations
- India long-only significance — **confounded** (bull-regime beta + survivorship +
  long-only ≠ the momentum factor). Cannot confirm *or* cleanly falsify H; excluded
  as non-probative.
- US +58.8% directional slice — real but **insignificant** and non-deployable;
  suggestive, not confirmatory.

### Verdict
**H does not survive.** Every risk-bearing prediction failed: no positive gross alpha
OOS, no significance, no deployable configuration. The supporting evidence is either
insignificant (US slice) or confounded (India long-only). **H is falsified for this
dataset.**

---

## Phase 3 — Remaining uncertainty (can it reverse the conclusion?)

| Category | Unknown | Expected direction | Magnitude | P(reverses conclusion) |
|---|---|---|---|---|
| **A — cannot reverse** | Transaction costs | already measured (~4pp) | small | ~0.00 |
| A | Portfolio construction | solved (M8), alpha unchanged | none on alpha | ~0.00 |
| A | Engine timing / data alignment | no defect/leakage (M9) | none | ~0.00 |
| A | Cap logic | amplifier not root (M9) | none on alpha | ~0.00 |
| **B — could moderate** | Point-in-time universe | removes look-ahead in membership | small | ~0.02 |
| B | Historical constituents / survivorship | **lowers** performance (delisted losers absent → WML inflated now) | tens of pp, **wrong direction** | ~0.01 |
| B | Corporate-action adjustment errors | noise, ± | small | ~0.03 |
| **C — different datasets (other hypotheses)** | Fundamentals, quality, value, profitability | N/A to *price* momentum | — | 0 (different factor) |
| C | Analyst revisions, earnings, macro, alt-data | N/A to *price* momentum | — | 0 (different factor) |

**Reading:** Category-A unknowns are resolved and cannot reverse. Category-B unknowns
point the **wrong way** — the biggest (survivorship) makes momentum *worse*, not
better, so correcting it strengthens the REJECT; combined P(reverse) ≲ 0.05.
Category-C unknowns belong to **different alpha hypotheses** (the roadmap), not to H —
they cannot rescue *price momentum*. **No credible path to reversal.**

---

## Phase 4 — Retirement decision

**ARCHIVE.** All three ARCHIVE conditions hold:

1. **Internally consistent** — no campaign contradicts another (Evidence Summary §2);
   the two apparent contradictions resolve to confound + evaluation-basis.
2. **No unresolved platform defect** — M9 certified 0 engine defects, no leakage,
   deterministic; 0 defects across the entire M1–M10 program.
3. **Remaining unknowns unlikely to overturn** — Category A ~0, Category B
   wrong-direction (≲0.05), Category C different-hypothesis.

**CONTINUE is not justified** — there is no specific unresolved uncertainty with
credible evidence it could reverse the conclusion (the strongest, survivorship, would
*worsen* momentum). Retiring the momentum hypothesis on this dataset is the
evidence-driven call, not a resource decision.

**Retirement scope:** cross-sectional **price** momentum on the 2014–2026 price-only
panel is retired. This does NOT retire: the platform (proven, 0 defects), the adopted
standards (M2 screen, M4 skip, M5 dual reporting, M8 bounded construction), or other
alpha families (see Future Roadmap — a fresh momentum test on CRSP/point-in-time data
with fundamentals is a *different* hypothesis and remains open there).
