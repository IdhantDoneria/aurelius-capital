"""AIDP M14 — Execution Management System & Order Management System tests.

Deterministic, offline. Covers OMS lifecycle + audit trail, EMS pipeline, execution
algorithms (immediate/TWAP/VWAP/POV), scheduler slicing, broker mocks, routing,
cost/slippage/implementation-shortfall attribution, monitoring, reconciliation,
M12 book integration, M13 risk-gate integration, validation, serialization,
diagnostics/fingerprint, registry attachment, failure handling, determinism, edges.
"""

from __future__ import annotations

from datetime import date

import pytest

from aurelius.research.execution import ems as E
from aurelius.research.execution.ems import scheduler
from aurelius.research.execution.ems.models import OrderStatus, OrderType
from aurelius.research.execution.ems.oms import OMS, OMSError
from aurelius.research.execution.ems.orders import MarketInfo
from aurelius.research.paper_trading.portfolio import PaperPortfolio
from aurelius.research.risk.engine import RiskEngine, RiskEngineConfig
from aurelius.research.risk.limits import RiskLimits

PRICES = {"AAA": 100.0, "BBB": 50.0, "CCC": 25.0}


def _market(prices=None, **kw):
    return MarketInfo(prices=prices or dict(PRICES), **kw)


def _mock(cash=1_000_000.0, **kw):
    return E.MockExecutionBroker(initial_cash=cash, **kw)


def _sim(cash=1_000_000.0, **kw):
    return E.SimulatedExecutionBroker(initial_cash=cash, **kw)


def _ems(broker=None, gate=None, **cfg):
    b = broker or _mock()
    engine = E.EMS(E.ExecutionRouter({"b": b}), risk_gate=gate, config=E.ExecutionConfig(**cfg))
    return engine, b


def _oms_with(order):
    oms = OMS()
    oms.create(order)
    return oms


def _walk_to_ack(oms, oid, bid="b1"):
    oms.validate(oid); oms.approve(oid); oms.submit(oid, broker_order_id=bid); oms.acknowledge(oid, bid)


# ── order-type factories / models ────────────────────────────────────────────

def test_market_order_factory():
    o = E.market_order("o", "AAA", 100, arrival_price=100.0)
    assert o.order_type == OrderType.MARKET and o.quantity == 100 and o.arrival_price == 100.0


def test_limit_order_factory():
    o = E.limit_order("o", "AAA", 100, 99.0)
    assert o.order_type == OrderType.LIMIT and o.limit_price == 99.0


def test_stop_order_factory():
    o = E.stop_order("o", "AAA", -100, 95.0)
    assert o.order_type == OrderType.STOP and o.limit_price == 95.0 and o.quantity == -100


def test_twap_vwap_pov_factories():
    assert E.twap_order("o", "AAA", 10).order_type == OrderType.TWAP
    assert E.vwap_order("o", "AAA", 10).order_type == OrderType.VWAP
    assert E.pov_order("o", "AAA", 10).order_type == OrderType.POV


def test_order_intent_side():
    from aurelius.research.execution.ems.models import OrderIntent
    assert OrderIntent("AAA", 5).side == "buy"
    assert OrderIntent("AAA", -5).side == "sell"
    assert OrderIntent("AAA", 0).side == "flat"


def test_intents_from_target_diff():
    intents = E.intents_from_target({"AAA": 100, "BBB": 50}, {"AAA": 40})
    d = {i.security_id: i.delta_shares for i in intents}
    assert d == {"AAA": 60, "BBB": 50}


def test_build_requests_stamps_arrival():
    intents = E.intents_from_target({"AAA": 100})
    reqs = E.build_requests(intents, market=_market())
    assert reqs[0].arrival_price == 100.0 and reqs[0].security_id == "AAA"


def test_to_sim_orders_bridge():
    reqs = [E.market_order("o", "AAA", 10)]
    sims = E.to_sim_orders(reqs)
    assert sims[0].security_id == "AAA" and sims[0].quantity == 10


# ── OMS lifecycle ─────────────────────────────────────────────────────────────

