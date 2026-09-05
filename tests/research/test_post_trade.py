"""AIDP M15 — Trade Lifecycle & Post-Trade Operations tests.

Deterministic, offline. Covers trade lifecycle, settlement timing (T+0/1/2 + business
days), cash/position/trade ledgers, corporate actions, reconciliation, accounting reuse
(M11), M12/M14 compatibility, performance, tax lots, reporting, monitoring, validation,
serialization, registry, failure scenarios, determinism, and edge cases.
"""

from __future__ import annotations

from datetime import date

import pytest

from mentisrex.research import post_trade as PT
from mentisrex.research.post_trade import serialization
from mentisrex.research.post_trade.models import (
    CashType,
    DelistingEvent,
    DividendEvent,
    LifecycleState,
    MergerEvent,
    SettlementStatus,
    SplitEvent,
    SymbolChangeEvent,
)

MON = date(2026, 8, 3)  # Monday
WED = date(2026, 8, 5)
FRI = date(2026, 8, 7)


def _eng(cash=1_000_000.0, days=2):
    return PT.PostTradeEngine(cash, settlement_config=PT.SettlementConfig(default_days=days))


def _booked(eng, sid="AAA", qty=100, price=100.0, cost=0.0, when=MON):
    return eng.book_fill(security_id=sid, quantity=qty, price=price, cost=cost, trade_date=when)


# ── settlement date math ──────────────────────────────────────────────────────


def test_settlement_t0():
    assert PT.settlement_date(MON, 0) == MON


def test_settlement_t1():
    assert PT.settlement_date(MON, 1) == date(2026, 8, 4)


def test_settlement_t2():
    assert PT.settlement_date(MON, 2) == WED


def test_settlement_skips_weekend():
    # Friday + T+1 → Monday
    assert PT.settlement_date(FRI, 1) == date(2026, 8, 10)


def test_settlement_skips_holiday():
    sd = PT.settlement_date(MON, 1, holidays=("2026-08-04",))
    assert sd == date(2026, 8, 5)


def test_settlement_none_date():
    assert PT.settlement_date(None, 2) is None


# ── trade lifecycle ───────────────────────────────────────────────────────────


def test_book_fill_returns_id():
    eng = _eng()
    assert _booked(eng).startswith("T")


def test_book_fill_state_pending():
    eng = _eng()
    tid = _booked(eng)
    assert eng.trades[tid] == LifecycleState.SETTLEMENT_PENDING


def test_book_fill_updates_m11_position():
    eng = _eng()
    _booked(eng, qty=100)
    assert eng.accounting.shares("AAA") == pytest.approx(100)


def test_book_fill_moves_economic_cash():
    eng = _eng()
    _booked(eng, qty=100, price=100.0, cost=5.0)
    assert eng.accounting.cash == pytest.approx(1_000_000 - 10_005)


def test_book_zero_qty_raises():
    eng = _eng()
    with pytest.raises(ValueError):
        eng.book_fill(security_id="AAA", quantity=0, price=100.0, trade_date=MON)


def test_book_duplicate_trade_id_raises():
    eng = _eng()
    eng.book_fill(security_id="AAA", quantity=1, price=100.0, trade_date=MON, trade_id="X")
    with pytest.raises(ValueError):
        eng.book_fill(security_id="AAA", quantity=1, price=100.0, trade_date=MON, trade_id="X")


def test_book_creates_settlement_instruction():
    eng = _eng()
    tid = _booked(eng)
    assert f"S-{tid}" in eng.settlement.instructions


def test_book_emits_events():
    eng = _eng()
    _booked(eng)
    from mentisrex.research.post_trade.models import CashEvent, PositionEvent, TradeEvent

    assert eng.log.of_type(TradeEvent)
    assert eng.log.of_type(PositionEvent)
    assert eng.log.of_type(CashEvent)


