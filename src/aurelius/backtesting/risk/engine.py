"""RiskEngine — pre-trade checks run before every order is accepted.

All checks are configurable via BacktestConfig. A failed check means the
order is rejected (OMS.reject()) and a RiskCheckResult is logged.

Risk limits implemented:
1. Max position size: prevents over-concentration in a single name.
2. Max gross leverage: prevents over-borrowing.
3. Drawdown circuit breaker: halts ALL new positions if portfolio is in
   deep drawdown — models the real-world risk management process where
   a PM is "stopped out" by the risk desk at a threshold drawdown.

In production these same checks would run asynchronously with real-time
position data. Here they run synchronously as part of the event loop.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from aurelius.backtesting.events.types import OrderEvent, Side
from aurelius.backtesting.portfolio.state import PortfolioState

if TYPE_CHECKING:
    from aurelius.backtesting.config import BacktestConfig


@dataclass
class RiskCheckResult:
    passed: bool
    reason: str = ""

    @classmethod
    def ok(cls) -> "RiskCheckResult":
        return cls(passed=True)

    @classmethod
    def fail(cls, reason: str) -> "RiskCheckResult":
        return cls(passed=False, reason=reason)


class RiskEngine:
    def __init__(self, config: "BacktestConfig") -> None:
        self._config = config
        self._halted = False

    @property
    def is_halted(self) -> bool:
        return self._halted

    def check(self, order: OrderEvent, state: PortfolioState) -> RiskCheckResult:
        """Run all pre-trade risk checks. Returns first failure encountered."""

        if self._halted:
            return RiskCheckResult.fail("Strategy halted: max drawdown breached")

        # 1. Drawdown circuit breaker
        drawdown = state.drawdown
        if drawdown < -self._config.max_drawdown_halt:
            self._halted = True
            return RiskCheckResult.fail(
                f"Drawdown {drawdown:.1%} exceeds limit "
                f"{-self._config.max_drawdown_halt:.1%}; halting"
            )

        # 2. Position size check (only for new buys/new shorts — not for closes)
        price = state.last_price(order.symbol)
        if price > 0:
            order_value = order.quantity * price
            nav = state.total_value
            if nav > 0:
                projected_position_pct = order_value / nav
                if projected_position_pct > self._config.max_position_pct * Decimal("2"):
                    # Allow up to 2x max_position_pct to accommodate rebalancing
                    return RiskCheckResult.fail(
                        f"Order notional {order_value:.0f} ({projected_position_pct:.1%} of NAV) "
                        f"exceeds 2x max_position_pct={self._config.max_position_pct:.1%}"
                    )

        # 3. Gross leverage check (approximate — uses current state before fill)
        if order.side == Side.BUY and price > 0:
            incremental_exposure = order.quantity * price
            projected_leverage = (state.gross_exposure + incremental_exposure) / max(
                state.total_value, Decimal("1")
            )
            if projected_leverage > self._config.max_gross_leverage:
                return RiskCheckResult.fail(
                    f"Projected gross leverage {projected_leverage:.2f}x exceeds limit "
                    f"{self._config.max_gross_leverage}"
                )

        return RiskCheckResult.ok()

    def reset(self) -> None:
        """Un-halt the engine. Used between independent test runs."""
        self._halted = False