def test_oms_create_sets_new():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    assert oms.status("o") == OrderStatus.NEW


def test_oms_full_lifecycle_to_filled():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    oms.validate("o"); oms.approve("o"); oms.submit("o", broker_order_id="b")
    oms.acknowledge("o", "b")
    assert oms.status("o") == OrderStatus.ACKNOWLEDGED
    oms.record_fill("o", 10, 100.0, 1.0, fill_id="f1")
    assert oms.status("o") == OrderStatus.FILLED


def test_oms_partial_then_complete():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    assert oms.record_fill("o", 4, 100.0, 0.0, fill_id="f1") == OrderStatus.PARTIALLY_FILLED
    assert oms.record_fill("o", 6, 100.0, 0.0, fill_id="f2") == OrderStatus.FILLED


def test_oms_reject_from_new():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    oms.reject("o", "bad")
    assert oms.status("o") == OrderStatus.REJECTED


def test_oms_validate_fail_rejects():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    oms.validate("o", ok=False, reason="x")
    assert oms.status("o") == OrderStatus.REJECTED


def test_oms_cancel_flow():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    oms.request_cancel("o")
    assert oms.status("o") == OrderStatus.PENDING_CANCEL
    oms.confirm_cancel("o")
    assert oms.status("o") == OrderStatus.CANCELLED


def test_oms_cancel_partially_filled():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    oms.record_fill("o", 4, 100.0, 0.0, fill_id="f1")
    oms.confirm_cancel("o")
    assert oms.status("o") == OrderStatus.CANCELLED


def test_oms_expire():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    oms.validate("o"); oms.approve("o"); oms.submit("o")
    oms.expire("o")
    assert oms.status("o") == OrderStatus.EXPIRED


def test_oms_avg_fill_price_weighted():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    oms.record_fill("o", 5, 100.0, 0.0, fill_id="f1")
    oms.record_fill("o", 5, 102.0, 0.0, fill_id="f2")
    assert oms.report("o").avg_fill_price == pytest.approx(101.0)


def test_oms_duplicate_id_raises():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    with pytest.raises(OMSError):
        oms.create(E.market_order("o", "AAA", 5))


def test_oms_unknown_order_raises():
    with pytest.raises(OMSError):
        OMS().status("nope")


# ── OMS illegal transitions ───────────────────────────────────────────────────

def test_oms_cannot_approve_before_validate():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    with pytest.raises(OMSError):
        oms.approve("o")


def test_oms_cannot_submit_before_approve():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    oms.validate("o")
    with pytest.raises(OMSError):
        oms.submit("o")


def test_oms_cannot_fill_before_submit():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    oms.validate("o"); oms.approve("o")
    with pytest.raises(OMSError):
        oms.record_fill("o", 10, 100.0, 0.0)


def test_oms_cannot_reject_terminal():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    oms.record_fill("o", 10, 100.0, 0.0, fill_id="f")
    with pytest.raises(OMSError):
        oms.reject("o", "late")


def test_oms_cannot_fill_after_filled():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    oms.record_fill("o", 10, 100.0, 0.0, fill_id="f")
    with pytest.raises(OMSError):
        oms.record_fill("o", 1, 100.0, 0.0, fill_id="f2")


def test_oms_cannot_cancel_new():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    with pytest.raises(OMSError):
        oms.request_cancel("o")


def test_oms_cannot_expire_filled():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    oms.record_fill("o", 10, 100.0, 0.0, fill_id="f")
    with pytest.raises(OMSError):
        oms.expire("o")


# ── audit trail ───────────────────────────────────────────────────────────────