def test_book_fills_batch():
    eng = _eng()
    from mentisrex.research.post_trade.models import CashEvent

    class F:
        def __init__(self, sid, q, p):
            self.security_id, self.quantity, self.price, self.cost, self.fill_id, self.when = (
                sid,
                q,
                p,
                0.0,
                f"f{sid}",
                MON,
            )

    ids = eng.book_fills([F("AAA", 10, 100.0), F("BBB", 5, 50.0)])
    assert len(ids) == 2
    assert eng.accounting.shares("BBB") == pytest.approx(5)
    assert len(eng.log.of_type(CashEvent)) == 2


# ── settlement engine ─────────────────────────────────────────────────────────


def test_settle_completes_due():
    eng = _eng()
    tid = _booked(eng)
    done = eng.settle(WED)
    assert done == [tid]
    assert eng.trades[tid] == LifecycleState.SETTLED


def test_settle_not_due_stays_pending():
    eng = _eng()
    tid = _booked(eng)
    assert eng.settle(date(2026, 8, 4)) == []  # T+2 not reached
    assert eng.trades[tid] == LifecycleState.SETTLEMENT_PENDING


def test_settled_cash_grows_on_settlement():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    before = eng.cash_ledger.settled_balance()
    eng.settle(WED)
    assert eng.cash_ledger.settled_balance() == pytest.approx(before - 10_000)


def test_settlement_failure():
    eng = _eng()
    tid = _booked(eng)
    eng.fail_settlement(tid, reason="dk")
    assert eng.trades[tid] == LifecycleState.FAILED
    assert eng.settlement.instructions[f"S-{tid}"].status == SettlementStatus.FAILED


def test_settlement_report_counts():
    eng = _eng()
    _booked(eng, sid="AAA")
    t2 = _booked(eng, sid="BBB", price=50.0)
    eng.settle(WED)
    eng.fail_settlement(t2.split("-")[-1] if "-" in t2 else t2) if False else None
    rep = eng.settlement.report(WED)
    assert rep.n_completed == 2
    assert rep.n_pending == 0


def test_t0_settles_same_day():
    eng = _eng(days=0)
    tid = _booked(eng)
    assert eng.settle(MON) == [tid]


# ── cash ledger ───────────────────────────────────────────────────────────────


def test_cash_economic_equals_m11():
    eng = _eng()
    _booked(eng, cost=3.0)
    assert eng.cash_ledger.economic_balance() == pytest.approx(eng.accounting.cash)


def test_cash_available_is_settled():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    assert eng.cash_ledger.available() == pytest.approx(
        1_000_000
    )  # unsettled outflow not yet available
    eng.settle(WED)
    assert eng.cash_ledger.available() == pytest.approx(990_000)


def test_cash_restricted_is_pending_outflow():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    assert eng.cash_ledger.restricted() == pytest.approx(10_000)


def test_cash_report_reconciles():
    eng = _eng()
    _booked(eng)
    assert PT.cash_report(eng).reconciles


def test_settlement_obligations():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    obl = PT.settlement_obligations(eng)
    assert obl[WED] == pytest.approx(-10_000)


# ── position ledger ───────────────────────────────────────────────────────────


def test_position_ledger_net_matches_m11():
    eng = _eng()
    _booked(eng, qty=100)
    _booked(eng, qty=-40, when=MON)
    assert eng.position_ledger.net_shares()["AAA"] == pytest.approx(60)
    assert eng.accounting.shares("AAA") == pytest.approx(60)


def test_ledger_reconciles_flag():
    eng = _eng()
    _booked(eng)
    assert PT.ledger_reconciles(eng)


# ── corporate actions ─────────────────────────────────────────────────────────


def test_cash_dividend():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="D", security_id="AAA", amount_per_share=2.0, ex_date=WED)
    )
    assert eng.accounting.cash == pytest.approx(1_000_000 - 10_000 + 200)


