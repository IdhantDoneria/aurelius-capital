# AIDP M9 — Institutional Research Validation & Diagnostics Framework

The final quality gate between research execution and paper trading. It does not
merely compute statistics — it renders a verdict on whether a result is
statistically significant, economically meaningful, robust, capacity-viable,
reproducible, and *not* overfit. No strategy is deployable without passing here.
Additive; M1–M8 untouched.

Module: `src/aurelius/research/validation/` (package). The pre-existing
lightweight `research/validation.py` was moved to `validation/legacy.py` and is
re-exported from the package, so every historical import keeps working — this is
an extension, not a redesign.

```python
validator = ResearchValidator(config=ValidationConfig(n_trials=50), registry=registry)
report = validator.validate(experiment, execution_result, research_matrix,
                            benchmark_returns=bench, positions=weights)
report.overall_verdict          # PASS | PASS_WITH_WARNINGS | REJECT | REQUIRES_REVIEW
report.confidence_score         # 0–100 research score
report.reasoning                # machine-generated, references the diagnostics
```

## Architecture

Pure functions + dependency injection. Each concern is an independent module the
engine composes; nothing re-implements a prior engine, and the framework never
re-runs a backtest itself (re-fitting probes take an injected `evaluator`).

- **Core API** — `ResearchValidator.validate(experiment, execution_result,
  research_matrix)` → `ValidationReport`. `execution_result` may be a M8
  `ResearchSession`, a `BacktestReport`, or a raw `PerformanceMetrics`.
- **Inputs are realized in-sample series only** — every statistic is a function of
  the produced returns/trades. No future information enters validation.

## Validation modules

| Module | Role |
|---|---|
| `significance` | t-stat, p-value (self-contained Student-t), SE, CI, effect size, Sharpe + Lo SE, moments, jackknife |
| `bootstrap` | IID, moving-block, circular-block, stationary (Politis–Romano) resampling → CIs |
| `monte_carlo` | return-noise, slippage, trade-reorder, execution-delay perturbation → confidence bands |
| `permutation` | return / sign / signal permutation → empirical p-values |
| `walkforward` | rolling, expanding, leave-one-year-out OOS consistency |
| `sensitivity` | parameter perturbation, feature removal, missing-data stress |
| `stability` | parameter stability curve/surface + plateau score |
| `overfitting` | Deflated & Probabilistic Sharpe, PBO (CSCV), White's Reality Check |
| `multiple_testing` | Bonferroni, Holm, Benjamini–Hochberg, FDR |
| `robustness` | aggregates the temporal/data/parameter probes |
| `capacity` | ADV utilisation, √-law market impact, implementation shortfall, capacity ceiling |
| `turnover` | turnover / holding-period profile |
| `factor_exposure` | market beta/alpha, style tilt (from the M6 matrix), concentration |
| `diagnostics` | severity-tagged flags referencing the raising number |
| `scoring` | 7 component scores + weighted research score + contribution decomposition |
| `report` | `ValidationReport` + verdict engine + manifest hash |
| `visualization` | chart data + standalone matplotlib script |
| `engine` | orchestration + registry/artifact integration |
| `quality` | report completeness/self-consistency check |

## Statistical methods & assumptions

- **Sharpe significance** — `t = mean/(std/√n)`, Student-t p-value via a
  self-contained regularized incomplete beta (scipy is not a dependency). Assumes
  weakly-dependent returns; block bootstrap is the autocorrelation-robust cross-check.
- **Sharpe SE** — Lo (2002), with skew/kurtosis correction.
- **Bootstrap** — the stationary bootstrap (Politis & Romano 1994) preserves
  short-horizon autocorrelation IID resampling destroys; default for Sharpe CIs.
- **Permutation** — the engine uses the **sign** permutation, because the Sharpe
  ratio is order-invariant (a plain return permutation is degenerate for it);
  randomizing the sign tests "is the positive drift beyond chance?".
- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014) — PSR against the
  expected maximum Sharpe of `n_trials` trials. When the cross-trial SR variance is
  unknown (a single track record) the estimator's own sampling variance is
  substituted, and the report flags `sr_variance_substituted: true` — an explicit,
  documented approximation, never a silent one.
- **PBO** (Bailey et al. 2017, CSCV) and **White's Reality Check** (2000) require a
  *matrix* of candidate-configuration returns (e.g. from a parameter sweep). With a
  single strategy they are reported as skipped-with-reason; pass `returns_matrix` /
  `excess_matrix` to enable them.
- **Multiple testing** — Holm (1979) FWER, Benjamini–Hochberg (1995) FDR, applied to
  the computed p-value family plus a Bonferroni adjustment of the single p-value by
  `n_trials`.
- **Market impact** — square-root law (Almgren et al. 2005): `impact ≈ c·σ·√(Q/ADV)`.
  Needs per-name ADV; absent it, only a turnover-based qualitative signal is given.

## Scoring methodology

Seven components, each 0–100 and **exposed separately**, combined by configurable,
documented weights (`scoring.DEFAULT_WEIGHTS`):

