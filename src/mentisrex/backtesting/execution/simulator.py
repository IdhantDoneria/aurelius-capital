"""ExecutionSimulator — converts pending OrderEvents into FillEvents.

Called at the start of each bar with the bar's market data.
Orders fill at the OPEN price (next-bar execution model).

Execution rules by order type:
  MARKET: always fills at open + spread + slippage
  LIMIT:  fills only if the limit price was reachable within [low, high].
          Fill price = min(open, limit_price) for buys (best possible).
  STOP:   fills only if the stop was triggered (high ≥ stop for shorts,
          low ≤ stop for longs). Fill at stop price.

Partial fills: if order_shares > max_fill_pct_adv x daily_volume, fill
only max_fill_pct_adv x volume. Remainder stays pending for next bar.

This assumption is important: very large orders in illiquid stocks cannot
be filled in one bar without enormous market impact. The model enforces this.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from mentisrex.backtesting.data.feed import BarData
from mentisrex.backtesting.events.types import FillEvent, OrderEvent, OrderType, Side
from mentisrex.backtesting.execution.models import CommissionModel, SlippageModel, SpreadModel

if TYPE_CHECKING:
    from mentisrex.backtesting.config import BacktestConfig


class ExecutionSimulator:
    def __init__(self, config: "BacktestConfig") -> None:
        self._commission = CommissionModel(config.commission_rate)
        self._spread = SpreadModel(config.spread_bps)
        self._slippage = SlippageModel(config.slippage_impact_bps)
        self._max_fill_pct_adv = config.max_fill_pct_adv

    def try_fill(self, order: OrderEvent, bar: BarData) -> FillEvent | None:
        """Attempt to fill a pending order against this bar's data.

        Returns FillEvent if filled (partial or full), None if conditions not met.
        For partial fills, the returned FillEvent has quantity < order.quantity.
        The engine is responsible for keeping the remainder in pending_orders.
        """
        is_buy = order.side == Side.BUY

        # 1. Determine base fill price by order type
        base_price = self._base_price(order, bar, is_buy)
        if base_price is None:
            return None  # order conditions not met this bar

        # 2. Apply spread
        spread_price = self._spread.adjusted_price(base_price, is_buy)

        # 3. Determine fillable quantity (volume constraint)
        fill_qty = self._fill_quantity(order.quantity, bar.volume)

        # 4. Apply slippage (market impact) to the fill price
        _, impact_adj = self._slippage.compute_impact(fill_qty, bar.volume, spread_price)
        if is_buy:
            fill_price = spread_price + impact_adj
        else:
            fill_price = spread_price - impact_adj

        # 5. Compute commission on this fill's notional
        notional = fill_qty * fill_price
        commission = self._commission.compute(notional)

        return FillEvent(
            timestamp=bar.timestamp,
            symbol=bar.symbol,
            side=order.side,
            quantity=fill_qty,
            fill_price=fill_price.quantize(Decimal("0.000001")),
            commission=commission,
            slippage_cost=fill_qty * impact_adj,
            order_id=order.order_id,
        )

    def _base_price(self, order: OrderEvent, bar: BarData, is_buy: bool) -> Decimal | None:
        if order.order_type == OrderType.MARKET:
            return bar.open

        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                return None
            lp = order.limit_price
            # Limit buy: fill if bar's low ≤ limit_price (price reached our limit)
            if is_buy and bar.low <= lp:
                return min(bar.open, lp)  # best possible: open if better than limit
            # Limit sell: fill if bar's high ≥ limit_price
            if not is_buy and bar.high >= lp:
                return max(bar.open, lp)
            return None  # limit not reached

        if order.order_type == OrderType.STOP:
            if order.stop_price is None:
                return None
            sp = order.stop_price
            # Stop buy (used to enter shorts on breakout): fill if bar's high ≥ stop
            if is_buy and bar.high >= sp:
                return max(bar.open, sp)
            # Stop sell (used to protect longs): fill if bar's low ≤ stop
            if not is_buy and bar.low <= sp:
                return min(bar.open, sp)
            return None

        return None

    def _fill_quantity(self, order_qty: Decimal, bar_volume: Decimal) -> Decimal:
        """Apply volume participation limit."""
        if bar_volume <= 0:
            return order_qty  # no volume data — assume full fill
        max_fill = bar_volume * self._max_fill_pct_adv
        return min(order_qty, max_fill)