def test_audit_trail_records_every_transition():
    oms = _oms_with(E.market_order("o", "AAA", 10, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    oms.record_fill("o", 10, 100.0, 0.0, fill_id="f")
    kinds = [e.kind for e in oms.history("o")]
    assert kinds == ["created", "validate", "approve", "submit", "acknowledge", "fill"]


def test_audit_seq_monotonic_global():
    oms = OMS()
    oms.create(E.market_order("a", "AAA", 1)); oms.create(E.market_order("b", "BBB", 1))
    seqs = [e.seq for e in oms.all_events()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_audit_events_are_frozen():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    ev = oms.history("o")[0]
    with pytest.raises(Exception):
        ev.kind = "hacked"


def test_audit_history_is_copy():
    oms = _oms_with(E.market_order("o", "AAA", 10))
    h = oms.history("o")
    h.append("junk")
    assert len(oms.history("o")) == 1


# ── scheduler ─────────────────────────────────────────────────────────────────

def test_uniform_schedule_sums_to_quantity():
    s = scheduler.uniform_schedule("o", 100, 3)
    assert sum(x.quantity for x in s.slices) == pytest.approx(100)
    assert s.n_slices == 3


def test_uniform_schedule_signed():
    s = scheduler.uniform_schedule("o", -90, 3)
    assert all(x.quantity < 0 for x in s.slices)
    assert sum(x.quantity for x in s.slices) == pytest.approx(-90)


def test_uniform_last_slice_absorbs_rounding():
    s = scheduler.uniform_schedule("o", 100, 3)   # 33.33 each, last = remainder
    assert sum(x.quantity for x in s.slices) == pytest.approx(100.0)


def test_profile_schedule_matches_profile():
    s = scheduler.profile_schedule("o", 100, [0.5, 0.3, 0.2])
    q = [x.quantity for x in s.slices]
    assert q[0] == pytest.approx(50) and sum(q) == pytest.approx(100)


def test_profile_empty_falls_back_single():
    s = scheduler.profile_schedule("o", 100, [])
    assert s.n_slices == 1


def test_pov_schedule_participation():
    # 20% of 1000 = 200/slice; qty 500 -> 200,200,100
    s = scheduler.pov_schedule("o", 500, 1000, 0.20)
    q = [x.quantity for x in s.slices]
    assert q == pytest.approx([200, 200, 100])


def test_pov_zero_volume_single_slice():
    s = scheduler.pov_schedule("o", 500, 0, 0.20)
    assert s.n_slices == 1


def test_pov_sums_to_quantity():
    s = scheduler.pov_schedule("o", 777, 500, 0.10)
    assert sum(x.quantity for x in s.slices) == pytest.approx(777)


# ── algorithms ────────────────────────────────────────────────────────────────

def test_registry_has_all_algos():
    assert set(E.available()) >= {"immediate", "twap", "vwap", "pov"}


def test_get_unknown_algo_raises():
    with pytest.raises(KeyError):
        E.get_algorithm("nope")


def test_immediate_single_child():
    plan = E.get_algorithm("immediate").plan(E.market_order("o", "AAA", 100, arrival_price=100.0), _market())
    assert len(plan.child_orders) == 1 and plan.child_orders[0].quantity == 100


def test_twap_n_children():
    plan = E.get_algorithm("twap", n_slices=4).plan(E.twap_order("o", "AAA", 100, arrival_price=100.0), _market())
    assert len(plan.child_orders) == 4
    assert sum(c.quantity for c in plan.child_orders) == pytest.approx(100)


def test_twap_children_are_market():
    plan = E.get_algorithm("twap", n_slices=3).plan(E.twap_order("o", "AAA", 90), _market())
    assert all(c.order_type == OrderType.MARKET for c in plan.child_orders)


def test_vwap_uses_default_profile():
    plan = E.get_algorithm("vwap").plan(E.vwap_order("o", "AAA", 100, arrival_price=100.0), _market())
    assert len(plan.child_orders) == 7   # default U-shape length
    assert sum(c.quantity for c in plan.child_orders) == pytest.approx(100)


def test_vwap_custom_profile():
    plan = E.get_algorithm("vwap", profile=[0.5, 0.5]).plan(E.vwap_order("o", "AAA", 100), _market())
    assert len(plan.child_orders) == 2


def test_vwap_market_profile_override():
    m = _market(volume_profile=[0.25, 0.25, 0.25, 0.25])
    plan = E.get_algorithm("vwap").plan(E.vwap_order("o", "AAA", 100), m)
    assert len(plan.child_orders) == 4


def test_pov_uses_market_interval_volume():
    m = _market(interval_volume={"AAA": 1000})
    plan = E.get_algorithm("pov", participation_rate=0.2).plan(E.pov_order("o", "AAA", 500), m)
    assert len(plan.child_orders) == 3


def test_child_ids_unique():
    plan = E.get_algorithm("twap", n_slices=5).plan(E.twap_order("o", "AAA", 100), _market())
    ids = [c.order_id for c in plan.child_orders]
    assert len(set(ids)) == 5


def test_algo_plan_is_pure():
    algo = E.get_algorithm("twap", n_slices=4)
    o = E.twap_order("o", "AAA", 100)
    assert [c.quantity for c in algo.plan(o, _market()).child_orders] == \
           [c.quantity for c in algo.plan(o, _market()).child_orders]


# ── router ────────────────────────────────────────────────────────────────────

def test_router_needs_broker():
    with pytest.raises(ValueError):
        E.ExecutionRouter({})


def test_router_market_to_immediate():
    r = E.ExecutionRouter({"b": _mock()})
    assert r.route(E.market_order("o", "AAA", 10)).algo == "immediate"


def test_router_twap_to_twap():
    r = E.ExecutionRouter({"b": _mock()})
    assert r.route(E.twap_order("o", "AAA", 10)).algo == "twap"


def test_router_order_override():
    r = E.ExecutionRouter({"b": _mock()})
    o = E.market_order("o", "AAA", 10)
    o = o.__class__(**{**o.__dict__, "algo": "vwap"})
    assert r.route(o).algo == "vwap" and r.route(o).reason == "order_override"


def test_router_high_urgency_forces_immediate():
    r = E.ExecutionRouter({"b": _mock()})
    o = E.twap_order("o", "AAA", 10)
    o = o.__class__(**{**o.__dict__, "urgency": "high"})
    assert r.route(o).algo == "immediate"


def test_router_records_decision_fields():
    r = E.ExecutionRouter({"b": _mock()})
    d = r.route(E.market_order("o", "AAA", 10))
    assert d.order_id == "o" and d.broker == "b"


# ── brokers ───────────────────────────────────────────────────────────────────

def test_mock_broker_full_fill():
    b = _mock(); b.set_prices(PRICES)
    ack = b.submit_order(E.market_order("o", "AAA", 100, arrival_price=100.0))
    assert ack.status == OrderStatus.FILLED or ack.status.value == "filled"
    fills = b.get_fills()
    assert len(fills) == 1 and fills[0].quantity == 100


def test_mock_broker_unpriced_rejects():
    b = _mock(); b.set_prices({"AAA": 100.0})
    ack = b.submit_order(E.market_order("o", "ZZZ", 10))
    assert ack.status.value == "rejected"


def test_sim_broker_partial():
    b = _sim(fill_ratio=0.5); b.set_prices(PRICES)
    b.submit_order(E.market_order("o", "AAA", 100, arrival_price=100.0))
    assert b.get_fills()[0].quantity == pytest.approx(50)


def test_sim_broker_slippage():
    b = _sim(slippage_bps=10); b.set_prices(PRICES)
    b.submit_order(E.market_order("o", "AAA", 100, arrival_price=100.0))
    assert b.get_fills()[0].price == pytest.approx(100.1)


def test_sim_broker_reject_every():
    b = _sim(reject_every=1); b.set_prices(PRICES)
    ack = b.submit_order(E.market_order("o", "AAA", 100))
    assert ack.status.value == "rejected"


def test_broker_get_order_status():
    b = _mock(); b.set_prices(PRICES)
    ack = b.submit_order(E.market_order("o", "AAA", 100))
    assert b.get_order_status(ack.broker_order_id) is not None


def test_broker_account_and_positions():
    b = _mock(); b.set_prices(PRICES)
    b.submit_order(E.market_order("o", "AAA", 100, arrival_price=100.0))
    b.get_fills()
    acct = b.get_account()
    assert acct.cash == pytest.approx(990_000) and "AAA" in b.get_positions()


def test_broker_cancel_filled_returns_false():
    b = _mock(); b.set_prices(PRICES)
    ack = b.submit_order(E.market_order("o", "AAA", 100, arrival_price=100.0))
    assert b.cancel_order(ack.broker_order_id) is False


def test_adapter_stub_raises():
    a = E.InteractiveBrokersAdapter()
    with pytest.raises(NotImplementedError):
        a.submit_order(E.market_order("o", "AAA", 10))


# ── EMS pipeline ──────────────────────────────────────────────────────────────

def test_ems_single_order_fills():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].status == OrderStatus.FILLED


def test_ems_twap_multiple_children():
    engine, _ = _ems(twap_slices=4)
    sess = engine.execute([E.twap_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].n_fills == 4 and sess.reports()[0].status == OrderStatus.FILLED


def test_ems_multi_order():
    engine, _ = _ems()
    reqs = [E.market_order("o1", "AAA", 100, arrival_price=100.0),
            E.market_order("o2", "BBB", 200, arrival_price=50.0)]
    sess = engine.execute(reqs, _market())
    assert len(sess.reports()) == 2 and all(r.status == OrderStatus.FILLED for r in sess.reports())


def test_ems_partial_fill_status():
    engine, _ = _ems(broker=_sim(fill_ratio=0.5))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].status == OrderStatus.PARTIALLY_FILLED


def test_ems_broker_reject_marks_rejected():
    engine, _ = _ems(broker=_sim(reject_every=1))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].status == OrderStatus.REJECTED


def test_ems_cancel_remainder_config():
    engine, _ = _ems(broker=_sim(fill_ratio=0.5), cancel_unfilled_remainder=True)
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].status == OrderStatus.CANCELLED


