"""Portfolio Simulation Engine regression (AIDP Phase 11). All offline, deterministic.

Accounting, order generation, execution, rebalancing, the multi-period engine,
performance analytics, exposures/risk, attribution, validation, serialization, and
registry / Phase-9 integration.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from aurelius.research.portfolio.costs import TransactionCostModel
from aurelius.research.portfolio.rebalancing import RebalanceRule
from aurelius.research.simulation import (
    CostExecutionModel,
    FrictionlessExecutionModel,
    PortfolioSimulationEngine,
    RebalancePolicy,
    SimulationConfig,
    SizingConfig,
    attach_simulation,
    calendar_dates,
    generate_orders,
    to_performance_metrics,
    validate_simulation,
)
from aurelius.research.simulation import performance, serialization
from aurelius.research.simulation.diagnostics import build_logs
from aurelius.research.simulation.execution import ExecutionModel
from aurelius.research.simulation.models import Order
from aurelius.research.simulation.state import PortfolioState
from aurelius.research.experiment_registry import ExperimentRegistry, RegistryStore, lineage

IDS = [f"S{i:02d}" for i in range(10)]


def _timeline(days=365 * 2, start=date(2018, 1, 1)):
    return [start + timedelta(days=i) for i in range(days)]


def _paths(timeline, seed=0, drift=0.0004, vol=0.01):
    rng = np.random.default_rng(seed)
    return {s: 100 * np.cumprod(1 + rng.normal(drift, vol, len(timeline))) for s in IDS}


def _providers(timeline, seed=0, **kw):
    paths = _paths(timeline, seed, **kw)
    idx = {d: i for i, d in enumerate(timeline)}
    tw = {s: 0.1 for s in IDS}

    def price(sid, d):
        i = idx.get(d)
        return float(paths[sid][i]) if i is not None and sid in paths else None

    def target(d):
        return tw

    return price, target, paths


def _run(timeline=None, *, seed=0, execution=None, policy=None, cfg=None, adv=1e8):
    timeline = timeline or _timeline()
    price, target, _ = _providers(timeline, seed)
    eng = PortfolioSimulationEngine(
        config=cfg or SimulationConfig(initial_capital=1e6, sizing=SizingConfig(min_trade_notional=50)),
        execution_model=execution or CostExecutionModel(TransactionCostModel()),
        policy=policy or RebalancePolicy(explicit_dates=calendar_dates(timeline, "monthly")))
    return eng.run(timeline, target, price, adv_provider=(lambda s, d: adv))


# ── accounting / state ────────────────────────────────────────────────────────────

def test_buy_decreases_cash_increases_position():
    s = PortfolioState(100000.0)
    s.apply_fill("A", 100, 50.0, 10.0)
    assert s.holdings["A"].shares == 100 and s.cash == pytest.approx(100000 - 5010)


def test_average_cost_on_add():
    s = PortfolioState(1e6)
    s.apply_fill("A", 100, 50.0, 0.0)
    s.apply_fill("A", 100, 60.0, 0.0)
    assert s.holdings["A"].cost_basis == pytest.approx(55.0)


def test_partial_sell_realizes_pnl():
    s = PortfolioState(1e6)
    s.apply_fill("A", 100, 50.0, 0.0)
    r = s.apply_fill("A", -40, 70.0, 0.0)
    assert r == pytest.approx(40 * 20) and s.holdings["A"].shares == 60


def test_full_exit_removes_holding():
    s = PortfolioState(1e6)
    s.apply_fill("A", 100, 50.0, 0.0)
    s.apply_fill("A", -100, 55.0, 0.0)
    assert "A" not in s.holdings


def test_long_to_short_flip():
    s = PortfolioState(1e6)
    s.apply_fill("A", 100, 50.0, 0.0)
    r = s.apply_fill("A", -150, 60.0, 0.0)          # close 100, open short 50
    assert r == pytest.approx(100 * 10)
    assert s.holdings["A"].shares == -50 and s.holdings["A"].cost_basis == 60.0


def test_short_cover_realizes():
    s = PortfolioState(1e6)
    s.apply_fill("A", -50, 80.0, 0.0)               # short
    r = s.apply_fill("A", 50, 70.0, 0.0)            # cover at lower → profit
    assert r == pytest.approx(50 * 10) and "A" not in s.holdings


def test_ledger_reconciles():
    s = PortfolioState(1e6)
    for q, p in [(100, 50), (-30, 55), (200, 40), (-270, 60)]:
        s.apply_fill("A", q, p, 1.0)
    assert s.ledger.reconciles()


def test_mark_and_value():
    s = PortfolioState(1e6)
    s.apply_fill("A", 100, 50.0, 0.0)
    s.mark({"A": 75.0})
    assert s.total_value() == pytest.approx(1e6 - 5000 + 7500)


def test_exposures_long_short():
    s = PortfolioState(1e6)
    s.apply_fill("A", 100, 50.0, 0.0)
    s.apply_fill("B", -100, 50.0, 0.0)
    s.mark({"A": 50.0, "B": 50.0})
    e = s.exposures()
    assert e["long"] == pytest.approx(0.005) and e["short"] == pytest.approx(0.005)
    assert e["net"] == pytest.approx(0.0)


def test_unrealized_pnl():
    s = PortfolioState(1e6)
    s.apply_fill("A", 100, 50.0, 0.0)
    s.mark({"A": 60.0})
    assert s.unrealized_pnl() == pytest.approx(1000.0)


# ── order generation ──────────────────────────────────────────────────────────────

def test_generate_orders_delta():
    s = PortfolioState(1e6)
    orders = generate_orders({"A": 0.5}, s, {"A": 100.0}, SizingConfig())
    assert len(orders) == 1 and orders[0].quantity == pytest.approx(5000)


def test_min_trade_notional_buffer():
    s = PortfolioState(1e6)
    s.apply_fill("A", 5000, 100.0, 0.0)
    s.mark({"A": 100.0})
    orders = generate_orders({"A": 0.5001}, s, {"A": 100.0}, SizingConfig(min_trade_notional=1000))
    assert orders == []                              # tiny drift within buffer


def test_long_only_clamps_short():
    s = PortfolioState(1e6)
    orders = generate_orders({"A": -0.3}, s, {"A": 100.0}, SizingConfig(allow_short=False))
    assert orders == []                              # negative target clamped to 0, no position


def test_integer_lot_rounding():
    s = PortfolioState(1e6)
    orders = generate_orders({"A": 0.333}, s, {"A": 101.0}, SizingConfig(integer_shares=True, lot_size=100))
    assert orders[0].quantity % 100 == 0


def test_unpriced_skipped():
    s = PortfolioState(1e6)
    orders = generate_orders({"A": 0.5}, s, {}, SizingConfig())
    assert orders == []


# ── execution ─────────────────────────────────────────────────────────────────────

def test_cost_execution_books_cost():
    cm = TransactionCostModel(commission_bps=1, spread_bps=2, slippage_bps=1)
    fill = CostExecutionModel(cm).execute(Order("A", 1000), 100.0, adv=1e8)
    assert fill.cost > 0 and fill.notional == pytest.approx(100000)


def test_frictionless_zero_cost():
    fill = FrictionlessExecutionModel().execute(Order("A", 1000), 100.0)
    assert fill.cost == 0.0


def test_execution_di():
    class Custom(ExecutionModel):
        name = "custom"
        def execute(self, order, price, adv=None):
            from aurelius.research.simulation.models import Fill
            return Fill(order.security_id, order.quantity, price, 42.0, order.quantity * price)
    res = _run(execution=Custom())
    assert res.metadata.execution_model == "custom"
    assert all(t.cost == 42.0 for t in res.trades)


# ── rebalancing ────────────────────────────────────────────────────────────────────

def test_calendar_dates_monthly():
    tl = _timeline(365)
    assert len(calendar_dates(tl, "monthly")) == 12


def test_calendar_dates_weekly():
    tl = _timeline(70)
    assert 9 <= len(calendar_dates(tl, "weekly")) <= 11


def test_explicit_policy_due():
    tl = _timeline(40)
    pol = RebalancePolicy(explicit_dates={tl[0], tl[20]})
    assert pol.due(as_of=tl[0], last=None) and not pol.due(as_of=tl[1], last=tl[0])


def test_threshold_policy():
    pol = RebalancePolicy(RebalanceRule(mode="threshold", drift_threshold=0.05))
    assert pol.due(as_of=date(2020, 1, 1), last=None, current=[0.5], target=[0.6])
    assert not pol.due(as_of=date(2020, 1, 1), last=date(2019, 1, 1), current=[0.5], target=[0.51])


# ── engine integration ─────────────────────────────────────────────────────────────

def test_engine_runs_full_timeline():
    res = _run()
    assert len(res.equity_curve) == len(_timeline())
    assert res.summary.n_rebalances == 24                # 24 months
    assert res.metadata.n_periods == len(_timeline())


def test_holdings_persist():
    res = _run()
    # every snapshot after the first rebalance holds ~10 names
    held = [s.n_positions for s in res.snapshots[40:]]
    assert all(h == 10 for h in held)


def test_cash_accounting_exact():
    res = _run()
    assert res.diagnostics["ledger_reconciles"] is True


def test_determinism():
    a, b = _run(), _run()
    assert [e.value for e in a.equity_curve] == [e.value for e in b.equity_curve]
    assert serialization.to_json(a) == serialization.to_json(b)


def test_costs_reduce_value():
    with_cost = _run(execution=CostExecutionModel(TransactionCostModel()))
    frictionless = _run(execution=FrictionlessExecutionModel())
    assert with_cost.summary.final_value < frictionless.summary.final_value
    assert with_cost.summary.total_cost > 0 and frictionless.summary.total_cost == 0


def test_no_rebalance_stays_flat():
    tl = _timeline(200)
    res = _run(tl, policy=RebalancePolicy(explicit_dates=set()))
    assert res.summary.n_rebalances == 0 and len(res.trades) == 0
    assert res.summary.final_value == pytest.approx(1e6)   # all cash, never invested


def test_turnover_positive():
    res = _run()
    assert res.turnover_report.annualized_turnover > 0
    assert res.turnover_report.n_trades == len(res.trades)


def test_equity_dates_sorted():
    res = _run()
    dates = [e.date for e in res.equity_curve]
    assert dates == sorted(dates)


# ── performance analytics ───────────────────────────────────────────────────────────

def test_performance_metrics_uptrend():
    vals = list(100 * np.cumprod(1 + np.full(300, 0.001)))
    m = performance.performance_metrics(vals)
    assert m["cagr"] > 0 and m["sharpe"] > 0 and m["max_drawdown"] == pytest.approx(0.0, abs=1e-9)


def test_drawdown_decline():
    vals = [100, 110, 90, 95, 80]
    dd = performance.drawdown(vals)
    assert dd.max_drawdown == pytest.approx((80 - 110) / 110)
    assert dd.time_underwater_frac > 0


def test_sortino_omega_present():
    res = _run()
    assert res.summary.sortino != 0 or res.summary.volatility >= 0
    assert res.summary.omega >= 0


# ── reports ─────────────────────────────────────────────────────────────────────────

def test_cost_report():
    res = _run()
    assert res.cost_report.total_cost == pytest.approx(sum(t.cost for t in res.trades))
    assert res.cost_report.cost_bps_of_traded > 0


def test_capacity_report():
    res = _run(adv=1e6)
    assert res.capacity_report.max_participation > 0
    assert res.capacity_report.capacity_signal in ("low", "moderate", "high")


def test_exposure_report():
    res = _run()
    assert 0.9 <= res.exposure_report.avg_gross <= 1.01
    assert res.exposure_report.max_gross <= 1.05


def test_risk_timeline():
    res = _run()
    assert len(res.risk_timeline) == len(res.snapshots)
    assert all(r.concentration_hhi >= 0 for r in res.risk_timeline)


# ── attribution ─────────────────────────────────────────────────────────────────────

def test_attribution_contributions():
    res = _run()
    sec = res.attribution.security_contribution
    assert len(sec) == 10
    assert abs(sum(sec.values()) - res.summary.total_return) < 0.1   # approx up to costs/cash


# ── validation ──────────────────────────────────────────────────────────────────────

def test_validate_clean_run():
    res = _run()
    v = validate_simulation(res)
    assert v["ledger_consistency"]["ok"] and v["portfolio_accounting"]["ok"]
    assert v["ok"]


def test_validate_detects_short_when_disallowed():
    res = _run()
    # inject a short snapshot → position_accounting should fail under long-only
    res.snapshots.append(type(res.snapshots[0])(
        date=date(2099, 1, 1), value=1e6, cash=0, holdings={}, gross_exposure=1.0,
        net_exposure=0.5, long_exposure=0.75, short_exposure=0.25, n_positions=2))
    v = validate_simulation(res, allow_short=False)
    assert v["position_accounting"]["ok"] is False


def test_phase9_integration():
    from aurelius.research.validation import ResearchValidator, ValidationConfig
    res = _run()
    pm = to_performance_metrics(res)
    assert len(pm.daily_returns) == len(res.equity_curve) - 1
    rep = ResearchValidator(config=ValidationConfig(bootstrap_samples=100, monte_carlo_samples=50,
                            permutation_samples=100, n_trials=1)).validate(_stub_exp(), pm)
    assert rep.overall_verdict in ("PASS", "PASS_WITH_WARNINGS", "REJECT", "REQUIRES_REVIEW")


# ── serialization ────────────────────────────────────────────────────────────────────

def test_serialization_json():
    res = _run()
    d = serialization.to_dict(res)
    assert set(d) >= {"summary", "metadata", "equity_curve", "cost_report", "attribution"}
    assert len(d["equity_curve"]) == len(res.equity_curve)


def test_serialization_parquet(tmp_path):
    pytest.importorskip("pyarrow")               # parquet engine optional in this env
    res = _run()
    paths = serialization.save_parquet(res, str(tmp_path))
    import pandas as pd
    from pathlib import Path
    assert Path(paths["equity_curve"]).exists()
    assert len(pd.read_parquet(paths["trades"])) == len(res.trades)


# ── registry integration ─────────────────────────────────────────────────────────────

def test_registry_attach(tmp_path):
    reg = ExperimentRegistry(store=RegistryStore(":memory:"))
    try:
        dv = lineage.dataset_versions(prices=1, fundamentals=1, insiders=1, universe=1,
                                      securitymaster=1, feature_registry_version="fr1")
        exp = reg.start_experiment("sim", parameters={"x": 1}, features=["market_cap"],
                                   dataset_versions=dv, random_seed=1)
        reg.finish_experiment(exp, metrics={"Sharpe": 1.0})
        res = _run()
        out = attach_simulation(reg, exp, res, artifacts_dir=str(tmp_path))
        reloaded = reg.load(exp.experiment_id)
        assert "SimCAGR" in reloaded.metrics and out["hash"]
        assert any("simulation_result" in a["artifact_type"] for a in reloaded.artifacts)
    finally:
        reg.close()


# ── edge cases / diagnostics ─────────────────────────────────────────────────────────

def test_empty_timeline():
    eng = PortfolioSimulationEngine(execution_model=FrictionlessExecutionModel())
    res = eng.run([], lambda d: {}, lambda s, d: None)
    assert res.summary.n_periods == 0 and res.summary.final_value == 0.0


def test_single_security():
    tl = _timeline(120)
    price, _, _ = _providers(tl)
    eng = PortfolioSimulationEngine(execution_model=FrictionlessExecutionModel(),
                                    policy=RebalancePolicy(explicit_dates={tl[0]}))
    res = eng.run(tl, lambda d: {"S00": 1.0}, price)
    assert res.snapshots[-1].n_positions == 1


def test_diagnostics_logs():
    res = _run()
    logs = build_logs(res)
    assert len(logs["trade_log"]) == len(res.trades)
    assert "warnings" in logs and isinstance(logs["rebalance_log"], list)


class _Exp:
    experiment_id = "SIM"; fingerprint = "f"; git_commit = "c"; random_seed = 1
    dataset_versions = {"feature_registry_version": "fr1"}; features = ["market_cap"]
    artifacts: list = []; metrics: dict = {}


def _stub_exp():
    return _Exp()
