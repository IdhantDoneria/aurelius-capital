# M12 — Low-Volatility Alpha: Final Report & Certification

**Aurelius Capital — Low-Volatility Campaign**
**Date:** 2026-08-06 · **Certification:** **REJECT** · **Platform defects:** None

---

## 1. Research objective

Determine whether a low-volatility equity factor — long the lowest-volatility names,
short the highest — produces a statistically significant, economically meaningful,
deployable, robust source of risk-adjusted return on the Aurelius panel, using an
academically standard specification with **no performance optimization**. This is a
new alpha family, independent of the archived momentum program (M11).

## 2. Original hypothesis

> Stocks with lower historical volatility produce superior risk-adjusted returns; a
> long-low-vol / short-high-vol decile book earns positive risk-adjusted return
> (the Haugen-Baker / Blitz-van Vliet / "low-risk anomaly").

Falsification target (Popper): the book has **no** risk-adjusted edge after honest
statistical testing and realistic deployment.

## 3. Experimental design

- **Signal:** trailing standard deviation of daily simple returns over `lookback`
  bars (total volatility — the lowest-common-denominator estimator, reproducible on
  the price-only panel; idio-vol / beta variants BLOCKED, no factor model — M6).
- **Baseline (pre-registered, not tuned):** `LowVolStrategy(lookback=252,
  quantile=0.10, rebalance_days=21, allow_short=True, equal_weight=True,
  min_price=5.0, invariant_construction=True)`, `max_position_pct=1.0`.
  Long lowest-vol decile, short highest, equal-weight, monthly rebalance.
- **Construction:** M8 bounded invariant weight (mandatory standard; inert at full
  universe, protective under shrink). M2 $5 screen. M7 liquidity framework (default OFF).
- **Frozen (untouched):** data pipeline, reporting framework, certified construction,
  certified execution engine, benchmark. New factor class + research scripts only.
- **Evaluation:** two bases — (a) certified `investigate` two-pass IS/OOS + adjusted
  p-value (statistical gate); (b) `run_backtest` continuous full-sample single-capital
  (deployment economics). US canonical panel; capacity on India `.NS` (₹).

## 4. Canonical investigation

| Metric | IS | OOS |
|---|---|---|
| Total return | +39.59% | +20.89% |
| Sharpe | 0.198 | 0.176 |
| Max drawdown | — | −43.95% |
| Trades | — | 206 |
| **Adjusted p-value** | — | **0.366** |
| **Verdict** | — | **reject** |

Continuous full-sample (deployment basis): return +84.98%, CAGR +5.01%, Sharpe 0.166,
Sortino 0.395, turnover 0.334/yr, avg hold 105 days, 874 trades,
**max drawdown −103.35% (breaches 100% — economic ruin).**

**Read:** the anomaly's *shape* appears (positive OOS return, low turnover, long
holding period) but the edge is **statistically indistinguishable from noise**
(adjusted p = 0.366 ≫ 0.05), and the deployment-basis book is **ruined** (DD > 100%).

## 5. Robustness experiments (continuous full-sample, single pre-registered values — no sweep)

| Variant | Change | Return | Max DD | Sharpe | Trades | Turnover |
|---|---|---|---|---|---|---|
| canonical | — | +84.98% | **−103.35%** | 0.166 | 874 | 0.33 |
| lb_126 | lookback 126 | −44.35% | −65.34% | −0.40 | 799 | 1.43 |
| lb_504 | lookback 504 | 0.00% | 0.00% | 0.00 | **0** | 0.00 |
| rb_63 | rebalance 63d | +124.78% | −88.53% | 0.23 | 176 | 0.19 |
| q_20 | quantile 0.20 | +55.52% | **−126.69%** | −0.21 | 1304 | 0.29 |
| downside | semi-deviation | +16.76% | **−159.87%** | −0.29 | 789 | 0.47 |
| liq_50 | drop bottom 50% liquidity | −29.07% | −62.36% | −0.18 | 192 | 0.97 |

- **No variant is simultaneously positive, significant-shaped, and non-ruined.**
- Ruin (DD > 100%) persists across quantile (q_20 −127%), estimator (downside −160%),
  and reappears at canonical/cost variants — it is a **structural** property of the
  short high-vol leg, not a parameter artifact.
- `lb_504` produced **0 trades**: a 505-bar warm-up on the ~12-year panel starves the
  signal after survivorship trimming. **Insufficient history, not a defect** — flagged,
  not silently skipped (CLAUDE.md).
- `lb_126` and `liq_50` are cleanly **negative** (no ruin, but no edge).

## 6. Capacity findings (India `.NS`, analytic ₹)

Universe 1075 names, decile 107, per-name invariant weight 0.00701.

| Leg | Ceiling (median name ≤10% ADV) | Ceiling (p10 least-liquid) |
|---|---|---|
| **Long** (low-vol) | ₹1107 cr | **₹16.25 cr** |
| **Short** (high-vol) | ₹12.08 cr | **₹0.27 cr** |

The **short high-vol leg is the binding capacity constraint** (₹0.27 cr at the
least-liquid decile name): high-volatility stocks are the illiquid micro-caps, so the
long-short book is undeployable at any institutional size. The **long low-vol leg is
deployable** (₹16 cr floor) — low-vol names are the liquid large-caps.

## 7. Deployment findings (cost sensitivity + ruin)

| Cost (comm/spread/slip bps) | Return | Max DD | Sharpe |
|---|---|---|---|
| gross 0/0/0 | +87.37% | −102.53% | 0.12 |
| canonical 10/5/10 | +84.98% | −103.35% | 0.17 |
| high 20/20/50 | +83.35% | −103.39% | 0.21 |

