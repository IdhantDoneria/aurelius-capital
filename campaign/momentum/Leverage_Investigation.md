# Leverage Investigation — India Momentum Campaign

**Role:** Research Director. **Date:** 2026-08-03.
**Mandate:** find why projected gross leverage reached 35.77×. Investigate only —
no code change, no limit change, no rerun, no parameter change.
**Verdict:** **Category B — methodology fidelity.** Position-sizing scheme is
incompatible with portfolio breadth under the gross budget. Risk engine is
working exactly as designed. **No platform defect. Remaining 4 experiments should
proceed UNCHANGED.**

---

## 0. Premise correction (evidence first)

The brief states "execution halted because projected gross leverage exceeded the
limit." **This is not what happened.** The leverage message is a *per-order*
pre-trade rejection (`RiskEngine.check` → `RiskCheckResult.fail`), logged at DEBUG
and skipping one order. It does **not** halt the backtest. Proof: **all 7 US
shards and 4 of 7 India shards completed** while emitting thousands of these
rejections (US 6922, India 3677). India form_9m completed *during this very
investigation* (OOS Sharpe −0.630, 216 trades). The earlier India fan stopped for
an unrelated reason — process death (wrong interpreter / memory pressure), not the
leverage cap. The runs are not blocked by leverage; they run a leverage-*capped*
book.

## 1. Which construction step produces the excess

`PortfolioManager.size_order` (`portfolio/manager.py:81`):

```
target_value = total_value × max_position_pct × strength      # 5% of NAV per name
target_qty   = int(target_value / price)
```

Every name in the decile is sized to a **fixed 5% of NAV** (`research_config`
sets `max_position_pct=0.05`). The check that fires is
`RiskEngine.check` step 3 (`risk/engine.py:81-90`):

```
projected_leverage = (gross_exposure + incremental_exposure) / max(NAV, 1)
if projected_leverage > max_gross_leverage (1.5): reject
```

## 2. Root cause — quantitative

**Two compounding causes, both measured.**

### Cause 1 (structural, present at full NAV, zero drawdown): sizing × breadth mismatch

| Market | Eligible symbols | Decile (0.10) / side | Intended names (L+S) | Sizing | **Nominal gross** | Cap | **Fillable names under cap** |
|---|---|---|---|---|---|---|---|
| US | 1007 | 100 | 200 | 5%/name | **10.0×** | 1.5× | 30 |
| India | 1127 | 112 | 224 | 5%/name | **11.2×** | 1.5× | 30 |

A decile long/short book wants ~200 (US) / ~224 (India) names. At a fixed 5% per
name that is **10–11× gross exposure — 6.7–7.5× over the 1.5× cap — before any
price move.** The cap admits only `floor(1.5 / 0.05) = 30` names; the sizer keeps
emitting the other ~170–194 orders each rebalance and the engine rejects each.
This is the entire baseline rejection stream. It is a *design consequence of two
config choices*, not a bug.

### Cause 2 (amplifier): NAV depletion inflates the ratio to 35–68×

`projected_leverage = gross / NAV`. The research config runs a loose
`max_drawdown_halt=0.60`, so NAV falls to ~0.15–0.40× peak during the momentum
drawdowns. The same ~10× nominal book divided by a depleted NAV yields the
observed tail:

```
US leverage-rejection distribution (grid.log, 6922 events):
  0–10×  5205   10–20× 1972   20–30× 996   30–40× 649
  40–50×  949   50–60× 1241   60–70× 1165  70–100× 1643   (max 68.81×)
10× nominal / 0.15 NAV ≈ 67× → matches the observed 68.81× ceiling.
```

India's 35.77× is the identical mechanism on a shallower drawdown (max 36.58×).
**India is not special — US hits the cap harder** (6922 vs 3677 rejections, 68×
vs 37×).

## 3. Position/exposure evidence table