def test_ems_zero_qty_child_skipped():
    engine, _ = _ems(twap_slices=3)
    sess = engine.execute([E.twap_order("o", "AAA", 3, arrival_price=100.0)], _market())
    assert sess.reports()[0].filled_quantity == pytest.approx(3)


def test_ems_routing_decision_recorded():
    engine, _ = _ems()
    sess = engine.execute([E.twap_order("o", "AAA", 100)], _market())
    assert sess.routing_decisions[0].algo == "twap"


# ── M13 risk-gate integration ─────────────────────────────────────────────────

def _gate(**lim):
    return RiskEngine(RiskEngineConfig(limits=RiskLimits(**lim))).as_gate()


def test_risk_gate_blocks_oversized():
    engine, _ = _ems(gate=_gate(max_position=0.05))
    book = PaperPortfolio(1_000_000)
    sess = engine.execute([E.market_order("o", "AAA", 1000, arrival_price=100.0)], _market(), book=book)
    assert sess.reports()[0].status == OrderStatus.REJECTED
    assert sess.rejections[0][3] == "risk_gate"


def test_risk_gate_blocked_never_routed():
    engine, _ = _ems(gate=_gate(max_position=0.05))
    book = PaperPortfolio(1_000_000)
    sess = engine.execute([E.market_order("o", "AAA", 1000, arrival_price=100.0)], _market(), book=book)
    assert sess.routing_decisions == []       # blocked before routing


