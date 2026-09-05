"""AIDP M13 — Institutional Risk Engine tests.

Deterministic, offline. Covers risk analytics, limits, the pre-trade gate (incl.
M12 integration), VaR, stress, drawdown, exposure, factor framework, covariance
estimators, monitoring, validation, registry, serialization, and edge cases.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import ClassVar

import numpy as np
import pytest

import mentisrex.research.risk as risk
from mentisrex.research.risk.engine import RiskEngine, RiskEngineConfig
from mentisrex.research.risk.limits import RiskLimits
from mentisrex.research.risk.models import RiskDecision

RNG = np.random.default_rng(7)


def _returns(ids, T=300):
    return {s: RNG.normal(0.0004, 0.02, T) for s in ids}


def _eng(**lim):
    return RiskEngine(RiskEngineConfig(limits=RiskLimits(**lim)))


# ── exposure ─────────────────────────────────────────────────────────────────


def test_exposure_long_only():
    e = risk.exposure_report({"A": 0.6, "B": 0.4})
    assert e.gross == pytest.approx(1.0)
    assert e.net == pytest.approx(1.0)
    assert e.long == pytest.approx(1.0)
    assert e.short == 0.0
    assert e.cash == pytest.approx(0.0)
    assert e.n_long == 2
    assert e.n_short == 0


def test_exposure_long_short():
    e = risk.exposure_report({"A": 0.6, "B": -0.4})
    assert e.gross == pytest.approx(1.0)
    assert e.net == pytest.approx(0.2)
    assert e.short == pytest.approx(0.4)
    assert e.n_short == 1


def test_exposure_cash_when_underinvested():
    e = risk.exposure_report({"A": 0.5})
    assert e.cash == pytest.approx(0.5)


def test_exposure_sector_grouping():
    e = risk.exposure_report({"A": 0.5, "B": 0.5}, sectors={"A": "tech", "B": "tech"})
    assert e.sector["tech"] == pytest.approx(1.0)


def test_exposure_empty():
    e = risk.exposure_report({})
    assert e.gross == 0.0
    assert e.n_long == 0


# ── concentration ────────────────────────────────────────────────────────────


def test_concentration_equal_weight():
    c = risk.concentration_report({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
    assert c.herfindahl == pytest.approx(0.25)
    assert c.effective_holdings == pytest.approx(4.0)


def test_concentration_single_name():
    c = risk.concentration_report({"A": 1.0})
    assert c.herfindahl == pytest.approx(1.0)
    assert c.effective_holdings == pytest.approx(1.0)
    assert c.largest_weight == pytest.approx(1.0)


def test_concentration_top5():
    w = {f"S{i}": 0.1 for i in range(10)}
    c = risk.concentration_report(w)
    assert c.top5_weight == pytest.approx(0.5)


def test_concentration_largest_contribution():
    c = risk.concentration_report({"A": 0.5, "B": 0.5}, risk_contribution={"A": 0.8, "B": 0.2})
    assert c.largest_contribution == pytest.approx(0.8)


# ── covariance estimators ────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["sample", "diagonal", "shrinkage", "ewma", "factor"])
def test_covariance_shape_and_symmetry(kind):
    X = RNG.normal(0, 0.02, (200, 6))
    C = risk.make_covariance(kind).estimate(X)
    assert C.shape == (6, 6)
    assert np.allclose(C, C.T, atol=1e-10)


def test_covariance_diagonal_is_diagonal():
    X = RNG.normal(0, 0.02, (200, 5))
    C = risk.make_covariance("diagonal").estimate(X)
    assert np.allclose(C - np.diag(np.diag(C)), 0.0)


def test_covariance_shrinkage_well_conditioned():
    X = RNG.normal(0, 0.02, (30, 20))  # T < N → sample is singular
    C = risk.make_covariance("shrinkage").estimate(X)
    assert np.linalg.cond(C) < np.linalg.cond(np.cov(X, rowvar=False) + 1e-12 * np.eye(20))


def test_covariance_ewma_weights_recent():
    C = risk.make_covariance("ewma", lam=0.9).estimate(RNG.normal(0, 0.02, (100, 4)))
    assert C.shape == (4, 4)


def test_covariance_factor_fallback_without_factors():
    X = RNG.normal(0, 0.02, (100, 4))
    C = risk.make_covariance("factor").estimate(X)  # no factor_returns → diagonal base
    assert C.shape == (4, 4)


def test_covariance_factor_with_factors():
    X = RNG.normal(0, 0.02, (150, 5))
    F = RNG.normal(0, 0.01, (150, 2))
    C = risk.make_covariance("factor", factor_returns=F).estimate(X)
    assert C.shape == (5, 5)
    assert np.all(np.diag(C) > 0)


def test_covariance_unknown_raises():
    with pytest.raises(ValueError):
        risk.make_covariance("nope")


# ── VaR / ES ─────────────────────────────────────────────────────────────────


def test_historical_var_monotone_in_confidence():
    r = RNG.normal(0.0003, 0.015, 500)
    v = risk.historical_var(r)
    assert v.var["95%"] <= v.var["97.5%"] <= v.var["99%"]


def test_expected_shortfall_exceeds_var():
    r = RNG.normal(0.0, 0.02, 1000)
    v = risk.historical_var(r)
    assert v.expected_shortfall["99%"] >= v.var["99%"]


def test_parametric_var_positive():
    r = RNG.normal(0.0, 0.02, 500)
    v = risk.parametric_var(r)
    assert all(x >= 0 for x in v.var.values())
    assert v.method == "parametric"


def test_var_horizon_scaling():
    r = RNG.normal(0.0, 0.02, 500)
    v1 = risk.parametric_var(r, horizon_days=1).var["99%"]
    v4 = risk.parametric_var(r, horizon_days=4).var["99%"]
    assert v4 == pytest.approx(2.0 * v1, rel=1e-6)


def test_var_empty_returns():
    v = risk.historical_var([])
    assert v.var["95%"] == 0.0


# ── stress testing ───────────────────────────────────────────────────────────


def test_stress_historical_scenarios_present():
    assert {"gfc_2008", "covid_2020", "inflation_2022"} <= set(risk.HISTORICAL_SCENARIOS)


def test_stress_long_book_loses_in_crash():
    st = risk.stress_test({"A": 0.5, "B": 0.5}, betas={"A": 1.0, "B": 1.0})
    assert st.worst_pnl_fraction < 0
    assert st.worst_scenario == "gfc_2008"


def test_stress_short_book_gains_in_crash():
    r = risk.apply_scenario({"A": -1.0}, risk.HISTORICAL_SCENARIOS["gfc_2008"], betas={"A": 1.0})
    assert r.pnl_fraction > 0


def test_stress_custom_scenario_breach_flag():
    from mentisrex.research.risk.models import StressScenario

    r = risk.apply_scenario(
        {"A": 1.0}, StressScenario("big", market_shock=-0.5), betas={"A": 1.0}, halt_threshold=-0.2
    )
    assert r.breached


def test_stress_sector_shock():
    from mentisrex.research.risk.models import StressScenario

    s = StressScenario("tech_selloff", sector_shocks={"tech": -0.3})
    r = risk.apply_scenario({"A": 1.0}, s, sectors={"A": "tech"})
    assert r.pnl_fraction == pytest.approx(-0.3)


# ── drawdown ─────────────────────────────────────────────────────────────────


def test_drawdown_basic():
    vals = [100, 110, 90, 95, 80, 120]
    d = risk.drawdown_report(vals)
    assert d.max_drawdown < 0
    assert d.current_drawdown == pytest.approx(0.0)  # ends at new high


def test_drawdown_halt_triggers():
    vals = [100, 100, 50]  # -50% current drawdown
    d = risk.drawdown_report(vals, halt_threshold=-0.25)
    assert d.halt_triggered


def test_should_halt_helper():
    assert risk.should_halt([100, 60], halt_threshold=-0.25)
    assert not risk.should_halt([100, 99], halt_threshold=-0.25)


def test_drawdown_empty():
    d = risk.drawdown_report([])
    assert d.max_drawdown == 0.0
    assert not d.halt_triggered


# ── liquidity / capacity ─────────────────────────────────────────────────────


def test_liquidity_participation_and_days():
    r = risk.liquidity_report({"A": 1.0}, {"A": 1e6}, portfolio_value=1e5)
    assert r.max_participation == pytest.approx(0.1)  # 100k / 1M
    assert r.max_days_to_liquidate == pytest.approx(1.0)  # 0.1 / 0.10 limit


def test_liquidity_illiquid_name_flagged():
    r = risk.liquidity_report(
        {"A": 1.0}, {"A": 1e4}, portfolio_value=1e6, liquidation_days_threshold=5.0
    )
    assert r.illiquid_weight == pytest.approx(1.0)
    assert r.liquidity_signal in ("warning", "critical")


def test_liquidity_missing_adv_is_infinite_days():
    r = risk.liquidity_report({"A": 1.0}, {}, portfolio_value=1e6)
    assert r.max_days_to_liquidate >= 1e9


def test_capacity_utilization():
    c = risk.capacity_report({"A": 1.0}, {"A": 1e8}, aum=1e6, participation_limit=0.1)
    assert c.capacity_usd == pytest.approx(1e7)
    assert c.utilization == pytest.approx(0.1)


def test_capacity_signal_critical_when_over():
    c = risk.capacity_report({"A": 1.0}, {"A": 1e6}, aum=1e9)
    assert c.capacity_signal == "critical"


# ── factor framework ─────────────────────────────────────────────────────────


def test_capm_factor_decomposition():
    ids = ["A", "B", "C"]
    R = np.column_stack([RNG.normal(0, 0.02, 250) for _ in ids])
    fe = risk.CAPMModel().analyze(
        {"A": 0.4, "B": 0.3, "C": 0.3}, R, {"market_returns": RNG.normal(0, 0.015, 250)}
    )
    assert fe.model == "capm"
    assert "market" in fe.betas
    assert fe.factor_risk >= 0
    assert fe.specific_risk >= 0
    assert 0.0 <= fe.r_squared <= 1.0


def test_capm_requires_market_returns():
    with pytest.raises(ValueError):
        risk.CAPMModel().analyze({"A": 1.0}, RNG.normal(0, 0.02, (100, 1)), {})


def test_custom_factor_model():
    R = RNG.normal(0, 0.02, (200, 3))
    F = RNG.normal(0, 0.01, (200, 2))
    fe = risk.CustomFactorModel().analyze(
        {"A": 0.5, "B": 0.3, "C": 0.2}, R, {"factor_returns": F, "factor_names": ["mom", "val"]}
    )
    assert set(fe.betas) == {"mom", "val"}


def test_fama_french_is_custom():
    assert issubclass(risk.FamaFrenchModel, risk.CustomFactorModel)


# ── limits ───────────────────────────────────────────────────────────────────


def test_limits_hard_breach():
    v = RiskLimits(max_position=0.1).evaluate({"max_position": 0.3})
    assert len(v) == 1
    assert v[0].severity == "hard"


def test_limits_soft_breach():
    v = RiskLimits(max_turnover=0.5).evaluate({"turnover": 0.9})
    assert v[0].severity == "soft"


def test_limits_disabled_when_none():
    assert RiskLimits(max_volatility=None).evaluate({"volatility": 5.0}) == []


def test_limits_none_metric_skipped():
    assert RiskLimits(max_volatility=0.1).evaluate({"volatility": None}) == []


# ── engine assess / decision ─────────────────────────────────────────────────


def test_assess_clean_approves():
    ids = ["A", "B", "C", "D"]
    rep = _eng(max_position=0.5).assess(
        {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}, returns=_returns(ids), portfolio_value=1e6
    )
    assert rep.decision == RiskDecision.APPROVE
    assert rep.volatility > 0
    assert rep.var is not None


def test_assess_hard_violation_rejects():
    rep = _eng(max_position=0.5).assess(
        {"A": 0.9, "B": 0.1}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )
    assert rep.decision == RiskDecision.REJECT


def test_assess_soft_violation_warns():
    rep = _eng(max_position=1.0, max_concentration=0.3).assess(
        {"A": 0.6, "B": 0.4}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )
    assert rep.decision == RiskDecision.APPROVE_WITH_WARNING


def test_assess_risk_contribution_sums_to_one():
    ids = ["A", "B", "C"]
    rep = _eng(max_position=1.0).assess(
        {"A": 0.5, "B": 0.3, "C": 0.2}, returns=_returns(ids), portfolio_value=1e6
    )
    assert sum(rep.risk_contribution.values()) == pytest.approx(1.0, abs=1e-6)


def test_assess_drawdown_halt_rejects():
    rep = _eng(max_position=1.0).assess(
        {"A": 1.0}, returns=_returns(["A"]), values=[100, 100, 50], portfolio_value=1e6
    )
    assert rep.decision == RiskDecision.REJECT


def test_assess_without_returns_skips_var():
    rep = _eng(max_position=1.0).assess({"A": 0.5, "B": 0.5}, portfolio_value=1e6)
    assert rep.var is None
    assert rep.volatility == 0.0
    assert rep.decision in (RiskDecision.APPROVE, RiskDecision.APPROVE_WITH_WARNING)


def test_assess_factor_when_model_injected():
    ids = ["A", "B"]
    eng = RiskEngine(
        RiskEngineConfig(limits=RiskLimits(max_position=1.0)), factor_model=risk.CAPMModel()
    )
    rep = eng.assess(
        {"A": 0.5, "B": 0.5},
        returns=_returns(ids),
        portfolio_value=1e6,
        factor_ctx={"market_returns": RNG.normal(0, 0.015, 300)},
    )
    assert rep.factor is not None
    assert rep.factor.model == "capm"


# ── pre-trade gate (M12 integration) ─────────────────────────────────────────


def test_gate_approves_within_limits():
    gate = _eng(max_position=0.5).as_gate()
    from mentisrex.research.simulation.models import Order
    from mentisrex.research.simulation.state import PortfolioState

    st = PortfolioState(1e6)
    orders = [Order("A", 4000.0)]  # 40% of 1M at $100
    approved, rejected = gate.check(orders, st, {"A": 100.0})
    assert len(approved) == 1
    assert not rejected


def test_gate_rejects_over_position():
    gate = _eng(max_position=0.1).as_gate()
    from mentisrex.research.simulation.models import Order
    from mentisrex.research.simulation.state import PortfolioState

    st = PortfolioState(1e6)
    approved, rejected = gate.check([Order("A", 9000.0)], st, {"A": 100.0})
    assert not approved
    assert rejected[0][1] == "max_position"


def test_gate_rejects_unpriced():
    gate = _eng().as_gate()
    from mentisrex.research.simulation.models import Order
    from mentisrex.research.simulation.state import PortfolioState

    approved, rejected = gate.check([Order("A", 1.0)], PortfolioState(1e6), {})
    assert not approved
    assert rejected[0][1] == "unpriced"


def test_gate_drops_into_m12_session():
    import mentisrex.research.paper_trading as pt

    gate = _eng(max_position=0.5).as_gate(adv_provider=lambda sid: 5e7)
    prices = {"A": 100.0, "B": 50.0, "C": 25.0}
    sess = pt.PaperTradingSession(broker=pt.MockBroker(initial_cash=1_000_000.0), risk_gate=gate)
    tl = [date(2024, 1, 1) + timedelta(days=30 * i) for i in range(3)]
    sess.run(tl, lambda d: {"A": 0.4, "B": 0.3, "C": 0.3}, lambda s, d: prices[s])
    assert sess.book.weights()["A"] == pytest.approx(0.4, abs=1e-6)
    assert sess.reconciliations[-1].ok


def test_gate_blocks_concentration_in_m12():
    import mentisrex.research.paper_trading as pt

    gate = _eng(max_position=0.1).as_gate()
    sess = pt.PaperTradingSession(broker=pt.MockBroker(initial_cash=1_000_000.0), risk_gate=gate)
    sess.step(date(2024, 1, 1), {"A": 0.9}, {"A": 100.0})
    assert not sess.book.state.holdings


# ── monitoring ───────────────────────────────────────────────────────────────


def test_monitor_timeline_length():
    eng = _eng(max_position=1.0)
    reps = [
        eng.assess(
            {"A": 0.5, "B": 0.5},
            returns=_returns(["A", "B"]),
            portfolio_value=1e6,
            when=date(2024, 1, 1) + timedelta(days=i),
        )
        for i in range(4)
    ]
    m = risk.monitor(reps)
    assert len(m["timeline"]) == 4


def test_monitor_detects_limit_breach():
    eng = _eng(max_position=0.4)
    rep = eng.assess(
        {"A": 0.9, "B": 0.1},
        returns=_returns(["A", "B"]),
        portfolio_value=1e6,
        when=date(2024, 1, 1),
    )
    m = risk.monitor([rep])
    assert any(a.kind == "limit_breach" for a in m["alerts"])


def test_monitor_detects_exposure_drift():
    eng = _eng(max_position=1.0)
    r1 = eng.assess({"A": 0.5}, portfolio_value=1e6, when=date(2024, 1, 1))
    r2 = eng.assess({"A": 0.5, "B": 0.5, "C": 0.5}, portfolio_value=1e6, when=date(2024, 1, 2))
    m = risk.monitor([r1, r2])
    assert any(e.kind == "exposure_drift" for e in m["events"])


# ── validation integration ───────────────────────────────────────────────────


def test_portfolio_health_clean():
    rep = _eng(max_position=1.0).assess(
        {"A": 0.5, "B": 0.5}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )
    h = risk.portfolio_health(rep)
    assert h.healthy
    assert h.score == 100.0


def test_portfolio_health_penalizes_violation():
    rep = _eng(max_position=0.1).assess(
        {"A": 0.9, "B": 0.1}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )
    h = risk.portfolio_health(rep)
    assert not h.healthy
    assert h.score < 100.0


def test_deployment_requires_risk_and_m9():
    rep = _eng(max_position=1.0).assess(
        {"A": 0.5, "B": 0.5}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )
    assert risk.deployment_risk_decision(rep, m9_verdict="PASS").deployable
    assert not risk.deployment_risk_decision(rep, m9_verdict="REJECT").deployable


def test_deployment_blocked_by_risk_reject():
    rep = _eng(max_position=0.1).assess(
        {"A": 0.9, "B": 0.1}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )
    assert not risk.deployment_risk_decision(rep, m9_verdict="PASS").deployable


def test_validate_risk_bundle():
    rep = _eng(max_position=1.0).assess(
        {"A": 0.5, "B": 0.5}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )
    res = risk.validate_risk(rep, m9_verdict="PASS")
    assert res.ok
    assert res.health.healthy
    assert res.deployment.deployable


# ── serialization / determinism ──────────────────────────────────────────────


def test_serialization_roundtrip_stable():
    import json

    from mentisrex.research.risk import serialization

    rep = _eng(max_position=1.0).assess(
        {"A": 0.5, "B": 0.5},
        returns=_returns(["A", "B"]),
        portfolio_value=1e6,
        when=date(2024, 1, 1),
    )
    a = serialization.to_json(rep)
    assert json.loads(a)["decision"] == "approve"


def test_fingerprint_deterministic():
    eng = _eng(max_position=1.0)
    ret = _returns(["A", "B"])
    kw = {"returns": ret, "portfolio_value": 1e6, "when": date(2024, 1, 1)}
    assert risk.fingerprint(eng.assess({"A": 0.5, "B": 0.5}, **kw)) == risk.fingerprint(
        eng.assess({"A": 0.5, "B": 0.5}, **kw)
    )


# ── registry ─────────────────────────────────────────────────────────────────


def test_registry_attach(tmp_path):
    rep = _eng(max_position=1.0).assess(
        {"A": 0.5, "B": 0.5}, returns=_returns(["A", "B"]), portfolio_value=1e6
    )

    class _Store:
        inserted = None

        def insert(self, exp):
            _Store.inserted = exp

    class _Exp:
        experiment_id = "e1"
        metrics: ClassVar[dict] = {}
        artifacts: ClassVar[list] = []
        notes = ""

    class _Reg:
        store = _Store()

        def load(self, _):
            return None

    exp = _Exp()
    out = risk.attach_risk(_Reg(), exp, rep, artifacts_dir=str(tmp_path))
    assert "hash" in out
    assert "RiskDecision" in exp.metrics


def test_registry_noop_without_registry():
    rep = _eng().assess({"A": 1.0}, portfolio_value=1e6)
    assert risk.attach_risk(None, None, rep) == {}


# ── edge cases ───────────────────────────────────────────────────────────────


def test_empty_portfolio():
    rep = _eng().assess({}, portfolio_value=1e6)
    assert rep.exposure.gross == 0.0
    assert rep.decision in (RiskDecision.APPROVE, RiskDecision.APPROVE_WITH_WARNING)


def test_short_returns_series_no_var():
    rep = _eng(max_position=1.0).assess({"A": 1.0}, returns={"A": [0.01]}, portfolio_value=1e6)
    assert rep.var is None  # <2 obs


def test_returns_as_matrix():
    R = RNG.normal(0, 0.02, (100, 2))
    rep = _eng(max_position=1.0).assess({"A": 0.5, "B": 0.5}, returns=R, portfolio_value=1e6)
    assert rep.volatility > 0