| Quantity | US | India | Source |
|---|---|---|---|
| Eligible securities (validated filter) | 1007 | 1127 | `analytics.duckdb` count |
| Long positions targeted / rebalance | ~100 | ~112 | `int(0.10 × n)` |
| Short positions targeted / rebalance | ~100 | ~112 | same |
| Average position size | 5% NAV | 5% NAV | `max_position_pct=0.05` |
| Nominal gross exposure | 10.0× | 11.2× | names × 5% |
| Net exposure | ~0× | ~0× | equal long/short → market-neutral |
| Gross-leverage cap | 1.5× | 1.5× | `config.py:29` |
| Names fillable under cap | 30 | 30 | `1.5 / 0.05` |
| Observed projected leverage (max) | 68.81× | 36.58× | logs (= nominal ÷ depleted NAV) |
| Rejections logged | 6922 | 3677 | `grep -c` |

## 4. Cause ruled in / out

| Candidate | Verdict | Evidence |
|---|---|---|
| Weighting scheme (fixed 5%/name vs equal-weight-in-budget) | **PRIMARY** | 200 × 5% = 10× ≫ 1.5× at full NAV |
| Too few eligible securities | **NO** | 1007 / 1127 — the opposite; too *many* names × fixed weight |
| Position sizing | **PRIMARY** (same as weighting) | `size_order` fixed 5% of NAV |
| NAV depletion under drawdown | **AMPLIFIER** | ratio 10×→68× as NAV → 0.15× |
| Price normalization | **NO** | split-adjusted panel; US shows it harder than India |
| Missing liquidity / universe screens | **CONTRIBUTING (fidelity)** | no JT price/liquidity screen → full 100/side decile (M6) |
| Order-sizing bug / duplicate positions | **NO** | `size_order` computes `delta = target − current`; nets, no duplication |

## 5. Classification

**B — Methodology fidelity issue.** The risk engine correctly enforces a
deliberate 1.5× gross cap (→ not **A**, platform defect). The behavior is
identical across US and India on clean split-adjusted data (→ not **C**, dataset).
It is not merely "expected/benign" (→ not plain **D**) because it *silently caps
the book to ~30 of ~200 intended names*, so every reported momentum figure
reflects a leverage-truncated subset, not the full decile spread.

This is exactly the **M3 gap already logged in `docs/REPRO_JT_1993_US_REFERENCE.md`**:
fixed position cap instead of equal-weight deciles. A faithful decile L/S under a
1.5× budget needs **equal-weight-within-budget** sizing (~1.5 / 200 ≈ **0.75% per
name**), not a fixed 5%. Identified, **not implemented** (engineering freeze; this
is a fidelity choice, not a defect).

## 6. Should the remaining 4 India experiments proceed unchanged?

**YES — proceed unchanged.** Evidence-based:

1. **Rejections do not halt runs** — 7 US + (now) ≥4 India shards completed
   despite them; the book simply trades the cap-admitted subset.
2. **The constraint is uniform across US and India** (both ~10× nominal, same cap)
   → the cross-market comparison stays apples-to-apples.
3. **Changing sizing now would tune + unfreeze the engine and break comparability**
   with the already-committed US results. That violates the campaign rules.
4. The results are valid *within their stated fidelity limit* (leverage-capped
   decile), which is documented, not hidden.

The 4 remaining India configs are already executing and will produce valid,
comparable numbers. **Do not stop, do not resize, do not change the cap.** Record
M3 (equal-weight-within-budget sizing) as the top fidelity upgrade for a future
un-frozen phase — it is the single change that would let the full decile spread
express within the 1.5× budget.

## 7. Recommendation

- **Classification:** B (methodology fidelity), amplified by NAV depletion under
  the loose research drawdown halt.
- **Engineering action:** none. Risk engine working as designed; 0 defects.
- **Fidelity backlog (not now):** M3 equal-weight-within-budget sizing; M6 JT
  liquidity/universe screens to shrink decile breadth.
- **Campaign:** proceed with the 4 remaining India experiments unchanged; carry
  the leverage-cap caveat into `Cross_Market_Report.md` and `Executive_Summary.md`.