def test_risk_gate_allows_within_limit():
    engine, _ = _ems(gate=_gate(max_position=0.50))
    book = PaperPortfolio(1_000_000)
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market(), book=book)
    assert sess.reports()[0].status == OrderStatus.FILLED


def test_no_gate_allows_all():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 10000, arrival_price=100.0)], _market())
    assert sess.reports()[0].status == OrderStatus.FILLED


def test_gate_without_book_allows():
    engine, _ = _ems(gate=_gate(max_position=0.01))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].status == OrderStatus.FILLED   # no book → cannot screen


# ── M12 book integration ──────────────────────────────────────────────────────

def test_m12_book_receives_fills():
    engine, _ = _ems()
    book = PaperPortfolio(1_000_000)
    engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market(), book=book)
    assert book.state.holdings["AAA"].shares == pytest.approx(100)


def test_m12_book_cash_accounting():
    engine, _ = _ems()
    book = PaperPortfolio(1_000_000)
    engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market(), book=book)
    assert book.cash == pytest.approx(990_000)


def test_m12_book_value_conserved_frictionless():
    engine, _ = _ems()
    book = PaperPortfolio(1_000_000)
    engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market(), book=book)
    assert book.value() == pytest.approx(1_000_000)


def test_m12_ledger_reconciles():
    engine, _ = _ems(twap_slices=4)
    book = PaperPortfolio(1_000_000)
    engine.execute([E.twap_order("o", "AAA", 100, arrival_price=100.0)], _market(), book=book)
    assert book.state.ledger.reconciles()


