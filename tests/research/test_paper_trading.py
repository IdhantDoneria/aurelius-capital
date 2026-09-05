"""AIDP M12 — Paper Trading Bridge & Live-State Reconciliation tests.

Deterministic, offline. Reconciliation is exercised directly on the pure
`reconcile()` function with hand-built divergent internal/external states (the
happy-path loop cannot diverge because the internal book replays the broker's own
fills — which is the correct behaviour, so the loop tests assert clean state).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import ClassVar

import pytest

import mentisrex.research.paper_trading as pt
from mentisrex.research.paper_trading.broker import MockBroker, SimulatedBroker
from mentisrex.research.paper_trading.models import (
    BrokerAccount,
    BrokerFill,
    BrokerPosition,
    OrderRequest,
    OrderStatus,
)
from mentisrex.research.paper_trading.reconciliation import ReconciliationConfig, reconcile
from mentisrex.research.simulation.state import PortfolioState

PRICES = {"A": 100.0, "B": 50.0, "C": 25.0}
LIM = pt.RiskLimits(max_name_weight=0.5, max_gross_leverage=1.05)


def _pp(sid, d):
    return PRICES[sid]


def _tp(d):
    return {"A": 0.4, "B": 0.3, "C": 0.3}


def _timeline(n=6):
    return [date(2024, 1, 1) + timedelta(days=30 * i) for i in range(n)]


def _session(broker, **kw):
    return pt.PaperTradingSession(broker=broker, risk_gate=pt.PreTradeRiskGate(LIM), **kw)


def _state_with(holdings, cash):
    """holdings: {sid: (shares, cost_basis, price)}."""
    st = PortfolioState(0.0)
    st.ledger.cash = cash
    from mentisrex.research.simulation.models import Holding

    for sid, (sh, cb, pr) in holdings.items():
        st.holdings[sid] = Holding(sid, sh, cb, pr)
    return st


def _account(positions, cash):
    pos = {sid: BrokerPosition(sid, sh, cb, pr) for sid, (sh, cb, pr) in positions.items()}
    return BrokerAccount("PAPER", cash, pos)


# ── broker mock / lifecycle ──────────────────────────────────────────────────


def test_mock_broker_fills_full_at_mark():
    b = MockBroker(initial_cash=1_000_000.0)
    b.set_prices(PRICES)
    o = b.place_order(OrderRequest("c1", "A", 100.0))
    assert o.status == OrderStatus.FILLED
    assert o.filled_quantity == 100.0
    assert o.avg_fill_price == 100.0


def test_mock_broker_rejects_unpriced():
    b = MockBroker(initial_cash=1_000_000.0)
    b.set_prices({"A": 100.0})
    o = b.place_order(OrderRequest("c1", "ZZZ", 10.0))
    assert o.status == OrderStatus.REJECTED


def test_mock_broker_account_reflects_fills():
    b = MockBroker(initial_cash=1_000_000.0)
    b.set_prices(PRICES)
    b.place_order(OrderRequest("c1", "A", 100.0))
    acct = b.get_account()
    assert acct.positions["A"].quantity == 100.0
    assert acct.cash == pytest.approx(1_000_000.0 - 100 * 100.0)


def test_poll_fills_drains_queue():
    b = MockBroker(initial_cash=1_000_000.0)
    b.set_prices(PRICES)
    b.place_order(OrderRequest("c1", "A", 10.0))
    assert len(b.poll_fills()) == 1
    assert b.poll_fills() == []


def test_simulated_broker_partial_fill():
    b = SimulatedBroker(initial_cash=1_000_000.0, fill_ratio=0.5)
    b.set_prices(PRICES)
    o = b.place_order(OrderRequest("c1", "A", 100.0))
    assert o.status == OrderStatus.PARTIALLY_FILLED
    assert o.filled_quantity == 50.0


def test_simulated_broker_slippage_costs_the_buyer():
    b = SimulatedBroker(initial_cash=1_000_000.0, slippage_bps=100.0)
    b.set_prices(PRICES)
    buy = b.place_order(OrderRequest("c1", "A", 10.0))
    assert buy.avg_fill_price > 100.0
    b.set_prices(PRICES)
    sell = b.place_order(OrderRequest("c2", "A", -10.0))
    assert sell.avg_fill_price < 100.0


def test_simulated_broker_rejects_every_n():
    b = SimulatedBroker(initial_cash=1_000_000.0, reject_every=1)
    b.set_prices(PRICES)
    o = b.place_order(OrderRequest("c1", "A", 10.0))
    assert o.status == OrderStatus.REJECTED


def test_adapter_stubs_raise():
    from mentisrex.research.paper_trading.adapter import AlpacaAdapter, FIXAdapter

    with pytest.raises(NotImplementedError):
        AlpacaAdapter().connect()
    with pytest.raises(NotImplementedError):
        FIXAdapter().get_account()


# ── order flow / accounting reuse ────────────────────────────────────────────


def test_loop_reaches_target_weights():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    w = s.book.weights()
    assert w["A"] == pytest.approx(0.4, abs=1e-6)
    assert w["B"] == pytest.approx(0.3, abs=1e-6)


def test_loop_ledger_reconciles():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    assert s.book.state.ledger.reconciles()


def test_loop_generates_trades_first_tick_only_when_needed():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    # once at target, later ticks generate no new trades
    assert len(s.trades) == 3


def test_internal_matches_broker_after_loop():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    assert s.reconciliations[-1].ok


def test_short_target_blocked_when_long_only():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.step(date(2024, 1, 1), {"A": -0.3}, PRICES)
    assert "A" not in s.book.state.holdings or s.book.state.holdings["A"].shares >= 0


def test_risk_gate_blocks_over_concentration():
    gate = pt.PreTradeRiskGate(pt.RiskLimits(max_name_weight=0.1))
    s = pt.PaperTradingSession(broker=MockBroker(initial_cash=1_000_000.0), risk_gate=gate)
    s.step(date(2024, 1, 1), {"A": 0.9}, PRICES)
    assert not s.book.state.holdings


def test_risk_gate_kill_switch():
    gate = pt.PreTradeRiskGate(pt.RiskLimits(kill=True))
    s = pt.PaperTradingSession(broker=MockBroker(initial_cash=1_000_000.0), risk_gate=gate)
    s.step(date(2024, 1, 1), _tp(None), PRICES)
    assert not s.book.state.holdings


# ── reconciliation: the nine break categories (pure function) ────────────────


def test_reconcile_clean():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=990_000.0)
    acct = _account({"A": (100.0, 100.0, 100.0)}, cash=990_000.0)
    r = reconcile(st, acct)
    assert r.ok
    assert not r.differences


def test_reconcile_missing_position():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({}, cash=0.0)
    r = reconcile(st, acct)
    assert r.categories.get("missing_position") == 1


def test_reconcile_unexpected_position():
    st = _state_with({}, cash=0.0)
    acct = _account({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    r = reconcile(st, acct)
    assert r.categories.get("unexpected_position") == 1


def test_reconcile_wrong_quantity():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (90.0, 100.0, 100.0)}, cash=0.0)
    r = reconcile(st, acct)
    assert r.categories.get("wrong_quantity") == 1


def test_reconcile_wrong_price():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (100.0, 100.0, 105.0)}, cash=0.0)
    r = reconcile(st, acct)
    assert r.categories.get("wrong_price") == 1


def test_reconcile_wrong_cost_basis():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (100.0, 110.0, 100.0)}, cash=0.0)
    r = reconcile(st, acct)
    assert r.categories.get("wrong_cost_basis") == 1


def test_reconcile_cash_mismatch():
    st = _state_with({}, cash=100_000.0)
    acct = _account({}, cash=90_000.0)
    r = reconcile(st, acct)
    assert r.categories.get("cash_mismatch") == 1
    assert r.cash_diff == pytest.approx(10_000.0)


def test_reconcile_stale_order():
    st = _state_with({}, cash=0.0)
    acct = _account({}, cash=0.0)
    r = reconcile(
        st, acct, pending_orders=[("c1", 7)], config=ReconciliationConfig(stale_order_days=5)
    )
    assert r.categories.get("stale_order") == 1


def test_reconcile_duplicate_fill():
    st = _state_with({}, cash=0.0)
    acct = _account({}, cash=0.0)
    r = reconcile(st, acct, applied_fill_ids=["f1", "f1", "f2"], broker_fill_ids=["f1", "f2"])
    assert r.categories.get("duplicate_fill") == 1


def test_reconcile_missing_fill():
    st = _state_with({}, cash=0.0)
    acct = _account({}, cash=0.0)
    r = reconcile(st, acct, applied_fill_ids=["f1"], broker_fill_ids=["f1", "f2"])
    assert r.categories.get("missing_fill") == 1


def test_reconcile_multiple_breaks():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=100_000.0)
    acct = _account({"B": (50.0, 50.0, 50.0)}, cash=80_000.0)
    r = reconcile(st, acct)
    assert not r.ok
    assert r.categories.get("missing_position") == 1
    assert r.categories.get("unexpected_position") == 1
    assert r.categories.get("cash_mismatch") == 1


def test_reconcile_qty_within_tolerance_is_clean():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (100.0 + 1e-9, 100.0, 100.0)}, cash=0.0)
    assert reconcile(st, acct).ok


# ── drift monitoring ─────────────────────────────────────────────────────────


def test_drift_weight_alert():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)  # 100% A
    acct = _account({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    d = pt.compute_drift(st, acct, {"A": 0.5})
    assert d.max_weight_drift == pytest.approx(0.5)
    assert any("weight_drift" in a for a in d.alerts)


def test_drift_cash_alert():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=10_000.0)
    acct = _account({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    d = pt.compute_drift(st, acct, {"A": 1.0})
    assert any("cash_drift" in a for a in d.alerts)


def test_drift_position_alert():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (50.0, 100.0, 100.0)}, cash=5000.0)
    d = pt.compute_drift(st, acct, {"A": 1.0})
    assert d.position_drift > 0
    assert any("position_drift" in a for a in d.alerts)


def test_drift_cost_alert():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    d = pt.compute_drift(st, acct, {"A": 1.0}, expected_cost=100.0, actual_cost=300.0)
    assert d.cost_drift == pytest.approx(2.0)
    assert any("cost_drift" in a for a in d.alerts)


def test_drift_timing_alert():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    d = pt.compute_drift(st, acct, {"A": 1.0}, timing_gap_days=5.0)
    assert any("timing_drift" in a for a in d.alerts)


def test_drift_clean_no_alerts():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    d = pt.compute_drift(st, acct, {"A": 1.0})
    assert not d.alerts


# ── monitoring ───────────────────────────────────────────────────────────────


def test_monitoring_report_clean_run():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    mon = pt.monitoring_report(s)
    assert mon.reconciliation_rate == 1.0
    assert mon.consistency_ok


def test_monitoring_counts_syncs():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(5), _tp, _pp)
    assert pt.monitoring_report(s).n_syncs == 5


# ── serialization ────────────────────────────────────────────────────────────


def test_serialization_roundtrip_stable():
    import json

    from mentisrex.research.paper_trading import serialization

    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    a = serialization.to_json(s)
    b = serialization.to_json(s)
    assert a == b
    assert json.loads(a)["diagnostics"]["ledger_reconciles"] is True


def test_serialization_save(tmp_path):
    from mentisrex.research.paper_trading import serialization

    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(3), _tp, _pp)
    serialization.save_json(s, str(tmp_path / "sess.json"))
    assert (tmp_path / "sess.json").exists()


# ── determinism ──────────────────────────────────────────────────────────────


def test_determinism_same_fingerprint():
    s1 = _session(MockBroker(initial_cash=1_000_000.0))
    s1.run(_timeline(), _tp, _pp)
    s2 = _session(MockBroker(initial_cash=1_000_000.0))
    s2.run(_timeline(), _tp, _pp)
    assert s1.fingerprint() == s2.fingerprint()


def test_determinism_simulated_broker():
    def build():
        s = _session(SimulatedBroker(initial_cash=1_000_000.0, fill_ratio=0.7, slippage_bps=20.0))
        s.run(_timeline(), _tp, _pp)
        return s

    assert build().book.value() == pytest.approx(build().book.value())


# ── registry ─────────────────────────────────────────────────────────────────


def test_registry_attach(tmp_path):
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(3), _tp, _pp)

    class _Store:
        def __init__(self):
            self.inserted = None

        def insert(self, exp):
            self.inserted = exp

    class _Exp:
        experiment_id = "e1"
        metrics: ClassVar[dict] = {}
        artifacts: ClassVar[list] = []
        notes = ""

    class _Reg:
        store = _Store()

        def load(self, _):
            return None

    reg, exp = _Reg(), _Exp()
    out = pt.attach_session(reg, exp, s, artifacts_dir=str(tmp_path))
    assert "hash" in out
    assert "PaperReconciliationRate" in exp.metrics
    assert reg.store.inserted is exp


def test_registry_noop_without_registry():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(2), _tp, _pp)
    assert pt.attach_session(None, None, s) == {}


# ── validation integration ───────────────────────────────────────────────────


def test_state_consistency_clean():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    c = pt.state_consistency(s)
    assert c.ok
    assert c.ledger_reconciles


def test_deployment_readiness_requires_both():
    from mentisrex.research.paper_trading.models import StateConsistencyReport

    good = StateConsistencyReport(True, True, True, 0.0, [])
    assert pt.deployment_readiness("PASS", 80.0, good).ready
    assert not pt.deployment_readiness("REJECT", 80.0, good).ready
    bad = StateConsistencyReport(False, False, False, 0.5, ["x"])
    assert not pt.deployment_readiness("PASS", 80.0, bad).ready


def test_validate_session_without_m9():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(), _tp, _pp)
    res = pt.validate_session(s)
    assert res.consistency.ok
    assert res.deployment.verdict == "SKIPPED"


def test_validate_session_with_m9():
    from mentisrex.research.validation import ResearchValidator, ValidationConfig

    # a longer run so M9 has >3 observations with variation
    prices = {"A": 100.0}
    seq = {}

    def pp(sid, d):
        return prices["A"] * (1.0 + 0.001 * seq.setdefault(d, len(seq)))

    def tp(d):
        return {"A": 0.4}

    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.run(_timeline(30), tp, pp)
    v = ResearchValidator(
        config=ValidationConfig(
            bootstrap_samples=50, monte_carlo_samples=30, permutation_samples=50, n_trials=1
        )
    )
    res = pt.validate_session(s, validator=v)
    assert res.deployment.verdict in ("PASS", "PASS_WITH_WARNINGS", "REJECT", "REQUIRES_REVIEW")
    assert "verdict" in res.validation


# ── edge cases ───────────────────────────────────────────────────────────────


def test_empty_target_no_trades():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.step(date(2024, 1, 1), {}, PRICES)
    assert not s.book.state.holdings


def test_unpriced_name_held_not_traded():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    s.step(date(2024, 1, 1), {"A": 0.4, "ZZZ": 0.1}, {"A": 100.0})  # ZZZ unpriced
    assert "ZZZ" not in s.book.state.holdings
    assert "A" in s.book.state.holdings


def test_duplicate_fill_ingest_idempotent():
    s = _session(MockBroker(initial_cash=1_000_000.0))
    f = BrokerFill("f1", "o1", "A", 10.0, 100.0, 0.0)
    assert s.book.ingest_fill(f) is True
    assert s.book.ingest_fill(f) is False  # same fill_id → skipped
    assert s.book.state.holdings["A"].shares == 10.0


def test_zero_capital_no_orders():
    s = pt.PaperTradingSession(
        broker=MockBroker(initial_cash=0.0),
        config=pt.SessionConfig(initial_capital=0.0),
        risk_gate=pt.PreTradeRiskGate(LIM),
    )
    s.step(date(2024, 1, 1), _tp(None), PRICES)
    assert not s.book.state.holdings


def test_account_snapshot_pairs_positions():
    st = _state_with({"A": (100.0, 100.0, 100.0)}, cash=0.0)
    acct = _account({"A": (90.0, 100.0, 100.0), "B": (10.0, 50.0, 50.0)}, cash=0.0)
    pp = pt.PaperPortfolio(0.0)
    pp.state = st
    snap = pp.snapshot(acct, when=date(2024, 1, 1))
    rows = {r.security_id: r for r in snap.positions}
    assert rows["A"].internal_qty == 100.0
    assert rows["A"].external_qty == 90.0
    assert rows["B"].internal_qty == 0.0
    assert rows["B"].external_qty == 10.0
