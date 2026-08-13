"""Phase-9 paper platform tests: broker, journal, engine recovery, dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from mentisrex.backtesting.events.types import OrderType, Side
from mentisrex.paper import (
    OrderRequest,
    PaperBroker,
    Tick,
    TradeJournal,
    TradingEngine,
    build_snapshot,
    render_text,
    replay,
)
from mentisrex.risk import RiskEngine

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _tick(sym, price, i=0):
    return Tick(T0 + timedelta(seconds=i), sym, Decimal(str(price)))


# ── broker ────────────────────────────────────────────────────────────────────


def test_market_order_fills_and_updates_balance():
    b = PaperBroker(cash=Decimal("100000"), commission_rate=Decimal("0"), slippage_bps=Decimal("0"))
    b.on_tick(_tick("AAA", 100))
    res = b.submit(OrderRequest("AAA", Side.BUY, Decimal("10")))
    assert res.accepted
    assert res.fill is not None
    assert b.state.position("AAA").quantity == Decimal("10")
    assert b.state.cash == Decimal("99000")  # 100k - 10*100


def test_market_order_needs_market_data():
    b = PaperBroker()
    res = b.submit(OrderRequest("AAA", Side.BUY, Decimal("1")))
    assert not res.accepted
    assert "no market data" in res.reason


def test_insufficient_buying_power_rejected():
    b = PaperBroker(cash=Decimal("500"))
    b.on_tick(_tick("AAA", 100))
    res = b.submit(OrderRequest("AAA", Side.BUY, Decimal("10")))  # needs 1000
    assert not res.accepted
    assert "buying power" in res.reason


def test_limit_order_rests_then_fills_on_cross():
    b = PaperBroker(cash=Decimal("100000"), commission_rate=Decimal("0"), slippage_bps=Decimal("0"))
    b.on_tick(_tick("AAA", 100, 0))
    res = b.submit(
        OrderRequest("AAA", Side.BUY, Decimal("5"), OrderType.LIMIT, limit_price=Decimal("95"))
    )
    assert res.accepted
    assert res.resting
    assert b.open_orders == 1
    fills = b.on_tick(_tick("AAA", 96, 1))  # above limit -> no fill
    assert fills == []
    fills = b.on_tick(_tick("AAA", 94, 2))  # crosses 95 -> fills
    assert len(fills) == 1
    assert b.open_orders == 0
    assert b.state.position("AAA").quantity == Decimal("5")


def test_slippage_hurts_the_taker():
    b = PaperBroker(
        cash=Decimal("100000"), commission_rate=Decimal("0"), slippage_bps=Decimal("10")
    )
    b.on_tick(_tick("AAA", 100))
    res = b.submit(OrderRequest("AAA", Side.BUY, Decimal("1")))
    assert res.fill.fill_price > Decimal("100")  # buy pays up


def test_risk_engine_screens_orders():
    eng = RiskEngine()
    eng.trip("halt")
    b = PaperBroker(cash=Decimal("100000"), risk_engine=eng)
    b.on_tick(_tick("AAA", 100))
    res = b.submit(OrderRequest("AAA", Side.BUY, Decimal("1")))
    assert not res.accepted  # kill switch blocks it


# ── journal ─────────────────────────────────────────────────────────────────


def test_journal_round_trip(tmp_path):
    j = TradeJournal(tmp_path / "j.jsonl")
    j.record("fill", symbol="AAA", qty=Decimal("10"), price=Decimal("100.5"))
    j.record("error", where="tick", error="boom")
    assert len(j.read()) == 2
    fills = j.read("fill")
    assert len(fills) == 1
    assert fills[0]["price"] == 100.5  # Decimal serialized to float


# ── engine: error recovery + restart ─────────────────────────────────────────


def _buy_once_strategy():
    placed = {"done": False}

    def strat(tick, _broker):
        if not placed["done"]:
            placed["done"] = True
            return [OrderRequest(tick.symbol, Side.BUY, Decimal("10"))]
        return []

    return strat


def test_engine_runs_and_fills(tmp_path):
    b = PaperBroker(cash=Decimal("100000"))
    eng = TradingEngine(b, TradeJournal(tmp_path / "j.jsonl"), strategy=_buy_once_strategy())
    ticks = [_tick("AAA", 100 + i, i) for i in range(5)]
    eng.run(replay(ticks))
    assert eng.health.ticks == 5
    assert eng.health.fills == 1
    assert b.state.position("AAA").quantity == Decimal("10")
    assert len(eng.equity_curve) == 5


def test_bad_tick_does_not_kill_loop(tmp_path):
    b = PaperBroker(cash=Decimal("100000"))
    eng = TradingEngine(b, TradeJournal(tmp_path / "j.jsonl"))
    alerts = []
    eng._alert = lambda level, msg: alerts.append((level, msg))

    good = [_tick("AAA", 100, 0), _tick("AAA", 101, 2)]

    def source():
        yield good[0]
        yield "NOT_A_TICK"  # will blow up in process_tick
        yield good[1]

    eng.run(source())
    assert eng.health.errors == 1  # one bad tick caught
    assert eng.health.ticks == 2  # both good ticks still processed
    assert any(lvl == "error" for lvl, _ in alerts)


def test_run_forever_restarts_on_source_failure(tmp_path):
    b = PaperBroker(cash=Decimal("100000"))
    eng = TradingEngine(
        b, TradeJournal(tmp_path / "j.jsonl"), checkpoint_path=str(tmp_path / "ckpt.json")
    )
    ticks = [_tick("AAA", 100 + i, i) for i in range(3)]
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:

            def boom():
                yield ticks[0]
                raise ConnectionError("dropped")

            return boom()
        return replay(ticks)

    eng.run_forever(factory, max_restarts=3, sleep=lambda _s: None)
    assert eng.health.restarts == 1
    assert (tmp_path / "ckpt.json").exists()  # checkpointed on shutdown


def test_run_forever_gives_up_at_max_restarts(tmp_path):
    b = PaperBroker(cash=Decimal("100000"))
    eng = TradingEngine(b, TradeJournal(tmp_path / "j.jsonl"))

    def always_fails():
        def boom():
            raise ConnectionError("dead feed")
            yield  # unreachable, makes it a generator

        return boom()

    eng.run_forever(always_fails, max_restarts=2, sleep=lambda _s: None)
    assert eng.health.restarts == 2  # bounded, does not hang


# ── dashboard ─────────────────────────────────────────────────────────────────


def test_dashboard_snapshot(tmp_path):
    b = PaperBroker(cash=Decimal("100000"))
    eng = TradingEngine(b, TradeJournal(tmp_path / "j.jsonl"), strategy=_buy_once_strategy())
    eng.run(replay([_tick("AAA", 100 + i, i) for i in range(4)]))
    snap = build_snapshot(eng, b)
    assert set(snap) >= {"account", "performance", "health"}
    assert "PAPER TRADING DASHBOARD" in render_text(eng, b)


def test_demo_self_check():
    from mentisrex.paper import demo

    demo()
