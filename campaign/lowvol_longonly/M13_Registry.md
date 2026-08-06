# M13 — Experiment & Certification Registry (Long-Only Low-Volatility)

**Date:** 2026-08-06 · **Platform defects:** None · **Research conclusion:** DEFER

## Experiment registry

All runs: `LowVolStrategy`, `allow_short=False`, M8 invariant construction ON, US
canonical panel, one pre-registered value each (robustness, not optimization).
Continuous = `run_backtest` full-sample; canonical also ran certified two-pass
`investigate`. Only change vs M12: `allow_short=False`.

| ID | Label | Change | Basis | Return | Max DD | Sharpe | Trades | adj p | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| M13-C | canonical | baseline (long-only) | investigate | OOS +36.19% | −7.40% | OOS 0.609 | 420 | 0.1182 | reject |
| M13-C | canonical | baseline (long-only) | continuous | +172.98% | −36.26% | 0.310 | 783 | — | positive |
| M13-R1 | lb_126 | lookback 126 | continuous | +153.61% | −31.66% | 0.269 | 1304 | — | positive |
| M13-R2 | lb_504 | lookback 504 | continuous | 0.00% | 0.00% | 0.00 | 0 | — | starved |
| M13-R3 | rb_63 | rebalance 63d | continuous | +159.75% | −37.70% | 0.275 | 181 | — | positive |
| M13-R4 | downside | semi-deviation | continuous | +160.40% | −34.56% | 0.285 | 701 | — | positive |
| M13-R5 | liq_50 | drop 50% illiquid | continuous | +176.23% | −31.94% | 0.312 | 226 | — | positive (improves) |
| M13-CAP | capacity_india | analytic ₹, long leg | — | ceiling ₹830 cr median / **₹12.19 cr p10** | — | — | — | — | deployable |

**IS pass (canonical):** return +46.12%, Sharpe 0.017, DD −36.26%.

## Certification registry

| Field | Value |
|---|---|
| Campaign | M13 — Long-Only Low-Volatility |
| Hypothesis | Long-only lowest-vol decile earns significant, deployable alpha |
| Baseline | lookback 252, quantile 0.10, rebalance 21d, **long-only**, EW, $5 screen, M8 |
| Statistical significance | FAIL (marginal) — adjusted p = 0.1182; IS Sharpe 0.017 |
| Economic significance | MARGINAL — CAGR 8.3%, Sharpe 0.31; beta-confounded, alpha undecomposable |
| Deployment viability | PASS — no ruin (DD −36%); capacity ₹12.19 cr; turnover 0.19 |
| Robustness | PASS (sign) — 4/5 live variants positive non-ruined; lb_504 starved |
| Internal consistency | PASS — IS-flat/OOS-strong = regime dependence; coheres with failed gate |
| Platform defects | **None** (engine sound per M9; short-leg diagnosis confirmed) |
| **Certification** | **DEFER** |
| Kept as infrastructure | `LowVolStrategy` long-only path retained |
| Unblock | CRSP/Compustat factor model (alpha vs beta / BAB); longer OOS |
