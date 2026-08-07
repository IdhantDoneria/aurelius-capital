# AIDP M10 — Institutional Portfolio Construction & Optimization Engine

Transforms validated research signals into implementable portfolios. Alpha
generation (the signal) is kept strictly separate from construction (sizing, risk,
constraints, costs): a signal is *not* a portfolio. Additive; M1–M9 untouched.

Module: `src/aurelius/research/portfolio/`.

```python
sig = signals_from_matrix(research_matrix, "earnings_yield")      # M6 → signal
port = PortfolioEngine().construct(
    sig, universe, ConstraintSet(max_position_weight=0.05, long_only=True),
    Objective.MIN_VARIANCE, as_of, covariance=cov, prices=px, current_weights=held,
    cost_model=TransactionCostModel(), adv=adv)
record_portfolio(registry, experiment, port, optimizer_name="min_variance",
                 constraints=constraints)                          # M7 lineage
```

## Architecture

Modular, dependency-injected, deterministic. The engine composes independent
concerns; nothing rebuilds prices/fundamentals/universe/insider data — those come
from the M6 matrix and given inputs.

| Module | Role |
|---|---|
| `engine` | `PortfolioEngine.construct(...)` + matrix/registry integration helpers |
| `models` | `PortfolioPosition`, `Portfolio` |
| `objectives` | `Objective` enum + per-objective definition/assumptions/limitations |
| `optimizer` | covariance estimators, expected-return models, DI `Optimizer` |
| `constraints` | `ConstraintSet` + feasibility projection + violation report |
| `costs` | `TransactionCostModel` (commission/spread/slippage + √-law impact) |
| `rebalancing` | `RebalanceRule` (calendar/threshold/volatility/hybrid) |
| `risk` | risk/return/marginal contributions, ENB, concentration (dense + diagonal) |
| `diagnostics` | assembles the portfolio diagnostics block |
| `validation` | portfolio-level checks (turnover/capacity/concentration/cost/violations) |
| `solvers/` | `Solver` ABC + equal-weight, mean-variance, risk-parity, max-diversification |

### Optimizer is dependency-injected

The engine depends on the `Solver` ABC, never a concrete optimizer. `solvers/`
ships analytic numpy implementations (no scipy/cvxpy dependency); a scipy/cvxpy or
custom solver drops in by implementing `Solver.solve(mu, cov, ctx)`. Covariance and
expected-return models are likewise injectable interfaces.

### Dense vs diagonal path (performance)

If a full covariance or a returns matrix is supplied, the dense solver path runs
(exact mean-variance with correlations; `pinv` is O(N³) — realistic for hundreds of
names). If only per-name volatilities are given (a diagonal risk model), the engine
uses **closed-form O(N)** weights and never materializes an N×N matrix — this is
what keeps a 10,000-name portfolio under ~0.25 s / <10 MB instead of minutes / GBs.

## Portfolio models

- **PortfolioPosition** — security_id, weight, shares, price, market_value,
  target_weight (pre-rounding), current_weight (pre-rebalance).
- **Portfolio** — date, positions, gross/net exposure, turnover, cash,
  expected_return, expected_risk, metadata (objective, solver, assumptions,
  constraints snapshot), diagnostics.

## Optimization methods

| Objective | Definition | Key assumption / limitation |
|---|---|---|
| Equal Weight | wᵢ = 1/N | ignores μ and Σ by design |
| Max Sharpe | w ∝ Σ⁻¹μ (tangency) | very sensitive to μ estimation error |
| Min Variance | w ∝ Σ⁻¹1 | return-agnostic; loads low-vol names |
| Risk Parity | equalize RCᵢ = wᵢ(Σw)ᵢ | sqrt-damped fixed point; no return view |
| Max Diversification | max (wᵀσ)/√(wᵀΣw); w ∝ Σ⁻¹σ | Σ-conditioning sensitive |
| Tracking Error | min (w−b)ᵀΣ(w−b), μ-tilted | collapses to b without a tilt; TE budget approximate |

Every objective's assumptions and limitations travel with the result in
`portfolio.metadata["objective_spec"]` — nothing hidden.

## Constraint system

