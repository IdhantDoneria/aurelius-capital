"""Tests for Position accounting and PortfolioState."""

from decimal import Decimal

import pytest

from mentisrex.backtesting.portfolio.position import Position
from mentisrex.backtesting.portfolio.state import PortfolioState

# ── Position ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_position_buy_opens_long():
    pos = Position("AAPL")
    pos.apply_buy(Decimal("100"), Decimal("185.00"))
    assert pos.quantity == Decimal("100")
    assert pos.avg_cost == Decimal("185.00")
    assert pos.is_long


@pytest.mark.unit
def test_position_avg_cost_weighted_average():
    pos = Position("AAPL")
    pos.apply_buy(Decimal("100"), Decimal("180.00"))  # 100 shares at 180
    pos.apply_buy(Decimal("100"), Decimal("200.00"))  # 100 shares at 200
    assert pos.avg_cost == Decimal("190.00")  # (18000 + 20000) / 200
    assert pos.quantity == Decimal("200")


@pytest.mark.unit
def test_position_sell_realizes_pnl():
    pos = Position("AAPL")
    pos.apply_buy(Decimal("100"), Decimal("180.00"))
    pos.apply_sell(Decimal("100"), Decimal("200.00"))
    assert pos.quantity == Decimal("0")
    assert pos.realized_pnl == Decimal("2000.00")  # (200-180) x 100
    assert pos.is_flat


@pytest.mark.unit
def test_position_partial_sell():
    pos = Position("AAPL")
    pos.apply_buy(Decimal("200"), Decimal("180.00"))
    pos.apply_sell(Decimal("100"), Decimal("190.00"))  # sell half
    assert pos.quantity == Decimal("100")
    assert pos.realized_pnl == Decimal("1000.00")  # (190-180) x 100
    assert pos.avg_cost == Decimal("180.00")  # unchanged for remaining


@pytest.mark.unit
def test_position_unrealized_pnl():
    pos = Position("AAPL")
    pos.apply_buy(Decimal("100"), Decimal("180.00"))
    pos.last_price = Decimal("200.00")
    assert pos.unrealized_pnl == Decimal("2000.00")


@pytest.mark.unit
def test_position_zero_unrealized_when_flat():
    pos = Position("AAPL")
    pos.last_price = Decimal("200.00")
    assert pos.unrealized_pnl == Decimal("0")


@pytest.mark.unit
def test_position_cover_short():
    pos = Position("AAPL")
    pos.apply_sell(Decimal("100"), Decimal("200.00"))  # short 100 at 200
    pos.apply_buy(Decimal("100"), Decimal("180.00"))  # cover at 180
    assert pos.quantity == Decimal("0")
    assert pos.realized_pnl == Decimal("2000.00")  # (200-180) x 100


@pytest.mark.unit
def test_position_buy_negative_quantity_raises():
    pos = Position("AAPL")
    with pytest.raises(ValueError, match="must be positive"):
        pos.apply_buy(Decimal("-10"), Decimal("185"))


# ── PortfolioState ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_portfolio_initial_state():
    state = PortfolioState(Decimal("1_000_000"))
    assert state.cash == Decimal("1_000_000")
    assert state.total_value == Decimal("1_000_000")
    assert state.gross_leverage == Decimal("0")


@pytest.mark.unit
def test_portfolio_total_value_includes_positions():
    state = PortfolioState(Decimal("1_000_000"))
    pos = state.position("AAPL")
    pos.apply_buy(Decimal("100"), Decimal("185"))
    pos.last_price = Decimal("190")
    state.debit(-(Decimal("-18500")))  # cash decreased by buy
    # market_value = 100 x 190 = 19000
    assert state.total_market_value == Decimal("19000")


@pytest.mark.unit
def test_portfolio_drawdown_calculation():
    state = PortfolioState(Decimal("1_000_000"))
    state.update_peak()
    # Simulate portfolio falling to 900k
    # We need to directly manipulate cash for simplicity
    state.debit(Decimal("100_000"))  # reduce cash
    dd = state.drawdown
    assert dd < 0, "Drawdown should be negative (below peak)"
    assert float(abs(dd)) == pytest.approx(0.10, rel=1e-2), "Should be ~10% drawdown"


@pytest.mark.unit
def test_portfolio_drawdown_resets_at_new_high():
    state = PortfolioState(Decimal("1_000_000"))
    state.update_peak()
    state.credit(Decimal("100_000"))  # portfolio grows to 1.1M
    state.update_peak()
    dd = state.drawdown
    assert dd == Decimal("0"), "No drawdown at new high"


@pytest.mark.unit
def test_portfolio_gross_leverage():
    state = PortfolioState(Decimal("1_000_000"))
    pos = state.position("AAPL")
    pos.last_price = Decimal("185")
    pos.apply_buy(Decimal("1000"), Decimal("185"))  # $185,000 position
    # gross_leverage = 185000 / total_value
    # total_value = 1_000_000 (cash unchanged, as we didn't adjust cash here)
    lev = state.gross_leverage
    # total_value = 1_000_000 cash + 185_000 market_value = 1_185_000
    # gross_leverage = 185_000 / 1_185_000 ≈ 0.1561
    assert float(lev) == pytest.approx(185_000 / 1_185_000, rel=1e-2)
