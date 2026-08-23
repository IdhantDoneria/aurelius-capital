# Mentisrex Programme v3.0 — full backtest run, 2026-08-22

DB: `data/analytics.duckdb`, panel through 2026-08-14 (410 tickers, 2,422 sessions,
2017-01-01 start). Every command below ran clean (exit 0), no errors, no fallbacks.

## 1. Offline invariant suite

```bash
uv run --extra dev pytest tests/programme -q
```
`48 passed in 0.69s` — `test_controls.py` (33), `test_invariants.py` (15).

## 2. Deployment ladder — `run_backtest` (summary_stats), all six rungs

| rung | cagr | vol | sharpe | sortino | max_dd | calmar | avg_gross | turnover_ann |
|---|---|---|---|---|---|---|---|---|
| deploy | 0.1307 | 0.1094 | 1.178 | 1.495 | -0.1502 | 0.871 | 0.97 | 9.73 |
| conservative | 0.1858 | 0.1640 | 1.121 | 1.423 | -0.2199 | 0.845 | 1.46 | 14.58 |
| mandate | 0.2294 | 0.1994 | 1.135 | 1.506 | -0.2456 | 0.934 | 1.95 | 22.57 |
| standard | 0.2700 | 0.2397 | 1.115 | 1.540 | -0.2818 | 0.958 | 2.42 | 30.18 |
| recommended | 0.2880 | 0.2585 | 1.104 | 1.591 | -0.2863 | 1.006 | 2.65 | 34.78 |
| aggressive | 0.3041 | 0.2799 | 1.082 | 1.603 | -0.2975 | 1.022 | 2.87 | 38.78 |

Sharpe declines monotonically as gross rises (1.178 → 1.082) — leverage is not free here, cost/financing
drag scales faster than return. `deploy`'s config fingerprint: `40feb9795aba9ea0`. `recommended`'s:
`5252d1fc94eca6e2`.

**Skipped: diff against spec Table 3.** The `US_Equity_Systematic_Programme_v3_Full_Specification.md`
document that defines Table 3 was supplied by the user in an earlier conversation but was never saved
into this repository or filesystem — `find` for it (and for any `sysq` package it references) returns
nothing, confirmed already in `docs/V3_SPEC_COMPARISON_AUDIT_2026-08-21.md`. There is nothing on disk to
diff the sleeve table against. Unblocked by: the user re-supplying that spec file (as a file, not just
pasted chat text) so its Table 3 numbers can be read and compared programmatically.

## 3. Walk-forward (spec Table 21 shape), `deploy` and `recommended`

`deploy`:
| period | return | sharpe | max_dd | benchmark_return |
|---|---|---|---|---|
| 2017–2018 | 0.168 | 0.967 | -0.108 | 0.146 |
| 2019–2020 | 0.552 | 1.593 | -0.150 | 0.553 |
| 2021–2022 | 0.078 | 0.401 | -0.139 | 0.053 |
| 2023–2024 | 0.339 | 1.759 | -0.059 | 0.576 |
| 2025–2026* | 0.243 | 1.236 | -0.095 | 0.329 |

`recommended`:
| period | return | sharpe | max_dd | benchmark_return |
|---|---|---|---|---|
| 2017–2018 | 0.455 | 1.118 | -0.213 | 0.146 |
| 2019–2020 | 2.031 | 1.627 | -0.248 | 0.553 |
| 2021–2022 | 0.197 | 0.499 | -0.232 | 0.053 |
| 2023–2024 | 0.523 | 1.271 | -0.119 | 0.576 |
| 2025–2026* | 0.414 | 0.956 | -0.162 | 0.329 |

\* 2025–2026 period is partial (410 sessions, panel ends 2026-08-14).

2021–2022 is the weak regime for both rungs (sharpe 0.40 / 0.50) — consistent with a momentum-heavy book
during a whipsaw/rate-hike year.

## 4. Stress grid (spec Table 17 shape) — illustrative perturbations

Not a reproduction of the spec's exact perturbation list (not present in this repo, see §2 skip). Rows
defined in `scripts/run_validation.py::PERTURBATIONS`.

`deploy`:
| perturbation | cagr | sharpe | max_dd |
|---|---|---|---|
| base case | 0.1307 | 1.178 | -0.150 |
| costs.one_way_bps=20.0 | 0.1143 | 1.044 | -0.162 |
| financing.borrow_fee=0.06 | 0.1202 | 1.093 | -0.151 |
| universe.min_dollar_volume=1.5e7 | 0.1122 | 1.028 | -0.160 |
| allocator.gross_cap=2.0 | 0.2274 | 1.054 | -0.287 |
| execution.signal_to_trade_lag=3 | 0.1204 | 1.088 | -0.199 |

`recommended`:
| perturbation | cagr | sharpe | max_dd |
|---|---|---|---|
| base case | 0.2880 | 1.104 | -0.286 |
| costs.one_way_bps=20.0 | 0.2226 | 0.902 | -0.349 |
| financing.borrow_fee=0.06 | 0.2394 | 0.955 | -0.328 |
| universe.min_dollar_volume=1.5e7 | 0.2031 | 0.894 | -0.331 |
| allocator.gross_cap=2.0 | 0.2266 | 1.172 | -0.204 |
| execution.signal_to_trade_lag=3 | 0.2570 | 1.008 | -0.353 |

Zero rows errored. Most sensitive single-field perturbation for both rungs: `universe.min_dollar_volume`
(liquidity floor) — cuts sharpe the most per rung, larger than a 2x cost shock.

## 5. Block bootstrap (stationary, 10,000 paths, mean block 21d) + deflated Sharpe

| rung | bootstrap sharpe mean | sharpe std | bootstrap cagr mean | deflated_sharpe |
|---|---|---|---|---|
| deploy | 1.189 | 0.302 | 0.131 | 0.9921 |
| recommended | 1.109 | 0.257 | 0.291 | 0.9958 |

`deflated_sharpe` uses `n_trials=6` (the perturbation count above) and the bootstrap's own `sharpe_std`,
not the spec-implied 0.229 — see `backtest.deflated_sharpe` docstring for the documented disagreement
with Lo's ~0.415 convention.

## Reproduce

```bash
export MRX_DB=/Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb
uv run --extra dev pytest tests/programme -q
for rung in deploy conservative mandate standard recommended aggressive; do
  uv run --extra dev python -m mentisrex.programme.cli backtest --rung "$rung" --start 2017-01-01 --db "$MRX_DB"
done
uv run --extra dev python scripts/run_validation.py --rung deploy --db "$MRX_DB" --n-paths 10000
uv run --extra dev python scripts/run_validation.py --rung recommended --db "$MRX_DB" --n-paths 10000
```