Declarative `ConstraintSet`; enforcement projects raw weights into the feasible
set. **Position**: max/min weight, long-only / long-short. **Portfolio**: gross,
net, leverage. **Risk**: volatility/beta targets, factor limits (reported).
**Concentration**: sector/industry/country limits. **Liquidity**: ADV
participation, turnover, capacity. **Trading**: min trade size, rebalance
threshold.

Projection is an iterated renormalize-then-box-clip (ending on the hard cap). It is
**always feasible for the box/gross/leverage constraints but is not guaranteed to
be the constrained optimum** — without a QP solver (no cvxpy dependency) that is the
honest trade-off, stated rather than hidden. Risk/concentration/liquidity limits
that aren't directly projectable are enforced where expressible and otherwise
surfaced via `ConstraintSet.violations(...)` for the caller (and the validation
layer) to act on.

## Cost model

`TransactionCostModel`: linear bps = commission + spread/2 + slippage, plus
non-linear market impact via the square-root law `impact = k·√(order/ADV)`
(Almgren et al. 2005). All coefficients configurable; costs never hard-coded into
the optimizer. Returns per-trade linear/impact/total cost, cost in bps, and ADV
participation.

## Rebalancing

`RebalanceRule.should_rebalance(...)` — calendar (daily/weekly/monthly/quarterly),
threshold (max weight drift), volatility-triggered (relative risk change), or
hybrid (calendar OR drift). Pure decision functions; they gate construction, never
perform it.

## Integration

- **Research Matrix (M6)** — `signals_from_matrix(matrix, column)` extracts a
  return-aligned signal (applying the registered direction: `lower` → negated).
- **Execution Platform (M8)** — a portfolio is constructed from a completed
  `ResearchSession`'s context and recorded against its experiment.
- **Experiment Registry (M7)** — `record_portfolio` persists the portfolio
  config (optimizer, objective, constraints, cost model, rebalance rule) as
  experiment parameters plus key metrics (turnover, gross, expected risk, effective
  holdings) via the existing store (a full upsert — no schema change).
- **Validation Framework (M9)** — `validate_portfolio` checks turnover,
  capacity/ADV participation, concentration, risk exposure, cost impact, and
  constraint violations; the same turnover/capacity signals feed the M9
  deployment gate.

## Benchmarks (`scripts/benchmark_portfolio.py`, 10,000 securities, diagonal Σ)

| Objective | Time | Max weight |
|---|---|---|
| equal_weight | ~0.24 s | 0.0001 |
| min_variance | ~0.25 s | 0.0012 |
| risk_parity | ~0.25 s | 0.0004 |
| max_diversification | ~0.27 s | 0.0004 |

Peak memory ~9.5 MB. Simple portfolios well under the 1 s target. **Dense
mean-variance** (full Σ, correlations) is O(N³) via pseudo-inverse — ~49 ms at
N=800, and intended for hundreds of names, not 10k (a dense 10k×10k Σ is ~800 MB and
its inverse is the bottleneck). Large universes use the diagonal risk model.

## Tests (`tests/research/test_portfolio.py`, 13, all offline & deterministic)

equal-weight · max-position · turnover · cost model · risk contribution · optimizer
DI · long-only · leverage · liquidity · deterministic reproduction · registry ·
execution · validation + matrix-signal integration. Full suite: **167 passed, 2
skipped**, zero regressions.

## Known limitations / Skipped

- **Constraint projection ≠ constrained QP optimum.** Iterated clip/renormalize is
  feasible but not provably optimal under joint constraints. Unblock: inject a
  cvxpy/scipy `Solver` that solves the constrained QP directly (the DI seam exists).
- **Dense mean-variance is O(N³)** — not for 10k-name universes; use the diagonal
  path or a factor covariance there.
- **Black-Litterman & Bayesian return models, HRP, factor-neutral & tax-aware
  optimization** are interfaces/extension points. Bayesian shrinkage and Ledoit-Wolf
  covariance are implemented; BL and HRP return a documented fallback with a note.
- **Sector/industry/country limits** need a classification map absent from the PIT
  stack (same SecurityMaster extension noted in M9).

## Future extensions

Full constrained QP via an injected cvxpy solver; factor-model covariance for
large-N mean-variance; concrete Black-Litterman (equilibrium prior + views);
Hierarchical Risk Parity (correlation clustering); factor-neutral and tax-aware
optimization; multi-period / transaction-cost-aware rebalancing.
