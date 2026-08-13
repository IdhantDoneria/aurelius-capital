# M10 — Capacity & Liquidity Deployability Audit

**Mentisrex Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-05
**Type:** deployability audit. Frozen: signal / factor / portfolio-construction rule /
data pipeline / benchmark. Varied only: execution assumptions (rebalance cadence,
costs), liquidity constraints, capital scaling. **No product-code change** (analysis
scripts only; 597 passed, 2 skipped).
**Strategy under audit:** corrected = M4 + M8 invariant construction
(`FactorStrategy(lookback=126, quantile=0.10, rebalance_days=21, allow_short=True,
equal_weight=True, min_price=5.0, skip=21, invariant_construction=True)`,
`max_position_pct=1.0`).
**Decision:** **REJECT** — alpha does not survive realistic execution.

---

## 1. Hypothesis

*Does the corrected strategy retain economically meaningful alpha after liquidity,
turnover, and scaling constraints?* Evaluation basis: `run_backtest` **full-sample**
(single continuous capital pool, 2014–2026) — the realistic deployment scenario (you
deploy once and run, you do not reset capital each slice as the certified `investigate`
IS/OOS split does). US canonical for Phases 1/2/4; India ₹ for Phase 3 capacity.

---

## 2. Phase 1 — Turnover audit (US, full universe)

Turnover reduced via **rebalance cadence** (execution assumption; construction rule
unchanged). `total_return` and `max_drawdown` are curve-real; ratio metrics on these
configs are **degenerate** (equity breaches 100% → crosses zero → sharpe/sortino/vol
go complex — themselves a deployability red flag, reported as DEGEN).

| rebalance | ann. turnover | trades | avg hold (d) | total return | max DD | status |
|---|---|---|---|---|---|---|
| 21d (base) | 1.406 | 1540 | 94.3 | −83.2% | **−152.0%** | DEGEN |
| 28d | 1.387 | 818 | 94.1 | −183.9% | **−216.1%** | DEGEN |
| 42d | 0.788 | 740 | 114.6 | −19.4% | **−115.1%** | DEGEN |
| 84d | 0.501 | 251 | 150.2 | +24.3% | **−134.1%** | DEGEN |

**Finding:** cadence mechanically cuts turnover (1.41 → 0.50) and trade count
(1540 → 251) and lengthens holding (94 → 150d), as intended. But **every cadence
still breaches 100% drawdown** — the full-universe book runs equity through zero
regardless of turnover. Turnover reduction does not make it deployable.

---

## 3. Phase 2 — Liquidity constraints (US, median-$vol screen + M8 construction)

| bucket (drop bottom) | CAGR | Sharpe | max DD | ann. turnover | trades | status |
|---|---|---|---|---|---|---|
| 0% (full) | — | — | **−152%** | 1.406 | 1540 | DEGEN (ruin) |
| 25% | −2.9% | +0.040 | −60.7% | 2.086 | 241 | clean |
| 50% | −9.4% | +0.012 | −62.7% | 2.305 | 91 | clean |
| 75% | −16.1% | −0.084 | −69.1% | 2.081 | 47 | clean |
| | total ret −10.3% / −23.4% / −42.3% respectively | | | | | |

**Finding:** liquidity filtering shrinks the universe enough that the **M8 bounded
construction binds and de-levers** → the book stops breaching 100% DD (−61% to −69%,
risk-controlled). But **returns are negative and worsen monotonically with a tighter
filter** (−10% → −42%). The deployable (liquidity-controlled) universe has **no
alpha**. (It also *raises* turnover to ~2.1–2.3× — the thin filtered book churns
more.)

---

## 4. Phase 3 — Capacity scaling (India ₹, analytic) — `capacity_india.json`

India eligible universe 1075 names, decile 107, per-name weight **0.70%** (M8
invariant, cap slack). Median daily ₹-volume **₹3.25cr**; 10th-percentile
(least-liquid held) name **₹0.029cr/day**.

| Portfolio | per-name position | ADV% (median name) | ADV% (p10 name) | tier (p10) |
|---|---|---|---|---|
| ₹10L | ₹0.001cr | 0.02% | 2.41% | moderate |
| ₹50L | ₹0.004cr | 0.11% | 12.1% | hard |
| ₹1cr | ₹0.007cr | 0.22% | 24.1% | hard |
| ₹5cr | ₹0.035cr | 1.08% | 120.7% | infeasible |
| ₹10cr | ₹0.070cr | 2.16% | 241% | infeasible |
| ₹50cr | ₹0.350cr | 10.8% | 1207% | infeasible |
| ₹100cr | ₹0.701cr | 21.6% | 2414% | infeasible |

