# M12 — Experiment & Certification Registry (Low-Volatility)

**Date:** 2026-08-06 · **Platform defects:** None · **Research conclusion:** REJECT

## Experiment registry

All runs: `LowVolStrategy`, M8 invariant construction ON, US canonical panel, one
pre-registered value each (robustness, not optimization). Continuous = `run_backtest`
full-sample; canonical also ran certified two-pass `investigate`.

| ID | Label | Change | Basis | Return | Max DD | Sharpe | Trades | adj p | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| M12-C | canonical | baseline | investigate | OOS +20.89% | −43.95% | OOS 0.176 | 206 | 0.366 | reject |
| M12-C | canonical | baseline | continuous | +84.98% | −103.35% | 0.166 | 874 | — | ruin |
| M12-R1 | lb_126 | lookback 126 | continuous | −44.35% | −65.34% | −0.40 | 799 | — | negative |
| M12-R2 | lb_504 | lookback 504 | continuous | 0.00% | 0.00% | 0.00 | 0 | — | starved |
| M12-R3 | rb_63 | rebalance 63d | continuous | +124.78% | −88.53% | 0.23 | 176 | — | DD-driven |
| M12-R4 | q_20 | quantile 0.20 | continuous | +55.52% | −126.69% | −0.21 | 1304 | — | ruin |
| M12-R5 | downside | semi-deviation | continuous | +16.76% | −159.87% | −0.29 | 789 | — | ruin |
| M12-D1 | liq_50 | drop 50% liquidity | continuous | −29.07% | −62.36% | −0.18 | 192 | — | negative |
| M12-D2 | cost_gross | 0/0/0 bps | continuous | +87.37% | −102.53% | 0.12 | 875 | — | ruin |
| M12-D3 | cost_high | 20/20/50 bps | continuous | +83.35% | −103.39% | 0.21 | 874 | — | ruin |
| M12-CAP | capacity_india | analytic ₹ | — | long ceil ₹16 cr / short ceil ₹0.27 cr (p10) | — | — | — | — | undeployable L/S |

## Certification registry

| Field | Value |
|---|---|
| Campaign | M12 — Low-Volatility Alpha |
| Hypothesis | Low-vol stocks earn superior risk-adjusted returns (L/S decile) |
| Baseline | lookback 252, quantile 0.10, rebalance 21d, L/S, EW, $5 screen, M8 construction |
| Statistical significance | FAIL — adjusted p = 0.366 |
| Economic significance | FAIL — OOS Sharpe 0.176, return not risk-adjusted alpha |
| Deployment viability | FAIL — continuous DD −103%; short-leg capacity ₹0.27 cr |
| Robustness | FAIL — 0/8 clean; ruin structural; lb_504 starved |
| Internal consistency | PASS (coherently negative; 4 contradictions resolved) |
| Platform defects | **None** (engine sound per M9; ruin is genuine behavior) |
| **Certification** | **REJECT** |
| Kept as infrastructure | `LowVolStrategy` factor retained (reusable, long-only future test) |
| Next | Long-only low-vol; vol-scaled construction; CRSP/Compustat unblock for idio-vol/BAB |
