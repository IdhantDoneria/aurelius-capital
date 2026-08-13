"""PortfolioEngine — validated signals → implementable portfolios (AIDP M10).

Strictly separates alpha (the input signal) from construction (sizing, risk,
constraints, costs). Strategy-agnostic, optimizer-agnostic (DI), deterministic, and
reproducible through the M7 registry. Never rebuilds prices/fundamentals/
universe/insider data — it consumes the M6 research matrix and given inputs.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

import numpy as np

from mentisrex.research.portfolio.constraints import ConstraintSet
from mentisrex.research.portfolio.diagnostics import build_diagnostics
from mentisrex.research.portfolio.models import Portfolio, PortfolioPosition
from mentisrex.research.portfolio.objectives import DEFINITIONS, Objective
from mentisrex.research.portfolio.risk import diagonal_risk_diagnostics
from mentisrex.research.portfolio.solvers.base import l1_normalize
from mentisrex.research.portfolio.optimizer import (
    CovarianceEstimator,
    ExpectedReturnModel,
    SampleCovariance,
    SignalExpectedReturns,
)
from mentisrex.research.portfolio.solvers import SOLVER_REGISTRY
from mentisrex.research.portfolio.solvers.base import Solver

_DEFAULT_ANNUAL_VAR = 0.04


class PortfolioEngine:
    def __init__(self, *, expected_return_model: ExpectedReturnModel | None = None,
                 cov_estimator: CovarianceEstimator | None = None) -> None:
        self._er = expected_return_model or SignalExpectedReturns()
        self._cov_est = cov_estimator or SampleCovariance()

    def construct(self, signals: dict, universe, constraints: ConstraintSet,
                  objective, as_of: date | None = None, *,
                  covariance=None, returns_matrix=None, vols=None, prices=None,
                  current_weights=None, benchmark_weights=None, solver: Solver | None = None,
                  sectors=None, adv=None, cost_model=None, capital: float = 1e7,
                  tracking_error_budget: float = 0.05) -> Portfolio:
        ids = [u["security_id"] if isinstance(u, dict) else u for u in universe]
        n = len(ids)
        if n == 0:
            return Portfolio(date=as_of, positions=[], metadata={"empty": True})

        signal = np.array([_finite(signals.get(sid, 0.0)) for sid in ids], dtype=float)
        mu = np.asarray(self._er.estimate(signal), dtype=float)

        obj = Objective(objective) if not isinstance(objective, Objective) else objective
        bench = np.asarray(benchmark_weights, dtype=float) if benchmark_weights is not None else None
        ctx = {"benchmark_weights": bench, "tracking_error_budget": tracking_error_budget}

        # dense path only when a real covariance/returns matrix is supplied; otherwise
        # a diagonal risk model solved in O(N) (never materialize an N×N for 10k names).
        dense = covariance is not None or returns_matrix is not None
        if dense:
            cov = self._covariance(covariance, returns_matrix, vols, n)
            solver = solver or SOLVER_REGISTRY[obj.value]()
            raw = solver.solve(mu, cov, ctx=ctx)
        else:
            var = np.asarray(vols, dtype=float) ** 2 if vols is not None else np.full(n, _DEFAULT_ANNUAL_VAR)
            raw = (solver.solve(mu, np.diag(var), ctx=ctx) if solver is not None
                   else _diagonal_solve(mu, var, obj, bench, tracking_error_budget))
        w = constraints.enforce(raw)

        prev = _align(current_weights, ids)
        turnover = 0.5 * float(np.abs(w - prev).sum())
        gross = float(np.abs(w).sum())
        net = float(w.sum())
        exp_ret = float(w @ mu)
        exp_risk = (float(np.sqrt(max(w @ cov @ w, 0.0))) if dense
                    else float(np.sqrt(max((w**2 * var).sum(), 0.0))))

        adv_vec = _align(adv, ids) if adv is not None else None
        cost = None
        participation = None
        if cost_model is not None and current_weights is not None:
            trade_notional = np.abs(w - prev) * capital
            cost = cost_model.estimate(trade_notional, adv_vec)
            if adv_vec is not None:
                participation = np.divide(trade_notional, adv_vec,
                                          out=np.zeros_like(trade_notional), where=adv_vec > 0)

        px = _align(prices, ids, default=None)
        positions = []
        for i, sid in enumerate(ids):
            price = px[i] if px is not None and px[i] is not None else None
            shares = (w[i] * capital / price) if (price and price > 0) else 0.0
            mv = shares * price if price else w[i] * capital
            positions.append(PortfolioPosition(
                security_id=sid, weight=float(w[i]), shares=float(shares), price=price,
                market_value=float(mv), target_weight=float(raw[i] if i < raw.size else 0.0),
                current_weight=float(prev[i])))

        if dense:
            diag = build_diagnostics(w, cov, mu, sectors=sectors, cost=cost, turnover=turnover)
        else:
            diag = diagonal_risk_diagnostics(w, var, mu)
            if turnover is not None:
                diag["turnover"] = turnover
            if cost is not None:
                diag["cost"] = cost
        return Portfolio(
            date=as_of, positions=positions, gross_exposure=gross, net_exposure=net,
            turnover=turnover, cash=float(capital * (1 - gross)),
            expected_return=exp_ret, expected_risk=exp_risk, diagnostics=diag,
            metadata={
                "objective": obj.value, "solver": solver.name if solver is not None else "diagonal_analytic",
                "objective_spec": DEFINITIONS.get(obj.value, {}),
                "constraints": _constraints_dict(constraints),
                "covariance_method": type(self._cov_est).__name__ if covariance is None and returns_matrix is not None
                else ("provided" if covariance is not None else ("diagonal_vols" if vols is not None else "default")),
                "expected_return_model": type(self._er).__name__,
                "capital": capital, "n_universe": n, "participation": participation.tolist() if participation is not None else None,
                "as_of": as_of.isoformat() if as_of else None,
            })

    # ── helpers ──────────────────────────────────────────────────────────────

    def _covariance(self, covariance, returns_matrix, vols, n) -> np.ndarray:
        if covariance is not None:
            return np.asarray(covariance, dtype=float)
        if returns_matrix is not None:
            return np.asarray(self._cov_est.estimate(returns_matrix), dtype=float)
        if vols is not None:
            v = np.asarray(vols, dtype=float)
            return np.diag(v**2)
        return np.eye(n) * (_DEFAULT_ANNUAL_VAR)


def _diagonal_solve(mu, var, obj: Objective, bench, te_budget: float) -> np.ndarray:
    """Closed-form O(N) weights under a diagonal (uncorrelated) risk model — the
    large-universe fast path. Matches the dense solvers when Σ is diagonal."""
    var = np.clip(np.asarray(var, dtype=float), 1e-16, None)
    n = mu.size
    if obj == Objective.EQUAL_WEIGHT:
        w = np.ones(n)
    elif obj == Objective.MIN_VARIANCE:
        w = 1.0 / var                                  # Σ⁻¹1 with diagonal Σ
    elif obj == Objective.MAX_SHARPE:
        w = mu / var                                   # Σ⁻¹μ
    elif obj in (Objective.RISK_PARITY, Objective.MAX_DIVERSIFICATION):
        w = 1.0 / np.sqrt(var)                         # equal RC / max DR when uncorrelated
    elif obj == Objective.TRACKING_ERROR and bench is not None:
        tilt = mu / var
        denom = np.sqrt(max((tilt**2 * var).sum(), 1e-16))
        w = np.asarray(bench, dtype=float) + te_budget * tilt / denom
    else:
        w = mu / var
    return l1_normalize(w)


# ── integration helpers ─────────────────────────────────────────────────────────

def signals_from_matrix(matrix, column: str, *, universe=None) -> dict:
    """Extract a return-aligned signal from a M6 ResearchMatrix column. Applies
    the registered direction ('lower' → negate) so the signal points toward higher
    expected return. Never rebuilds any upstream data."""
    frame = matrix.frame
    if column not in frame.columns:
        raise KeyError(f"'{column}' not in research matrix")
    sign = -1.0 if matrix.directions.get(column) == "lower" else 1.0
    ids = universe or list(frame.index)
    out = {}
    for sid in ids:
        if sid in frame.index:
            val = frame.loc[sid, column]
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                out[sid] = sign * float(val)
    return out


def record_portfolio(registry, experiment, portfolio: Portfolio, *, optimizer_name: str,
                     constraints: ConstraintSet, cost_model=None, rebalance=None) -> None:
    """Capture the portfolio config + key metrics in the M7 registry (via the
    existing store — no schema change)."""
    if registry is None or experiment is None:
        return
    exp = registry.load(experiment.experiment_id) or experiment
    exp.metrics = {**(exp.metrics or {}),
                   "PortfolioTurnover": portfolio.turnover,
                   "PortfolioGrossExposure": portfolio.gross_exposure,
                   "PortfolioExpectedRisk": portfolio.expected_risk,
                   "PortfolioEffectiveHoldings": portfolio.diagnostics.get("effective_holdings", 0.0)}
    cfg = {"optimizer": optimizer_name, "objective": portfolio.metadata.get("objective"),
           "constraints": _constraints_dict(constraints),
           "cost_model": asdict(cost_model) if cost_model is not None else None,
           "rebalance": asdict(rebalance) if rebalance is not None else None}
    exp.notes = f"portfolio objective={cfg['objective']} optimizer={optimizer_name} turnover={portfolio.turnover:.3f}"
    exp.parameters = {**(exp.parameters or {}), "portfolio_config": cfg}
    # full upsert (update_run persists metrics/status but not parameter_sets); insert
    # round-trips every satellite table from the loaded experiment.
    registry.store.insert(exp)


def _finite(x) -> float:
    try:
        v = float(x)
        return 0.0 if (v != v) else v
    except (TypeError, ValueError):
        return 0.0


def _align(values, ids, default=0.0):
    if values is None:
        return np.zeros(len(ids)) if default == 0.0 else [None] * len(ids)
    if isinstance(values, dict):
        arr = [values.get(sid, default if default is not None else 0.0) for sid in ids]
    else:
        arr = list(values)
    if default is None:
        return arr
    return np.array([float(a) for a in arr], dtype=float)


def _constraints_dict(constraints: ConstraintSet) -> dict:
    return asdict(constraints)