def test_cash_dividend_reconciles():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="D", security_id="AAA", amount_per_share=2.0)
    )
    assert eng.cash_ledger.reconciles(eng.accounting.cash)


def test_stock_dividend_adds_shares():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="SD", security_id="AAA", stock_ratio=0.1)
    )
    assert eng.accounting.shares("AAA") == pytest.approx(110)


def test_split_doubles_shares_halves_basis():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    PT.apply_corporate_action(eng, SplitEvent(action_id="SP", security_id="AAA", ratio=2.0))
    h = eng.accounting.state.holdings["AAA"]
    assert h.shares == pytest.approx(200)
    assert h.cost_basis == pytest.approx(50)


def test_split_preserves_value():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    eng.accounting.mark({"AAA": 100.0})
    v0 = eng.accounting.state.holdings["AAA"].market_value
    PT.apply_corporate_action(eng, SplitEvent(action_id="SP", security_id="AAA", ratio=4.0))
    assert eng.accounting.state.holdings["AAA"].market_value == pytest.approx(v0)


def test_reverse_split_type():
    ev = SplitEvent(action_id="R", security_id="AAA", ratio=0.5)
    assert ev.action_type == "reverse_split"


def test_merger_cash_and_rename():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    PT.apply_corporate_action(
        eng,
        MergerEvent(
            action_id="M",
            security_id="AAA",
            new_security_id="BBB",
            share_ratio=1.0,
            cash_per_share=5.0,
        ),
    )
    assert eng.accounting.shares("AAA") == 0
    assert eng.accounting.shares("BBB") == pytest.approx(100)
    assert eng.accounting.cash == pytest.approx(1_000_000 - 10_000 + 500)


def test_merger_ratio_keeps_ledger_reconciled():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    PT.apply_corporate_action(
        eng, MergerEvent(action_id="M2", security_id="AAA", new_security_id="CCC", share_ratio=1.5)
    )
    assert eng.accounting.shares("CCC") == pytest.approx(150)
    assert PT.ledger_reconciles(eng)  # rename + ratio must not desync position ledger


def test_symbol_change_keeps_ledger_reconciled():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, SymbolChangeEvent(action_id="SC2", security_id="AAA", new_security_id="ZZZ")
    )
    assert PT.ledger_reconciles(eng)


def test_symbol_change():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, SymbolChangeEvent(action_id="SC", security_id="AAA", new_security_id="ZZZ")
    )
    assert eng.accounting.shares("ZZZ") == pytest.approx(100)
    assert eng.accounting.shares("AAA") == 0


def test_delisting_closes_position():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    PT.apply_corporate_action(
        eng, DelistingEvent(action_id="DL", security_id="AAA", final_price=0.0)
    )
    assert eng.accounting.shares("AAA") == 0


def test_corporate_action_emits_event():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="D", security_id="AAA", amount_per_share=1.0)
    )
    from mentisrex.research.post_trade.models import CorporateActionEvent

    assert len(eng.log.of_type(CorporateActionEvent)) == 1


def test_corporate_action_report():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="D", security_id="AAA", amount_per_share=1.0)
    )
    PT.apply_corporate_action(eng, SplitEvent(action_id="S", security_id="AAA", ratio=2.0))
    rep = PT.corporate_action_report(eng)
    assert rep.n_actions == 2
    assert rep.total_cash_impact == pytest.approx(100)


# ── reconciliation ────────────────────────────────────────────────────────────


def test_reconcile_clean():
    eng = _eng()
    _booked(eng)
    assert PT.reconcile(eng).ok


def test_reconcile_broker_match():
    from mentisrex.research.paper_trading.models import BrokerAccount, BrokerPosition

    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    acct = BrokerAccount(
        "B", eng.accounting.cash, {"AAA": BrokerPosition("AAA", 100, 100.0, 100.0)}
    )
    assert PT.reconcile(eng, broker_account=acct).ok


