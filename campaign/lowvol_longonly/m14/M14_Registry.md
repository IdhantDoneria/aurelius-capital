# M14 — Experiment & Certification Registry (Factor Attribution)

**Date:** 2026-08-06 · **Platform defects:** None · **Research conclusion:** DEFER

## Experiment registry

Attribution only — no strategy change. M13 canonical book (unchanged) regressed against
constructible risk factors. 2890 daily obs, 2015-01-05 → 2026-07-30.

| ID | Phase | What | Result |
|---|---|---|---|
| M14-P1 | exposures | market + momentum betas (2-factor) | mkt β 0.012 (t 6.67), mom β 0.001 (t 1.45), α +4.55%/yr (t 1.19), R² 0.015 |
| M14-P2 | market OLS | single-factor α/β/R²/CI | α +4.43%/yr (t 1.16, CI [−3.08%,+11.93%]), β 0.011, R² 0.0145 |
| M14-P3 | rolling β | 126d rolling single-factor beta | mean 0.491, min 0.001, max 0.788, std 0.209 |
| M14-P4 | sector | sector attribution | **skipped — no sector metadata (M6)** |
| M14-P5 | residual | strip β·market | residual CAGR +3.65%, Sharpe 0.34, DD −37.03% |

## Certification registry

| Field | Value |
|---|---|
| Campaign | M14 — Factor Attribution & Beta Decomposition |
| Question | Does the M13 return survive after controlling for systematic risk? |
| Portfolio | M13 canonical long-only low-vol, **unchanged** |
| Residual alpha significance | FAIL — α +4.4%/yr, t 1.16, 95% CI straddles 0 |
| Return explained by beta | INCONCLUSIVE — full-sample β ≈ 0, R² 1.5% (nothing to remove) |
| Benchmark adequacy | FAIL (data) — equal-weight proxy mis-specified; no cap weights |
| Factor completeness | FAIL (data) — 2/4 factors; size & value unavailable |
| Internal consistency | PASS — rolling β 0.49 vs pooled 0.01 both explained by proxy mis-spec |
| Platform defects | **None** (regression sound; block is data) |
| **Certification** | **DEFER** — attribution incomplete, required data unavailable |
| Unblock | CRSP shares-outstanding (cap-weighted market + size) + Compustat (value) + sector codes |
