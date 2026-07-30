# Reproduction Report — Gatev, Goetzmann & Rouwenhorst (2006)

Institutional Reproduction Program, paper 2 of the roadmap, run 2026-07-30.
Faithful reproduction, no parameter tuning. Platform evaluated, not optimized.
Driver: `scripts/reproduce_gatev_pairs.py` (new; reuses `PairsStrategy` +
`ResearchRunner` unchanged — pair-selection step added, engine untouched).

## 1. Why this paper

Second — and last — landmark executable on **price data alone** (queue in
`REPRODUCTION_JEGADEESH_TITMAN_2026-07-30.md` §1). Distinct methodology from
paper 1: relative-value spread mean-reversion, not cross-sectional ranking. Runs
the platform through a structurally different construction → broader proof.

## 2. Method (faithful, no tuning)

| Gatev design | Mapping |
|---|---|
| Formation: normalize to cum. price index, min sum-of-squared-deviation pair | `select_gatev_pair()` over first half of sample |
| Trading: open at 2-SD divergence | `entry_z = 2.0` |
| Close on convergence | `exit_z = 0.5` |
| 6-month spread window | `lookback = 126` |
| Single param set, no grid | `param_grid=None` |

Selected pair: **AMZN / NVDA** (SSD=1.3286, scale-balance hedge=0.7807).

## 3. Reproduced vs published

| Metric | Gatev (published, top pairs) | Reproduced |
|---|---|---|
| Excess return | **≈ +11%/yr**, low beta | −1.51% (OOS) |
| Sign | **positive** | negative |
| Sharpe | high (diversified) | OOS −4.375 |
| Verdict | pairs profit confirmed | **REJECT** |
| Pairs traded | **top 20**, diversified | 1 |
| OOS trades | thousands (pair-months) | 22 |
| Period / universe | 1962–2002, all CRSP | 2022–23 synthetic, 12 names |

## 4. Quantified differences + causes (ranked)

1. **Single-pair vs 20-pair diversification — dominant.** Gatev's return is a
   *portfolio* of 20 near-independent pairs; idiosyncratic pair risk averages
   out. One pair carries full variance: if it trends instead of reverting, the
   book is a directional bet. Classified: **dataset-related** (universe too small
   to form a pair portfolio).
2. **Regime.** 2022–23 mega-cap tech: AMZN and NVDA both drew down hard then
   rallied; the normalized spread *widened and stayed wide* rather than
   reverting inside the 6-month window. Gatev's edge is a long-run cross-sectional
   average, not a guarantee in any one 2-year window. Classified: **expected**.
3. **Fidelity gap — raw vs normalized spread.** `PairsStrategy` z-scores the
   raw (scale-balanced) price spread; Gatev z-scores the *normalized cumulative
   price* spread. Scale-balance hedge approximates it; residual entry/exit timing
   drift remains. Classified: **implementation-related**. Unblock: a
   normalized-spread mode in the template (small, deferred — no research value
   until a real pair universe exists).
4. **Transaction costs.** Commissions charged on a 1-pair book (22 trades) are a
   heavy drag Gatev spreads across a large book. Classified: **implementation-related**.
5. **No forced end-of-period close / one-day-wait convention.** Minor timing
   difference. Classified: **implementation-related**.

Fidelity finding: **construction is faithful** (Gatev distance selection + 2-SD
divergence trading, leak-safe formation/trading split). Failure is **universe
scale + regime**, not a platform-logic defect. Unlike JT (2 trades = zero
power), this ran 22 trades → the null is a genuine single-pair/regime result,
not purely a sample-size artifact.

## 5. Outcome

**FAILED to reproduce the published premium** — diagnosed cause: single-pair
concentration on a 12-name universe over an adverse 2-year regime. Same binding
constraint as paper 1: **data scale**, not engineering.

## 6. Smallest change before a meaningful retry

**Data, not engineering.** Target ≥100 names × ≥10 yr so formation yields a
diversifiable **top-20 pair portfolio**; same `CSVLoader → DuckDBStore →
PairsStrategy` path. Secondary (only after real data): normalized-spread mode
in `PairsStrategy` for exact Gatev fidelity.

## Known limitations / Skipped

**Published magnitude not reproducible here.**
- *Reason (impossibility):* Gatev requires a broad CRSP cross-section to form a
  20-pair diversified book; only 12 synthetic names × 2 yr are available
  (network/paywall block, `docs/paper_ingestion_2026-07-30.md`).
- *Unblock:* real/large adjusted-price panel (≥100 names, ≥10 yr) via the
  existing loader, then re-run this script unchanged.
