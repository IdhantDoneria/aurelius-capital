# M13 — Institutional Risk Engine Consolidation

**Milestone:** M13
**Capability:** Risk Engine (see `AURELIUS_ROADMAP.md`)
**Depends on:** M9 (validation), M10 (covariance / risk contribution), M11 (drawdown / exposure), M12 (paper-trading state)
**Status:** DRAFT → CERTIFIED
**Branch:** `aidp/audit-and-pit-gaps`

---

## Summary

M13 builds the **canonical Aurelius Institutional Risk Engine** — the missing
risk-management layer between portfolio construction/simulation/paper-trading and
live deployment. It answers: is the portfolio within limits, where does risk come
from, what exposures exist, what happens under stress, should a trade be blocked,
should the portfolio rebalance, is it deployable.

It **consolidates and supersedes** the legacy Platform-Track risk engine
(`aurelius.risk`) in the canonical M-line. Per the legacy-track audit, the legacy
package is left **historical and untouched** — no renames, no breakage. M13 is
additive, dependency-injected, deterministic, PIT-safe, and **reuses** M9/M10/M11
rather than duplicating accounting, covariance, or validation.

## Architecture

```
weights (from M10 construction / M11 sim / M12 paper state)
      │        + returns, values, adv, aum, sectors, factor model  (all injected)
      ▼
 RiskEngine.assess(...)
      ├── exposure_report          gross/net/long/short/cash + sector/…
      ├── concentration_report     HHI, effective holdings, largest, top5   (M10 risk-contrib reused)
      ├── covariance / vol         realized portfolio vol (O(N·T)); diagonal risk contrib (O(N))
      ├── VaR / ES                 historical | parametric, 95/97.5/99%
      ├── drawdown_report          M11 drawdown + rolling + halt rule
      ├── factor.analyze           CAPM / Fama-French / custom (DI FactorModel)
      ├── liquidity / capacity     ADV participation, days-to-liquidate, capacity
      └── limits.evaluate → RiskDecision   APPROVE | APPROVE_WITH_WARNING | REJECT
      ▼
 RiskReport → monitor() · validate_risk() (+M9) · attach_risk() (M7) · RiskGate → M12
```

## Legacy migration approach

The legacy `aurelius.risk` (Decimal, `backtesting.PortfolioState`, single-asset
lineage) stays frozen as the Platform-Track historical implementation. M13 is a
**parallel canonical package** `aurelius.research.risk` (numpy, cross-sectional,
reuses M9/M10/M11). Object names intentionally overlap (`RiskEngine`, `RiskDecision`,
`RiskReport`, `RiskLimits`) but live in a different package — no collision, no
rename, per `AURELIUS_LEGACY_TRACK_AUDIT.md` (freeze legacy by name, rebuild into the
M-line). Capability mapping legacy → M13: `RiskEngine`→`research.risk.RiskEngine`,
`StressTester`→`stress`, `PortfolioRiskMonitor`→`monitoring`, `RiskLimits`→`limits`.

## Risk hierarchy

1. **Pre-trade** (`RiskGate`): per-name position cap + portfolio-level gross/leverage
   → blocks orders before submission (M12 integration).
2. **Portfolio** (`assess`): exposure, concentration, volatility, VaR, factor,
   drawdown, liquidity, capacity → `RiskDecision`.
3. **Monitoring** (`monitor`): time-series of reports → limit-breach / drawdown /
   vol-spike / exposure-drift / liquidity / concentration events + alerts.
4. **Deployment** (`validate_risk`): portfolio health (M13) × statistical verdict
   (M9) → `DeploymentRiskDecision`.

## Major components

| Module | Responsibility |
|---|---|
| `models.py` | All frozen reports + `RiskDecision` enum. |
| `limits.py` | `RiskLimits` + pure violation evaluator (hard=reject, soft=warn). |
| `exposure.py` | Gross/net/long/short/cash + sector/industry/country/currency interfaces. |
| `concentration.py` | HHI, effective holdings, largest weight/contribution, top5. |
| `covariance.py` | Reuses M10 estimators; adds EWMA + factor covariance; `make_covariance` DI. |
| `factor.py` | DI `FactorModel` — CAPM, Fama-French hook, custom; factor/specific risk. |
| `var.py` | Historical + parametric VaR & ES at 95/97.5/99%. |
| `stress.py` | Historical (2008/2020/2022) + custom scenarios; market/sector/vol/liquidity shocks. |
| `drawdown.py` | Reuses M11 drawdown; rolling DD + halt rule. |
| `liquidity.py` | ADV participation, days-to-liquidate, liquidity concentration. |
| `capacity.py` | Strategy dollar-capacity + utilization. |
| `engine.py` | `RiskEngine` orchestrator + `RiskGate` (M12 pre-trade adapter). |
| `monitoring.py` | `RiskSnapshot` timeline + `RiskEvent`/`RiskAlert` detection. |
| `validation.py` | Portfolio health + M9-combined deployment decision. |
| `serialization.py` / `diagnostics.py` / `registry.py` | JSON, health dict + deterministic fingerprint, M7 attach. |

## Data flow / integration points

- **M10** — reuses `CovarianceEstimator` family (`SampleCovariance`,
  `DiagonalCovariance`, `ShrinkageCovariance`) and `diagonal_risk_diagnostics` for
  O(N) risk contributions. No covariance math re-implemented.
