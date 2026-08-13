# M8 — Portfolio Invariance Framework

**Mentisrex Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-05
**Baseline:** M1+M2+M4 (net), M5 dual reporting, M6 audit, M7 liquidity (REJECTED).
**Objective:** invariance, NOT performance — portfolio exposure stable under
reasonable universe-size changes.
**Scope rule:** only portfolio construction changed. No alpha/factor/liquidity/
exchange/market-cap/survivorship change.
**Decision:** ADOPT bounded equal-weight as the standard construction (default OFF;
mandatory for future universe-reducing campaigns).
**Regression:** 597 passed, 2 skipped. Baseline reproduced byte-identical (probe
f≥0.25 and confirm-slack test).

---

## 1. Investigation — why shrinking the universe changes exposures

Root of the incumbent M4 construction (`templates.py`): per-name
`strength = budget/_count`, with `_count = int(quantile · n)`. Everything downstream
follows from `_count ∝ n`:

| Quantity | Dependence on universe `n` | Behaviour as `n` ↓ |
|---|---|---|
| Number of names (decile) | `_count = int(0.10·n)` | shrinks linearly |
| Position sizing | `budget/_count ∝ 1/n` | **rises without bound** |
| Gross exposure | `_count · budget/_count = budget` | invariant (until floor) |
| Net exposure | ~0 in a synchronous snapshot | drifts live (async/cap, engine) |
| **Single-name concentration** | `max_w = budget/_count ∝ 1/n` | **explodes** |
| HHI | `2·_count·(budget/_count)² ∝ 1/n` | explodes |
| Effective leverage | = gross | invariant (until floor) |
| Capacity | ∝ 1/max_w | collapses as weights grow |
| Turnover (realized) | via cap-rejection on big positions | destabilises (see §4) |
| Sector concentration | — | **unmeasurable** (no sector metadata, M6) |

**Finding:** gross leg budget is *already* invariant. The uncontrolled quantity is
**single-name concentration** (max weight, HHI) — and that is exactly the
portfolio-construction-controllable channel M8 targets.

---

## 2. Design candidates (investigated, not optimised)

| Candidate | Verdict | Reason |
|---|---|---|
| Fixed-N portfolio | partial | fixes per-name weight but changes *which* names trade (selection) → drifts toward a factor change; disallowed in spirit |
| Dollar-neutral sizing | subsumed | with the gross budget slack both legs target `budget` → net≈0 already |
| Constant gross exposure | subsumed | leg-budget normalization is the gross-constancy piece |
| Volatility scaling | rejected | needs a covariance estimate (extra state, look-ahead risk); off-target for concentration |
| Risk budgeting | rejected | same covariance dependence; heavier, not the failure channel |
| **Minimum-constituent floor** | **adopted** | de-levers a near-empty leg instead of concentrating |
| **Weight normalization + single-name cap** | **adopted** | bounds max weight / HHI directly |

**Recommended framework — bounded equal-weight** (`portfolio_construction.py`):

```
weight = min( budget / max(count, n_min), w_max )
```

the union of the invariance-relevant candidates: constant-gross normalization +
single-name cap `w_max` + minimum-constituent floor `n_min`. Defaults
`w_max=0.10`, `n_min=10` (conventional risk limits, not tuned to any result).
Deterministic, no look-ahead (depends only on counts known at rebalance `t`).

---

## 3. Experiment — exposure vs universe size (`invariance_probe.json`)

One real M4 US cross-section (785 names), universe shrunk by deterministic,
momentum-unbiased subsampling. Only universe size varies.

| frac | design | univ_n | decile | gross | net | max_w | HHI | eff_lev |
|---|---|---|---|---|---|---|---|---|
| 1.00 | baseline | 785 | 78 | 1.500 | 0 | 0.0096 | 0.0144 | 1.500 |
| 1.00 | invariant | 785 | 78 | 1.500 | 0 | 0.0096 | 0.0144 | 1.500 |
| 0.50 | baseline | 392 | 39 | 1.500 | 0 | 0.0192 | 0.0289 | 1.500 |
| 0.50 | invariant | 392 | 39 | 1.500 | 0 | 0.0192 | 0.0289 | 1.500 |
| 0.25 | baseline | 196 | 19 | 1.500 | 0 | 0.0395 | 0.0592 | 1.500 |
| 0.25 | invariant | 196 | 19 | 1.500 | 0 | 0.0395 | 0.0592 | 1.500 |
| 0.10 | baseline | 78 | 7 | 1.500 | 0 | **0.1071** | **0.1607** | 1.500 |
| 0.10 | invariant | 78 | 7 | 1.050 | 0 | 0.0750 | 0.0788 | 1.050 |
| 0.05 | baseline | 39 | 3 | 1.500 | 0 | **0.2500** | **0.3750** | 1.500 |
| 0.05 | invariant | 39 | 3 | 0.450 | 0 | 0.0750 | 0.0338 | 0.450 |
| 0.02 | baseline | 15 | 1 | 1.500 | 0 | **0.7500** | **1.1250** | 1.500 |
| 0.02 | invariant | 15 | 1 | 0.150 | 0 | 0.0750 | 0.0113 | 0.150 |

**Invariance result:**
- Baseline max single-name weight **0.96% → 75%** (×78); HHI ×78 → total
  concentration in one name at extreme shrink.