def test_duplicate_fill_protection():
    fp = E.FillProcessor()
    oms = _oms_with(E.market_order("o", "AAA", 100, arrival_price=100.0))
    _walk_to_ack(oms, "o")
    from aurelius.research.execution.ems.models import BrokerFill
    bf = BrokerFill("f1", "b", "AAA", 50, 100.0, 0.0)
    assert fp.process(bf, parent_id="o", child_id="o.0", oms=oms) is not None
    assert fp.process(bf, parent_id="o", child_id="o.0", oms=oms) is None
    assert fp.n_duplicates == 1


# ── cost / slippage / IS ──────────────────────────────────────────────────────

def test_slippage_buy_positive_when_fill_above_arrival():
    from aurelius.research.execution.ems.slippage import arrival_slippage_bps
    assert arrival_slippage_bps(100.1, 100.0, 100) == pytest.approx(10.0)


def test_slippage_sell_sign_flips():
    from aurelius.research.execution.ems.slippage import arrival_slippage_bps
    # sell filled below arrival is adverse → positive
    assert arrival_slippage_bps(99.9, 100.0, -100) == pytest.approx(10.0)


def test_slippage_zero_arrival_safe():
    from aurelius.research.execution.ems.slippage import arrival_slippage_bps
    assert arrival_slippage_bps(100, 0, 100) == 0.0


def test_report_slippage_from_sim():
    engine, _ = _ems(broker=_sim(slippage_bps=10))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].slippage_bps == pytest.approx(10.0)


def test_cost_attribution_components():
    engine, _ = _ems(broker=_sim(slippage_bps=10))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    ca = E.attribute(sess.reports()[0], adv=1e7)
    assert ca.commission > 0 and ca.spread > 0 and ca.impact > 0
    assert ca.arrival_slippage_bps == pytest.approx(10.0, abs=0.02)


def test_implementation_shortfall_matches_slippage_frictionless():
    engine, _ = _ems(broker=_sim(slippage_bps=20))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    r = sess.reports()[0]
    # zero explicit cost → IS bps == arrival slippage bps
    assert r.implementation_shortfall_bps == pytest.approx(r.slippage_bps, abs=0.05)


# ── monitoring / analytics ────────────────────────────────────────────────────

def test_metrics_fill_rate():
    engine, _ = _ems(broker=_sim(fill_ratio=0.5))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert E.metrics(sess).fill_rate == pytest.approx(0.5)


def test_metrics_counts():
    engine, _ = _ems()
    reqs = [E.market_order("o1", "AAA", 100, arrival_price=100.0),
            E.market_order("o2", "BBB", 100, arrival_price=50.0)]
    m = E.metrics(engine.execute(reqs, _market()))
    assert m.n_orders == 2 and m.n_filled == 2


def test_metrics_total_cost_with_cost_model():
    from aurelius.research.portfolio.costs import TransactionCostModel
    from aurelius.research.simulation.execution import CostExecutionModel
    b = E.MockExecutionBroker(initial_cash=1_000_000,
                              execution_model=CostExecutionModel(TransactionCostModel()))
    engine = E.EMS(E.ExecutionRouter({"b": b}))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)],
                          _market(adv={"AAA": 1e7}))
    assert E.metrics(sess).total_cost > 0


def test_by_algorithm_groups():
    engine, _ = _ems()
    reqs = [E.market_order("o1", "AAA", 100, arrival_price=100.0),
            E.twap_order("o2", "BBB", 100, arrival_price=50.0)]
    ba = E.by_algorithm(engine.execute(reqs, _market()))
    assert set(ba) == {"immediate", "twap"}


