"""Tests for trading validation models: OrderCreateRequest, FillIngest, PositionCloseRequest.

Module at 0% coverage — these are the trust-boundary validators that gate every
order and fill before they hit the DB. All path-of-no-return business rules live here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from mentisrex.infrastructure.database.validation.trading import (
    FillIngest,
    OrderCreateRequest,
    PositionCloseRequest,
)

_ACCOUNT = uuid4()
_SYMBOL = uuid4()
_ORDER = uuid4()
_STRATEGY = uuid4()


def _base_order(**kw) -> dict:
    defaults = {
        "account_id": _ACCOUNT,
        "symbol_id": _SYMBOL,
        "order_type": "market",
        "side": "buy",
        "quantity": Decimal("100"),
    }
    defaults.update(kw)
    return defaults


def _base_fill(**kw) -> dict:
    defaults = {
        "order_id": _ORDER,
        "account_id": _ACCOUNT,
        "symbol_id": _SYMBOL,
        "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
        "side": "buy",
        "price": Decimal("185.00"),
        "quantity": Decimal("100"),
        "notional_value": Decimal("18500.00"),
        "commission": Decimal("0"),
    }
    defaults.update(kw)
    return defaults


# ── OrderCreateRequest ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_market_order_valid():
    req = OrderCreateRequest(**_base_order())
    assert req.order_type == "market"
    assert req.side == "buy"


@pytest.mark.unit
def test_limit_order_requires_limit_price():
    with pytest.raises(Exception, match="limit_price required"):
        OrderCreateRequest(**_base_order(order_type="limit"))


@pytest.mark.unit
def test_limit_order_with_price_valid():
    req = OrderCreateRequest(**_base_order(order_type="limit", limit_price=Decimal("185")))
    assert req.limit_price == Decimal("185")


@pytest.mark.unit
def test_stop_order_requires_stop_price():
    with pytest.raises(Exception, match="stop_price required"):
        OrderCreateRequest(**_base_order(order_type="stop"))


@pytest.mark.unit
def test_stop_limit_requires_both_prices():
    with pytest.raises(ValueError, match=".*"):
        # Missing both limit_price and stop_price
        OrderCreateRequest(**_base_order(order_type="stop_limit"))


@pytest.mark.unit
def test_stop_limit_with_both_prices_valid():
    req = OrderCreateRequest(
        **_base_order(
            order_type="stop_limit", limit_price=Decimal("184"), stop_price=Decimal("183")
        )
    )
    assert req.order_type == "stop_limit"


@pytest.mark.unit
def test_invalid_order_type_rejected():
    with pytest.raises(ValueError, match="order_type"):
        OrderCreateRequest(**_base_order(order_type="futures"))


@pytest.mark.unit
def test_invalid_side_rejected():
    with pytest.raises(ValueError, match="side"):
        OrderCreateRequest(**_base_order(side="long"))


@pytest.mark.unit
def test_all_valid_sides():
    for side in ("buy", "sell", "sell_short", "buy_to_cover"):
        req = OrderCreateRequest(**_base_order(side=side))
        assert req.side == side


@pytest.mark.unit
def test_gtd_requires_good_till_date():
    with pytest.raises(ValueError, match="good_till_date"):
        OrderCreateRequest(**_base_order(time_in_force="gtd"))


@pytest.mark.unit
def test_gtd_with_date_valid():
    req = OrderCreateRequest(
        **_base_order(time_in_force="gtd", good_till_date=datetime(2024, 12, 31, tzinfo=UTC))
    )
    assert req.time_in_force == "gtd"


@pytest.mark.unit
def test_invalid_tif_rejected():
    with pytest.raises(ValueError, match="time_in_force"):
        OrderCreateRequest(**_base_order(time_in_force="eod"))


@pytest.mark.unit
def test_zero_quantity_rejected():
    with pytest.raises(ValueError, match=".*"):
        OrderCreateRequest(**_base_order(quantity=Decimal("0")))


@pytest.mark.unit
def test_negative_quantity_rejected():
    with pytest.raises(ValueError, match=".*"):
        OrderCreateRequest(**_base_order(quantity=Decimal("-10")))


@pytest.mark.unit
def test_strategy_id_optional():
    req = OrderCreateRequest(**_base_order(strategy_id=_STRATEGY))
    assert req.strategy_id == _STRATEGY
    req2 = OrderCreateRequest(**_base_order())
    assert req2.strategy_id is None


# ── FillIngest ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fill_valid():
    fill = FillIngest(**_base_fill())
    assert fill.price == Decimal("185.00")
    assert fill.quantity == Decimal("100")


@pytest.mark.unit
def test_fill_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        FillIngest(**_base_fill(timestamp=datetime(2024, 1, 15)))  # naive


@pytest.mark.unit
def test_fill_notional_inconsistency_rejected():
    """notional must be within 0.01% of price x qty."""
    with pytest.raises(ValueError, match="notional_value"):
        FillIngest(**_base_fill(notional_value=Decimal("9000.00")))  # 185*100=18500, not 9000


@pytest.mark.unit
def test_fill_notional_within_tolerance_accepted():
    # 185.00 * 100 = 18500, tolerance = 1.85; 18501 is within tolerance
    fill = FillIngest(**_base_fill(notional_value=Decimal("18501.00")))
    assert fill.notional_value == Decimal("18501.00")


@pytest.mark.unit
def test_fill_zero_price_rejected():
    with pytest.raises(ValueError, match=".*"):
        FillIngest(**_base_fill(price=Decimal("0")))


@pytest.mark.unit
def test_fill_negative_commission_rejected():
    with pytest.raises(ValueError, match=".*"):
        FillIngest(**_base_fill(commission=Decimal("-1")))


@pytest.mark.unit
def test_fill_commission_zero_accepted():
    fill = FillIngest(**_base_fill())
    assert fill.commission == Decimal("0")


@pytest.mark.unit
def test_fill_negative_latency_rejected():
    with pytest.raises(ValueError, match=".*"):
        FillIngest(**_base_fill(execution_latency_ms=-1))


# ── PositionCloseRequest ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_position_close_market_no_limit_price():
    req = PositionCloseRequest(account_id=_ACCOUNT, symbol_id=_SYMBOL)
    assert req.order_type == "market"
    assert req.limit_price is None


@pytest.mark.unit
def test_position_close_limit_requires_price():
    with pytest.raises(ValueError, match="limit_price required"):
        PositionCloseRequest(account_id=_ACCOUNT, symbol_id=_SYMBOL, order_type="limit")


@pytest.mark.unit
def test_position_close_limit_with_price_valid():
    req = PositionCloseRequest(
        account_id=_ACCOUNT, symbol_id=_SYMBOL, order_type="limit", limit_price=Decimal("185")
    )
    assert req.limit_price == Decimal("185")


@pytest.mark.unit
def test_position_close_partial_quantity():
    req = PositionCloseRequest(account_id=_ACCOUNT, symbol_id=_SYMBOL, close_quantity=Decimal("50"))
    assert req.close_quantity == Decimal("50")


@pytest.mark.unit
def test_position_close_zero_quantity_rejected():
    with pytest.raises(ValueError, match=".*"):
        PositionCloseRequest(account_id=_ACCOUNT, symbol_id=_SYMBOL, close_quantity=Decimal("0"))