- Invariant max weight **0.96% → 7.5%** (×7.8); HHI bounded ≤0.079. Below the
  n_min floor it **de-levers gross** (1.5→0.15) rather than concentrating — the book
  shrinks its footprint, never bets the farm.
- **Baseline == invariant exactly for f ≥ 0.25** → baseline preserved whenever the
  universe is not severely reduced (and byte-identical at f=1.0).

**Crossover ≈ f 0.10** (universe < ~78 names, decile < ~8). Honest consequence:
M7's 20% liquidity shrink was *above* this crossover (max weight only ~1.2% there),
so **M7's −116% blow-up was NOT snapshot concentration** — it had async-vintage /
leg-composition / leverage-cap drivers that are engine-level and frozen (out of M8
scope). M8 bounds the concentration channel — the construction-controllable
invariance guarantee — which protects against *severe* universe reduction.

---

## 4. End-to-end confirmation & risk analysis (`us_jt_m8_confirm.jsonl`)

Certified M4 on a 5%-shrunk US universe (50 names, decile ~5), varying ONLY
construction:

| Metric | baseline | invariant |
|---|---|---|
| IS Sharpe | −0.4703 | −0.1451 |
| OOS Sharpe | −0.8600 | +0.0687 |
| OOS Return | −54.06% | +20.17% |
| **OOS Max Drawdown** | **−77.63%** | **−21.88%** |
| OOS Trades (turnover proxy) | 19 | 229 |
| Adjusted p | 1.000 | 0.447 |

**Risk reading:** baseline concentrates the decile into ~5 positions at ~15% NAV
each; the 1.5× leverage cap then rejects most orders (only **19 trades**) and the
few that clear form an undiversified, cap-truncated book → **−77.6% drawdown**. The
invariant framework caps/floors weights (~7.5%, de-levered gross) so orders fit under
the cap and the book diversifies (**229 trades**) → **drawdown −77.6% → −21.9%**. The
+20% return is a *byproduct* of not blowing up, not the objective — the objective is
the bounded exposure/DD, achieved.

---

## 5. Regression report

- Full suite: **597 passed, 2 skipped** (added
  `test_invariant_construction_preserves_baseline_and_bounds_concentration`).
- **Baseline unchanged:** invariant construction with slack bounds reproduces the M4
  equity curve point-for-point (test) and equals baseline for all f ≥ 0.25 (probe).
- Determinism: confirmed (deterministic weight map; re-runnable probe/confirm).
- No look-ahead: weights depend only on rebalance-time counts.

---

## 6. Decision log

**Recommend — bounded equal-weight (M8 invariant construction) — as the standard
portfolio-construction framework for all future universe-reducing methodology
campaigns** (exchange filters, market-cap filters, survivorship corrections,
liquidity screens). Rationale, against the success criteria:

| Success criterion | Met? | Evidence |
|---|---|---|
| Approximately constant exposure | ✅ | gross constant while slack; graceful de-lever below floor (§3) |
| Avoid concentration explosions | ✅ | max weight ×7.8 vs ×78; DD −78%→−22% (§3,§4) |
| Deterministic | ✅ | pure count→weight map |
| Baseline preserved when no reduction | ✅ | identical f≥0.25; byte-identical at f=1.0; test |
| No look-ahead | ✅ | rebalance-time counts only |
| Pass all regression | ✅ | 597 passed, 2 skipped |

**Default remains OFF** so the currently-certified M1+M2+M4 runs are unchanged;
future campaigns that shrink the universe **must** enable
`invariant_construction=True`. No baseline promotion of the strategy itself — M8 is a
construction-layer standard, like M5 was a reporting standard.

---

## 7. Known limitations / Skipped (CLAUDE.md)

- **Net-exposure drift & M7's moderate-shrink blow-up** — not fixed here. *Reason:*
  driven by async per-symbol rebalance vintages + integer-share leverage-cap
  rejection, which are **engine-level** (frozen; M8 scope is construction only).
  *Unblock:* synchronous portfolio-level rebalance + dollar-hold sizing (the M3
  unblock). M8 bounds the concentration channel it owns.
- **Capacity** — reported only qualitatively (∝ 1/max_weight → invariant framework
  has higher capacity). *Reason:* no capacity/ADV-participation model in the frozen
  platform. *Unblock:* a capacity module (ADV × participation cap).
- **Sector concentration** — not computed. *Reason:* no sector/industry metadata
  (per M6). *Unblock:* CRSP/Compustat classification (SIC/GICS).
- **Bounds not swept** — `w_max=0.10`, `n_min=10` are single conventional
  risk-limit values, deliberately not optimised (sweeping would be tuning).

---

## 8. Certification

| Condition | Status |
|---|---|
| Framework implemented | ✅ (`portfolio_construction.py` + wired) |
| Default OFF | ✅ (`invariant_construction=False`) |
| Controlled experiments run | ✅ (probe all levels + confirm end-to-end) |
| Baseline unchanged | ✅ (f≥0.25 identical; test byte-identical) |
| Regression pass | ✅ (597 passed, 2 skipped) |
| Decision supported by evidence | ✅ ADOPT (§3,§4,§6) |

**M8 CERTIFIED — ADOPT bounded equal-weight as the standard construction (default
OFF; mandatory for universe-reducing campaigns).** STOP — M9 not begun.
