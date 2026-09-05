"""PortfolioManager — translates signals to orders and applies fills.

Two responsibilities:
1. apply_fill(fill): update Position + cash after confirmed execution.
2. size_order(signal, state): compute target quantity and create OrderEvent.

Position sizing uses equal-weight allocation by default:
  target_value = total_value x max_position_pct x signal.strength
  target_shares = floor(target_value / last_price)
  delta_shares = target_shares - current_shares

For FLAT signals: create a closing order for the entire position.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from mentisrex.backtesting.events.types import (
    Direction,
    FillEvent,
    OrderEvent,
    OrderType,
    Side,
    SignalEvent,
)
from mentisrex.backtesting.portfolio.state import PortfolioState

if TYPE_CHECKING:
    from mentisrex.backtesting.config import BacktestConfig


class PortfolioManager:
    def __init__(self, config: "BacktestConfig") -> None:
        self._config = config

    def apply_fill(self, fill: FillEvent, state: PortfolioState) -> None:
        """Update position and cash from a confirmed fill."""
        pos = state.position(fill.symbol)

        if fill.side == Side.BUY:
            pos.apply_buy(fill.quantity, fill.fill_price)
        else:
            pos.apply_sell(fill.quantity, fill.fill_price)

        state.debit(-fill.signed_cash_delta())  # cash_delta is negative for buys

    def mark_to_market(self, symbol: str, price: Decimal, state: PortfolioState) -> None:
        """Update last_price for a symbol; unrealized P&L recalculates lazily."""
        if symbol in state.positions:
            state.positions[symbol].last_price = price
        else:
            # Pre-populate position record so last_price is accessible
            pos = state.position(symbol)
            pos.last_price = price

    def size_order(self, signal: SignalEvent, state: PortfolioState) -> OrderEvent | None:
        """Convert a signal into a sized OrderEvent.

        Returns None if no trade is needed (already at target, or price unknown).
        """
        pos = state.position(signal.symbol)
        current_qty = pos.quantity
        price = pos.last_price

        if price <= 0:
            return None  # no price data yet — cannot size

        if signal.direction == Direction.FLAT:
            if current_qty == 0:
                return None
            side = Side.SELL if current_qty > 0 else Side.BUY
            return OrderEvent(
                timestamp=signal.timestamp,
                symbol=signal.symbol,
                order_type=OrderType.MARKET,
                side=side,
                quantity=abs(current_qty),
                strategy_id=signal.strategy_id,
            )

        target_value = (
            state.total_value * self._config.max_position_pct * Decimal(str(signal.strength))
        )
        if signal.direction == Direction.SHORT:
            target_value = -target_value

        target_qty = int(
            (target_value / price).to_integral_value(rounding="ROUND_DOWN")
        )  # floor to whole shares
        delta_qty = Decimal(str(target_qty)) - current_qty

        if delta_qty == 0:
            return None

        side = Side.BUY if delta_qty > 0 else Side.SELL
        return OrderEvent(
            timestamp=signal.timestamp,
            symbol=signal.symbol,
            order_type=OrderType.MARKET,
            side=side,
            quantity=abs(delta_qty),
            strategy_id=signal.strategy_id,
        )