def test_by_broker_groups():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert "b" in E.by_broker(sess)


def test_metrics_alerts_on_duplicate():
    engine, _ = _ems(broker=_sim(reject_every=1))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert any("rejected" in a for a in E.metrics(sess).alerts)


# ── reconciliation ────────────────────────────────────────────────────────────

def test_reconcile_execution_clean():
    engine, broker = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    # broker fills already drained by EMS → compare against processed fills
    rr = E.reconcile_execution(sess, [E.models.BrokerFill(f.fill_id, "b", f.security_id, f.quantity, f.price, f.cost) for f in sess.fills])
    assert rr.ok


def test_reconcile_execution_missing_fill():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    extra = E.models.BrokerFill("ghost", "b", "AAA", 1, 100.0, 0.0)
    rr = E.reconcile_execution(sess, [*[E.models.BrokerFill(f.fill_id, "b", f.security_id, f.quantity, f.price, f.cost) for f in sess.fills], extra])
    assert not rr.ok and "ghost" in rr.missing_fill_ids


def test_reconcile_state_delegates_m12():
    engine, broker = _ems()
    book = PaperPortfolio(1_000_000)
    engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market(), book=book)
    broker.set_prices(PRICES)
    rep = E.reconcile_state(book, broker.get_account())
    assert rep.ok      # EMS book and broker book both got the same fills


def test_reconcile_state_detects_divergence():
    engine, broker = _ems()
    book = PaperPortfolio(1_000_000)     # empty internal book …
    engine2 = E.EMS(E.ExecutionRouter({"b": broker}))
    engine2.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())  # broker only
    broker.set_prices(PRICES)
    rep = E.reconcile_state(book, broker.get_account())
    assert not rep.ok


def test_reconcile_partial_nonterminal_flagged():
    engine, _ = _ems(broker=_sim(fill_ratio=0.5))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    rr = E.reconcile_execution(sess, [E.models.BrokerFill(f.fill_id, "b", f.security_id, f.quantity, f.price, f.cost) for f in sess.fills])
    assert rr.ok      # partially_filled is a legitimate open state, not stale


# ── validation ────────────────────────────────────────────────────────────────

def test_validate_request_ok():
    assert E.validate_request(E.market_order("o", "AAA", 10, arrival_price=100.0)).ok


def test_validate_request_zero_qty():
    assert "zero_quantity" in E.validate_request(E.market_order("o", "AAA", 0)).issues


def test_validate_request_limit_needs_price():
    o = E.OrderRequest("o", "AAA", 10, OrderType.LIMIT)
    assert "limit_order_without_price" in E.validate_request(o).issues


def test_validate_request_unpriced():
    r = E.validate_request(E.market_order("o", "ZZZ", 10), prices=PRICES)
    assert "unpriced_security" in r.issues


def test_validate_session_ok():
    engine, _ = _ems(twap_slices=3)
    sess = engine.execute([E.twap_order("o", "AAA", 90, arrival_price=100.0)], _market())
    assert E.validate_session(sess).ok


def test_validate_session_audit_starts_created():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert sess.reports()[0].events[0].kind == "created"


# ── serialization ─────────────────────────────────────────────────────────────

def test_serialization_round_trip_stable():
    from aurelius.research.execution.ems import serialization
    engine, _ = _ems(twap_slices=3)
    sess = engine.execute([E.twap_order("o", "AAA", 90, arrival_price=100.0)], _market())
    j1 = serialization.to_json(sess)
    j2 = serialization.to_json(sess)
    assert j1 == j2


def test_serialization_sorted_keys():
    from aurelius.research.execution.ems import serialization
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    d = serialization.to_dict(sess)
    assert "reports" in d and "metrics" in d and "diagnostics" in d


def test_serialization_save(tmp_path):
    from aurelius.research.execution.ems import serialization
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    p = tmp_path / "s.json"
    serialization.save_json(sess, str(p))
    assert p.exists() and p.stat().st_size > 0