def test_reconcile_incorrect_quantity():
    from mentisrex.research.paper_trading.models import BrokerAccount, BrokerPosition

    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    acct = BrokerAccount("B", eng.accounting.cash, {"AAA": BrokerPosition("AAA", 90, 100.0, 100.0)})
    rep = PT.reconcile(eng, broker_account=acct)
    assert not rep.ok
    assert any(d["category"] == "incorrect_quantity" for d in rep.differences)


def test_reconcile_missing_trade():
    class F:
        fill_id, security_id, quantity, price, cost, when = "ghost", "AAA", 10, 100.0, 0.0, MON

    eng = _eng()
    _booked(eng)
    rep = PT.reconcile(eng, execution_fills=[F()])
    assert not rep.ok
    assert any(d["category"] == "missing_trade" for d in rep.differences)


def test_reconcile_failed_settlement():
    eng = _eng()
    tid = _booked(eng)
    eng.fail_settlement(tid)
    rep = PT.reconcile(eng)
    assert any(d["category"] == "failed_settlement" for d in rep.differences)


# ── accounting reuse (M11) ────────────────────────────────────────────────────


def test_m11_ledger_reconciles():
    eng = _eng()
    _booked(eng, qty=100, price=100.0, cost=5.0)
    _booked(eng, qty=-50, price=110.0, cost=2.0)
    assert eng.accounting.state.ledger.reconciles()


def test_realized_pnl_from_m11():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    eng.book_fill(security_id="AAA", quantity=-100, price=110.0, trade_date=MON)
    assert eng.accounting.realized_pnl() == pytest.approx(1000)


def test_unrealized_pnl_from_m11():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    eng.accounting.mark({"AAA": 105.0})
    assert eng.accounting.unrealized_pnl() == pytest.approx(500)


# ── M14 execution integration ─────────────────────────────────────────────────


def test_book_m14_execution_report():
    from mentisrex.research.execution import ems as E
    from mentisrex.research.execution.ems.orders import MarketInfo

    broker = E.MockExecutionBroker(initial_cash=1e9)
    engine = E.EMS(E.ExecutionRouter({"b": broker}))
    sess = engine.execute(
        [E.market_order("o", "AAA", 100, arrival_price=100.0)], MarketInfo(prices={"AAA": 100.0})
    )
    pt = _eng()
    tid = pt.book_execution_report(sess.reports()[0], trade_date=MON)
    assert tid
    assert pt.accounting.shares("AAA") == pytest.approx(100)


def test_book_m14_fills():
    from mentisrex.research.execution import ems as E
    from mentisrex.research.execution.ems.orders import MarketInfo

    broker = E.MockExecutionBroker(initial_cash=1e9)
    engine = E.EMS(E.ExecutionRouter({"b": broker}), config=E.ExecutionConfig(twap_slices=4))
    sess = engine.execute(
        [E.twap_order("o", "AAA", 100, arrival_price=100.0)], MarketInfo(prices={"AAA": 100.0})
    )
    pt = _eng()
    ids = pt.book_fills(sess.fills, trade_date=MON)
    assert len(ids) == 4
    assert pt.accounting.shares("AAA") == pytest.approx(100)


# ── performance ───────────────────────────────────────────────────────────────


def test_performance_turnover():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    assert PT.performance(eng)["turnover"] > 0


def test_performance_dividend_impact():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="D", security_id="AAA", amount_per_share=1.0)
    )
    assert PT.performance(eng)["dividend_impact"] == pytest.approx(100)


def test_cost_attribution():
    eng = _eng()
    _booked(eng, qty=100, price=100.0, cost=7.0)
    assert PT.cost_attribution(eng)["total_cost"] == pytest.approx(7.0)


# ── tax lots ──────────────────────────────────────────────────────────────────