- **M11** — reuses `drawdown()` and the exposure/risk-snapshot notions.
- **M12** — `RiskEngine.as_gate()` yields a `RiskGate` with the exact
  `check(orders, state, prices)` contract `PaperTradingSession(risk_gate=…)` expects,
  so the M12 gate uses M13 **by injection, with zero change to certified M12 code**.
- **M9** — `validate_risk(report, m9_verdict=…)` folds the statistical verdict into
  the deployment decision; risk becomes a first-class deployment gate.
- **M7** — `attach_risk` writes risk metrics + a hash-recorded JSON artifact onto the
  existing experiment (research → sim → paper → risk provenance).

## Point-in-time / determinism

No RNG. Historical VaR is an empirical quantile of the supplied realized series;
parametric VaR uses hard-coded normal z-scores (no scipy); stress shocks are fixed.
All factor/covariance inputs are injected by the caller, so PIT-safety is inherited
from M6/M10/M11 upstream. Identical inputs → identical `fingerprint(report)`.

## Analytics implemented

Exposure (gross/net/long/short/cash, sector/industry/country/currency interfaces);
concentration (HHI, effective holdings, largest weight & risk contribution, top5);
covariance (sample/diagonal/shrinkage/EWMA/factor, DI); VaR + ES (historical &
parametric, 95/97.5/99%, √t horizon); factor risk (CAPM/FF/custom betas,
factor/specific risk, R²); drawdown (max/avg/current/rolling + halt); liquidity
(ADV participation, days-to-liquidate, illiquid weight); capacity (dollar capacity,
utilization); limits (11 pre-trade/portfolio checks); monitoring (6 event types).

## Validation

`portfolio_health` → 0–100 composite (penalizes hard/soft violations + halt);
`deployment_risk_decision` deployable only if risk ≠ REJECT **and** M9 ∈
{PASS, PASS_WITH_WARNINGS}. `validate_risk` bundles both into a
`RiskValidationResult`.

## Tests

`tests/research/test_risk.py` — **74 tests**: exposure, concentration, all 5
covariance estimators, VaR/ES (monotonicity, ES≥VaR, horizon scaling), stress
(historical + custom + sector + short book), drawdown + halt, liquidity/capacity,
factor framework (CAPM/custom/FF), limits (hard/soft/disabled), engine decisions,
pre-trade gate **including live M12 session integration**, monitoring, validation,
registry, serialization/determinism, edge cases. Full suite: **862 passed, 3
skipped, zero regressions**.

## Benchmarks

`scripts/benchmark_risk.py`:

| N | assess | VaR | stress | monitor(12) | peak mem |
|---|---|---|---|---|---|
| 100 | 25.2 ms | 0.13 ms | 0.03 ms | 0.05 ms | 1.3 MB |
| 1,000 | 9.3 ms | 0.12 ms | 0.29 ms | 0.04 ms | 2.1 MB |
| 10,000 | 85.7 ms | 0.12 ms | 2.97 ms | 0.04 ms | 20.5 MB |

Scale-safe by design: no dense N×N covariance is materialised (realized portfolio
vol is O(N·T); risk contributions are the O(N) diagonal model), so memory stays
linear (20.5 MB at 10k) and assess stays sub-100 ms.

## Limitations / Known gaps

- **Correlation in risk contributions is diagonal.** Portfolio *volatility* is
  correlation-aware (realized series), but per-name *risk contribution* uses the O(N)
  diagonal model to stay scale-safe. *Unblock:* inject a dense covariance for small-N
  books where full marginal-contribution decomposition is wanted.
- **Classification exposures are interfaces.** Sector/industry/country/currency
  aggregation runs only when a `{security_id: label}` map is injected; none is bundled
  (the SecurityMaster classification gap noted since M9). *Unblock:* a PIT
  classification source.
- **Factor/market data not bundled.** CAPM/Fama-French need injected factor-return
  series; none ship. *Unblock:* a PIT factor-return provider.
- **Stress scenarios are equity-shock approximations.** 2008/2020/2022 use
  peak-to-trough market shocks with per-name beta; full multi-factor scenario
  revaluation needs a factor-shock × exposure matrix. *Unblock:* a Barra-style
  exposure matrix.

Nothing requested was skipped; the above are honest data/dependency gaps with named
unblocks, per the project skip rule.

## Future extensions

Designed seams for: Barra models (factor-covariance interface + exposure matrix),
real-time risk (the pure `assess` is callable per tick), options Greeks / margin /
borrow costs / multi-currency (additional exposure dimensions on `ExposureReport`),
portfolio insurance & automatic deleveraging (drive off `RiskDecision`/halt),
ML risk models (a new `CovarianceEstimator` / `FactorModel` implementation).

## Commit hash

`<filled at commit>` (branch `aidp/audit-and-pit-gaps`).

## Recommendation for next milestone

**M14 — Live Execution & Order Management (OMS/EMS).** With risk (M13) now gating
paper trading (M12), the natural next capability is a real execution layer: broker
adapters implemented (beyond M12 stubs), smart order routing, child-order scheduling
(VWAP/TWAP/POV), and live fill handling — with the M13 gate enforced pre-route.
