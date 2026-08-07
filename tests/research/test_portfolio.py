"""Portfolio Construction & Optimization regression (AIDP M10). All offline.

Equal-weight, constraints (position/turnover/long-only/leverage/liquidity), cost
model, risk contributions, optimizer DI, determinism, and registry / execution /
validation integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, date

import numpy as np
import pandas as pd
import pytest

from aurelius.market_data.research_matrix.schema import ResearchMatrix
from aurelius.research.portfolio import (
    ConstraintSet,
    Objective,
    Optimizer,
    PortfolioEngine,
    TransactionCostModel,
    record_portfolio,
    signals_from_matrix,
    validate_portfolio,
)
from aurelius.research.portfolio.risk import risk_diagnostics
from aurelius.research.portfolio.solvers.base import Solver
from aurelius.research.experiment_registry import ExperimentRegistry, RegistryStore, lineage

N = 20
IDS = [f"S{i:03d}" for i in range(N)]


def _cov(seed=0):
    rng = np.random.default_rng(seed)
    R = rng.normal(0.0005, 0.01, size=(300, N))
    return np.cov(R, rowvar=False)


def _signals(seed=1):
    rng = np.random.default_rng(seed)
    return {s: float(rng.normal()) for s in IDS}


@pytest.fixture
def engine():
    return PortfolioEngine()


# 1. equal weight ────────────────────────────────────────────────────────────────

def test_equal_weight(engine):
    p = engine.construct(_signals(), IDS, ConstraintSet(), Objective.EQUAL_WEIGHT, covariance=_cov())
    w = [pos.weight for pos in p.positions]
    assert all(abs(x - 1.0 / N) < 1e-9 for x in w)
    assert abs(p.gross_exposure - 1.0) < 1e-9 and p.n_positions == N


# 2. max position constraint ──────────────────────────────────────────────────────

def test_max_position_constraint(engine):
    c = ConstraintSet(max_position_weight=0.08, long_only=True)
    p = engine.construct(_signals(), IDS, c, Objective.MAX_SHARPE, covariance=_cov())
    assert max(abs(pos.weight) for pos in p.positions) <= 0.08 + 1e-9


# 3. turnover constraint ──────────────────────────────────────────────────────────

def test_turnover(engine):
    current = {s: 1.0 / N for s in IDS}
    p = engine.construct(_signals(), IDS, ConstraintSet(), Objective.EQUAL_WEIGHT,
                         covariance=_cov(), current_weights=current)
    assert p.turnover == pytest.approx(0.0, abs=1e-9)          # already equal-weight
    p2 = engine.construct(_signals(), IDS, ConstraintSet(max_position_weight=0.15),
                          Objective.MAX_SHARPE, covariance=_cov(), current_weights=current)
    assert p2.turnover > 0
    v = validate_portfolio(p2, ConstraintSet(max_turnover=0.01))
    assert "turnover_violation" in v["constraint_violations"]


# 4. cost model ────────────────────────────────────────────────────────────────────

def test_cost_model():
    cm = TransactionCostModel(commission_bps=1.0, spread_bps=2.0, slippage_bps=1.0, impact_coef=0.1)
    assert cm.linear_bps() == pytest.approx(3.0)               # 1 + 2/2 + 1
    out = cm.estimate([1e6], adv=[1e8])
    assert out["linear_cost"] == pytest.approx(300.0)          # 3bps * 1e6
    assert out["impact_cost"] == pytest.approx(10_000.0)       # 0.1*sqrt(0.01)*1e6
    assert out["total_cost"] == pytest.approx(10_300.0)


# 5. risk contribution ─────────────────────────────────────────────────────────────

def test_risk_contribution():
    cov = _cov()
    w = np.full(N, 1.0 / N)
    d = risk_diagnostics(w, cov)
    assert sum(d["risk_contribution"]) == pytest.approx(d["volatility"], rel=1e-9)
    assert d["effective_holdings"] == pytest.approx(N, rel=1e-9)  # equal weight → N
    assert sum(d["pct_risk_contribution"]) == pytest.approx(1.0, rel=1e-9)


# 6. optimizer interface (DI) ──────────────────────────────────────────────────────

def test_optimizer_interface(engine):
    class ReverseSolver(Solver):
        name = "reverse"
        def solve(self, mu, cov, *, ctx=None):
            w = np.arange(1, mu.size + 1, dtype=float)
            return w / w.sum()

    opt = Optimizer(ReverseSolver(), ConstraintSet(max_position_weight=0.2))
    w = opt.optimize(np.zeros(N), _cov())
    assert w.max() <= 0.2 + 1e-9 and abs(np.abs(w).sum() - 1.0) < 1e-9
    # injected into the engine
    p = engine.construct(_signals(), IDS, ConstraintSet(), Objective.EQUAL_WEIGHT,
                         covariance=_cov(), solver=ReverseSolver())
    assert p.metadata["solver"] == "reverse"


# 7. long-only ─────────────────────────────────────────────────────────────────────

def test_long_only(engine):
    p = engine.construct(_signals(), IDS, ConstraintSet(long_only=True), Objective.MAX_SHARPE,
                         covariance=_cov())
    assert all(pos.weight >= -1e-12 for pos in p.positions)


# 8. leverage ──────────────────────────────────────────────────────────────────────

def test_leverage(engine):
    c = ConstraintSet(long_only=False, gross_exposure=1.5, max_leverage=1.5, max_position_weight=0.3)
    p = engine.construct(_signals(), IDS, c, Objective.MAX_SHARPE, covariance=_cov())
    assert p.gross_exposure <= 1.5 + 1e-6


# 9. liquidity constraint ──────────────────────────────────────────────────────────

def test_liquidity(engine):
    current = {s: 0.0 for s in IDS}
    cm = TransactionCostModel()
    c = ConstraintSet(max_position_weight=0.15, max_adv_participation=0.05)
    p = engine.construct(_signals(), IDS, c, Objective.MAX_SHARPE, covariance=_cov(),
                         current_weights=current, cost_model=cm,
                         adv={s: 1e5 for s in IDS}, capital=1e8)
    part = np.array(p.metadata["participation"])
    v = validate_portfolio(p, c, participation=part)
    assert "adv_participation_violation" in v["constraint_violations"]   # tiny ADV → breach


# 10. deterministic reproduction ───────────────────────────────────────────────────

def test_deterministic(engine):
    a = engine.construct(_signals(), IDS, ConstraintSet(max_position_weight=0.15),
                         Objective.RISK_PARITY, covariance=_cov())
    b = engine.construct(_signals(), IDS, ConstraintSet(max_position_weight=0.15),
                         Objective.RISK_PARITY, covariance=_cov())
    assert [p.weight for p in a.positions] == [p.weight for p in b.positions]


# 11. registry integration ─────────────────────────────────────────────────────────

def test_registry_integration(engine):
    reg = ExperimentRegistry(store=RegistryStore(":memory:"))
    try:
        dv = lineage.dataset_versions(prices=1, fundamentals=1, insiders=1, universe=1,
                                      securitymaster=1, feature_registry_version="fr1")
        exp = reg.start_experiment("pf", parameters={"lookback": 5}, features=["market_cap"],
                                   dataset_versions=dv, random_seed=1)
        reg.finish_experiment(exp, metrics={"Sharpe": 1.0})
        p = engine.construct(_signals(), IDS, ConstraintSet(max_position_weight=0.15),
                             Objective.MIN_VARIANCE, covariance=_cov())
        record_portfolio(reg, exp, p, optimizer_name="min_variance",
                         constraints=ConstraintSet(max_position_weight=0.15))
        reloaded = reg.load(exp.experiment_id)
        assert "PortfolioTurnover" in reloaded.metrics
        assert reloaded.parameters["portfolio_config"]["objective"] == "min_variance"
    finally:
        reg.close()


# 12. execution platform integration ───────────────────────────────────────────────

def test_execution_integration():
    from aurelius.research.execution import ResearchRunner, RunConfiguration
    from aurelius.backtesting.analytics.performance import PerformanceMetrics, EquityPoint

    reg = ExperimentRegistry(store=RegistryStore(":memory:"))
    try:
        curve = [EquityPoint(datetime(2020, 1, 1, tzinfo=UTC), 1e6),
                 EquityPoint(datetime(2020, 1, 2, tzinfo=UTC), 1.01e6)]

        def executor(session):
            class R:
                metrics = PerformanceMetrics(daily_returns=[0.01], equity_curve=curve)
            return R()

        runner = ResearchRunner(registry=reg)
        dv = lineage.dataset_versions(prices=1, fundamentals=1, insiders=1, universe=1,
                                      securitymaster=1, feature_registry_version="fr1")
        cfg = RunConfiguration(name="e2e", parameters={"lookback": 5}, features=["market_cap"],
                               dataset_versions=dv, random_seed=1, executor=executor)
        session = runner.run(cfg)
        # portfolio construction consuming the completed session's experiment
        p = PortfolioEngine().construct(_signals(), IDS, ConstraintSet(max_position_weight=0.2),
                                        Objective.EQUAL_WEIGHT, covariance=_cov())
        record_portfolio(reg, session.experiment, p, optimizer_name="equal_weight",
                         constraints=ConstraintSet(max_position_weight=0.2))
        assert reg.load(session.experiment_id).metrics.get("PortfolioGrossExposure") == pytest.approx(1.0)
    finally:
        reg.close()


# 13. validation framework integration + matrix signal ─────────────────────────────

def test_validation_and_matrix_integration(engine):
    frame = pd.DataFrame({"market_cap": np.linspace(1, 2, N), "leverage": np.linspace(2, 1, N)},
                         index=IDS)
    matrix = ResearchMatrix(as_of_date=date(2020, 6, 30), universe_size=N, data_versions={},
                            generated_at=datetime(2020, 6, 30, tzinfo=UTC), frame=frame,
                            directions={"market_cap": "higher", "leverage": "lower"})
    sig = signals_from_matrix(matrix, "leverage")           # 'lower' → negated
    assert sig[IDS[0]] == pytest.approx(-2.0)               # highest leverage → most negative signal
    p = engine.construct(sig, IDS, ConstraintSet(max_position_weight=0.15), Objective.MAX_SHARPE,
                         covariance=_cov())
    checks = validate_portfolio(p, ConstraintSet(max_position_weight=0.15, max_turnover=1.0),
                                cost={"total_cost_bps": 12.0})
    assert checks["ok"] and checks["concentration"]["ok"]
    assert "cost_impact_bps" in checks