def test_tax_lots_fifo_close():
    book = PT.TaxLotBook()
    book.buy("AAA", 100, 100.0, when=date(2026, 1, 1))
    gains = book.sell("AAA", 60, 120.0, when=date(2026, 3, 1))
    assert gains[0].gain == pytest.approx(60 * 20)
    assert book.open_lots("AAA")[0].shares == pytest.approx(40)


def test_tax_holding_period_classification():
    book = PT.TaxLotBook()
    book.buy("AAA", 10, 100.0, when=date(2025, 1, 1))
    g = book.sell("AAA", 10, 110.0, when=date(2026, 6, 1))
    assert g[0].category == "long_term"


def test_tax_short_term():
    book = PT.TaxLotBook()
    book.buy("AAA", 10, 100.0, when=date(2026, 1, 1))
    g = book.sell("AAA", 10, 110.0, when=date(2026, 3, 1))
    assert g[0].category == "short_term"


def test_tax_build_from_engine():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    book = PT.build_from_engine(eng)
    assert book.open_lots("AAA")[0].shares == pytest.approx(100)


# ── reporting / monitoring ────────────────────────────────────────────────────


def test_post_trade_report_composite():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    eng.settle(WED)
    rep = PT.post_trade_report(eng, as_of=WED)
    assert rep.health.ok
    assert rep.ledger.reconciles
    assert rep.cash.reconciles


def test_operational_health_flags_failure():
    eng = _eng()
    tid = _booked(eng)
    eng.fail_settlement(tid)
    h = PT.operational_health(eng)
    assert not h.ok
    assert h.n_failed_settlements == 1


def test_settlement_completion_rate():
    eng = _eng()
    _booked(eng, sid="AAA")
    _booked(eng, sid="BBB", price=50.0)
    eng.settle(WED)
    assert PT.operational_health(eng).settlement_completion_rate == pytest.approx(1.0)


# ── validation ────────────────────────────────────────────────────────────────


def test_validate_engine_ok():
    eng = _eng()
    _booked(eng)
    assert PT.validate_engine(eng).ok


def test_validate_fill_zero_qty():
    assert "zero_quantity" in PT.validate_fill("AAA", 0, 100.0).issues


def test_validate_fill_negative_price():
    assert "negative_price" in PT.validate_fill("AAA", 10, -1.0).issues


