# Methodology Fidelity — Pairs Trading Campaign

**Mentisrex Capital — Workstream C**
**Date:** 2026-08-04
**Scope:** how faithfully the frozen `PairsStrategy` / `MultiPairStrategy` +
`select_pairs` reproduce the canonical Gatev (2006) construction, every deviation
named, ranked, and classified. **No deviation is "fixed" here** — this is the gap
register that governs which engineering is (not) authorized under the freeze.

## 1. Construction map — Gatev vs Mentisrex

| Step | Gatev 2006 | Mentisrex frozen | Faithful? |
|---|---|---|---|
| Universe | liquid CRSP common stock | complete-history-in-formation, top-300 by formation dollar-volume | ✓ (liquidity screen equivalent) |
| Normalization | cumulative **total-return** index | cumulative **price** index (close) | partial — no dividends in panel |
| Distance | SSD of normalized paths | SSD of normalized paths | ✓ exact |
| Formation window | 12 months | 252 trading days | ✓ exact |
| Selection | top 20 (+5, +101–120 control) | top-N (5 / 20 / 40) | ✓ |
| Hedge ratio | ≈1 (both normalized to 1) | scale-balance `mean(px_x)/mean(px_y)` | approx |
| Spread object | **normalized-price** spread | **raw price** spread, z-scored | approx (P1) |
| Entry | 2 SD divergence | `entry_z` (2.0) | ✓ exact |
| Exit | convergence (cross 0) | `exit_z` band (0.5) | approx (P2) |
| Trading window | 6 months, **rolling monthly** | single 70/30 chronological OOS split | gap (P3) |
| Force close | end of 6-mo window | none (holds across split) | gap |
| Wait-one-day | trade next day's price | immediate fill at close | gap (P4) |
| Costs | gross **and** net, conservative | engine commission, net only | partial |
| Sizing | committed capital / fully invested | fixed `max_position_pct` (5%/leg), gross cap 1.5× | gap (P5) |

## 2. Ranked fidelity gaps (classification per stopping rules)

Classes: **A** platform defect (only this authorizes engineering) · **B**
methodology difference · **C** data limitation · **D** market evolution · **E**
statistical variation.

1. **P3 — single 70/30 split vs rolling monthly re-formation.** *Class B (highest
   impact).* Gatev re-selects pairs every month over 6-month books; Mentisrex picks
   the top-N **once** on the first 12 months and trades them for ~11 years. Pairs
   decay (co-integration breaks), so a static book is a *pessimistic* bound — it
   biases against reproduction. **Unblock:** a walk-forward re-formation harness
   (research-layer, deferred under freeze).
2. **P1 — raw-price spread vs normalized-price spread.** *Class B.* The template
   z-scores the scale-balanced raw spread; Gatev z-scores the normalized-cumulative
   spread. The `hedge = mean(x)/mean(y)` scale-balance approximates it; residual
   entry/exit timing drift remains. **Unblock:** a normalized-spread mode in the
   template.
3. **P5 — fixed 5%/leg sizing + 1.5× gross cap vs committed-capital.** *Class B
   (same M3 interaction as the momentum campaign).* 20 pairs × 2 legs × 5% = 200%
   nominal gross vs a 1.5× cap → the risk engine truncates the book to ~15 legs
   (~7 pairs). Pairs are dollar-balanced so **net** exposure ≈ 0, but the gross cap
   still limits how many pairs express. Uniform across markets; documented, not a
   defect. Cross-referenced: `../momentum/Leverage_Investigation.md`.
4. **P2 — exit band (0.5 SD) vs exact convergence (0).** *Class B.* A 0.5-SD exit
   closes slightly early; the `exit_0.25` grid config probes sensitivity.
5. **P4 — no wait-one-day / immediate close fill.** *Class B (small).* Removes
   Gatev's bid-ask-bounce guard; on daily close data the bounce bias is already
   minimal. Low priority.
6. **Total-return vs price normalization.** *Class C (data).* Panel has no dividend
   stream; distance is computed on price, not total-return, index. Affects
   dividend-heavy pairs' selection. **Unblock:** dividend-adjusted price panel.
7. **Force-close at window end.** *Class B (minor).* Folded into P3 — irrelevant
   without rolling windows.

## 3. What is faithful (do NOT touch)

- **SSD distance selection over a 12-month formation window** — exact Gatev.
- **2-SD entry, convergence exit, top-N portfolio** — exact Gatev trading rule.
- **Leak-safe formation/trading separation** — pairs chosen only from formation
  dates; IS/OOS split is chronological; `ctx.history` never looks ahead.
- **Market-neutral book** — one long + one short leg per pair, dollar-balanced.

## 4. Engineering authorization (stopping rules)

**None authorized.** No Class-A platform defect is identified — every gap is B
(methodology) or C (data). Per the stopping rules, engineering is permitted only
for a defect that is reproduced, isolated, measurable, minimal, and
regression-tested. The ranked B/C items are **research-layer fidelity upgrades**
for a future un-frozen phase, not engine changes:

1. Walk-forward rolling re-formation harness (P3).
2. Normalized-/cointegration-spread selection mode (P1, + Vidyamurthy).
3. Committed-capital / equal-weight-within-budget sizing (P5).
4. Dividend-adjusted (total-return) price panel (P6, data).

## Known limitations / Skipped
- **No fidelity gap is implemented in this campaign.** *Reason:* platform frozen;
  all gaps classify B/C, none A. *Unblock:* explicit un-freeze + the specific
  research-layer additions above. Recorded, not silently skipped.
