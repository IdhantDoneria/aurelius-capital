"""Tests for ExecutionSimulator — fill prices, costs, partial fills."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aurelius.backtesting.config import BacktestConfig
from aurelius.backtesting.data.feed import BarData
from aurelius.backtesting.events.types import OrderEvent, OrderType, Side
from aurelius.backtesting.execution.models import CommissionModel, SlippageModel, SpreadModel
from aurelius.backtesting.execution.simulator import ExecutionSimulator


def _bar(
    open_: float = 185.0,
    high: float = 187.0,
    low: float = 183.0,
    close: float = 186.0,
    volume: float = 1_000_000,
) -> BarData:
    ts = datetime(2024, 1, 15, tzinfo=UTC)
    return BarData(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def _market_order(side: Side = Side.BUY, qty: float = 100) -> OrderEvent:
    return OrderEvent(
        timestamp=datetime(2024, 1, 14, tzinfo=UTC),
        symbol="AAPL",
        order_type=OrderType.MARKET,
        side=side,
        quantity=Decimal(str(qty)),
    )


def _sim(
    commission: float = 0.001,
    spread: float = 5,
    slippage: float = 10,
    max_fill_pct: float = 0.20,
) -> ExecutionSimulator:
    config = BacktestConfig(
        commission_rate=Decimal(str(commission)),
        spread_bps=Decimal(str(spread)),
        slippage_impact_bps=Decimal(str(slippage)),
        max_fill_pct_adv=Decimal(str(max_fill_pct)),
    )
    return ExecutionSimulator(config)


# ── Commission model ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_commission_flat_rate():
    model = CommissionModel(Decimal("0.001"))
    comm = model.compute(Decimal("18_500"))  # $18,500 notional
    assert comm == Decimal("18.50")


# ── Spread model ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_spread_increases_buy_price():
    model = SpreadModel(half_spread_bps=Decimal("10"))  # 10 bps = 0.10%
    price = model.adjusted_price(Decimal("100.00"), is_buy=True)
    assert float(price) == pytest.approx(100.10, rel=1e-4)


@pytest.mark.unit
def test_spread_decreases_sell_price():
    model = SpreadModel(half_spread_bps=Decimal("10"))
    price = model.adjusted_price(Decimal("100.00"), is_buy=False)
    assert float(price) == pytest.approx(99.90, rel=1e-4)


# ── Slippage model ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_slippage_zero_at_tiny_order():
    model = SlippageModel(impact_coefficient_bps=Decimal("10"))
    # 1 share out of 1,000,000 ADV = negligible participation
    _, adj = model.compute_impact(Decimal("1"), Decimal("1_000_000"), Decimal("185"))
    assert float(adj) < 0.001  # less than $0.001 impact per share


@pytest.mark.unit
def test_slippage_fallback_on_zero_volume():
    model = SlippageModel(fallback_bps=Decimal("5"))
    _, adj = model.compute_impact(Decimal("100"), Decimal("0"), Decimal("100"))
    # fallback = 5bps of $100 = $0.05
    assert float(adj) == pytest.approx(0.05, rel=1e-4)


# ── ExecutionSimulator ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_market_order_fills_at_open():
    sim = _sim()
    order = _market_order(Side.BUY, qty=100)
    bar = _bar(open_=185.0)
    fill = sim.try_fill(order, bar)

    assert fill is not None
    assert fill.symbol == "AAPL"
    assert fill.side == Side.BUY
    # Fill price > open due to spread + slippage
    assert float(fill.fill_price) > 185.0


@pytest.mark.unit
def test_market_sell_order_fills_below_open():
    sim = _sim()
    order = _market_order(Side.SELL, qty=100)
    bar = _bar(open_=185.0)
    fill = sim.try_fill(order, bar)

    assert fill is not None
    # Sell: fill_price < open due to spread and slippage
    assert float(fill.fill_price) < 185.0


@pytest.mark.unit
def test_limit_buy_fills_when_price_reached():
    sim = _sim()
    order = OrderEvent(
        timestamp=datetime(2024, 1, 14, tzinfo=UTC),
        symbol="AAPL",
        order_type=OrderType.LIMIT,
        side=Side.BUY,
        quantity=Decimal("100"),
        limit_price=Decimal("184.00"),  # limit below bar's low? No, bar.low=183
    )
    bar = _bar(low=183.0)  # bar's low=183 ≤ limit=184 → fills
    fill = sim.try_fill(order, bar)
    assert fill is not None


@pytest.mark.unit
def test_limit_buy_does_not_fill_when_price_not_reached():
    sim = _sim()
    order = OrderEvent(
        timestamp=datetime(2024, 1, 14, tzinfo=UTC),
        symbol="AAPL",
        order_type=OrderType.LIMIT,
        side=Side.BUY,
        quantity=Decimal("100"),
        limit_price=Decimal("180.00"),  # limit below bar's low (183)
    )
    bar = _bar(low=183.0)  # price never reached 180 this bar
    fill = sim.try_fill(order, bar)
    assert fill is None


@pytest.mark.unit
def test_stop_sell_triggers_when_price_breached():
    sim = _sim()
    order = OrderEvent(
        timestamp=datetime(2024, 1, 14, tzinfo=UTC),
        symbol="AAPL",
        order_type=OrderType.STOP,
        side=Side.SELL,
        quantity=Decimal("100"),
        stop_price=Decimal("184.00"),  # stop above bar's low (183)
    )
    bar = _bar(low=183.0)  # bar's low ≤ stop → triggered
    fill = sim.try_fill(order, bar)
    assert fill is not None


@pytest.mark.unit
def test_partial_fill_on_large_order():
    """Orders > 20% ADV should be partially filled."""
    sim = _sim(max_fill_pct=0.20)
    # 1,000,000 volume x 20% = 200,000 shares max fill
    order = _market_order(Side.BUY, qty=500_000)  # way more than ADV
    bar = _bar(volume=1_000_000)
    fill = sim.try_fill(order, bar)

    assert fill is not None
    assert fill.quantity == pytest.approx(200_000, rel=1e-4)  # 20% of 1M ADV
    assert fill.quantity < order.quantity


@pytest.mark.unit
def test_commission_on_fill():
    sim = _sim(commission=0.001)  # 10bps
    order = _market_order(Side.BUY, qty=100)
    bar = _bar(open_=185.0, volume=1_000_000)
    fill = sim.try_fill(order, bar)

    # Commission ≈ 100 x 185 x 0.001 = $18.50 (approximately, after spread/slippage)
    assert float(fill.commission) > 0
    assert float(fill.commission) == pytest.approx(float(fill.fill_price) * 100 * 0.001, rel=1e-2)


@pytest.mark.unit
def test_fill_notional():
    sim = _sim()
    order = _market_order(Side.BUY, qty=100)
    bar = _bar(open_=185.0)
    fill = sim.try_fill(order, bar)
    expected_notional = fill.quantity * fill.fill_price
    assert fill.notional == expected_notional
