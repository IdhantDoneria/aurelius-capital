"""Tests for EventQueue ordering and event types."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aurelius.backtesting.events.base import EventQueue
from aurelius.backtesting.events.types import (
    Direction,
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderType,
    Side,
    SignalEvent,
)


def _ts(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=UTC)


@pytest.mark.unit
def test_fill_processes_before_market_same_timestamp():
    """FillEvent (priority 1) must pop before MarketEvent (priority 2)."""
    queue = EventQueue()
    ts = _ts(1)

    market = MarketEvent(
        ts,
        "AAPL",
        Decimal("185"),
        Decimal("186"),
        Decimal("184"),
        Decimal("185.5"),
        Decimal("1e6"),
    )
    fill = FillEvent(
        ts,
        "AAPL",
        Side.BUY,
        Decimal("100"),
        Decimal("185"),
        Decimal("18.50"),
        Decimal("1.85"),
        "ord-1",
    )

    queue.push(market)
    queue.push(fill)

    first = queue.pop()
    assert isinstance(first, FillEvent), "Fill must process before Market at same timestamp"
    second = queue.pop()
    assert isinstance(second, MarketEvent)


@pytest.mark.unit
def test_signal_processes_after_market():
    queue = EventQueue()
    ts = _ts(1)

    market = MarketEvent(
        ts,
        "AAPL",
        Decimal("185"),
        Decimal("186"),
        Decimal("184"),
        Decimal("185.5"),
        Decimal("1e6"),
    )
    signal = SignalEvent(ts, "AAPL", Direction.LONG)

    queue.push(signal)
    queue.push(market)

    assert isinstance(queue.pop(), MarketEvent)
    assert isinstance(queue.pop(), SignalEvent)


@pytest.mark.unit
def test_order_processes_after_signal():
    queue = EventQueue()
    ts = _ts(1)

    signal = SignalEvent(ts, "AAPL", Direction.LONG)
    order = OrderEvent(ts, "AAPL", OrderType.MARKET, Side.BUY, Decimal("100"))

    queue.push(order)
    queue.push(signal)

    assert isinstance(queue.pop(), SignalEvent)
    assert isinstance(queue.pop(), OrderEvent)


@pytest.mark.unit
def test_earlier_timestamp_processes_first():
    queue = EventQueue()

    m1 = MarketEvent(
        _ts(1),
        "AAPL",
        Decimal("185"),
        Decimal("186"),
        Decimal("184"),
        Decimal("185.5"),
        Decimal("1e6"),
    )
    m2 = MarketEvent(
        _ts(2),
        "AAPL",
        Decimal("186"),
        Decimal("187"),
        Decimal("185"),
        Decimal("186.5"),
        Decimal("1e6"),
    )
    m3 = MarketEvent(
        _ts(3),
        "AAPL",
        Decimal("187"),
        Decimal("188"),
        Decimal("186"),
        Decimal("187.5"),
        Decimal("1e6"),
    )

    queue.push(m3)
    queue.push(m1)
    queue.push(m2)

    assert queue.pop().timestamp == _ts(1)
    assert queue.pop().timestamp == _ts(2)
    assert queue.pop().timestamp == _ts(3)


@pytest.mark.unit
def test_queue_empty():
    queue = EventQueue()
    assert queue.empty()
    queue.push(SignalEvent(_ts(1), "AAPL", Direction.FLAT))
    assert not queue.empty()
    queue.pop()
    assert queue.empty()


@pytest.mark.unit
def test_sequence_numbers_are_unique():
    """Sequence numbers guarantee total order within same timestamp + type."""
    ts = _ts(1)
    events = [SignalEvent(ts, "AAPL", Direction.LONG) for _ in range(5)]
    seqs = [e._seq for e in events]
    assert len(set(seqs)) == 5, "All sequence numbers must be unique"


@pytest.mark.unit
def test_fill_event_cash_delta():
    fill = FillEvent(
        _ts(1),
        "AAPL",
        Side.BUY,
        Decimal("100"),
        Decimal("185"),
        Decimal("18.50"),
        Decimal("0"),
        "ord-1",
    )
    # Buy: cash goes out = -(notional + commission)
    assert fill.signed_cash_delta() == -(Decimal("100") * Decimal("185") + Decimal("18.50"))

    sell_fill = FillEvent(
        _ts(1),
        "AAPL",
        Side.SELL,
        Decimal("100"),
        Decimal("185"),
        Decimal("18.50"),
        Decimal("0"),
        "ord-2",
    )
    # Sell: cash comes in = notional - commission
    assert sell_fill.signed_cash_delta() == Decimal("100") * Decimal("185") - Decimal("18.50")