| Component | Weight | Driven by |
|---|---|---|
| statistical_validity | 0.25 | p-value, permutation p, DSR |
| robustness | 0.20 | rolling/expanding OOS positivity, missing-data degradation |
| economic_significance | 0.15 | annualized Sharpe (saturating) |
| capacity | 0.10 | ADV utilisation / turnover |
| overfitting_risk | 0.15 | DSR, PBO (higher score = lower risk) |
| reproducibility | 0.10 | git commit, dataset versions, seed, fingerprint present |
| transparency | 0.05 | features, artifacts, computed exposures |

`research_score = Σ score·weight / Σ weight`. The report also carries a
**contribution decomposition** (`score·weight/Σweight` per component) so the final
number is explainable. Weights are overridable via `ValidationConfig.weights`.

## Verdict engine

Four outcomes, each with reasoning that cites the numbers:
- **REJECT** — any hard failure: Sharpe ≤ 0, p > 0.05, DSR < 0.5, or a critical
  diagnostic flag (unstable alpha, parameter fragility).
- **REQUIRES_REVIEW** — ≥ 2 *core* analyses (bootstrap/MC/DSR/rolling) could not be
  computed, or research score < review threshold. (Absent optional enrichment —
  benchmark, positions, evaluator — does *not* force review.)
- **PASS_WITH_WARNINGS** — core gates pass but warning flags exist (e.g. excess
  turnover, benchmark crowding).
- **PASS** — all gates clear.

## Risk diagnostics

Severity-tagged flags, each quoting the raising metric: excess turnover, unstable
alpha (critical), time-period dependence, capacity risk, factor crowding (high R²
vs benchmark), style drift, parameter fragility (critical on high sensitivity
dispersion). Sector/industry/country/currency exposures are marked
`supported: false` — a permanent architecture gap (no classification map), not a
per-run miss.

## Integration

- **Execution Platform** — validate a completed `ResearchSession` directly.
- **Research Matrix** — style/tilt exposures read from the M6 matrix frame.
- **Experiment Registry** — the report becomes experiment artifacts
  (`validation_report.json`, `validation_visuals.json`, `plot_validation.py`,
  hashed), and the registry records `ValidationScore`, `DeflatedSharpe`, the verdict
  (in notes), and the validation version — via the existing store, no M7
  schema change.

## Benchmarks (`scripts/benchmark_validation.py`, 1000 returns, 2000 resamples)

| | Result |
|---|---|
| stationary bootstrap | ~540 ms |
| Monte Carlo | ~39 ms |
| full validation pass | ~580 ms |
| peak traced memory | ~1.5 MB |
| 4-thread speedup | 0.8× (no gain) |

Bootstrap dominates. Thread-level parallelism does **not** help — the resampling
loops are Python-level and hold the GIL; parallelism belongs at the
experiment/process level (each validation is independent and side-effect-free
except its own artifact dir), where a process pool scales linearly.

## Tests (`tests/research/test_validation.py`, 13, all offline & deterministic)

bootstrap correctness · permutation correctness · walk-forward splits · parameter
sensitivity/stability · capacity estimation · multiple-testing · overfitting
pipeline (DSR strong>0.9 / weak<0.5, PBO) · verdict logic (PASS/REJECT/PASS_WITH_
WARNINGS) · artifact generation · registry integration · execution integration ·
failure recovery · scoring. Full suite: **154 passed, 2 skipped**, zero regressions.

## Known limitations / Skipped

- **PBO / Reality Check / SPA need a multi-configuration returns matrix.** With a
  single track record they are skipped-with-reason. Unblock: pass `returns_matrix`
  (per-config OOS returns from a M8 parameter sweep). SPA (Hansen 2005) is a
  documented extension point on top of the implemented Reality Check.
- **CSCV PBO** is implemented; its combinatorial cost is `C(S, S/2)` (S=10 → 252
  combos) — fine here, but S is capped for tractability.
- **Sector/industry/country/currency exposures** require a classification map absent
  from the PIT stack. Unblock: add GICS sector/industry + country/currency to
  SecurityMaster (a M2 extension).
- **DSR variance substitution** when only one track record is available (flagged in
  the report), per the note above.
- **Re-fitting robustness** (parameter perturbation, feature removal, stability
  surfaces) needs an injected `evaluator`; without it those probes report
  `insufficient_data` rather than a fabricated result.
- **No image rendering** — chart data + a matplotlib script are emitted (the stack
  has no plotting dependency), per the spec.

## References

- Lo (2002), "The Statistics of Sharpe Ratios", *FAJ*.
- Politis & Romano (1994), "The Stationary Bootstrap", *JASA*.
- White (2000), "A Reality Check for Data Snooping", *Econometrica*.
- Hansen (2005), "A Test for Superior Predictive Ability", *JBES*.
- Bailey & López de Prado (2014), "The Deflated Sharpe Ratio", *J. Portfolio Mgmt*.
- Bailey, Borwein, López de Prado, Zhu (2017), "The Probability of Backtest
  Overfitting", *J. Computational Finance*.
- Benjamini & Hochberg (1995); Holm (1979) — multiple testing.
- Almgren, Thum, Hauptmann, Li (2005), "Direct Estimation of Equity Market Impact".

## Future extensions

Bayesian performance estimation, a regime-detection interface (leave-one-regime-out
is stubbed pending a regime model), a validation plug-in registry for new tests,
SPA on top of the Reality Check, automatic baseline comparison (equal-weight /
index / random), and an explainability layer summarizing the strongest for/against
evidence beyond the current contribution decomposition.