def test_serialization_reports_have_events():
    from aurelius.research.execution.ems import serialization
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert serialization.to_dict(sess)["reports"][0]["events"]


# ── diagnostics / fingerprint ─────────────────────────────────────────────────

def test_diagnostics_shape():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    d = E.diagnostics(sess)
    assert d["n_orders"] == 1 and d["n_filled"] == 1


def test_fingerprint_stable():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert E.fingerprint(sess) == E.fingerprint(sess)


def test_fingerprint_changes_with_content():
    e1, _ = _ems(); s1 = e1.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    e2, _ = _ems(); s2 = e2.execute([E.market_order("o", "AAA", 50, arrival_price=100.0)], _market())
    assert E.fingerprint(s1) != E.fingerprint(s2)


# ── registry ──────────────────────────────────────────────────────────────────

class _FakeStore:
    def __init__(self): self.rows = {}
    def insert(self, exp): self.rows[exp.experiment_id] = exp


class _FakeRegistry:
    def __init__(self): self.store = _FakeStore()
    def load(self, eid): return self.store.rows.get(eid)


class _FakeExp:
    def __init__(self, eid): self.experiment_id = eid; self.metrics = {}; self.notes = ""; self.artifacts = []


def test_registry_attach_writes_metrics(tmp_path):
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    reg, exp = _FakeRegistry(), _FakeExp("E1")
    out = E.attach_execution(reg, exp, sess, artifacts_dir=str(tmp_path))
    assert "ExecFillRate" in reg.store.rows["E1"].metrics
    assert out["hash"] and out["session_fingerprint"]


def test_registry_attach_none_safe():
    assert E.attach_execution(None, None, None) == {}


# ── determinism ───────────────────────────────────────────────────────────────

def test_determinism_helper():
    def run():
        engine, _ = _ems(twap_slices=4)
        return engine.execute([E.twap_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert E.check_determinism(run, n=3)


def test_determinism_simulated_broker():
    def run():
        engine, _ = _ems(broker=_sim(fill_ratio=0.5, slippage_bps=15))
        return engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert E.check_determinism(run, n=3)


# ── edge cases ────────────────────────────────────────────────────────────────

def test_empty_batch():
    engine, _ = _ems()
    sess = engine.execute([], _market())
    assert sess.reports() == [] and E.metrics(sess).n_orders == 0


def test_sell_order_accounting():
    engine, _ = _ems()
    book = PaperPortfolio(1_000_000)
    engine.execute([E.market_order("buy", "AAA", 100, arrival_price=100.0)], _market(), book=book)
    engine.execute([E.market_order("sell", "AAA", -40, arrival_price=100.0)], _market(),
                   book=book, session_id="s2")
    assert book.state.holdings["AAA"].shares == pytest.approx(60)


def test_unpriced_order_rejected_by_broker():
    engine, _ = _ems()
    sess = engine.execute([E.market_order("o", "ZZZ", 100, arrival_price=0.0)], _market())
    assert sess.reports()[0].status == OrderStatus.REJECTED


def test_large_order_book_many_names():
    engine, _ = _ems()
    prices = {f"S{i}": 10.0 + i for i in range(200)}
    reqs = [E.market_order(f"o{i}", f"S{i}", 10, arrival_price=10.0 + i) for i in range(200)]
    sess = engine.execute(reqs, _market(prices=prices))
    assert E.metrics(sess).n_filled == 200


def test_fill_rate_bounds():
    engine, _ = _ems(broker=_sim(fill_ratio=0.3))
    sess = engine.execute([E.market_order("o", "AAA", 100, arrival_price=100.0)], _market())
    assert 0.0 <= sess.reports()[0].fill_rate <= 1.0


def test_pov_large_split_bounded():
    m = _market(interval_volume={"AAA": 10})
    plan = E.get_algorithm("pov", participation_rate=0.1, max_slices=50).plan(
        E.pov_order("o", "AAA", 100000), m)
    assert len(plan.child_orders) <= 50    # guard caps runaway slicing