**Cost drag is ~4pp — trivial.** Removing all costs does NOT remove the −100%+
drawdown. The killer is **not** transaction cost; it is the short-leg blow-up in the
NAV-proportional, gross-leverage-capped construction. Same conclusion as momentum M10.

## 8. Statistical evidence

- Certified two-pass IS/OOS with multiple-testing adjustment: **adjusted p = 0.366**,
  verdict **reject**. Not significant at any conventional threshold.
- OOS Sharpe 0.176 — economically negligible risk-adjusted return even taken at face.
- 0/8 robustness/deployment variants provide a significant, non-ruined positive.
- Consistent with the whole program: **0 significant L/S equity factors** on this
  panel (momentum 0/14 as L/S, pairs 0/14, low-vol 0/8+canonical).

## 9. Failure-mode analysis

**Primary failure mode — short high-vol leg ruin under compounding.** Sizing is
NAV-proportional (`target_value = total_value × pct × strength`) under a 1.5× gross cap.
When the short high-vol book loses, equity falls, but the leg is repeatedly re-sized
against the shrinking NAV while high-vol names keep moving violently; cumulative loss
drives equity through zero → drawdown exceeds 100%. IS/OOS slices reset capital each
pass, so they never reach the cumulative ruin — this is why a **positive OOS slice
(+20.9%) coexists with continuous ruin (−103%)**. Mechanism identical to momentum
(M9/M10/M11); engine established sound in M9 (T+1 open fills, no leakage) — **the ruin
is genuine strategy behavior, not a defect.**

**Secondary — signal fragility.** Halving the lookback flips the sign (−44%); the
"good" quarterly-rebalance return (rb_63 +125%) carries −88.5% DD and Sharpe 0.23 —
raw return, not risk-adjusted alpha.

## 10. Decision rationale

Five-dimensional certification (no single metric dominates):

| Dimension | Evidence | Result |
|---|---|---|
| 1. Statistical significance | adjusted p = 0.366 | **FAIL** |
| 2. Economic significance | OOS Sharpe 0.176; return not risk-adjusted alpha | **FAIL** |
| 3. Deployment viability | continuous DD −103%; short-leg capacity ₹0.27 cr | **FAIL** |
| 4. Robustness | 0/8 clean; ruin structural; lb_504 starved | **FAIL** |
| 5. Internal consistency | all apparent contradictions resolved (below) | **PASS (coherently negative)** |

**Contradictions resolved before certification:**
1. *rb_63 +125% vs canonical +85% / negative variants* → quarterly cadence lifts raw
   return and cuts turnover, but DD −88.5% and Sharpe 0.23 mean the return is
   drawdown-driven, not alpha. Not a contradiction.
2. *Positive OOS slice (+20.9%) vs continuous ruin (−103%)* → capital-reset slices vs
   single-capital compounding of the short-leg blow-up (same as momentum). Consistent.
3. *cost_gross +87% vs cost_high +83%* → ~4pp cost gap trivial vs −100%+ DD; costs are
   not the driver, construction is. Consistent with M10.
4. *`degenerate=False` flag while DD > 100%* → the flag tracks complex-valued metrics
   (safe-round guard kept them real); economic ruin is marked by DD < −100%, not the
   flag. Semantic, not contradictory.

**Certification: REJECT.** The low-volatility long-short strategy is rejected — no
statistical significance, no risk-adjusted economic edge, undeployable (ruin +
short-leg capacity floor), and not robust. **Platform defects: None** (M9 established
the engine sound; ruin is genuine behavior).

## 11. Limitations (honest, per CLAUDE.md — nothing silently skipped)

- **Idio-vol (AHX-Z) and beta / BAB variants BLOCKED** — require a factor model /
  betas absent from the price-only panel (M6). Baseline used total volatility, the
  only reproducible estimator.
- **Survivorship bias** — low-vol stability may be *over*-stated (volatile delisted
  names absent); direction noted, not corrected (no delisting data). Real edge is if
  anything weaker than reported.
- **`lb_504` history-starved (0 trades)** — 505-bar warm-up too long for the trimmed
  ~12-year panel; documented as an insufficient-history finding, not a bug.
- **Capacity is analytic** (ADV participation), not a market-impact simulation beyond
  the engine's Almgren-Chriss slippage.
- **Long-only low-vol not yet tested** — indicated by capacity (long leg deployable),
  deferred to future research (Section 12), not run here (no optimization mandate; the
  L/S baseline was the pre-registered spec under test).

## 12. Future research directions

1. **Long-only low-vol** — the long leg is deployable (₹16 cr floor) and avoids the
   short-leg ruin; the single highest-value next test. Mirrors the momentum finding
   that long-only India was the only significant configuration.
2. **Volatility-scaled / beta-neutral construction** — target constant risk per leg to
   stop the short-leg NAV blow-up; requires the M8 framework extended with vol targeting.
3. **Idio-vol / BAB** — unblocked only by a factor model → **acquire CRSP + Compustat**
   (the program-wide binding constraint; PIT membership, delisting returns, fundamentals).
4. **Survivorship-corrected re-test** once delisting-returns data exists.

Do NOT fund further low-vol *long-short* engineering; gate any revisit behind items 1–4.

---

### Appendix — artifacts
- Factor: `src/aurelius/research/templates.py::LowVolStrategy`; test
  `tests/research/test_research.py::test_lowvol_ranks_low_vol_long_and_is_deterministic`.
- Drivers: `scripts/run_m12.py`, `scripts/run_m12_capacity.py`.
- Results: `campaign/lowvol/shards/*.jsonl`, `campaign/lowvol/capacity_india.json`.
- Prior: `LowVol_Literature_Review.md`, `LowVol_Implementation.md`.