**Capacity ceiling (≤10% ADV):** ₹**46.4cr** if only the *median* decile name must
clear, but ₹**0.41cr** once the *illiquid decile tail* must trade. The equal-weight
decile forces holding very illiquid names → capacity is bound to **~₹0.4cr** unless
those names are dropped — i.e. unless you liquidity-filter, which (Phase 2) turns the
return negative. Capacity and alpha are in direct conflict.

---

## 5. Phase 4 — Cost integration (US, full universe)

Config-only cost sweep [commission/spread/slippage bps]. Full-universe path is DEGEN
(ruin); `total_return` real.

| scenario | bps (c/s/sl) | total return | Δ vs gross (cost drag) |
|---|---|---|---|
| gross | 0/0/0 | −81.54% | — |
| low | 5/5/10 | −83.26% | −1.7 pp |
| mid | 10/10/25 | −84.26% | −2.7 pp |
| high | 20/20/50 | −85.68% | −4.1 pp |

**Finding:** total cost drag across the whole realistic range is **~4 pp** — trivial
against an **−81.5% gross** loss. Removing *every* execution cost still ruins the
book. **Costs are not what kills the strategy; there is no gross alpha to kill.**
Consistent with M5 (full-universe gross OOS already −23.76%).

---

## 6. Decision — REJECT

*ADOPT iff positive after realistic costs AND capacity supports meaningful deployment
AND liquidity constraints don't destroy the edge.* All three fail:

1. **Not positive after costs** — full-universe continuous deployment breaches 100%
   drawdown (ruin) at every cadence and cost; gross is −81.5% (Phase 1, 4). The only
   risk-controlled configs (liquidity-filtered, Phase 2) are **negative** (−10% to
   −42%). Cost drag (~4 pp) is immaterial — there is no gross alpha to preserve.
2. **Capacity conflicts with alpha** — the equal-weight decile's illiquid tail caps
   ₹ capacity at ~₹0.4cr; escaping it requires liquidity filtering, which makes the
   return negative (Phase 2/3).
3. **Liquidity constraints destroy the (already-absent) edge** — tighter filter →
   more negative return, monotone.

**→ Alpha disappears under realistic execution. REJECT.** The strategy is not
deployable. This is coherent with the whole campaign: 0/14 configs significant,
M5 gross OOS negative, momentum decayed to 2014–2026 US even before the
survivorship correction (which would lower it further).

**Scope note:** REJECT is the *deployability* verdict for this price-only momentum
book on the available data. It is not a platform defect (M9: 0 engine defects) nor a
retraction of M1–M9 (framework/construction/reporting all stand). M8 bounded
construction still correctly prevents the concentration-driven ruin *on shrunk
universes* — it just cannot manufacture alpha that isn't there.

---

## 7. Limitations / DEFER (CLAUDE.md)

- **Full-sample ratio metrics on ruined configs** — sharpe/sortino/vol go complex
  once equity ≤ 0; only `total_return`/`max_drawdown` are reported for DEGEN configs.
  The >100% DD itself reflects the sim allowing negative equity (no ruin-stop); a real
  broker liquidates at ruin — outcome (total loss) is the same. *Unblock:* a
  ruin/margin-halt in the engine (frozen).
- **PIT / survivorship** — DEFERRED (no as-of-date/delisting data, M6/M9). Biases
  performance **upward**, so a corrected universe strengthens the REJECT, never
  reverses it — hence a full DEFER of the verdict is not warranted.
- **Sector-neutral capacity** — no sector metadata (M6). Skipped.
- **Cost × liquidity interaction & deployment-currency alpha (India)** — not run;
  the full-universe gross is already negative and the liquidity-filtered gross is
  already negative, so the interaction cannot rescue it. *Unblock:* only worth
  running if a positive-gross configuration is first found.

---

## 8. Certification

| Requirement | Status |
|---|---|
| Turnover audit | ✅ (Phase 1) |
| Liquidity constraints | ✅ (Phase 2) |
| Capacity scaling | ✅ (Phase 3, India ₹) |
| Cost integration | ✅ (Phase 4) |
| Decision evidence-backed | ✅ **REJECT** |
| Frozen surfaces untouched / regression | ✅ 597 passed, 2 skipped |

**M10 CERTIFIED — REJECT (not deployable; alpha absent under realistic execution).**
STOP — M11 not begun.
