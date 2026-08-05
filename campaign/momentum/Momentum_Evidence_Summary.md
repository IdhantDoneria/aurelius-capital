# Momentum Evidence Summary (M1–M10)

**Aurelius Capital — Momentum Campaign, Phase-1 synthesis (M11)**
**Date:** 2026-08-05. Archival — no code, no new runs. Reproducibility re-verified
(M9 byte-identical; 597 passed, 2 skipped).

## 1. Certified-result table

| Campaign | Question | Evidence (measured) | Decision | Confidence |
|---|---|---|---|---|
| M1 | Does equal-weight decile construction express the JT book? | OOS Sharpe −0.687, 848 trades, adj p 1.000 (baseline) | Baseline set | HIGH |
| M2 | Does the JT-2001 $5 price screen help? | OOS Sharpe −0.687→**+0.098**, trades 848→672, p 0.424 | **KEEP** | HIGH |
| M3 | Do JT-1993 overlapping K=6 cohorts help? | OOS Sharpe +0.006, trades 4781, p 0.495; engine NAV-% vs dollar-hold gap | **BLOCKED** (engine, not defect) | HIGH |
| M4 | Does the JT-1993 1-month skip help? | OOS Sharpe +0.098→**+0.112**, turnover −12% (672→593), p 0.413 | **KEEP** | HIGH |
| M5 | Gross (JT) vs net (production) reporting? | Gross OOS **−23.76%** vs net −24.84%; cost wedge ~1.08pp | **KEEP** (dual-basis) | HIGH |
| M6 | What universe methodology is reproducible? | Panel = prices+volume only; survivorship 9/2143 (0.4%); CRSP = unblock | Audit (data-blocked rows documented) | HIGH |
| M7 | Does a liquidity screen improve deployability? | OOS **−95.85% / −115.87% DD** blow-up; Sharpe/p up optically | **REJECT** | HIGH |
| M8 | Can construction be made universe-invariant? | Max weight ×78→×7.8 under shrink; DD −77.6%→−21.9% at 5% shrink | **ADOPT** bounded construction | HIGH |
| M9 | Is the M7 anomaly an engine defect? | Byte-identical repro; no leakage (T+1 fills); cap/async amplifiers not root | **REJECT** (no defect) | HIGH |
| M10 | Does the corrected strategy survive deployment? | Full-universe continuous **>100% DD ruin**; liquidity-filtered −10/−23/−42%; cost drag ~4pp vs −81.5% gross; ₹ capacity ceiling ₹0.4cr (illiquid tail) | **REJECT** (not deployable) | HIGH |

**Prior-campaign context (pre-M numbering, same panel):** 14 momentum runs (7 US + 7
India), **1/14 significant** — India long-only decile (+416%, Sharpe 1.012, **p
0.026**); US JT WML +58.8% directional but **insignificant** (p 0.161). Pairs
campaign (Gatev): **0/14** significant.

## 2. Consistency / contradiction audit

Two apparent contradictions; both resolve — no genuine conflict.

**(a) India long-only "significant" (p 0.026) vs the overall REJECT.**
- *Resolution:* it is **confounded**, not a momentum-alpha signal. (i) Long-only =
  net market beta in a single 2014–2026 Indian **bull regime**, not the momentum L/S
  factor; (ii) **survivorship-inflated** (currently-listed panel, L8/L17); (iii) the
  actual momentum *factor* (L/S WML) was negative/insignificant in India and every US
  config. A confounded long-only beta result does not contradict "price-momentum L/S
  is not deployable alpha."

**(b) US JT WML +58.8% (directional positive) vs M10 −81.5% (ruin).**
- *Resolution:* **different evaluation bases**, not a conflict. +58.8% is a single
  30% OOS *slice* with fresh capital at one config, and **statistically insignificant**
  (p 0.161). −81.5% is the **continuous single-capital 2014–2026** deployment sim
  (M10). A weak, insignificant directional slice that does not survive continuous
  deployment or costs is the *same* coherent story: fragile, insignificant,
  non-deployable.

**No campaign contradicts another.** Every KEEP (M2, M4) improved *risk-adjusted*
construction fidelity without ever clearing significance; every REJECT (M7, M9, M10)
and the M3 BLOCK are consistent with a weak, insignificant, non-deployable factor on
this dataset. Platform defects across the entire program: **0**.

## 3. One-line synthesis

Sequential fidelity (M1–M4) improved the *construction* of the JT book; M5 showed the
**gross** result is already negative OOS; M6 bounded what the data can reproduce; M7–M9
proved the failures are construction/behavior not engine defects; M8 fixed the
controllable (concentration) channel without creating alpha; M10 showed the corrected
book is undeployable. The edge is absent, not hidden.