def test_validate_engine_event_seq_monotonic():
    eng = _eng()
    _booked(eng, sid="AAA")
    _booked(eng, sid="BBB", price=50.0)
    seqs = [e.seq for e in eng.log.events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


# ── serialization ─────────────────────────────────────────────────────────────


def test_serialization_round_trip_stable():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    eng.settle(WED)
    assert serialization.to_json(eng) == serialization.to_json(eng)


def test_serialization_has_events():
    eng = _eng()
    _booked(eng)
    d = serialization.to_dict(eng)
    assert d["events"]
    assert d["report"]
    assert "diagnostics" in d


def test_serialization_save(tmp_path):
    eng = _eng()
    _booked(eng)
    p = tmp_path / "s.json"
    serialization.save_json(eng, str(p))
    assert p.exists()
    assert p.stat().st_size > 0


# ── diagnostics / determinism ─────────────────────────────────────────────────


def test_fingerprint_stable():
    eng = _eng()
    _booked(eng)
    assert PT.fingerprint(eng) == PT.fingerprint(eng)


def test_fingerprint_changes_with_content():
    e1 = _eng()
    _booked(e1, qty=100)
    e2 = _eng()
    _booked(e2, qty=50)
    assert PT.fingerprint(e1) != PT.fingerprint(e2)


def test_determinism_helper():
    def run():
        eng = _eng()
        _booked(eng, qty=100, price=100.0, cost=5.0)
        eng.settle(WED)
        PT.apply_corporate_action(
            eng, DividendEvent(action_id="D", security_id="AAA", amount_per_share=1.0)
        )
        return eng

    assert PT.check_determinism(run, n=3)


def test_replay_reproduces_event_count():
    eng = _eng()
    _booked(eng, qty=100)
    eng.settle(WED)
    seen = []
    eng.log.replay(lambda e: seen.append(e.seq))
    assert seen == sorted(seen)
    assert len(seen) == len(eng.log)


# ── registry ──────────────────────────────────────────────────────────────────


class _Store:
    def __init__(self):
        self.rows = {}

    def insert(self, exp):
        self.rows[exp.experiment_id] = exp


class _Registry:
    def __init__(self):
        self.store = _Store()

    def load(self, eid):
        return self.store.rows.get(eid)


class _Exp:
    def __init__(self, eid):
        self.experiment_id = eid
        self.metrics = {}
        self.notes = ""
        self.artifacts = []


def test_registry_attach(tmp_path):
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    eng.settle(WED)
    reg, exp = _Registry(), _Exp("E1")
    out = PT.attach_post_trade(reg, exp, eng, artifacts_dir=str(tmp_path))
    assert "PostTradeValue" in reg.store.rows["E1"].metrics
    assert out["hash"]


def test_registry_none_safe():
    assert PT.attach_post_trade(None, None, None) == {}


# ── failure / edge cases ──────────────────────────────────────────────────────


def test_empty_engine_reports():
    eng = _eng()
    rep = PT.post_trade_report(eng)
    assert rep.n_positions == 0
    assert rep.health.ok


def test_short_sell_then_cover():
    eng = _eng()
    _booked(eng, qty=-100, price=100.0)
    assert eng.accounting.shares("AAA") == pytest.approx(-100)
    eng.book_fill(security_id="AAA", quantity=100, price=90.0, trade_date=MON)
    assert eng.accounting.realized_pnl() == pytest.approx(1000)  # shorted 100, covered 90


def test_post_cash_interest_reconciles():
    eng = _eng()
    eng.post_cash(1234.0, CashType.INTEREST, when=MON)
    assert eng.cash_ledger.reconciles(eng.accounting.cash)
    assert eng.accounting.cash == pytest.approx(1_001_234)


def test_dividend_on_zero_position_no_cash():
    eng = _eng()
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="D", security_id="AAA", amount_per_share=1.0)
    )
    assert eng.accounting.cash == pytest.approx(1_000_000)


def test_delisting_nonzero_price_books_cash():
    eng = _eng()
    _booked(eng, qty=100, price=100.0)
    PT.apply_corporate_action(
        eng, DelistingEvent(action_id="DL2", security_id="AAA", final_price=30.0)
    )
    assert eng.accounting.cash == pytest.approx(1_000_000 - 10_000 + 3_000)
    assert eng.accounting.realized_pnl() == pytest.approx(100 * (30.0 - 100.0))


def test_stock_dividend_keeps_ledger_reconciled():
    eng = _eng()
    _booked(eng, qty=100)
    PT.apply_corporate_action(
        eng, DividendEvent(action_id="SD2", security_id="AAA", stock_ratio=0.5)
    )
    assert eng.accounting.shares("AAA") == pytest.approx(150)
    assert PT.ledger_reconciles(eng)


def test_tax_realized_summary():
    book = PT.TaxLotBook()
    book.buy("AAA", 10, 100.0, when=date(2026, 1, 1))
    book.sell("AAA", 10, 130.0, when=date(2026, 2, 1))
    assert book.realized_summary()["short_term"] == pytest.approx(300)


def test_t1_settlement_config():
    eng = _eng(days=1)
    tid = _booked(eng)
    assert eng.settlement.instructions[f"S-{tid}"].settle_date == date(2026, 8, 4)


def test_pending_then_settle_full_cycle():
    eng = _eng()
    tid = _booked(eng, qty=100, price=100.0)
    assert eng.trades[tid] == LifecycleState.SETTLEMENT_PENDING
    eng.settle(WED)
    assert eng.trades[tid] == LifecycleState.SETTLED
    assert PT.validate_engine(eng).ok
